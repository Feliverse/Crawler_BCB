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
    "cifras",
    "economica",
    "economicas",
    "financiera",
    "financieras",
    "mercado",
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
    def __init__(
        self,
        config: dict,
    ) -> None:
        self.config = config

    @staticmethod
    def _searchable_text(
        url: str,
        text: str,
    ) -> str:
        return (
            unquote(url)
            + " "
            + text
        ).lower()

    def should_follow(
        self,
        url: str,
    ) -> bool:
        lowered = url.lower()

        if any(
            token in lowered
            for token in IGNORE_KEYWORDS
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

        query = parse_qs(
            parsed.query
        )

        # Evita URLs generadas con cantidades absurdas
        # de filtros o parámetros.
        if len(query) > 8:
            return False

        return True

    def priority(
        self,
        url: str,
        text: str,
    ) -> int:
        searchable = self._searchable_text(
            url,
            text,
        )

        if any(
            keyword in searchable
            for keyword in HIGH_PRIORITY_KEYWORDS
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
        ):
            page_numbers = re.findall(
                r"\d+",
                parsed.query,
            )

            if page_numbers:
                largest = max(
                    int(value)
                    for value in page_numbers
                )

                if largest > 100:
                    return 80

            return 40

        if any(
            keyword in searchable
            for keyword in LOW_PRIORITY_KEYWORDS
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
            and len(cleaned) <= 100
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
            .replace("-", " ")
            .replace("_", " ")
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

        # Evita rutas enormes por navegación repetitiva.
        return new_path[-6:]

    def should_detect_data(
        self,
        url: str,
        title: str,
    ) -> bool:
        """
        Por defecto todas las páginas HTML pueden ser
        evaluadas por DataDetector.

        Los adapters específicos pueden sobrescribir este
        comportamiento para evitar falsos datasets.
        """

        return True