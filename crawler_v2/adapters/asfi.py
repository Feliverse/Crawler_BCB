from __future__ import annotations

from urllib.parse import (
    parse_qs,
    unquote,
    urlparse,
)

from adapters.generic import GenericAdapter


DATA_KEYWORDS = (
    "estadistica",
    "estadisticas",
    "boletin-estadistico",
    "boletines-estadisticos",
    "serie-historica",
    "series-historicas",
    "indicadores-financieros",
    "anuario-estadistico",
    "reportes-dinamicos",
    "mercado-valores",
    "intermediacion-financiera",
    "datos-sobre-reclamos",
    "estadisticas-reclamos",
    "inclusion-financiera",
    "publicaciones",
)

LOW_PRIORITY = (
    "resena-historica",
    "educacion-financiera",
    "actividad-financiera-ilegal",
    "spots",
    "denunciar",
)

PAGINATION_LABELS = {
    "siguiente",
    "siguiente ›",
    "siguiente »",
    "anterior",
    "última »",
    "ultima »",
    "primera «",
}


class AsfiAdapter(GenericAdapter):

    def should_follow(
        self,
        url: str,
    ) -> bool:
        if not super().should_follow(
            url
        ):
            return False

        parsed = urlparse(
            url
        )

        hostname = (
            parsed.hostname
            or ""
        ).lower()

        # No recorremos las aplicaciones ASPX.
        # Se mapearán como sistemas externos,
        # pero no deben consumir las páginas del crawl.
        if hostname.startswith(
            "appweb"
        ):
            return False

        path = (
            parsed.path
            or ""
        ).lower()

        # Prensa histórica estaba consumiendo
        # demasiadas páginas.
        if "pagina-lista-articulos" in path:
            return False

        return True

    def priority(
        self,
        url: str,
        text: str,
    ) -> int:
        searchable = (
            unquote(url)
            + " "
            + text
        ).lower()

        if any(
            keyword in searchable
            for keyword in DATA_KEYWORDS
        ):
            return 2

        if any(
            keyword in searchable
            for keyword in LOW_PRIORITY
        ):
            return 90

        return super().priority(
            url,
            text,
        )

    def extend_path(
        self,
        current_path: tuple[str, ...],
        text: str,
        url: str,
    ) -> tuple[str, ...]:

        cleaned = " ".join(
            text.split()
        ).strip()

        # No queremos:
        # Boletines > 2 > 3 > 4
        if cleaned.isdigit():
            return current_path

        if cleaned.lower() in PAGINATION_LABELS:
            return current_path

        return super().extend_path(
            current_path,
            text,
            url,
        )