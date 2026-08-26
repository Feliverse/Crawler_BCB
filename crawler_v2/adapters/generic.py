from __future__ import annotations

import re

from urllib.parse import (
    parse_qs,
    unquote,
    urlparse,
)


# ============================================================
# PRIORIDADES GENÉRICAS
# ============================================================

HIGH_PRIORITY_KEYWORDS = (
    "estadistica",
    "estadisticas",
    "statistics",
    "statistical",
    "datos",
    "data",
    "dataset",
    "datasets",
    "indicador",
    "indicadores",
    "indicator",
    "indicators",
    "serie",
    "series",
    "historico",
    "historica",
    "historical",
    "base-de-datos",
    "base de datos",
    "database",
    "cuadro-estadistico",
    "cuadro estadistico",
    "cuadro estadístico",
    "microdatos",
    "microdata",
    "cifras",
    "excel",
    "csv",
    "xlsx",
    "xls",
    "json",
    "geojson",
    "parquet",
    "zip",
    "api",
    "open-data",
    "open data",
    "descargar-datos",
    "descargar datos",
    "download-data",
    "download data",
)

# Términos que pueden llevar a datos, pero que por sí solos
# no deben tratarse como evidencia fuerte.
MEDIUM_PRIORITY_KEYWORDS = (
    "boletin",
    "boletines",
    "bulletin",
    "anuario",
    "anuarios",
    "reporte",
    "reportes",
    "report",
    "reports",
    "informe",
    "informes",
    "publicacion",
    "publicaciones",
    "publication",
    "publications",
    "descarga",
    "descargas",
    "download",
    "downloads",
)

LOW_PRIORITY_KEYWORDS = (
    "mision",
    "vision",
    "historia",
    "autoridades",
    "directorio",
    "contacto",
    "contact",
    "galeria",
    "gallery",
    "noticia",
    "noticias",
    "news",
    "evento",
    "eventos",
    "transparencia",
    "etica",
    "quienes-somos",
    "nosotros",
    "auditoria",
    "auditoría",
    "reglamento",
    "normativa",
    "resolucion",
    "resolución",
    "convocatoria",
    "formulario",
    "organigrama",
)

IGNORE_KEYWORDS = (
    "login",
    "logout",
    "wp-admin",
    "wp-login",
    "javascript:",
    "mailto:",
    "tel:",
)

STATIC_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".css",
    ".js",
    ".woff",
    ".woff2",
    ".ttf",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
)

# Archivos auxiliares que no son páginas HTML navegables ni datasets
# finales útiles por sí mismos. Se omiten de la frontera para evitar que
# el crawler consuma tiempo GET por GET en checksums/firmas.
NON_NAVIGABLE_SIDECAR_EXTENSIONS = (
    ".sha",
    ".sha1",
    ".sha224",
    ".sha256",
    ".sha384",
    ".sha512",
    ".md5",
    ".sig",
)

GENERIC_LABELS = {
    "",
    "leer mas",
    "leer más",
    "ver mas",
    "ver más",
    "más",
    "mas",
    "aqui",
    "aquí",
    "click",
    "inicio",
    "home",
}


