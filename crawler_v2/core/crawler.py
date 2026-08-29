from __future__ import annotations

import heapq
import ipaddress
import itertools
import time

from dataclasses import dataclass, field

from urllib.parse import (
    parse_qsl,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

from bs4 import BeautifulSoup
from requests.exceptions import RequestException, Timeout

from adapters.generic import GenericAdapter

from core.api_detector import ApiDetector
from core.api_discovery import ApiReferenceDiscovery
from core.api_identity import ApiIdentity
from core.api_pagination import ApiPagination
from core.api_policy import ApiPolicy
from core.crawl_budget import CrawlBudget
from core.data_detector import DataDetector
from core.duplicate_validator import DuplicateValidator
from core.file_detector import FileDetection, FileDetector
from core.http_client import HttpClient
from core.relevance import RelevanceEngine
from core.resource_dedupe import (
    RepresentationCandidate,
    RepresentationDeduper,
    SPREADSHEET_FORMATS,
)
from core.metadata import clean_text, extract_date, filename_from_url
from core.openapi_discovery import OpenApiDiscovery
from core.pagination_policy import PaginationYieldPolicy
from core.sitemap_discovery import SitemapDiscovery
from core.zip_inspector import ZipInspector


TRACKING_PARAMETERS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
}


API_URL_HINTS = (
    "/api/",
    "/api?",
    "/oapi/",
    "/v1/",
    "/v2/",
    "/v3/",
    "/graphql",
    "/openapi",
    "/swagger",
    "api.",
    "format=json",
    "f=json",
    "f=geojson",
)


# ============================================================
# MODELOS
# ============================================================

@dataclass
class PageRecord:
    url: str
    title: str
    parent_url: str | None
    depth: int
    path: list[str]


@dataclass
class DataPageRecord:
    id_fuente: str
    descripcion: str
    url: str
    url_origen: str | None
    ruta: list[str]
    fecha_referencia: str | None
    tiene_tabla_html: bool
    tablas_detectadas: int
    permite_exportar: bool
    tiene_filtros: bool
    metodo_deteccion: str

    tipo_recurso: str = "web"
    formato: str | None = None
    registros_detectados: int | None = None
    es_openapi: bool | None = None
    es_geojson: bool | None = None
    tiene_paginacion: bool | None = None
    documentacion_url: str | None = None
    metodo_http: str | None = None


@dataclass
class FileRecord:
    id_fuente: str
    descripcion: str
    url_descarga: str
    url_origen: str
    origenes: list[str]
    tipo_archivo: str | None
    extension: str | None
    fecha_actualizacion: str | None
    ruta: list[str]
    metodo_deteccion: str | None
    content_type: str | None = None
    contenido_zip: list[str] = field(default_factory=list)
    zip_inspeccion: str | None = None
    zip_bytes_descargados: int = 0


