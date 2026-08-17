from __future__ import annotations

from urllib.parse import (
    parse_qs,
    unquote,
    urlparse,
)

from adapters.generic import GenericAdapter


DATA_KEYWORDS = (
    "estadistic",
    "reporte-estadistico",
    "boletines-mensuales",
    "serie",
    "series",
    "tipo-de-cambio",
    "ufv",
    "balanza-pagos",
    "deuda-externa",
    "reservas",
    "mercado-diario",
    "mercado-semanal",
    "mercado-monetario",
    "sistema-pagos",
    "informe-de-estabilidad",
    "operaciones-mercado-abierto",
    "indicador",
    "publicaciones",
    "memorias",
)

MEDIUM_PRIORITY = (
    "informe",
    "boletin",
    "compendio",
    "jornada",
    "economistas",
)

LOW_PRIORITY = (
    "auditoria",
    "mision",
    "vision",
    "directorio",
    "personal",
    "historia",
    "transparencia",
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


class BcbAdapter(GenericAdapter):

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
            for keyword in MEDIUM_PRIORITY
        ):
            return 15

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

        if cleaned.isdigit():
            return current_path

        if cleaned.lower() in PAGINATION_LABELS:
            return current_path

        return super().extend_path(
            current_path,
            text,
            url,
        )