from __future__ import annotations

from urllib.parse import (
    unquote,
    urlparse,
)

from adapters.generic import GenericAdapter


HIGH_PRIORITY = (
    "/estadisticas/",
    "/mercados/",
    "/estado-del-mercado/",
    "montos-negociados",
    "instrumentos-negociados",
    "tasas-de-rendimiento",
    "fondos-de-inversion",
    "calificaciones-de-riesgo",
    "reportes-de-calificacion",
    "resumen_diario",
    "informacion-financiera",
    "boletin",
    "bolsames",
    "estadisticas",
)


MEDIUM_PRIORITY = (
    "memorias-anuales",
    "bbv-sostenible",
    "publicaciones",
    "boletin",
    "reporte",
    "wp-content/uploads",
)


LOW_PRIORITY = (
    "/participantes-del-mercado/participante/",
    "noticias_fecha.aspx",
    "/noticias/",
    "/contacto/",
    "/acerca-de-la-bolsa/",
)


class BbvAdapter(
    GenericAdapter
):

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
            for keyword
            in HIGH_PRIORITY
        ):
            return 1

        if any(
            keyword in searchable
            for keyword
            in MEDIUM_PRIORITY
        ):
            return 10

        if (
            "/participantes-del-mercado/"
            "participante/"
            in searchable
        ):
            return 90

        if any(
            keyword in searchable
            for keyword
            in LOW_PRIORITY
        ):
            return 80

        return super().priority(
            url,
            text,
        )

    def should_detect_data(
        self,
        url: str,
        title: str,
    ) -> bool:

        parsed = urlparse(
            url
        )

        path = (
            parsed.path
            or ""
        ).lower()

        if (
            "/participantes-del-mercado/"
            "participante/"
            in path
        ):
            return False

        if (
            "noticias_fecha.aspx"
            in path
        ):
            return False

        return True

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

        return super().extend_path(
            current_path,
            text,
            url,
        )