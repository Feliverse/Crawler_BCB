from __future__ import annotations

import re

from urllib.parse import (
    parse_qs,
    unquote,
    urlparse,
)


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
    "boletin",
    "boletines",
    "bulletin",
    "anuario",
    "anuarios",
    "publicacion",
    "publicaciones",
    "publication",
    "publications",
    "reporte",
    "reportes",
    "report",
    "reports",
    "informe",
    "informes",
    "descarga",
    "descargas",
    "download",
    "downloads",
    "archivo",
    "archivos",
    "documento",
    "documentos",
    "cifras",
    "economica",
    "economicas",
    "financiera",
    "financieras",
    "mercado",
    "catalogo",
    "catalog",
    "excel",
    "csv",
    "xlsx",
    "zip",
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

    La mayor parte de las fuentes deben poder resolverse con este adapter
    más un archivo JSON de configuración. Los adapters específicos quedan
    reservados para comportamientos que no se puedan expresar mediante:

    - entrypoints
    - allowed_domains
    - prioridades adicionales
    - inclusión/exclusión de rutas
    - configuración de detección de datos
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
            return 70

        return 50

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