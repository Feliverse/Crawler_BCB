from __future__ import annotations

import re

from urllib.parse import (
    unquote,
    urlparse,
)

from adapters.generic import GenericAdapter


BULLETIN_POST_PATTERN = re.compile(
    r"/index\.php/"
    r"\d{4}/"
    r"\d{2}/"
    r"\d{2}/"
    r"no-?\d+/?$",
    re.IGNORECASE,
)


HIGH_PRIORITY = (
    "indicadores-financieros",
    "indicadores-sociales",
    "indicadores_financieros",
    "indicadores_sociales",
    "reporte-financiero",
    "reporte-social",
    "boletin_financiero",
    "boletin_social",
    "boletines",
)


DOCUMENT_PRIORITY = (
    "category/documentos",
    "/documentos/",
    "memoria",
    "memorias",
)


LOW_PRIORITY = (
    "/publicaciones/",
    "educacion_financiera_rse",
    "/tag/",
    "/author/",
    "/feed/",
    "/comments/",
    "wp-json",
)


PAGINATION_LABELS = {
    "older",
    "newer",
    "← older",
    "older →",
    "← newer",
    "newer →",
    "anterior",
    "siguiente",
}


class AsofinAdapter(GenericAdapter):

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

        if hostname not in {
            "asofinbolivia.com",
            "www.asofinbolivia.com",
        }:
            return False

        searchable = unquote(
            url
        ).lower()

        # Secciones que no aportan al mapeo
        # estadístico/documental.
        if any(
            token in searchable
            for token in LOW_PRIORITY
        ):
            return False

        # WordPress puede crear muchas paginaciones.
        # Solo permitimos paginación en las áreas
        # que realmente necesitamos recorrer.
        if "/page/" in searchable:

            relevant_archive = any(
                token in searchable
                for token in (
                    "boletines",
                    "boletin_financiero",
                    "boletin_social",
                    "category/documentos",
                )
            )

            if not relevant_archive:
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

        # Gráficos y datasets.
        if any(
            token in searchable
            for token in (
                "reporte-financiero",
                "reporte-social",
                "indicadores-financieros",
                "indicadores-sociales",
                "indicadores_financieros",
                "indicadores_sociales",
            )
        ):
            return 1

        # Índices principales de boletines.
        if any(
            token in searchable
            for token in (
                "boletin_financiero",
                "boletin_social",
                "boletines",
            )
        ):
            return 2

        # Publicaciones individuales:
        # /2024/05/08/no-224/
        if BULLETIN_POST_PATTERN.search(
            urlparse(url).path
        ):
            return 3

        # Otros documentos útiles.
        if any(
            token in searchable
            for token in DOCUMENT_PRIORITY
        ):
            return 8

        if any(
            token in searchable
            for token in LOW_PRIORITY
        ):
            return 95

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

        lowered = (
            cleaned.lower()
        )

        # Evitamos jerarquías absurdas:
        # Boletines > 2 > 3 > 49
        if cleaned.isdigit():
            return current_path

        if lowered in PAGINATION_LABELS:
            return current_path

        return super().extend_path(
            current_path,
            text,
            url,
        )