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

from requests.exceptions import (
    RequestException,
    Timeout,
)

from adapters.generic import GenericAdapter

from core.data_detector import DataDetector

from core.file_detector import (
    FileDetection,
    FileDetector,
)

from core.http_client import HttpClient

from core.metadata import (
    clean_text,
    extract_date,
    filename_from_url,
)

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

    contenido_zip: list[str] = field(
        default_factory=list
    )

    zip_inspeccion: str | None = None

    zip_bytes_descargados: int = 0


@dataclass
class CrawlResult:
    pages: list[PageRecord] = field(
        default_factory=list
    )

    files: list[FileRecord] = field(
        default_factory=list
    )

    data_pages: list[DataPageRecord] = field(
        default_factory=list
    )

    errors: list[str] = field(
        default_factory=list
    )

    stop_reason: str = (
        "frontier_exhausted"
    )

    duration_seconds: float = 0.0


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

        self.zip_inspector = ZipInspector(
            client
        )

        self.data_detector = (
            DataDetector()
        )

        self.source_id = str(
            config["id_fuente"]
        )

        self.allowed_domains = tuple(
            domain.lower()
            for domain in config.get(
                "allowed_domains",
                [],
            )
        )

        self.visited: set[str] = set()

        self.queued: set[str] = set()

        self.files_by_url: dict[
            str,
            FileRecord,
        ] = {}

        self.sequence = (
            itertools.count()
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

        value = url.strip()

        if not value:
            return None

        lowered = value.lower()

        if lowered.startswith(
            (
                "mailto:",
                "tel:",
                "javascript:",
                "data:",
            )
        ):
            return None

        if value.startswith("#"):
            return None

        if base_url:
            value = urljoin(
                base_url,
                value,
            )

        parsed = urlparse(
            value
        )

        if parsed.scheme.lower() not in {
            "http",
            "https",
        }:
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

        parsed = urlparse(
            url
        )

        hostname = (
            parsed.hostname
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
            ip = ipaddress.ip_address(
                hostname
            )

        except ValueError:
            # Dominio DNS normal.
            return True

        if ip.is_private:
            return False

        if ip.is_loopback:
            return False

        if ip.is_link_local:
            return False

        if ip.is_multicast:
            return False

        if ip.is_unspecified:
            return False

        if ip.is_reserved:
            return False

        return True

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
    # LÍMITES
    # ========================================================

    def _max_depth_reached(
        self,
        depth: int,
    ) -> bool:

        max_depth = self.config.get(
            "max_depth"
        )

        if max_depth is None:
            return False

        return (
            depth
            >= int(max_depth)
        )

    def _max_pages_reached(
        self,
        result: CrawlResult,
    ) -> bool:

        max_pages = self.config.get(
            "max_pages"
        )

        if max_pages is None:
            return False

        return (
            len(result.pages)
            >= int(max_pages)
        )

    def _max_files_reached(
        self,
    ) -> bool:

        max_files = self.config.get(
            "max_files"
        )

        if max_files is None:
            return False

        return (
            len(self.files_by_url)
            >= int(max_files)
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
    ) -> None:

        normalized = (
            self.normalize_url(
                url
            )
        )

        if not normalized:
            return

        # Evita registrar IP privadas,
        # localhost, etc.
        if not self.is_public_web_url(
            normalized
        ):
            print(
                f"[{self.source_id.upper()}] "
                f"DESCARTADO URL PRIVADA | "
                f"{normalized}",
                flush=True,
            )

            return

        # Dedupe de archivos.
        existing = (
            self.files_by_url.get(
                normalized
            )
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

            return

        if self._max_files_reached():
            return

        description = clean_text(
            description
        )

        if not description:
            description = (
                filename_from_url(
                    normalized
                )
            )

        # ----------------------------------------------------
        # ZIP
        # ----------------------------------------------------

        contenido_zip = []

        zip_status = None

        zip_bytes = 0

        if detection.file_type == "zip":

            print(
                f"[{self.source_id.upper()}] "
                f"ZIP REMOTO | "
                f"inspeccionando índice | "
                f"{normalized}",
                flush=True,
            )

            zip_result = (
                self.zip_inspector.inspect(
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

            print(
                f"[{self.source_id.upper()}] "
                f"ZIP | "
                f"estado={zip_status} | "
                f"internos={len(contenido_zip)} | "
                f"bytes={zip_bytes}",
                flush=True,
            )

        # ----------------------------------------------------
        # REGISTRO
        # ----------------------------------------------------

        record = FileRecord(
            id_fuente=self.source_id,

            descripcion=description,

            url_descarga=normalized,

            url_origen=source_page,

            origenes=[
                source_page
            ],

            tipo_archivo=(
                detection.file_type
            ),

            extension=(
                detection.extension
            ),

            fecha_actualizacion=(
                extract_date(
                    normalized,
                    description,
                )
            ),

            ruta=list(
                path
            ),

            metodo_deteccion=(
                detection.method
            ),

            content_type=(
                detection.content_type
            ),

            contenido_zip=(
                contenido_zip
            ),

            zip_inspeccion=(
                zip_status
            ),

            zip_bytes_descargados=(
                zip_bytes
            ),
        )

        self.files_by_url[
            normalized
        ] = record

        total = len(
            self.files_by_url
        )

        if (
            total <= 10
            or total % 25 == 0
        ):
            print(
                f"[{self.source_id.upper()}] "
                f"ARCHIVOS={total} | "
                f"{record.tipo_archivo or '?'} | "
                f"{normalized}",
                flush=True,
            )

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

        if normalized in self.visited:
            return

        if normalized in self.queued:
            return

        if not self.is_allowed(
            normalized
        ):
            return

        if not self.adapter.should_follow(
            normalized
        ):
            return

        if priority_override is not None:

            priority = (
                priority_override
            )

        else:

            priority = (
                self.adapter.priority(
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

    # ========================================================
    # CRAWL
    # ========================================================

    def crawl(
        self,
    ) -> CrawlResult:

        result = CrawlResult()

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

        # ----------------------------------------------------
        # SEEDS
        # ----------------------------------------------------

        for entrypoint in entrypoints:

            normalized = (
                self.normalize_url(
                    entrypoint
                )
            )

            if not normalized:
                continue

            self._queue_page(
                queue,
                url=normalized,
                depth=0,
                parent_url=None,
                path=(),
                text="",
                priority_override=0,
            )

        # ----------------------------------------------------
        # LOOP PRINCIPAL
        # ----------------------------------------------------

        while queue:

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

            if current_url in self.visited:
                continue

            elapsed = (
                time.monotonic()
                - started
            )

            print(
                f"[{self.source_id.upper()}] "
                f"t={elapsed:6.1f}s | "
                f"pag={len(result.pages):3} | "
                f"files={len(self.files_by_url):4} | "
                f"cola={len(queue):4} | "
                f"prio={priority:2} | "
                f"{current_url}",
                flush=True,
            )

            # ------------------------------------------------
            # REQUEST
            # ------------------------------------------------

            try:
                response = (
                    self.client.get(
                        current_url
                    )
                )

            except Timeout:

                message = (
                    f"TIMEOUT -> "
                    f"{current_url}"
                )

                result.errors.append(
                    message
                )

                print(
                    f"[{self.source_id.upper()}] "
                    f"{message}",
                    flush=True,
                )

                self.visited.add(
                    current_url
                )

                continue

            except RequestException as exc:

                message = (
                    f"{current_url} -> "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

                result.errors.append(
                    message
                )

                print(
                    f"[{self.source_id.upper()}] "
                    f"ERROR -> "
                    f"{current_url}",
                    flush=True,
                )

                self.visited.add(
                    current_url
                )

                continue

            # ------------------------------------------------
            # RESPUESTA
            # ------------------------------------------------

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

                # ============================================
                # DEDUPE DE REDIRECTS
                # ============================================
                #
                # Ejemplo BBV:
                #
                # www2.bbv.com.bo/estadisticas/
                # www2.bbv.com.bo/bbv-insight/
                #
                # podían terminar ambos en:
                #
                # www.bbv.com.bo/
                #
                # Si esa URL final ya fue procesada,
                # no repetimos toda la página.
                # ============================================

                if (
                    final_url in self.visited
                    and final_url != current_url
                ):
                    self.visited.add(
                        current_url
                    )

                    continue

                # ------------------------------------------------
                # DOMINIO
                # ------------------------------------------------

                if not self.is_allowed(
                    final_url
                ):

                    result.errors.append(
                        "Redirect fuera del dominio permitido: "
                        f"{current_url} -> "
                        f"{final_url}"
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

                # ------------------------------------------------
                # ¿LA RESPUESTA ES UN ARCHIVO?
                # ------------------------------------------------

                response_detection = (
                    self.detector.detect_response(
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

                # ------------------------------------------------
                # SOLO HTML
                # ------------------------------------------------

                content_type = (
                    response.headers
                    .get(
                        "Content-Type",
                        "",
                    )
                    .lower()
                )

                if (
                    "html"
                    not in content_type
                    and
                    "xhtml"
                    not in content_type
                ):
                    continue

                html = response.text

                soup = BeautifulSoup(
                    html,
                    "html.parser",
                )

                # ------------------------------------------------
                # TITLE
                # ------------------------------------------------

                title = ""

                if soup.title:

                    title = clean_text(
                        soup.title.get_text(
                            " ",
                            strip=True,
                        )
                    )

                # ------------------------------------------------
                # PÁGINA
                # ------------------------------------------------

                page_record = PageRecord(
                    url=final_url,

                    title=title,

                    parent_url=parent_url,

                    depth=depth,

                    path=list(
                        current_path
                    ),
                )

                result.pages.append(
                    page_record
                )

                # =================================================
                # DETECCIÓN DE DATASETS WEB
                # =================================================
                #
                # El adapter puede decidir que una página NO
                # debe analizarse como dataset.
                #
                # BBV usa esto para evitar que las fichas de
                # participantes sean consideradas datasets.
                # =================================================

                should_detect_data = (
                    self.adapter.should_detect_data(
                        final_url,
                        title,
                    )
                )

                if should_detect_data:

                    data_detection = (
                        self.data_detector.detect(
                            soup,
                            title,
                            final_url,
                        )
                    )

                else:

                    data_detection = None

                if (
                    data_detection is not None
                    and data_detection.is_data_page
                ):

                    data_record = DataPageRecord(
                        id_fuente=self.source_id,

                        descripcion=(
                            title
                            or final_url
                        ),

                        url=final_url,

                        url_origen=parent_url,

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
                            data_detection.has_table
                        ),

                        tablas_detectadas=(
                            data_detection.tables_count
                        ),

                        permite_exportar=(
                            data_detection.has_export
                        ),

                        tiene_filtros=(
                            data_detection.has_filters
                        ),

                        metodo_deteccion=(
                            data_detection.reason
                            or "data_page"
                        ),
                    )

                    result.data_pages.append(
                        data_record
                    )

                    total_data = len(
                        result.data_pages
                    )

                    if (
                        total_data <= 10
                        or total_data % 25 == 0
                    ):
                        print(
                            f"[{self.source_id.upper()}] "
                            f"DATASETS={total_data} | "
                            f"{data_record.metodo_deteccion} | "
                            f"{final_url}",
                            flush=True,
                        )

                # =================================================
                # LINKS <a href="">
                # =================================================

                for anchor in soup.find_all(
                    "a",
                    href=True,
                ):

                    href = anchor.get(
                        "href"
                    )

                    if not href:
                        continue

                    target = (
                        self.normalize_url(
                            href,
                            final_url,
                        )
                    )

                    if not target:
                        continue

                    text = clean_text(
                        anchor.get_text(
                            " ",
                            strip=True,
                        )
                    )

                    # ---------------------------------------------
                    # ARCHIVO DIRECTO
                    # ---------------------------------------------

                    detection = (
                        self.detector.detect_url(
                            target
                        )
                    )

                    if detection.is_file:

                        self._register_file(
                            url=target,

                            source_page=(
                                final_url
                            ),

                            description=text,

                            path=current_path,

                            detection=detection,
                        )

                        continue

                    # ---------------------------------------------
                    # <a download="">
                    # ---------------------------------------------

                    download_name = (
                        anchor.get(
                            "download"
                        )
                    )

                    if download_name:

                        hint_detection = (
                            self.detector.detect_url(
                                str(
                                    download_name
                                )
                            )
                        )

                        if hint_detection.is_file:

                            self._register_file(
                                url=target,

                                source_page=(
                                    final_url
                                ),

                                description=(
                                    text
                                    or str(
                                        download_name
                                    )
                                ),

                                path=current_path,

                                detection=(
                                    hint_detection
                                ),
                            )

                            continue

                    # ---------------------------------------------
                    # PROFUNDIDAD
                    # ---------------------------------------------

                    if self._max_depth_reached(
                        depth
                    ):
                        continue

                    child_path = (
                        self.adapter.extend_path(
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

                        parent_url=(
                            final_url
                        ),

                        path=child_path,

                        text=text,
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

                    detection = (
                        self.detector.detect_url(
                            target
                        )
                    )

                    if detection.is_file:

                        self._register_file(
                            url=target,

                            source_page=(
                                final_url
                            ),

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

                        parent_url=(
                            final_url
                        ),

                        path=current_path,

                        text=label,
                    )

            finally:

                response.close()

        # ========================================================
        # FINAL
        # ========================================================

        result.files = list(
            self.files_by_url.values()
        )

        result.duration_seconds = (
            time.monotonic()
            - started
        )

        return result