class GenericAdapter:
    """
    Adapter genérico configurable.

    Responsabilidad:
    - decidir qué URLs vale la pena seguir;
    - priorizar rutas prometedoras;
    - mantener una ruta jerárquica razonable;
    - exponer hooks para que adapters específicos ajusten
      relevancia, sitemaps y catalogación SIN modificar el core.

    El adapter NO realiza HTTP y NO reemplaza al RelevanceEngine.
    """

    def __init__(
        self,
        config: dict,
    ) -> None:
        self.config = config

        self.high_priority_keywords = self._merge_tokens(
            HIGH_PRIORITY_KEYWORDS,
            config.get(
                "high_priority_keywords",
                [],
            ),
        )

        self.medium_priority_keywords = self._merge_tokens(
            MEDIUM_PRIORITY_KEYWORDS,
            config.get(
                "medium_priority_keywords",
                [],
            ),
        )

        self.low_priority_keywords = self._merge_tokens(
            LOW_PRIORITY_KEYWORDS,
            config.get(
                "low_priority_keywords",
                [],
            ),
        )

        self.ignore_keywords = self._merge_tokens(
            IGNORE_KEYWORDS,
            config.get(
                "ignore_url_patterns",
                [],
            ),
        )

        self.include_url_patterns = tuple(
            self._clean_tokens(
                config.get(
                    "include_url_patterns",
                    [],
                )
            )
        )

        self.relevance_positive_patterns = tuple(
            self._clean_tokens(
                config.get(
                    "adapter_positive_patterns",
                    [],
                )
            )
        )

        self.relevance_negative_patterns = tuple(
            self._clean_tokens(
                config.get(
                    "adapter_negative_patterns",
                    [],
                )
            )
        )

        try:
            self.max_query_params = max(
                0,
                int(
                    config.get(
                        "max_query_params",
                        8,
                    )
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            self.max_query_params = 8

        self.seed_urls = {
            self._canonical_for_scope(
                url
            )
            for url in [
                config.get(
                    "base_url",
                    "",
                ),
                *(
                    config.get(
                        "entrypoints",
                        [],
                    )
                    or []
                ),
            ]
            if str(
                url
                or ""
            ).strip()
        }

    # ========================================================
    # TOKENS
    # ========================================================

    @staticmethod
    def _clean_tokens(
        values,
    ) -> list[str]:
        if isinstance(
            values,
            str,
        ):
            values = [
                values
            ]

        if not isinstance(
            values,
            (
                list,
                tuple,
                set,
            ),
        ):
            return []

        result: list[str] = []

        for value in values:
            token = str(
                value
                or ""
            ).strip().lower()

            if (
                token
                and token not in result
            ):
                result.append(
                    token
                )

        return result

    @classmethod
    def _merge_tokens(
        cls,
        base: tuple[str, ...],
        extra,
    ) -> tuple[str, ...]:
        values = list(
            base
        )

        for token in cls._clean_tokens(
            extra
        ):
            if token not in values:
                values.append(
                    token
                )

        return tuple(
            values
        )

    # ========================================================
    # URL / TEXTO
    # ========================================================

    @staticmethod
    def _canonical_for_scope(
        url: str,
    ) -> str:
        value = str(
            url
            or ""
        ).strip()

        if not value:
            return ""

        parsed = urlparse(
            value
        )

        scheme = (
            parsed.scheme.lower()
        )

        hostname = (
            parsed.hostname
            or ""
        ).lower()

        path = (
            parsed.path
            or "/"
        )

        if (
            not scheme
            or not hostname
        ):
            return (
                value
                .rstrip("/")
                .lower()
            )

        return (
            f"{scheme}://"
            f"{hostname}"
            f"{path}"
        ).rstrip("/").lower()

    @staticmethod
    def _searchable_text(
        url: str,
        text: str,
    ) -> str:
        return (
            unquote(
                url
            )
            + " "
            + text
        ).lower()

    def _matches_include_scope(
        self,
        url: str,
    ) -> bool:
        if not self.include_url_patterns:
            return True

        canonical = (
            self._canonical_for_scope(
                url
            )
        )

        if canonical in self.seed_urls:
            return True

        lowered = (
            unquote(
                url
            )
            .lower()
        )

        return any(
            pattern in lowered
            for pattern
            in self.include_url_patterns
        )

    # ========================================================
    # NAVEGACIÓN
    # ========================================================

    def should_follow(
        self,
        url: str,
    ) -> bool:
        lowered = (
            unquote(
                url
            )
            .lower()
        )

        canonical = (
            self._canonical_for_scope(
                url
            )
        )

        is_explicit_seed = (
            canonical
            in self.seed_urls
        )

        # Un entrypoint explícitamente configurado puede ser inspeccionado
        # aunque su URL contenga una palabra normalmente ignorada.
        # Los enlaces descubiertos hacia login/logout siguen bloqueados.
        if (
            not is_explicit_seed
            and any(
                token in lowered
                for token
                in self.ignore_keywords
            )
        ):
            return False

        if not self._matches_include_scope(
            url
        ):
            return False

        parsed = urlparse(
            url
        )

        path = (
            parsed.path
            or ""
        ).lower()

        if path.endswith(
            STATIC_EXTENSIONS
        ):
            return False

        if path.endswith(
            NON_NAVIGABLE_SIDECAR_EXTENSIONS
        ):
            return False

        query = parse_qs(
            parsed.query
        )

        # Evita URLs generadas con cantidades absurdas
        # de filtros o parámetros.
        if (
            self.max_query_params > 0
            and len(
                query
            ) > self.max_query_params
        ):
            return False

        return True

    def priority(
        self,
        url: str,
        text: str,
    ) -> int:
        searchable = (
            self._searchable_text(
                url,
                text,
            )
        )

        if any(
            keyword in searchable
            for keyword
            in self.high_priority_keywords
        ):
            return 10

        if any(
            keyword in searchable
            for keyword
            in self.medium_priority_keywords
        ):
            return 30

        parsed = urlparse(
            url
        )

        query = parse_qs(
            parsed.query
        )

        if (
            "page" in query
            or "pagina" in query
            or "__pagina__" in query
            or "limitstart" in query
            or "offset" in query
        ):
            page_numbers = re.findall(
                r"\d+",
                parsed.query,
            )

            if page_numbers:
                largest = max(
                    int(
                        value
                    )
                    for value
                    in page_numbers
                )

                if largest > 100:
                    return 80

            return 40

        if any(
            keyword in searchable
            for keyword
            in self.low_priority_keywords
        ):
            return 80

        return 50

    # ========================================================
    # RUTA
    # ========================================================

    def label(
        self,
        text: str,
        url: str,
    ) -> str:
        cleaned = " ".join(
            text.split()
        ).strip()

        if (
            cleaned
            and cleaned.lower()
            not in GENERIC_LABELS
            and len(
                cleaned
            ) <= 100
        ):
            return cleaned

        parsed = urlparse(
            url
        )

        slug = (
            parsed.path
            .strip("/")
            .split("/")[-1]
        )

        slug = (
            slug
            .replace(
                "-",
                " ",
            )
            .replace(
                "_",
                " ",
            )
        )

        return (
            slug.strip()
            or "Inicio"
        )

    def extend_path(
        self,
        current_path: tuple[str, ...],
        text: str,
        url: str,
    ) -> tuple[str, ...]:
        label = self.label(
            text,
            url,
        )

        if not label:
            return current_path

        if (
            current_path
            and current_path[-1].lower()
            == label.lower()
        ):
            return current_path

        new_path = (
            *current_path,
            label,
        )

        try:
            max_route_depth = max(
                1,
                int(
                    self.config.get(
                        "max_route_depth",
                        6,
                    )
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            max_route_depth = 6

        return (
            new_path[
                -max_route_depth:
            ]
        )

    # ========================================================
    # DATA DETECTOR
    # ========================================================

    def should_detect_data(
        self,
        url: str,
        title: str,
    ) -> bool:
        """
        Por defecto todas las páginas HTML pueden ser evaluadas por
        DataDetector. Los adapters específicos pueden sobrescribir este
        comportamiento cuando una fuente requiera una regla más estricta.
        """

        return True

    # ========================================================
    # HOOKS DE RELEVANCIA
    # ========================================================

    def relevance_adjustment(
        self,
        *,
        url: str,
        description: str = "",
        origin_url: str = "",
        path: tuple[str, ...] | list[str] = (),
        resource_type: str = "",
    ) -> int:
        """
        Ajuste de puntuación adicional para RelevanceEngine.

        El core calcula primero la relevancia genérica. El adapter puede
        sumar/restar puntos sin duplicar la lógica de clasificación.
        """

        searchable = " ".join(
            (
                unquote(str(url or "")),
                unquote(str(origin_url or "")),
                str(description or ""),
                " ".join(
                    str(item or "")
                    for item in path
                ),
                str(resource_type or ""),
            )
        ).lower()

        adjustment = 0

        for pattern in self.relevance_positive_patterns:
            if pattern in searchable:
                adjustment += 20

        for pattern in self.relevance_negative_patterns:
            if pattern in searchable:
                adjustment -= 50

        return adjustment

    def should_keep_file(
        self,
        *,
        decision,
        url: str,
        description: str,
        origin_url: str,
        path: tuple[str, ...] | list[str],
        detection,
    ) -> bool:
        """
        Hook final para archivos.

        `decision` es RelevanceDecision. El comportamiento genérico
        conserva exactamente la decisión del motor.
        """

        return bool(
            getattr(
                decision,
                "keep",
                False,
            )
        )

    def should_keep_data_page(
        self,
        *,
        decision,
        url: str,
        description: str,
        origin_url: str | None,
        path: tuple[str, ...] | list[str],
        resource_type: str,
    ) -> bool:
        """
        Hook final para tablas, páginas de datos y APIs.
        """

        return bool(
            getattr(
                decision,
                "keep",
                False,
            )
        )

    # ========================================================
    # HOOK DE SITEMAP
    # ========================================================

    def should_follow_sitemap_url(
        self,
        url: str,
    ) -> bool:
        """
        Permite que un adapter filtre URLs provenientes de sitemap
        antes de que consuman una solicitud HTTP.

        Por defecto se aplican las mismas reglas básicas de navegación.
        """

        return self.should_follow(
            url
        )

    # ========================================================
    # HOOK DE NORMALIZACIÓN DE RUTA
    # ========================================================

    def normalize_resource_path(
        self,
        *,
        path: tuple[str, ...] | list[str],
        url: str,
        description: str = "",
    ) -> tuple[str, ...]:
        """
        Permite corregir rutas de salida sin modificar el contrato JSON.
        """

        cleaned = []

        for item in path:
            value = " ".join(
                str(item or "").split()
            ).strip()

            if not value:
                continue

            if (
                cleaned
                and cleaned[-1].lower()
                == value.lower()
            ):
                continue

            cleaned.append(
                value
            )

        return tuple(
            cleaned
        )