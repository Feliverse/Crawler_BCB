from __future__ import annotations

from urllib.parse import (
    unquote,
    urlparse,
)

from adapters.generic import GenericAdapter


HIGH_PRIORITY = (
    "/datos/",
    "/estadisticas/",
    "/reportes-de-estadisticas/",
    "/indicador/",
    "/boletines/",
    "/boletin/",
    "memoria-intitucional",
    "presupuesto",
    "ejecucion-presupuestaria",
    "fuente-de-financiamiento",
    "programas-y-proyectos",
    "informe",
    "reportes",
    "revistas",
    "publicaciones",
)


MEDIUM_PRIORITY = (
    "rendicion-publica",
    "rendicion_cuenta",
    "pei-descargable",
    "normativa",
    "resolucion",
    "leyes",
    "decretos",
)


LOW_PRIORITY = (
    "/nota_prensa/",
    "comunicados-de-prensa",
    "lista-notas-prensa",
    "/servidor_publico/",
    "nomina-de-servidores",
    "/personal/",
    "/proveedores/",
    "convocatorias",
    "contrataciones",
    "oportunidad-de-empleo",
    "perfiles-de-cargo",
    "perfiles-requeridos",
    "fotografias",
    "multimedia",
    "campanas-y-actividades",
    "enlaces-de-interes",
    "formulario-de-denuncias",
    "formulario-de-solicitud",
    "terminos-y-condiciones",
    "politica-privacidad",
)


BLOCK_PATHS = (
    "/nota_prensa/",
    "/servidor_publico/",
    "/comunicados-de-prensa/page/",
    "/nomina-de-servidores-publicos/page/",
    "/proveedores/page/",
    "/listado-de-convocatorias-vigentes-de-bienes-y-servicios/page/",
)


class MdrytAdapter(GenericAdapter):

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
            "ruralytierras.gob.bo",
            "www.ruralytierras.gob.bo",
        }:
            return False

        path = (
            parsed.path
            or ""
        ).lower()

        if any(
            blocked in path
            for blocked in BLOCK_PATHS
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
            return 2

        if any(
            token in searchable
            for token in MEDIUM_PRIORITY
        ):
            return 15

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

        if cleaned.isdigit():
            return current_path

        if cleaned.lower() in {
            "leer nota",
            "ver detalles",
            "siguiente",
            "anterior",
        }:
            return current_path

        return super().extend_path(
            current_path,
            text,
            url,
        )