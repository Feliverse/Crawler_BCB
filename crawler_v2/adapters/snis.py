from __future__ import annotations

import re

from urllib.parse import (
    unquote,
    urlparse,
)

from adapters.generic import GenericAdapter


HIGH_PRIORITY = (
    "/reportes/",
    "/reportes_vigilancia/",
    "/publicaciones/",
    "form_produccion_",
    "form_301",
    "form_vigi_",
    "form_tipo_vigi_",
    "produccion",
    "vigilancia",
    "estadistica",
    "estadisticas",
)


MEDIUM_PRIORITY = (
    "anuario",
    "boletin",
    "indicador",
    "mortalidad",
    "morbilidad",
    "natalidad",
    "salud",
)


LOW_PRIORITY = (
    "/noticias/",
    "/contacto/",
    "/nosotros/",
    "/galeria/",
    "/eventos/",
)


BLOCKED_HOSTS = {
    "reportes-rues.minsalud.gob.bo",
    "reportes-siahv.minsalud.gob.bo",
    "estadisticahechosvitales.minsalud.gob.bo",
}


# Estas páginas históricas ya fueron probadas
# y actualmente terminan en TIMEOUT.
OLD_GENERAL_REPORT = re.compile(
    r"/Reportes_Dinamicos/"
    r"WF_Reporte_Gral_"
    r"(200[1-9]|2010)\.aspx$",
    re.IGNORECASE,
)


class SnisAdapter(GenericAdapter):

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

        # Solamente portales SNIS / Ministerio de Salud.
        if not (
            hostname == "minsalud.gob.bo"
            or hostname.endswith(
                ".minsalud.gob.bo"
            )
        ):
            return False

        # Subdominios que en la prueba real
        # fallaron por DNS, timeout o SSL.
        if hostname in BLOCKED_HOSTS:
            return False

        path = (
            parsed.path
            or ""
        )

        # Reportes 2001-2010 que ya comprobamos
        # que consumen timeout sin devolver datos.
        if OLD_GENERAL_REPORT.search(
            path
        ):
            return False

        searchable = (
            unquote(url)
        ).lower()

        if any(
            token in searchable
            for token in LOW_PRIORITY
        ):
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
            token in searchable
            for token in HIGH_PRIORITY
        ):
            return 1

        if any(
            token in searchable
            for token in MEDIUM_PRIORITY
        ):
            return 10

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

        lowered = cleaned.lower()

        if cleaned.isdigit():
            return current_path

        if lowered in {
            "inicio",
            "volver",
            "anterior",
            "siguiente",
            "ver reporte",
            "consultar",
        }:
            return current_path

        return super().extend_path(
            current_path,
            text,
            url,
        )