@dataclass
class CrawlResult:
    pages: list[PageRecord] = field(default_factory=list)
    files: list[FileRecord] = field(default_factory=list)
    data_pages: list[DataPageRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # Fallos de sondeos API descubiertos automáticamente.
    # Se conservan para diagnóstico, pero NO son errores de la fuente.
    api_probe_errors: list[str] = field(default_factory=list)
    stop_reason: str = "frontier_exhausted"
    duration_seconds: float = 0.0

    sitemap_documents: int = 0
    sitemap_urls_discovered: int = 0
    sitemap_urls_queued: int = 0
    sitemap_errors: int = 0

    # Métricas operacionales. No forman parte del JSON contractual;
    # se usan para diagnóstico, batch y trazabilidad.
    relevance_rejected: int = 0
    budget_metrics: dict = field(default_factory=dict)

    # Diagnóstico de deduplicación. No modifica el JSON contractual.
    # En esta etapa solo detectamos candidatos; todavía no descargamos
    # archivos ni eliminamos representaciones.
    dedupe_metrics: dict = field(default_factory=dict)

    # Métricas de la política genérica de paginación por rendimiento.
    # No forman parte del JSON contractual.
    pagination_metrics: dict = field(default_factory=dict)


# ============================================================
# CRAWLER
# ============================================================

class Crawler:
    def __init__(
        self,
        config: dict,
        client: HttpClient,
        detector: FileDetector,
        adapter: GenericAdapter,
    ) -> None:

        self.config = config
        self.client = client
        self.detector = detector
        self.adapter = adapter

        self.zip_inspector = ZipInspector(client)
        self.data_detector = DataDetector(config)
        self.api_detector = ApiDetector()
        self.api_reference_discovery = ApiReferenceDiscovery()
        self.api_policy = ApiPolicy()
        self.api_identity = ApiIdentity()
        self.api_pagination = ApiPagination()
        self.openapi_discovery = OpenApiDiscovery()
        self.sitemap_discovery = SitemapDiscovery(
            client
        )

        # ====================================================
        # RELEVANCIA / PRESUPUESTO
        # ====================================================

        self.relevance_engine = RelevanceEngine(
            config
        )

        # ====================================================
        # DEDUPLICACIÓN - ETAPA 1: CANDIDATOS
        # ====================================================
        #
        # Todavía NO descargamos contenido y NO eliminamos archivos.
        # El adapter puede aportar una identidad semántica específica
        # para su fuente; si no existe, se usa la identidad genérica
        # conservadora del RepresentationDeduper.
        #
        semantic_identity_resolver = getattr(
            adapter,
            "semantic_resource_identity",
            None,
        )

        if not callable(
            semantic_identity_resolver
        ):
            semantic_identity_resolver = None

        self.representation_deduper = RepresentationDeduper(
            identity_resolver=semantic_identity_resolver,
        )

        self.representation_candidates_by_identity: dict[
            str,
            list[RepresentationCandidate],
        ] = {}

        self.duplicate_candidate_events = 0

        # Validador final de duplicidad. La comparación de contenido
        # permanece desactivable por configuración y solo se ejecuta
        # sobre grupos candidatos ya detectados.
        self.duplicate_validator = DuplicateValidator(
            deduper=self.representation_deduper,
            min_content_confidence=float(
                config.get(
                    "dedupe_min_content_confidence",
                    0.97,
                )
            ),
        )

        self.dedupe_content_validation_enabled = bool(
            config.get(
                "dedupe_content_validation_enabled",
                False,
            )
        )

        try:
            self.dedupe_max_content_requests = max(
                0,
                int(
                    config.get(
                        "dedupe_max_content_requests",
                        40,
                    )
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            self.dedupe_max_content_requests = 40

        try:
            self.dedupe_max_file_bytes = max(
                1024,
                int(
                    config.get(
                        "dedupe_max_file_bytes",
                        12 * 1024 * 1024,
                    )
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            self.dedupe_max_file_bytes = (
                12 * 1024 * 1024
            )

        self.dedupe_content_requests = 0
        self.dedupe_confirmed_duplicates = 0
        self.dedupe_removed_representations = 0
        self.dedupe_content_inconclusive = 0
        self.dedupe_content_different = 0
        self._dedupe_payload_cache: dict[
            str,
            bytes | None,
        ] = {}

        self.budget = CrawlBudget.from_config(
            config
        )

        # ====================================================
        # PAGINACIÓN WEB POR RENDIMIENTO
        # ====================================================
        #
        # Es una capacidad GENÉRICA del core. Cada source puede
        # activarla/desactivarla y ajustar sus límites sin modificar
        # el crawler.
        #
        pagination_yield_config = (
            config.get(
                "pagination_yield",
                {},
            )
            or {}
        )

        if not isinstance(
            pagination_yield_config,
            dict,
        ):
            pagination_yield_config = {}

        self.pagination_yield_policy = PaginationYieldPolicy(
            enabled=bool(
                pagination_yield_config.get(
                    "enabled",
                    False,
                )
            ),
            zero_yield_stop_after=int(
                pagination_yield_config.get(
                    "zero_yield_stop_after",
                    3,
                )
            ),
            min_pages_before_stop=int(
                pagination_yield_config.get(
                    "min_pages_before_stop",
                    3,
                )
            ),
            high_yield_threshold=int(
                pagination_yield_config.get(
                    "high_yield_threshold",
                    5,
                )
            ),
            max_tracked_yields=int(
                pagination_yield_config.get(
                    "max_tracked_yields",
                    20,
                )
            ),
        )

        # Cuenta nuevas páginas NO paginadas descubiertas mientras se
        # procesa una página. Esto evita cortar listados que no enlazan
        # archivos directamente, pero sí descubren páginas detalle útiles.
        self.pagination_discovery_events = 0
        self.pagination_skip_events = 0

        self.source_id = str(
            config["id_fuente"]
        )

        # ====================================================
        # SITEMAPS
        # ====================================================

        self.discover_sitemaps = bool(
            config.get(
                "discover_sitemaps",
                True,
            )
        )

        try:
            self.max_sitemap_urls = max(
                0,
                int(
                    config.get(
                        "max_sitemap_urls",
                        10000,
                    )
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            self.max_sitemap_urls = 10000

        try:
            self.max_sitemap_documents = max(
                1,
                int(
                    config.get(
                        "max_sitemap_documents",
                        100,
                    )
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            self.max_sitemap_documents = 100

        try:
            self.max_sitemap_bytes = max(
                1_000_000,
                int(
                    config.get(
                        "max_sitemap_bytes",
                        20_000_000,
                    )
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            self.max_sitemap_bytes = 20_000_000

        # ====================================================
        # DESCUBRIMIENTO GENÉRICO DE REFERENCIAS API
        # ====================================================

        self.discover_api_references = bool(
            config.get(
                "discover_api_references",
                True,
            )
        )

        try:
            self.max_api_candidates_per_page = max(
                0,
                int(
                    config.get(
                        "max_api_candidates_per_page",
                        50,
                    )
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            self.max_api_candidates_per_page = 50

        self.api_reference_urls_seen: set[
            str
        ] = set()

        # URLs que llegaron a la frontera EXCLUSIVAMENTE como
        # referencias API oportunistas descubiertas en HTML/JS.
        # Si una de ellas falla, se registra como sondeo fallido
        # y no como error estructural de la fuente.
        self.api_reference_urls_queued: set[str] = set()

        # ====================================================
        # API CONFIGURADA / OPENAPI
        # ====================================================

        self.api_endpoints: dict[str, dict] = {}

        self.api_documentation: list[
            tuple[str, str]
        ] = []

        self.openapi_endpoints: dict[
            str,
            dict,
        ] = {}

        self.openapi_documents_seen: set[
            str
        ] = set()

        # ====================================================
        # PAGINACIÓN API
        # ====================================================

        pagination_config = (
            config.get(
                "api_pagination",
                {},
            )
            or {}
        )

        if not isinstance(
            pagination_config,
            dict,
        ):
            pagination_config = {}

        self.api_pagination_enabled = bool(
            pagination_config.get(
                "enabled",
                False,
            )
        )

        try:

            pagination_max_pages = int(
                pagination_config.get(
                    "max_pages",
                    10,
                )
            )

        except (
            TypeError,
            ValueError,
        ):

            pagination_max_pages = 10

        self.api_pagination_max_pages = max(
            1,
            pagination_max_pages,
        )

        # URL paginada -> contexto del dataset padre.
        self.pagination_context_by_url: dict[
            str,
            dict,
        ] = {}

        # Dataset -> número de páginas procesadas.
        self.pagination_pages_by_identity: dict[
            str,
            int,
        ] = {}

        # ====================================================
        # DOMINIOS
        # ====================================================

        allowed_domains = {
            str(domain).lower()
            for domain
            in config.get(
                "allowed_domains",
                [],
            )
            if domain
        }

        self._load_api_configuration(
            allowed_domains
        )

        self.allowed_domains = tuple(
            sorted(
                allowed_domains
            )
        )

        # ====================================================
        # ESTADO
        # ====================================================

        self.visited: set[str] = set()

        self.queued: set[str] = set()

        self.files_by_url: dict[
            str,
            FileRecord,
        ] = {}

        # Evita volver a puntuar/inspeccionar el mismo archivo descartado
        # cuando aparece enlazado desde múltiples páginas.
        self.rejected_file_urls: set[str] = set()

        self.data_index_by_identity: dict[
            str,
            int,
        ] = {}

        self.api_skipped = 0

        self.sequence = (
            itertools.count()
        )

    # ========================================================
    # CONFIGURACIÓN API
    # ========================================================

    def _load_api_configuration(
        self,
        allowed_domains: set[str],
    ) -> None:

        endpoints = (
            self.config.get(
                "api_endpoints",
                [],
            )
            or []
        )

        for item in endpoints:

            if isinstance(
                item,
                str,
            ):

                metadata = {
                    "url": item,
                    "descripcion": "",
                    "method": "GET",
                    "documentation_url": None,
                }

            elif isinstance(
                item,
                dict,
            ):

                if not item.get(
                    "enabled",
                    True,
                ):
                    continue

                metadata = dict(
                    item
                )

            else:
                continue

            raw_url = str(
                metadata.get(
                    "url",
                    "",
                )
            ).strip()

            normalized = (
                self.normalize_url(
                    raw_url
                )
            )

            if not normalized:
                continue

            metadata[
                "url"
            ] = normalized

            metadata[
                "method"
            ] = str(
                metadata.get(
                    "method",
                    "GET",
                )
            ).strip().upper()

            metadata[
                "_declared"
            ] = True

            self.api_endpoints[
                normalized
            ] = metadata

            hostname = (
                urlparse(
                    normalized
                ).hostname
                or ""
            ).lower()

            if hostname:

                allowed_domains.add(
                    hostname
                )

                if hostname.startswith(
                    "www."
                ):
                    allowed_domains.add(
                        hostname[4:]
                    )

            documentation_url = (
                metadata.get(
                    "documentation_url"
                )
            )

            if not documentation_url:
                continue

            normalized_doc = (
                self.normalize_url(
                    str(
                        documentation_url
                    )
                )
            )

            if not normalized_doc:
                continue

            description = (
                clean_text(
                    str(
                        metadata.get(
                            "descripcion",
                            "",
                        )
                    )
                )
                or "API"
            )

            self.api_documentation.append(
                (
                    normalized_doc,
                    description,
                )
            )

            doc_hostname = (
                urlparse(
                    normalized_doc
                ).hostname
                or ""
            ).lower()

            if doc_hostname:

                allowed_domains.add(
                    doc_hostname
                )

                if doc_hostname.startswith(
                    "www."
                ):
                    allowed_domains.add(
                        doc_hostname[4:]
                    )

    # ========================================================
    # URL
    # ========================================================

    @staticmethod
    def normalize_url(
        url: str,
        base_url: str | None = None,
    ) -> str | None:

        if not url:
            return None

        value = (
            url.strip()
        )

        if not value:
            return None

        lowered = (
            value.lower()
        )

        if lowered.startswith(
            (
                "mailto:",
                "tel:",
                "javascript:",
                "data:",
            )
        ):
            return None

        if value.startswith(
            "#"
        ):
            return None

        if base_url:

            value = urljoin(
                base_url,
                value,
            )

        parsed = urlparse(
            value
        )

        # ----------------------------------------------------
        # REPARACIÓN GENÉRICA DE URL ABSOLUTA INCRUSTADA
        # ----------------------------------------------------
        #
        # Algunos sitios publican hrefs defectuosos del tipo:
        #
        # /carpeta/https://dominio.tld/?q=recurso
        #
        # urljoin los convierte en:
        #
        # https://dominio.tld/carpeta/https://dominio.tld/?q=recurso
        #
        # Eso parece una URL válida para urlparse, pero en realidad la
        # segunda URL absoluta quedó incrustada dentro del path.
        #
        # Solo corregimos esquemas incrustados dentro del PATH. No
        # tocamos URLs absolutas que aparezcan legítimamente como valor
        # de un parámetro query (redirect=https://..., url=https://...).
        #
        path_lowered = (
            parsed.path
            or ""
        ).lower()

        embedded_index = -1

        for marker in (
            "https://",
            "http://",
        ):
            index = path_lowered.find(
                marker
            )

            if (
                index >= 0
                and (
                    embedded_index < 0
                    or index < embedded_index
                )
            ):
                embedded_index = index

        if embedded_index >= 0:

            repaired = (
                parsed.path[
                    embedded_index:
                ]
            )

            if parsed.query:
                repaired += (
                    "?"
                    + parsed.query
                )

            repaired_parsed = urlparse(
                repaired
            )

            if (
                repaired_parsed.scheme.lower()
                in {
                    "http",
                    "https",
                }
                and repaired_parsed.hostname
            ):
                value = repaired
                parsed = repaired_parsed

        if (
            parsed.scheme.lower()
            not in {
                "http",
                "https",
            }
        ):
            return None

        if not parsed.hostname:
            return None

        scheme = (
            parsed.scheme.lower()
        )

        hostname = (
            parsed.hostname.lower()
        )

        try:

            port = parsed.port

        except ValueError:

            return None

        if (
            port is None
            or (
                scheme == "http"
                and port == 80
            )
            or (
                scheme == "https"
                and port == 443
            )
        ):

            netloc = hostname

        else:

            netloc = (
                f"{hostname}:{port}"
            )

        path = (
            parsed.path
            or "/"
        )

        query_pairs = []

        for (
            key,
            query_value,
        ) in parse_qsl(
            parsed.query,
            keep_blank_values=True,
        ):

            if (
                key.lower()
                in TRACKING_PARAMETERS
            ):
                continue

            query_pairs.append(
                (
                    key,
                    query_value,
                )
            )

        query = urlencode(
            sorted(
                query_pairs
            ),
            doseq=True,
        )

        return urlunparse(
            (
                scheme,
                netloc,
                path,
                "",
                query,
                "",
            )
        )

    # ========================================================
    # SEGURIDAD
    # ========================================================

    @staticmethod
    def is_public_web_url(
        url: str,
    ) -> bool:

        hostname = (
            urlparse(
                url
            ).hostname
            or ""
        ).strip().lower()

        if not hostname:
            return False

        if hostname in {
            "localhost",
            "localhost.localdomain",
        }:
            return False

        if hostname.endswith(
            ".local"
        ):
            return False

        try:

            ip = (
                ipaddress.ip_address(
                    hostname
                )
            )

        except ValueError:

            return True

        return not any(
            (
                ip.is_private,
                ip.is_loopback,
                ip.is_link_local,
                ip.is_multicast,
                ip.is_unspecified,
                ip.is_reserved,
            )
        )

    def is_allowed(
        self,
        url: str,
    ) -> bool:

        hostname = (
            urlparse(
                url
            ).hostname
            or ""
        ).lower()

        if not hostname:
            return False

        for domain in self.allowed_domains:

            if hostname == domain:
                return True

            if hostname.endswith(
                f".{domain}"
            ):
                return True

        return False

    # ========================================================
    # API
    # ========================================================

    @staticmethod
    def _looks_like_api_url(
        url: str,
    ) -> bool:

        lowered = (
            url.lower()
        )

        return any(
            hint in lowered
            for hint in API_URL_HINTS
        )

    def _request_headers_for(
        self,
        url: str,
    ) -> dict[str, str] | None:
        """
        Cabeceras específicas para endpoints API.

        Las páginas HTML normales conservan las cabeceras comunes del
        HttpClient. Los endpoints API declarados, descubiertos por OpenAPI,
        paginados o reconocibles por URL usan una identificación
        transparente y un Accept orientado a datos.

        Se puede sobrescribir por fuente mediante:
        "api_request_headers": {"User-Agent": "...", "Accept": "..."}
        """

        normalized = (
            self.normalize_url(
                url
            )
        )

        if not normalized:
            return None

        is_api_request = (
            normalized
            in self.api_endpoints
            or normalized
            in self.openapi_endpoints
            or normalized
            in self.pagination_context_by_url
            or self._looks_like_api_url(
                normalized
            )
        )

        if not is_api_request:
            return None

        headers = {
            "User-Agent": (
                "PublicDataCrawler/1.0"
            ),
            "Accept": (
                "application/json,"
                "application/geo+json;q=0.95,"
                "application/xml;q=0.9,"
                "text/csv;q=0.85,"
                "*/*;q=0.5"
            ),
        }

        configured_headers = (
            self.config.get(
                "api_request_headers",
                {},
            )
            or {}
        )

        if isinstance(
            configured_headers,
            dict,
        ):
            for (
                key,
                value,
            ) in configured_headers.items():

                header_name = str(
                    key
                    or ""
                ).strip()

                header_value = str(
                    value
                    or ""
                ).strip()

                if (
                    header_name
                    and header_value
                ):
                    headers[
                        header_name
                    ] = header_value

        return headers

    def _pagination_context_for(
        self,
        url: str,
    ) -> dict | None:

        normalized = (
            self.normalize_url(
                url
            )
        )

        if not normalized:
            return None

        return (
            self.pagination_context_by_url
            .get(
                normalized
            )
        )

    def _api_metadata_for(
        self,
        current_url: str,
        final_url: str,
    ) -> dict | None:

        for url in (
            current_url,
            final_url,
        ):

            normalized = (
                self.normalize_url(
                    url
                )
            )

            if not normalized:
                continue

            pagination_context = (
                self.pagination_context_by_url
                .get(
                    normalized
                )
            )

            if pagination_context:

                metadata = (
                    pagination_context.get(
                        "metadata"
                    )
                )

                if isinstance(
                    metadata,
                    dict,
                ):
                    return metadata

            if (
                normalized
                in self.api_endpoints
            ):

                return (
                    self.api_endpoints[
                        normalized
                    ]
                )

            if (
                normalized
                in self.openapi_endpoints
            ):

                return (
                    self.openapi_endpoints[
                        normalized
                    ]
                )

        return None

    def _prefer_api_detection(
        self,
        current_url: str,
        final_url: str,
        metadata: dict | None,
    ) -> bool:

        if metadata is not None:
            return True

        return (
            self._looks_like_api_url(
                current_url
            )
            or
            self._looks_like_api_url(
                final_url
            )
        )

    def _allow_discovered_url(
        self,
        url: str,
    ) -> bool:

        normalized = (
            self.normalize_url(
                url
            )
        )

        if not normalized:
            return False

        declared = (
            normalized
            in self.api_endpoints
        )

        known_api = (
            declared
            or normalized
            in self.openapi_endpoints
            or self._looks_like_api_url(
                normalized
            )
        )

        if not known_api:
            return True

        decision = (
            self.api_policy
            .should_follow_discovered(
                normalized,
                declared=declared,
            )
        )

        if decision.allowed:
            return True

        self.api_skipped += 1

        if (
            self.api_skipped <= 10
            or self.api_skipped % 50 == 0
        ):

            print(
                f"[{self.source_id.upper()}] "
                f"API OMITIDA | "
                f"{decision.reason} | "
                f"{normalized}",
                flush=True,
            )

        return False

    def _should_register_api(
        self,
        url: str,
        detection,
        metadata: dict | None,
    ) -> bool:

        declared = bool(
            metadata
            and metadata.get(
                "_declared",
                False,
            )
        )

        decision = (
            self.api_policy
            .should_register_api(
                url,
                detection,
                declared=declared,
            )
        )

        return (
            decision.allowed
        )

    # ========================================================
    # REFERENCIAS API EN HTML
    # ========================================================

    def _queue_html_api_references(
        self,
        queue: list,
        *,
        soup: BeautifulSoup,
        page_url: str,
        depth: int,
    ) -> None:

        if not self.discover_api_references:
            return

        if self.max_api_candidates_per_page <= 0:
            return

        candidates = (
            self.api_reference_discovery
            .discover(
                soup,
                page_url,
                max_candidates=(
                    self.max_api_candidates_per_page
                ),
            )
        )

        if not candidates:
            return

        queued = 0

        for candidate in candidates:

            normalized = (
                self.normalize_url(
                    candidate.url,
                    page_url,
                )
            )

            if not normalized:
                continue

            if (
                normalized
                in self.api_reference_urls_seen
            ):
                continue

            self.api_reference_urls_seen.add(
                normalized
            )

            if not self.is_public_web_url(
                normalized
            ):
                continue

            if not self.is_allowed(
                normalized
            ):
                continue

            if not self._allow_discovered_url(
                normalized
            ):
                continue

            before = len(
                self.queued
            )

            self._queue_page(
                queue,
                url=normalized,
                depth=(
                    depth + 1
                ),
                parent_url=page_url,
                path=(
                    "API",
                    "DESCUBIERTA",
                ),
                text=(
                    candidate.reason
                ),
                priority_override=1,
            )

            if (
                len(
                    self.queued
                )
                > before
            ):

                self.api_reference_urls_queued.add(
                    normalized
                )

                queued += 1

                if queued <= 10:

                    print(
                        f"[{self.source_id.upper()}] "
                        f"API REFERENCIA | "
                        f"{candidate.reason} | "
                        f"{normalized}",
                        flush=True,
                    )

        if queued > 10:

            print(
                f"[{self.source_id.upper()}] "
                f"API REFERENCIA | "
                f"nuevas_en_cola={queued}",
                flush=True,
            )

    # ========================================================
    # ERRORES DE SONDEO API
    # ========================================================

    def _is_optional_api_probe(
        self,
        url: str,
    ) -> bool:
        """
        True solo para referencias API oportunistas descubiertas
        automáticamente en HTML/JS.

        Nunca degrada a "sondeo opcional" una API declarada, un
        endpoint OpenAPI confirmado ni una continuación paginada.
        """

        normalized = self.normalize_url(url)

        if not normalized:
            return False

        if normalized in self.api_endpoints:
            return False

        if normalized in self.openapi_endpoints:
            return False

        if normalized in self.pagination_context_by_url:
            return False

        return normalized in self.api_reference_urls_queued

    def _record_crawl_error(
        self,
        result: CrawlResult,
        url: str,
        message: str,
    ) -> None:
        """
        Separa fallos reales de la fuente de fallos de exploración
        oportunista de APIs. Ambos quedan trazables.
        """

        if self._is_optional_api_probe(url):
            result.api_probe_errors.append(message)

            count = len(result.api_probe_errors)

            if count <= 10 or count % 50 == 0:
                print(
                    f"[{self.source_id.upper()}] "
                    f"API SONDEO FALLIDO | "
                    f"{url}",
                    flush=True,
                )

            return

        result.errors.append(message)

    # ========================================================
    # OPENAPI
    # ========================================================

    def _discover_openapi(
        self,
        queue: list,
        response,
        document_url: str,
    ) -> None:

        normalized_document = (
            self.normalize_url(
                document_url
            )
        )

        if not normalized_document:
            return

        if (
            normalized_document
            in self.openapi_documents_seen
        ):
            return

        self.openapi_documents_seen.add(
            normalized_document
        )

        try:

            max_endpoints = int(
                self.config.get(
                    "max_openapi_endpoints",
                    40,
                )
            )

        except (
            TypeError,
            ValueError,
        ):

            max_endpoints = 40

        max_endpoints = max(
            1,
            max_endpoints,
        )

        discovery = (
            self.openapi_discovery.discover(
                response,
                normalized_document,
                max_endpoints=(
                    max_endpoints
                ),
            )
        )

        print(
            f"[{self.source_id.upper()}] "
            f"OPENAPI | "
            f"version={discovery.version or '?'} | "
            f"GET={len(discovery.endpoints)} | "
            f"ejecutables="
            f"{len(discovery.executable_endpoints)} | "
            f"omitidos="
            f"{discovery.skipped_endpoints}",
            flush=True,
        )

        queued = 0

        for endpoint in (
            discovery.executable_endpoints
        ):

            normalized = (
                self.normalize_url(
                    endpoint.url
                )
            )

            if not normalized:
                continue

            if not self.is_public_web_url(
                normalized
            ):
                continue

            # OpenAPI no puede ampliar silenciosamente
            # el dominio permitido.
            if not self.is_allowed(
                normalized
            ):

                print(
                    f"[{self.source_id.upper()}] "
                    f"OPENAPI OMITIDO | "
                    f"dominio_no_permitido | "
                    f"{normalized}",
                    flush=True,
                )

                continue

            policy = (
                self.api_policy
                .should_follow_discovered(
                    normalized,
                    declared=False,
                )
            )

            if not policy.allowed:
                continue

            if (
                normalized
                in self.api_endpoints
            ):
                continue

            description = (
                endpoint.summary
                or endpoint.operation_id
                or endpoint.path
            )

            self.openapi_endpoints[
                normalized
            ] = {
                "url": normalized,
                "descripcion": description,
                "method": "GET",
                "documentation_url": (
                    normalized_document
                ),
                "_declared": False,
                "_openapi_discovered": True,
            }

            before = len(
                self.queued
            )

            self._queue_page(
                queue,
                url=normalized,
                depth=0,
                parent_url=(
                    normalized_document
                ),
                path=(
                    "API",
                    "OpenAPI",
                    description,
                ),
                text=description,
                priority_override=2,
            )

            if (
                len(
                    self.queued
                )
                > before
            ):
                queued += 1

        print(
            f"[{self.source_id.upper()}] "
            f"OPENAPI | "
            f"nuevos_en_cola={queued}",
            flush=True,
        )

    # ========================================================
    # PAGINACIÓN API
    # ========================================================

    def _accumulate_paginated_response(
        self,
        result: CrawlResult,
        identity: str,
        detection,
    ) -> bool:

        existing_index = (
            self.data_index_by_identity
            .get(
                identity
            )
        )

        if existing_index is None:
            return False

        existing = (
            result.data_pages[
                existing_index
            ]
        )

        page_records = getattr(
            detection,
            "records_count",
            None,
        )

        if page_records is not None:

            if (
                existing.registros_detectados
                is None
            ):
                existing.registros_detectados = 0

            existing.registros_detectados += (
                page_records
            )

        existing.tiene_paginacion = True

        if (
            not existing.formato
            and getattr(
                detection,
                "format",
                None,
            )
        ):

            existing.formato = (
                detection.format
            )

        return True

    def _queue_next_api_page(
        self,
        queue: list,
        *,
        response,
        current_url: str,
        current_path: tuple[str, ...],
        metadata: dict | None,
        identity: str,
        continuation: bool,
    ) -> None:

        if not self.api_pagination_enabled:
            return

        # ----------------------------------------------------
        # CONTABILIZAR PÁGINA PROCESADA
        # ----------------------------------------------------

        if continuation:

            processed_pages = (
                self.pagination_pages_by_identity
                .get(
                    identity,
                    1,
                )
                + 1
            )

            self.pagination_pages_by_identity[
                identity
            ] = processed_pages

        else:

            processed_pages = (
                self.pagination_pages_by_identity
                .setdefault(
                    identity,
                    1,
                )
            )

        pagination = (
            self.api_pagination.detect(
                response,
                current_url,
            )
        )

        if not pagination.has_pagination:
            return

        if not pagination.next_url:
            return

        if (
            processed_pages
            >= self.api_pagination_max_pages
        ):

            print(
                f"[{self.source_id.upper()}] "
                f"API PAGINACION | "
                f"limite="
                f"{self.api_pagination_max_pages} | "
                f"{identity}",
                flush=True,
            )

            return

        next_url = (
            self.normalize_url(
                pagination.next_url,
                current_url,
            )
        )

        if not next_url:
            return

        if not self.is_public_web_url(
            next_url
        ):
            return

        if not self.is_allowed(
            next_url
        ):

            print(
                f"[{self.source_id.upper()}] "
                f"API PAGINACION OMITIDA | "
                f"dominio_no_permitido | "
                f"{next_url}",
                flush=True,
            )

            return

        policy = (
            self.api_policy
            .should_follow_discovered(
                next_url,
                declared=False,
            )
        )

        if not policy.allowed:

            print(
                f"[{self.source_id.upper()}] "
                f"API PAGINACION OMITIDA | "
                f"{policy.reason} | "
                f"{next_url}",
                flush=True,
            )

            return

        if (
            next_url in self.visited
            or next_url in self.queued
        ):
            return

        # La siguiente página pertenece al MISMO dataset.
        self.pagination_context_by_url[
            next_url
        ] = {
            "identity": identity,
            "metadata": metadata,
        }

        before = len(
            self.queued
        )

        self._queue_page(
            queue,
            url=next_url,
            depth=0,
            parent_url=current_url,
            path=current_path,
            text="API pagination",
            priority_override=3,
        )

        # Adapter o algún filtro pudo impedir agregarla.
        if (
            len(
                self.queued
            )
            <= before
        ):

            self.pagination_context_by_url.pop(
                next_url,
                None,
            )

            return

        page_label = (
            processed_pages
            + 1
        )

        if (
            pagination.total_pages
            is not None
        ):

            page_text = (
                f"pagina={page_label}/"
                f"{pagination.total_pages}"
            )

        else:

            page_text = (
                f"pagina={page_label}"
            )

        print(
            f"[{self.source_id.upper()}] "
            f"API PAGINACION | "
            f"{pagination.method or 'next'} | "
            f"{page_text} | "
            f"{next_url}",
            flush=True,
        )

    # ========================================================
    # PROCESAMIENTO API
    # ========================================================

    def _process_api_response(
        self,
        *,
        queue: list,
        result: CrawlResult,
        response,
        current_url: str,
        final_url: str,
        parent_url: str | None,
        current_path: tuple[str, ...],
        metadata: dict | None,
    ) -> bool:

        detection = (
            self.api_detector.detect(
                response
            )
        )

        if not detection.is_api:
            return False

        # ----------------------------------------------------
        # OPENAPI
        # ----------------------------------------------------

        if detection.is_openapi:

            if self.config.get(
                "discover_openapi_endpoints",
                True,
            ):

                self._discover_openapi(
                    queue,
                    response,
                    final_url,
                )

            return True

        # ----------------------------------------------------
        # CONTINUACIÓN PAGINADA
        # ----------------------------------------------------

        pagination_context = (
            self._pagination_context_for(
                current_url
            )
            or
            self._pagination_context_for(
                final_url
            )
        )

        continuation = (
            pagination_context
            is not None
        )

        if continuation:

            identity = str(
                pagination_context.get(
                    "identity",
                    "",
                )
            )

            registered = False

            if identity:

                registered = (
                    self._accumulate_paginated_response(
                        result,
                        identity,
                        detection,
                    )
                )

            # Si por alguna razón no existe el registro padre,
            # se registra normalmente.
            if not registered:

                registered = (
                    self._register_api_response(
                        result=result,
                        current_url=current_url,
                        final_url=final_url,
                        parent_url=parent_url,
                        current_path=current_path,
                        metadata=metadata,
                        detection=detection,
                    )
                )

                identity = (
                    self.api_identity
                    .canonical_key(
                        final_url
                    )
                )

        else:

            registered = (
                self._register_api_response(
                    result=result,
                    current_url=current_url,
                    final_url=final_url,
                    parent_url=parent_url,
                    current_path=current_path,
                    metadata=metadata,
                    detection=detection,
                )
            )

            identity = (
                self.api_identity
                .canonical_key(
                    final_url
                )
            )

        # ----------------------------------------------------
        # BUSCAR NEXT
        # ----------------------------------------------------

        if registered:

            self._queue_next_api_page(
                queue,
                response=response,
                current_url=final_url,
                current_path=current_path,
                metadata=metadata,
                identity=identity,
                continuation=continuation,
            )

        return True

    # ========================================================
    # LÍMITES
    # ========================================================

    def _max_depth_reached(
        self,
        depth: int,
    ) -> bool:
        """
        Límite absoluto de profundidad.

        Cuando la profundidad adaptativa está desactivada, `max_depth`
        conserva el comportamiento clásico.

        Cuando está activa:
        - max_depth = límite normal / soft limit
        - adaptive_max_depth = límite absoluto / hard limit

        La decisión de si una rama merece superar el soft limit se toma
        dentro de `_queue_page()` mediante el hook del adapter.
        """

        max_depth = self.config.get(
            "max_depth"
        )

        if max_depth is None:
            return False

        try:
            soft_limit = max(
                0,
                int(
                    max_depth
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            return False

        adaptive_enabled = bool(
            self.config.get(
                "adaptive_depth_enabled",
                False,
            )
        )

        if not adaptive_enabled:
            return (
                depth
                >= soft_limit
            )

        try:
            hard_limit = max(
                soft_limit,
                int(
                    self.config.get(
                        "adaptive_max_depth",
                        soft_limit,
                    )
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            hard_limit = soft_limit

        return (
            depth
            >= hard_limit
        )

    def _max_pages_reached(
        self,
        result: CrawlResult,
    ) -> bool:

        max_pages = (
            self.config.get(
                "max_pages"
            )
        )

        return (
            max_pages is not None
            and len(
                result.pages
            )
            >= int(
                max_pages
            )
        )

    def _max_files_reached(
        self,
    ) -> bool:

        max_files = (
            self.config.get(
                "max_files"
            )
        )

        return (
            max_files is not None
            and len(
                self.files_by_url
            )
            >= int(
                max_files
            )
        )

    # ========================================================
    # DATASETS
    # ========================================================

    def _register_data_page(
        self,
        result: CrawlResult,
        record: DataPageRecord,
    ) -> bool:
        """
        Evalúa y registra únicamente datasets/páginas de datos útiles.

        El DataDetector/ApiDetector decide qué encontró técnicamente.
        RelevanceEngine + adapter deciden si debe entrar al catálogo.
        """

        normalized = self.normalize_url(
            record.url
        )

        if not normalized:
            return False

        record.url = normalized

        normalized_path = (
            self.adapter
            .normalize_resource_path(
                path=record.ruta,
                url=normalized,
                description=record.descripcion,
                origin_url=(
                    record.url_origen
                    or ""
                ),
            )
        )

        record.ruta = list(
            normalized_path
        )

        adjustment = (
            self.adapter
            .relevance_adjustment(
                url=normalized,
                description=record.descripcion,
                origin_url=(
                    record.url_origen
                    or ""
                ),
                path=normalized_path,
                resource_type=record.tipo_recurso,
            )
        )

        decision = (
            self.relevance_engine
            .evaluate_data_page(
                url=normalized,
                description=record.descripcion,
                origin_url=(
                    record.url_origen
                    or ""
                ),
                route=normalized_path,
                resource_type=record.tipo_recurso,
                data_format=record.formato,
                has_table=record.tiene_tabla_html,
                has_export=record.permite_exportar,
                has_filters=record.tiene_filtros,
                records_count=record.registros_detectados,
                adjustment=adjustment,
            )
        )

        if not (
            self.adapter
            .should_keep_data_page(
                decision=decision,
                url=normalized,
                description=record.descripcion,
                origin_url=record.url_origen,
                path=normalized_path,
                resource_type=record.tipo_recurso,
            )
        ):
            self.budget.note_rejected_resource()
            return False

        identity = (
            self.api_identity
            .canonical_key(
                normalized
            )
        )

        existing_index = (
            self.data_index_by_identity
            .get(
                identity
            )
        )

        # ----------------------------------------------------
        # DATASET NUEVO
        # ----------------------------------------------------

        if existing_index is None:
            result.data_pages.append(
                record
            )

            self.data_index_by_identity[
                identity
            ] = (
                len(
                    result.data_pages
                )
                - 1
            )

            self.budget.note_dataset_kept()

            total = len(
                result.data_pages
            )

            if (
                total <= 10
                or total % 25 == 0
            ):
                print(
                    f"[{self.source_id.upper()}] "
                    f"DATASETS={total} | "
                    f"score={decision.score} | "
                    f"{record.metodo_deteccion} | "
                    f"{normalized}",
                    flush=True,
                )

            return True

        # ----------------------------------------------------
        # MISMO DATASET, MEJOR REPRESENTACIÓN
        # ----------------------------------------------------

        existing = (
            result.data_pages[
                existing_index
            ]
        )

        if not (
            self.api_identity
            .should_replace(
                existing,
                record,
            )
        ):
            return True

        if (
            not record.ruta
            and existing.ruta
        ):
            record.ruta = list(
                existing.ruta
            )

        if (
            not record.url_origen
            and existing.url_origen
        ):
            record.url_origen = (
                existing.url_origen
            )

        if (
            record.registros_detectados
            is None
            and
            existing.registros_detectados
            is not None
        ):
            record.registros_detectados = (
                existing.registros_detectados
            )

        result.data_pages[
            existing_index
        ] = record

        print(
            f"[{self.source_id.upper()}] "
            f"DATASET ACTUALIZADO | "
            f"{existing.url} -> "
            f"{record.url}",
            flush=True,
        )

        return True

    def _register_api_response(
        self,
        *,
        result: CrawlResult,
        current_url: str,
        final_url: str,
        parent_url: str | None,
        current_path: tuple[str, ...],
        metadata: dict | None,
        detection,
    ) -> bool:

        if not self._should_register_api(
            final_url,
            detection,
            metadata,
        ):
            return False

        description = ""

        documentation_url = None

        method = "GET"

        if metadata:

            description = clean_text(
                str(
                    metadata.get(
                        "descripcion",
                        "",
                    )
                )
            )

            documentation_url = (
                metadata.get(
                    "documentation_url"
                )
            )

            method = str(
                metadata.get(
                    "method",
                    "GET",
                )
            ).upper()

        if not description:

            description = (
                filename_from_url(
                    final_url
                )
                or final_url
            )

        path = list(
            current_path
        )

        if not path:

            path = [
                "API",
                description,
            ]

        record = DataPageRecord(
            id_fuente=(
                self.source_id
            ),

            descripcion=(
                description
            ),

            url=(
                final_url
            ),

            url_origen=(
                parent_url
                or current_url
            ),

            ruta=(
                path
            ),

            fecha_referencia=(
                extract_date(
                    final_url,
                    description,
                )
            ),

            tiene_tabla_html=False,

            tablas_detectadas=0,

            permite_exportar=True,

            tiene_filtros=bool(
                detection.has_pagination
            ),

            metodo_deteccion=(
                detection.reason
                or "api_response"
            ),

            tipo_recurso="api",

            formato=(
                detection.format
            ),

            registros_detectados=(
                detection.records_count
            ),

            es_openapi=False,

            es_geojson=(
                detection.is_geojson
            ),

            tiene_paginacion=(
                detection.has_pagination
            ),

            documentacion_url=(
                str(
                    documentation_url
                )
                if documentation_url
                else None
            ),

            metodo_http=(
                method
            ),
        )

        return self._register_data_page(
            result,
            record,
        )

    # ========================================================
    # CANDIDATOS A DUPLICADO
    # ========================================================

    def _register_duplicate_candidate(
        self,
        record: FileRecord,
    ) -> None:
        """
        Registra posibles representaciones equivalentes.

        Esta etapa es deliberadamente pasiva:
        - no hace nuevas peticiones;
        - no descarga archivos;
        - no elimina registros;
        - no altera files_by_url.

        Solo construye grupos que más adelante podrán pasar por
        DuplicateValidator + comparación de contenido.
        """

        resource_type = (
            str(
                record.tipo_archivo
                or record.extension
                or ""
            )
            .lower()
            .strip()
            .lstrip(".")
        )

        if resource_type not in SPREADSHEET_FORMATS:
            return

        candidate = RepresentationCandidate(
            url=record.url_descarga,
            resource_type=resource_type,
            description=record.descripcion,
            origin_url=record.url_origen,
            metadata={
                "fecha_actualizacion": (
                    record.fecha_actualizacion
                ),
                "ruta": list(
                    record.ruta
                ),
            },
        )

        identity = (
            self.representation_deduper
            .identity_for(
                candidate
            )
        )

        if not identity:
            return

        group = (
            self.representation_candidates_by_identity
            .setdefault(
                identity,
                [],
            )
        )

        # Seguridad ante llamadas repetidas.
        if any(
            existing.url
            == candidate.url
            for existing in group
        ):
            return

        group.append(
            candidate
        )

        if len(group) < 2:
            return

        self.duplicate_candidate_events += 1

        # Logs controlados: suficientes para revisar que la lógica funciona
        # sin imprimir cientos de líneas.
        if (
            self.duplicate_candidate_events <= 10
            or self.duplicate_candidate_events % 25 == 0
        ):
            formats = ",".join(
                item.normalized_type
                for item in group
            )

            print(
                f"[{self.source_id.upper()}] "
                f"CANDIDATO DUP={self.duplicate_candidate_events} | "
                f"reps={len(group)} | "
                f"formatos={formats} | "
                f"id={identity}",
                flush=True,
            )

    # ========================================================
    # VALIDACIÓN DE CONTENIDO DE DUPLICADOS
    # ========================================================

    def _download_dedupe_payload(
        self,
        candidate: RepresentationCandidate,
    ) -> bytes | None:
        """
        Descarga acotada exclusivamente para validar duplicidad.

        No se usa para descubrir recursos. Solo se llama cuando:
        - ya existe un grupo candidato;
        - la validación de contenido está activada;
        - todavía queda presupuesto de requests;
        - el archivo no supera el límite configurado.
        """

        url = str(
            candidate.url
            or ""
        ).strip()

        if not url:
            return None

        if url in self._dedupe_payload_cache:
            return self._dedupe_payload_cache[
                url
            ]

        if (
            self.dedupe_content_requests
            >= self.dedupe_max_content_requests
        ):
            return None

        self.dedupe_content_requests += 1

        response = None

        try:
            # HttpClient centraliza delays, timeout, TLS y sesión.
            # Su interfaz pública actual no expone el argumento
            # ``stream``; por eso usamos el GET estándar del core.
            #
            # La validación sigue estando acotada exclusivamente a
            # candidatos de duplicidad y al límite de requests/bytes
            # configurado para la fuente.
            response = self.client.get(
                url
            )

            if response.status_code != 200:
                self._dedupe_payload_cache[
                    url
                ] = None
                return None

            content_length = (
                response.headers.get(
                    "Content-Length",
                    ""
                )
                or ""
            ).strip()

            if content_length:
                try:
                    declared_size = int(
                        content_length
                    )
                except ValueError:
                    declared_size = 0

                if (
                    declared_size > 0
                    and declared_size
                    > self.dedupe_max_file_bytes
                ):
                    print(
                        f"[{self.source_id.upper()}] "
                        f"DEDUPE CONTENIDO OMITIDO | "
                        f"size={declared_size} | "
                        f"limite={self.dedupe_max_file_bytes} | "
                        f"{url}",
                        flush=True,
                    )

                    self._dedupe_payload_cache[
                        url
                    ] = None
                    return None

            chunks: list[bytes] = []
            downloaded = 0

            for chunk in response.iter_content(
                chunk_size=64 * 1024
            ):
                if not chunk:
                    continue

                downloaded += len(
                    chunk
                )

                if (
                    downloaded
                    > self.dedupe_max_file_bytes
                ):
                    print(
                        f"[{self.source_id.upper()}] "
                        f"DEDUPE CONTENIDO OMITIDO | "
                        f"descarga_supera_limite | "
                        f"{url}",
                        flush=True,
                    )

                    self._dedupe_payload_cache[
                        url
                    ] = None
                    return None

                chunks.append(
                    chunk
                )

            payload = b"".join(
                chunks
            )

            if not payload:
                self._dedupe_payload_cache[
                    url
                ] = None
                return None

            self._dedupe_payload_cache[
                url
            ] = payload

            return payload

        except (
            RequestException,
            Timeout,
        ) as exc:
            print(
                f"[{self.source_id.upper()}] "
                f"DEDUPE CONTENIDO ERROR | "
                f"{type(exc).__name__} | "
                f"{url}",
                flush=True,
            )

            self._dedupe_payload_cache[
                url
            ] = None

            return None

        except Exception as exc:
            print(
                f"[{self.source_id.upper()}] "
                f"DEDUPE CONTENIDO ERROR | "
                f"{type(exc).__name__}: {exc} | "
                f"{url}",
                flush=True,
            )

            self._dedupe_payload_cache[
                url
            ] = None

            return None

        finally:
            if response is not None:
                response.close()

    def _validate_duplicate_groups(
        self,
    ) -> None:
        """
        Confirma duplicados mediante comparación lógica de contenido.

        Regla de seguridad:
        - ante duda, se conservan ambas representaciones;
        - solo se elimina una representación con
          CONFIRMED_DUPLICATE.
        """

        if not self.dedupe_content_validation_enabled:
            return

        duplicate_groups = [
            (
                identity,
                candidates,
            )
            for identity, candidates
            in self.representation_candidates_by_identity.items()
            if len(
                candidates
            ) >= 2
        ]

        if not duplicate_groups:
            return

        print(
            f"[{self.source_id.upper()}] "
            f"DEDUPE CONTENIDO | "
            f"grupos={len(duplicate_groups)} | "
            f"max_requests={self.dedupe_max_content_requests} | "
            f"max_file_bytes={self.dedupe_max_file_bytes}",
            flush=True,
        )

        for identity, candidates in duplicate_groups:

            if (
                self.dedupe_content_requests
                >= self.dedupe_max_content_requests
            ):
                break

            # Elegimos como referencia la representación con mejor
            # puntuación de formato/calidad.
            reference = max(
                candidates,
                key=(
                    self.representation_deduper
                    .quality_score
                ),
            )

            reference_payload = (
                self._download_dedupe_payload(
                    reference
                )
            )

            if reference_payload is None:
                self.dedupe_content_inconclusive += (
                    max(
                        0,
                        len(
                            candidates
                        ) - 1,
                    )
                )
                continue

            for candidate in candidates:

                if candidate.url == reference.url:
                    continue

                if (
                    self.dedupe_content_requests
                    >= self.dedupe_max_content_requests
                    and candidate.url
                    not in self._dedupe_payload_cache
                ):
                    break

                candidate_payload = (
                    self._download_dedupe_payload(
                        candidate
                    )
                )

                if candidate_payload is None:
                    self.dedupe_content_inconclusive += 1
                    continue

                # Evidencia técnica previa a la decisión final.
                #
                # Esta línea es permanente y útil para auditoría: permite
                # distinguir entre una diferencia real y una discrepancia
                # sistemática del parser entre XLSX/ODS. No elimina nada.
                (
                    content_comparison,
                    reference_fingerprint,
                    candidate_fingerprint,
                ) = (
                    self.duplicate_validator
                    .compare_content(
                        left=reference,
                        right=candidate,
                        left_payload=reference_payload,
                        right_payload=candidate_payload,
                    )
                )

                if (
                    content_comparison is not None
                    and reference_fingerprint is not None
                    and candidate_fingerprint is not None
                ):
                    evidence_detail = ";".join(
                        content_comparison.reasons
                    )

                    print(
                        f"[{self.source_id.upper()}] "
                        f"DEDUPE EVIDENCIA | "
                        f"estado={content_comparison.status} | "
                        f"sim={content_comparison.similarity:.4f} | "
                        f"conf={content_comparison.confidence:.4f} | "
                        f"ref={reference.normalized_type}:"
                        f"celdas={reference_fingerprint.sampled_cells}:"
                        f"hojas={reference_fingerprint.sheet_count}:"
                        f"trunc={int(reference_fingerprint.truncated)} | "
                        f"cand={candidate.normalized_type}:"
                        f"celdas={candidate_fingerprint.sampled_cells}:"
                        f"hojas={candidate_fingerprint.sheet_count}:"
                        f"trunc={int(candidate_fingerprint.truncated)} | "
                        f"detalle={evidence_detail} | "
                        f"id={identity}",
                        flush=True,
                    )

                validation = (
                    self.duplicate_validator
                    .validate(
                        left=reference,
                        right=candidate,
                        left_payload=reference_payload,
                        right_payload=candidate_payload,
                    )
                )

                if (
                    validation.status
                    == "CONFIRMED_DUPLICATE"
                    and validation.loser
                    is not None
                ):
                    loser_url = (
                        validation.loser.url
                    )

                    if loser_url in self.files_by_url:
                        del self.files_by_url[
                            loser_url
                        ]

                        self.dedupe_removed_representations += 1

                    self.dedupe_confirmed_duplicates += 1

                    print(
                        f"[{self.source_id.upper()}] "
                        f"DEDUPE CONFIRMADO | "
                        f"conf={validation.confidence:.4f} | "
                        f"contenido={validation.content_status} | "
                        f"conserva={validation.winner.normalized_type if validation.winner else '-'} | "
                        f"elimina={validation.loser.normalized_type} | "
                        f"id={identity}",
                        flush=True,
                    )

                elif (
                    validation.content_status
                    == "DIFFERENT"
                ):
                    self.dedupe_content_different += 1

                    print(
                        f"[{self.source_id.upper()}] "
                        f"DEDUPE DIFERENTE | "
                        f"conf={validation.confidence:.4f} | "
                        f"id={identity}",
                        flush=True,
                    )

                else:
                    self.dedupe_content_inconclusive += 1

                    print(
                        f"[{self.source_id.upper()}] "
                        f"DEDUPE CONSERVA AMBOS | "
                        f"estado={validation.content_status} | "
                        f"conf={validation.confidence:.4f} | "
                        f"id={identity}",
                        flush=True,
                    )

    # ========================================================
    # ARCHIVOS
    # ========================================================

    def _register_file(
        self,
        *,
        url: str,
        source_page: str,
        description: str,
        path: tuple[str, ...],
        detection: FileDetection,
    ) -> bool:
        """
        Registra solo archivos que superen el filtro de relevancia.

        Los ZIP se inspeccionan mediante Range únicamente cuando el
        contexto previo indica que podrían contener datos útiles.
        """

        normalized = self.normalize_url(
            url
        )

        if not normalized:
            return False

        if not self.is_public_web_url(
            normalized
        ):
            return False

        if normalized in self.rejected_file_urls:
            return False

        existing = self.files_by_url.get(
            normalized
        )

        if existing:
            if (
                source_page
                and source_page
                not in existing.origenes
            ):
                existing.origenes.append(
                    source_page
                )

            return True

        if self._max_files_reached():
            return False

        description = (
            clean_text(
                description
            )
            or filename_from_url(
                normalized
            )
        )

        normalized_path = (
            self.adapter
            .normalize_resource_path(
                path=path,
                url=normalized,
                description=description,
                origin_url=(
                    source_page
                    or ""
                ),
            )
        )

        adjustment = (
            self.adapter
            .relevance_adjustment(
                url=normalized,
                description=description,
                origin_url=source_page,
                path=normalized_path,
                resource_type=(
                    detection.file_type
                    or "file"
                ),
            )
        )

        # Primera decisión sin descargar contenido del archivo.
        decision = (
            self.relevance_engine
            .evaluate_file(
                url=normalized,
                description=description,
                origin_url=source_page,
                route=normalized_path,
                file_type=detection.file_type,
                extension=detection.extension,
                adjustment=adjustment,
            )
        )

        contenido_zip: list[str] = []
        zip_status = None
        zip_bytes = 0

        # Un ZIP desconocido no justifica dos solicitudes Range extra.
        # Lo inspeccionamos solo si el contexto ya es razonablemente
        # prometedor o si el adapter lo favoreció.
        if (
            detection.file_type == "zip"
            and (
                decision.keep
                or decision.score >= 35
                or adjustment > 0
            )
        ):
            zip_result = (
                self.zip_inspector
                .inspect(
                    normalized
                )
            )

            contenido_zip = (
                zip_result.files
            )

            zip_status = (
                zip_result.status
            )

            zip_bytes = (
                zip_result.bytes_downloaded
            )

            # Segunda evaluación: ahora sí conoce el índice del ZIP.
            decision = (
                self.relevance_engine
                .evaluate_file(
                    url=normalized,
                    description=description,
                    origin_url=source_page,
                    route=normalized_path,
                    file_type=detection.file_type,
                    extension=detection.extension,
                    zip_content=contenido_zip,
                    adjustment=adjustment,
                )
            )

        if not (
            self.adapter
            .should_keep_file(
                decision=decision,
                url=normalized,
                description=description,
                origin_url=source_page,
                path=normalized_path,
                detection=detection,
            )
        ):
            self.rejected_file_urls.add(
                normalized
            )
            self.budget.note_rejected_resource()
            return False

        record = FileRecord(
            id_fuente=self.source_id,
            descripcion=description,
            url_descarga=normalized,
            url_origen=source_page,
            origenes=[
                source_page
            ],
            tipo_archivo=detection.file_type,
            extension=detection.extension,
            fecha_actualizacion=(
                extract_date(
                    normalized,
                    description,
                )
            ),
            ruta=list(
                normalized_path
            ),
            metodo_deteccion=detection.method,
            content_type=detection.content_type,
            contenido_zip=contenido_zip,
            zip_inspeccion=zip_status,
            zip_bytes_descargados=zip_bytes,
        )

        self.files_by_url[
            normalized
        ] = record

        # Solo analizamos duplicidad entre recursos que ya superaron
        # relevancia. Así no gastamos esfuerzo en basura documental.
        self._register_duplicate_candidate(
            record
        )

        self.budget.note_file_kept()

        total = len(
            self.files_by_url
        )

        if total <= 10 or total % 100 == 0:
            print(
                f"[{self.source_id.upper()}] "
                f"ARCHIVO UTIL={total} | "
                f"score={decision.score} | "
                f"{detection.file_type or '?'} | "
                f"{normalized}",
                flush=True,
            )

        return True

    # ========================================================
    # COLA
    # ========================================================

    def _queue_page(
        self,
        queue: list,
        *,
        url: str,
        depth: int,
        parent_url: str | None,
        path: tuple[str, ...],
        text: str,
        priority_override: int | None = None,
    ) -> None:

        normalized = (
            self.normalize_url(
                url
            )
        )

        if not normalized:
            return

        if not self.is_public_web_url(
            normalized
        ):
            return

        if (
            normalized in self.visited
            or normalized in self.queued
        ):
            return

        if not self.is_allowed(
            normalized
        ):
            return

        if not self.adapter.should_follow(
            normalized
        ):
            return

        # ----------------------------------------------------
        # PAGINACIÓN WEB: CORTE ANTES DE ENCOLAR
        # ----------------------------------------------------
        #
        # Solo se aplica a navegación web descubierta normalmente.
        # Seeds, endpoints API y otras URLs con prioridad forzada no
        # se alteran aquí. Las páginas no paginadas siempre pasan.
        #
        # El loop principal vuelve a evaluar la URL antes de visitarla,
        # porque una familia puede haberse estancado después de que varias
        # páginas ya hubieran entrado previamente en la frontera.
        if (
            priority_override is None
            and self.pagination_yield_policy.enabled
        ):
            pagination_decision = (
                self.pagination_yield_policy
                .should_visit(
                    normalized
                )
            )

            if not pagination_decision.allow:
                self.pagination_skip_events += 1

                if (
                    self.pagination_skip_events <= 10
                    or self.pagination_skip_events % 25 == 0
                ):
                    print(
                        f"[{self.source_id.upper()}] "
                        f"PAGINACION SKIP COLA | "
                        f"motivo={pagination_decision.reason} | "
                        f"{normalized}",
                        flush=True,
                    )

                return

        # ----------------------------------------------------
        # PROFUNDIDAD ADAPTATIVA
        # ----------------------------------------------------
        #
        # El límite configurado en max_depth actúa como soft limit.
        # Más allá de ese nivel, el adapter decide si la rama todavía
        # parece suficientemente valiosa como para continuar.
        #
        # Los seeds / endpoints explícitos con prioridad forzada siguen
        # pudiendo entrar mientras no superen el hard limit absoluto.
        #
        max_depth = self.config.get(
            "max_depth"
        )

        if (
            depth > 0
            and priority_override is None
        ):
            should_follow_depth = getattr(
                self.adapter,
                "should_follow_at_depth",
                None,
            )

            if callable(
                should_follow_depth
            ):
                if not should_follow_depth(
                    url=normalized,
                    text=text,
                    next_depth=depth,
                    soft_max_depth=max_depth,
                ):
                    return

            elif (
                max_depth is not None
                and depth > int(
                    max_depth
                )
            ):
                return

        # Incluso para seeds/endpoints forzados se respeta el hard limit.
        if (
            max_depth is not None
            and bool(
                self.config.get(
                    "adaptive_depth_enabled",
                    False,
                )
            )
        ):
            try:
                soft_limit = max(
                    0,
                    int(
                        max_depth
                    ),
                )

                hard_limit = max(
                    soft_limit,
                    int(
                        self.config.get(
                            "adaptive_max_depth",
                            soft_limit,
                        )
                    ),
                )

            except (
                TypeError,
                ValueError,
            ):
                hard_limit = int(
                    max_depth
                )

            if depth > hard_limit:
                return

        priority = (
            priority_override
            if priority_override
            is not None

            else self.adapter.priority(
                normalized,
                text,
            )
        )

        heapq.heappush(
            queue,
            (
                priority,
                next(
                    self.sequence
                ),
                normalized,
                depth,
                parent_url,
                path,
            ),
        )

        self.queued.add(
            normalized
        )

        # Para evaluar el rendimiento de una página paginada no contamos
        # como "valor" otros enlaces de paginación. Sí contamos nuevas
        # páginas normales descubiertas, porque un listado puede ser útil
        # aun cuando los archivos estén en páginas detalle.
        if self.pagination_yield_policy.enabled:
            pagination_identity = (
                self.pagination_yield_policy
                .identify(
                    normalized
                )
            )

            if not pagination_identity.is_pagination:
                self.pagination_discovery_events += 1

    # ========================================================
    # SITEMAP SEEDS
    # ========================================================

    def _queue_sitemap_seeds(
        self,
        queue: list,
        result: CrawlResult,
    ) -> None:

        if not self.discover_sitemaps:
            return

        if self.max_sitemap_urls <= 0:
            return

        base_url = str(
            self.config.get(
                "base_url",
                "",
            )
            or ""
        ).strip()

        if not base_url:
            return

        discovery = self.sitemap_discovery.discover(
            base_url=base_url,
            allowed_domains=self.allowed_domains,
            max_sitemaps=self.max_sitemap_documents,
            max_urls=self.max_sitemap_urls,
            max_document_bytes=self.max_sitemap_bytes,
        )

        result.sitemap_documents = len(
            discovery.sitemap_documents
        )

        result.sitemap_urls_discovered = len(
            discovery.urls
        )

        result.sitemap_errors = len(
            discovery.errors
        )

        for error in discovery.errors:
            result.errors.append(
                f"SITEMAP -> {error}"
            )

        queued = 0

        for sitemap_url in discovery.urls:

            if not (
                self.adapter
                .should_follow_sitemap_url(
                    sitemap_url
                )
            ):
                continue

            if not self._allow_discovered_url(
                sitemap_url
            ):
                continue

            before = len(
                self.queued
            )

            sitemap_priority = (
                self.adapter
                .priority(
                    sitemap_url,
                    "sitemap",
                )
            )

            self._queue_page(
                queue,
                url=sitemap_url,
                depth=0,
                parent_url=None,
                path=(),
                text="sitemap",
                priority_override=sitemap_priority,
            )

            if len(
                self.queued
            ) > before:
                queued += 1

        result.sitemap_urls_queued = queued

        print(
            f"[{self.source_id.upper()}] "
            f"SITEMAP | "
            f"docs={result.sitemap_documents} | "
            f"urls={result.sitemap_urls_discovered} | "
            f"en_cola={result.sitemap_urls_queued} | "
            f"errores={result.sitemap_errors}",
            flush=True,
        )

    # ========================================================
    # API SEEDS
    # ========================================================

    def _queue_api_seeds(
        self,
        queue: list,
        result: CrawlResult,
    ) -> None:

        for (
            endpoint,
            metadata,
        ) in self.api_endpoints.items():

            method = str(
                metadata.get(
                    "method",
                    "GET",
                )
            ).upper()

            if method != "GET":

                result.errors.append(
                    (
                        "API método no soportado: "
                        f"{method} -> "
                        f"{endpoint}"
                    )
                )

                continue

            description = (
                clean_text(
                    str(
                        metadata.get(
                            "descripcion",
                            "",
                        )
                    )
                )
                or "API"
            )

            self._queue_page(
                queue,
                url=endpoint,
                depth=0,
                parent_url=None,
                path=(
                    "API",
                    description,
                ),
                text=description,
                priority_override=0,
            )

        if not self.config.get(
            "crawl_api_documentation",
            True,
        ):
            return

        for (
            documentation_url,
            description,
        ) in self.api_documentation:

            self._queue_page(
                queue,
                url=documentation_url,
                depth=0,
                parent_url=None,
                path=(
                    "API",
                    description,
                    "Documentacion",
                ),
                text=description,
                priority_override=5,
            )

    # ========================================================
    # CRAWL
    # ========================================================

    def crawl(
        self,
    ) -> CrawlResult:

        result = (
            CrawlResult()
        )

        started = (
            time.monotonic()
        )

        queue: list = []

        entrypoints = (
            self.config.get(
                "entrypoints"
            )
            or [
                self.config[
                    "base_url"
                ]
            ]
        )

        # ====================================================
        # SEEDS
        # ====================================================

        for entrypoint in entrypoints:

            self._queue_page(
                queue,
                url=entrypoint,
                depth=0,
                parent_url=None,
                path=(),
                text="",
                priority_override=0,
            )

        self._queue_sitemap_seeds(
            queue,
            result,
        )

        self._queue_api_seeds(
            queue,
            result,
        )

        # ====================================================
        # LOOP PRINCIPAL
        # ====================================================

        while queue:

            budget_decision = (
                self.budget
                .decision()
            )

            if budget_decision.stop:
                result.stop_reason = (
                    budget_decision.reason
                    or "crawl_budget"
                )

                print(
                    f"[{self.source_id.upper()}] "
                    f"BUDGET STOP | "
                    f"{result.stop_reason} | "
                    f"req={self.budget.requests} | "
                    f"utiles={self.budget.useful_resources} | "
                    f"rechazados={self.budget.resources_rejected}",
                    flush=True,
                )

                break

            if self._max_pages_reached(
                result
            ):

                result.stop_reason = (
                    "max_pages"
                )

                break

            if self._max_files_reached():

                result.stop_reason = (
                    "max_files"
                )

                break

            (
                priority,
                _,
                current_url,
                depth,
                parent_url,
                current_path,
            ) = heapq.heappop(
                queue
            )

            self.queued.discard(
                current_url
            )

            if (
                current_url
                in self.visited
            ):
                continue

            # -------------------------------------------------
            # PAGINACIÓN WEB: CORTE POR RENDIMIENTO
            # -------------------------------------------------
            #
            # Se vuelve a evaluar aquí (y no solo al encolar) porque una
            # página anterior pudo haber puesto muchas páginas futuras en
            # la frontera antes de que el core aprendiera que esa familia
            # ya no aporta valor.
            pagination_decision = (
                self.pagination_yield_policy
                .should_visit(
                    current_url
                )
            )

            if not pagination_decision.allow:
                self.visited.add(
                    current_url
                )

                self.pagination_skip_events += 1

                if (
                    self.pagination_skip_events <= 10
                    or self.pagination_skip_events % 25 == 0
                ):
                    print(
                        f"[{self.source_id.upper()}] "
                        f"PAGINACION SKIP | "
                        f"motivo={pagination_decision.reason} | "
                        f"{current_url}",
                        flush=True,
                    )

                continue

            # Baselines para calcular cuánto valor produjo ESTA página.
            pagination_useful_before = (
                len(
                    self.files_by_url
                )
                + len(
                    result.data_pages
                )
            )

            pagination_discovery_before = (
                self.pagination_discovery_events
            )

            pagination_observe_url: str | None = None

            elapsed = (
                time.monotonic()
                - started
            )

            print(
                f"[{self.source_id.upper()}] "
                f"t={elapsed:6.1f}s | "
                f"pag={len(result.pages):3} | "
                f"files={len(self.files_by_url):4} | "
                f"data={len(result.data_pages):3} | "
                f"req={self.budget.requests:4} | "
                f"rej={self.budget.resources_rejected:4} | "
                f"cola={len(queue):4} | "
                f"prio={priority:2} | "
                f"{current_url}",
                flush=True,
            )

            # =================================================
            # HTTP
            # =================================================

            try:

                response = (
                    self.client.get(
                        current_url,
                        headers=(
                            self._request_headers_for(
                                current_url
                            )
                        ),
                    )
                )

                self.budget.note_request(
                    success=True
                )

            except Timeout:

                self.budget.note_request(
                    success=False
                )

                self._record_crawl_error(
                    result,
                    current_url,
                    f"TIMEOUT -> {current_url}",
                )

                self.visited.add(
                    current_url
                )

                continue

            except RequestException as exc:

                # Los sondeos API oportunistas siguen consumiendo
                # presupuesto de requests, pero su error se separa
                # posteriormente de los errores reales de la fuente.
                self.budget.note_request(
                    success=False
                )

                self._record_crawl_error(
                    result,
                    current_url,
                    (
                        f"{current_url} -> "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                )

                self.visited.add(
                    current_url
                )

                continue

            try:

                final_url = (
                    self.normalize_url(
                        response.url
                    )
                )

                if not final_url:

                    self.visited.add(
                        current_url
                    )

                    continue

                # ------------------------------------------------
                # REDIRECT DEDUPE
                # ------------------------------------------------

                if (
                    final_url
                    in self.visited

                    and final_url
                    != current_url
                ):

                    self.visited.add(
                        current_url
                    )

                    continue

                if not self.is_allowed(
                    final_url
                ):

                    self._record_crawl_error(
                        result,
                        current_url,
                        (
                            "Redirect fuera del dominio permitido: "
                            f"{current_url} -> "
                            f"{final_url}"
                        ),
                    )

                    self.visited.add(
                        current_url
                    )

                    continue

                self.visited.add(
                    current_url
                )

                self.visited.add(
                    final_url
                )

                content_type = (
                    response.headers.get(
                        "Content-Type",
                        "",
                    )
                    .lower()
                )

                metadata = (
                    self._api_metadata_for(
                        current_url,
                        final_url,
                    )
                )

                # =================================================
                # API
                # =================================================

                if self._prefer_api_detection(
                    current_url,
                    final_url,
                    metadata,
                ):

                    if self._process_api_response(
                        queue=queue,
                        result=result,
                        response=response,
                        current_url=current_url,
                        final_url=final_url,
                        parent_url=parent_url,
                        current_path=current_path,
                        metadata=metadata,
                    ):

                        continue

                # =================================================
                # ARCHIVO
                # =================================================

                response_detection = (
                    self.detector
                    .detect_response(
                        response
                    )
                )

                if response_detection.is_file:

                    self._register_file(
                        url=final_url,

                        source_page=(
                            parent_url
                            or current_url
                        ),

                        description=(
                            filename_from_url(
                                final_url
                            )
                        ),

                        path=current_path,

                        detection=(
                            response_detection
                        ),
                    )

                    continue

                # =================================================
                # NO HTML
                # =================================================

                if (
                    "html"
                    not in content_type

                    and "xhtml"
                    not in content_type
                ):

                    self._process_api_response(
                        queue=queue,
                        result=result,
                        response=response,
                        current_url=current_url,
                        final_url=final_url,
                        parent_url=parent_url,
                        current_path=current_path,
                        metadata=metadata,
                    )

                    continue

                # =================================================
                # HTML
                # =================================================

                # Solo las respuestas HTML alimentan la política de
                # paginación web. API tiene su propia política.
                pagination_observe_url = current_url

                soup = BeautifulSoup(
                    response.text,
                    "html.parser",
                )

                title = ""

                if soup.title:

                    title = clean_text(
                        soup.title.get_text(
                            " ",
                            strip=True,
                        )
                    )

                result.pages.append(
                    PageRecord(
                        url=final_url,
                        title=title,
                        parent_url=parent_url,
                        depth=depth,
                        path=list(
                            current_path
                        ),
                    )
                )

                self.budget.note_page()

                # =================================================
                # DATASET HTML
                # =================================================

                if (
                    self.adapter
                    .should_detect_data(
                        final_url,
                        title,
                    )
                ):

                    data_detection = (
                        self.data_detector
                        .detect(
                            soup,
                            title,
                            final_url,
                        )
                    )

                    if (
                        data_detection
                        .is_data_page
                    ):

                        self._register_data_page(
                            result,

                            DataPageRecord(
                                id_fuente=(
                                    self.source_id
                                ),

                                descripcion=(
                                    title
                                    or final_url
                                ),

                                url=(
                                    final_url
                                ),

                                url_origen=(
                                    parent_url
                                ),

                                ruta=list(
                                    current_path
                                ),

                                fecha_referencia=(
                                    extract_date(
                                        final_url,
                                        title,
                                    )
                                ),

                                tiene_tabla_html=(
                                    data_detection
                                    .has_table
                                ),

                                tablas_detectadas=(
                                    data_detection
                                    .tables_count
                                ),

                                permite_exportar=(
                                    data_detection
                                    .has_export
                                ),

                                tiene_filtros=(
                                    data_detection
                                    .has_filters
                                ),

                                metodo_deteccion=(
                                    data_detection.reason
                                    or "data_page"
                                ),
                            ),
                        )

                # =================================================
                # REFERENCIAS API EXPUESTAS EN EL HTML / JS INLINE
                # =================================================

                if not self._max_depth_reached(
                    depth
                ):

                    self._queue_html_api_references(
                        queue,
                        soup=soup,
                        page_url=final_url,
                        depth=depth,
                    )

                # =================================================
                # LINKS
                # =================================================

                for anchor in soup.find_all(
                    "a",
                    href=True,
                ):

                    target = (
                        self.normalize_url(
                            str(
                                anchor.get(
                                    "href"
                                )
                            ),
                            final_url,
                        )
                    )

                    if not target:
                        continue

                    if not self._allow_discovered_url(
                        target
                    ):
                        continue

                    text = clean_text(
                        anchor.get_text(
                            " ",
                            strip=True,
                        )
                    )

                    detection = (
                        self.detector
                        .detect_url(
                            target
                        )
                    )

                    # -----------------------------------------
                    # ARCHIVO
                    # -----------------------------------------

                    if detection.is_file:

                        if (
                            target
                            in self.api_endpoints

                            or target
                            in self.openapi_endpoints
                        ):

                            if not self._max_depth_reached(
                                depth
                            ):

                                self._queue_page(
                                    queue,
                                    url=target,
                                    depth=(
                                        depth + 1
                                    ),
                                    parent_url=(
                                        final_url
                                    ),
                                    path=current_path,
                                    text=text,
                                    priority_override=0,
                                )

                            continue

                        self._register_file(
                            url=target,
                            source_page=final_url,
                            description=text,
                            path=current_path,
                            detection=detection,
                        )

                        continue

                    # -----------------------------------------
                    # DOWNLOAD
                    # -----------------------------------------

                    download_name = (
                        anchor.get(
                            "download"
                        )
                    )

                    if download_name:

                        hint = (
                            self.detector
                            .detect_url(
                                str(
                                    download_name
                                )
                            )
                        )

                        if hint.is_file:

                            self._register_file(
                                url=target,
                                source_page=final_url,

                                description=(
                                    text
                                    or str(
                                        download_name
                                    )
                                ),

                                path=current_path,

                                detection=hint,
                            )

                            continue

                    if self._max_depth_reached(
                        depth
                    ):
                        continue

                    child_path = (
                        self.adapter
                        .extend_path(
                            current_path,
                            text,
                            target,
                        )
                    )

                    self._queue_page(
                        queue,
                        url=target,
                        depth=(
                            depth + 1
                        ),
                        parent_url=final_url,
                        path=child_path,
                        text=text,
                    )

                # =================================================
                # FORM ACTIONS (GET)
                # =================================================

                if not self._max_depth_reached(
                    depth
                ):

                    for form in soup.find_all(
                        "form",
                        action=True,
                    ):

                        method = str(
                            form.get(
                                "method",
                                "get",
                            )
                            or "get"
                        ).strip().lower()

                        # No se ejecutan formularios POST de manera
                        # genérica: pueden crear efectos laterales o
                        # requerir parámetros/CSRF. Un adapter puede
                        # implementarlos cuando sea estrictamente
                        # necesario y seguro.
                        if method not in {
                            "",
                            "get",
                        }:
                            continue

                        target = self.normalize_url(
                            str(
                                form.get(
                                    "action"
                                )
                            ),
                            final_url,
                        )

                        if not target:
                            continue

                        if not self._allow_discovered_url(
                            target
                        ):
                            continue

                        child_path = (
                            self.adapter
                            .extend_path(
                                current_path,
                                "Formulario",
                                target,
                            )
                        )

                        self._queue_page(
                            queue,
                            url=target,
                            depth=(
                                depth + 1
                            ),
                            parent_url=final_url,
                            path=child_path,
                            text="Formulario",
                        )

                # =================================================
                # IFRAME / EMBED / OBJECT
                # =================================================

                embedded = []

                for tag in soup.find_all(
                    "iframe",
                    src=True,
                ):

                    embedded.append(
                        (
                            tag.get(
                                "src"
                            ),
                            "iframe",
                        )
                    )

                for tag in soup.find_all(
                    "embed",
                    src=True,
                ):

                    embedded.append(
                        (
                            tag.get(
                                "src"
                            ),
                            "embed",
                        )
                    )

                for tag in soup.find_all(
                    "object",
                    data=True,
                ):

                    embedded.append(
                        (
                            tag.get(
                                "data"
                            ),
                            "object",
                        )
                    )

                for (
                    raw_target,
                    label,
                ) in embedded:

                    target = (
                        self.normalize_url(
                            str(
                                raw_target
                            ),
                            final_url,
                        )
                    )

                    if not target:
                        continue

                    if not self._allow_discovered_url(
                        target
                    ):
                        continue

                    detection = (
                        self.detector
                        .detect_url(
                            target
                        )
                    )

                    if detection.is_file:

                        if (
                            target
                            in self.api_endpoints

                            or target
                            in self.openapi_endpoints
                        ):

                            if not self._max_depth_reached(
                                depth
                            ):

                                self._queue_page(
                                    queue,
                                    url=target,
                                    depth=(
                                        depth + 1
                                    ),
                                    parent_url=final_url,
                                    path=current_path,
                                    text=label,
                                    priority_override=0,
                                )

                            continue

                        self._register_file(
                            url=target,
                            source_page=final_url,
                            description=label,
                            path=current_path,
                            detection=detection,
                        )

                        continue

                    if self._max_depth_reached(
                        depth
                    ):
                        continue

                    self._queue_page(
                        queue,
                        url=target,
                        depth=(
                            depth + 1
                        ),
                        parent_url=final_url,
                        path=current_path,
                        text=label,
                    )

            except RequestException as exc:

                self._record_crawl_error(
                    result,
                    current_url,
                    (
                        "ERROR DE LECTURA -> "
                        f"{current_url} -> "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                )

                print(
                    f"[{self.source_id.upper()}] "
                    f"ERROR DE LECTURA | "
                    f"{type(exc).__name__} | "
                    f"{current_url}",
                    flush=True,
                )

                continue

            except (
                ValueError,
                UnicodeError,
            ) as exc:

                self._record_crawl_error(
                    result,
                    current_url,
                    (
                        "ERROR DE CONTENIDO -> "
                        f"{current_url} -> "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                )

                print(
                    f"[{self.source_id.upper()}] "
                    f"ERROR DE CONTENIDO | "
                    f"{type(exc).__name__} | "
                    f"{current_url}",
                    flush=True,
                )

                continue

            finally:

                if pagination_observe_url:
                    pagination_useful_after = (
                        len(
                            self.files_by_url
                        )
                        + len(
                            result.data_pages
                        )
                    )

                    direct_yield = max(
                        0,
                        pagination_useful_after
                        - pagination_useful_before,
                    )

                    discovery_yield = max(
                        0,
                        self.pagination_discovery_events
                        - pagination_discovery_before,
                    )

                    total_yield = (
                        direct_yield
                        + discovery_yield
                    )

                    self.pagination_yield_policy.note_page_yield(
                        pagination_observe_url,
                        useful_resources=total_yield,
                    )

                response.close()

        # ====================================================
        # FINAL
        # ====================================================

        # La deduplicación por contenido sucede al final del crawl para
        # no interferir con el descubrimiento ni con la relevancia.
        self._validate_duplicate_groups()

        result.files = list(
            self.files_by_url.values()
        )

        result.budget_metrics = (
            self.budget.metrics()
        )

        result.relevance_rejected = int(
            result.budget_metrics.get(
                "resources_rejected",
                0,
            )
        )

        duplicate_groups = {
            identity: candidates
            for identity, candidates
            in self.representation_candidates_by_identity.items()
            if len(candidates) >= 2
        }

        duplicate_resources = sum(
            len(candidates)
            for candidates in duplicate_groups.values()
        )

        # Para validar un grupo de N representaciones basta, inicialmente,
        # comparar N-1 contra una referencia. No contamos combinaciones
        # N*(N-1)/2 porque generaría trabajo innecesario.
        pending_content_checks = sum(
            max(
                0,
                len(candidates) - 1,
            )
            for candidates in duplicate_groups.values()
        )

        remaining_content_checks = max(
            0,
            pending_content_checks
            - self.dedupe_confirmed_duplicates
            - self.dedupe_content_different
            - self.dedupe_content_inconclusive
        )

        result.dedupe_metrics = {
            "candidate_groups": len(
                duplicate_groups
            ),
            "candidate_resources": (
                duplicate_resources
            ),
            "pending_content_checks": (
                remaining_content_checks
            ),
            "confirmed_duplicates": (
                self.dedupe_confirmed_duplicates
            ),
            "removed_representations": (
                self.dedupe_removed_representations
            ),
            "content_requests": (
                self.dedupe_content_requests
            ),
            "content_different": (
                self.dedupe_content_different
            ),
            "content_inconclusive": (
                self.dedupe_content_inconclusive
            ),
        }

        result.pagination_metrics = (
            self.pagination_yield_policy
            .metrics()
        )

        if self.pagination_yield_policy.enabled:
            print(
                f"[{self.source_id.upper()}] "
                f"PAGINACION RESULTADO | "
                f"familias={result.pagination_metrics.get('families_observed', 0)} | "
                f"productivas={result.pagination_metrics.get('productive_families', 0)} | "
                f"estancadas={result.pagination_metrics.get('stagnant_families', 0)} | "
                f"saltadas={result.pagination_metrics.get('pages_skipped', 0)}",
                flush=True,
            )

        print(
            f"[{self.source_id.upper()}] "
            f"DEDUPE RESULTADO | "
            f"grupos={result.dedupe_metrics['candidate_groups']} | "
            f"recursos={result.dedupe_metrics['candidate_resources']} | "
            f"confirmados={result.dedupe_metrics['confirmed_duplicates']} | "
            f"diferentes={result.dedupe_metrics['content_different']} | "
            f"inconclusos={result.dedupe_metrics['content_inconclusive']} | "
            f"eliminados={result.dedupe_metrics['removed_representations']} | "
            f"requests_extra={result.dedupe_metrics['content_requests']}",
            flush=True,
        )

        print(
            f"[{self.source_id.upper()}] "
            f"BUDGET | "
            f"req={result.budget_metrics.get('requests', 0)} | "
            f"utiles={result.budget_metrics.get('useful_resources', 0)} | "
            f"rechazados={result.relevance_rejected} | "
            f"sin_valor={result.budget_metrics.get('requests_without_value', 0)}",
            flush=True,
        )

        if result.api_probe_errors:
            print(
                f"[{self.source_id.upper()}] "
                f"API SONDEOS FALLIDOS | "
                f"total={len(result.api_probe_errors)}",
                flush=True,
            )

        result.duration_seconds = (
            time.monotonic()
            - started
        )

        return result