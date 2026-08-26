from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

from adapters.generic import GenericAdapter


# En ATT solo necesitamos navegar el portal web principal.
# Los documentos pueden seguir apuntando a portal.att.gob.bo u otros
# hosts públicos, pero no necesitamos entrar a sus aplicaciones.
CRAWL_HOSTS = {
    "att.gob.bo",
    "www.att.gob.bo",
}


DATA_KEYWORDS = (
    "estadistica",
    "estadisticas",
    "estadistica-sectorial",
    "informacion-estadistica",
    "serie-historica",
    "situacion-de-las-telecomunicaciones",
    "telecomunicaciones",
    "transportes",
    "postal",
    "extractos-publicacion",
    "boletin",
    "boletines",
    "indicadores",
    "datos",
    "series",
)


DOCUMENT_KEYWORDS = (
    "memoria",
    "auditoria",
    "auditorias",
    "presupuesto",
    "rendicion",
    "planificacion",
    "plan-operativo",
    "poa",
    "pei",
    "financiamiento",
    "normativa",
    "regulacion",
    "informe",
    "informes",
    "publicacion",
)


LOW_VALUE_KEYWORDS = (
    "notas-prensa",
    "nota-prensa",
    "resena-historica",
    "objetivos-estrategicos",
    "denuncias-reclamos",
    "seguimiento-de-tramite",
)


class AttAdapter(GenericAdapter):
    """
    Reglas específicas del portal ATT.

    El core sigue siendo genérico. Este adapter únicamente evita
    navegación irrelevante y prioriza las áreas que contienen datos
    y documentos.
    """

    def should_follow(
        self,
        url: str,
    ) -> bool:
        if not super().should_follow(url):
            return False

        parsed = urlparse(url)

        hostname = (
            parsed.hostname
            or ""
        ).lower()

        # Evita entrar en:
        # plataformas.att.gob.bo
        # sis.att.gob.bo
        # mivuelo.att.gob.bo
        # portabilidad.att.gob.bo
        # etc.
        if hostname not in CRAWL_HOSTS:
            return False

        path = (
            parsed.path
            or "/"
        ).lower()

        query = parse_qs(
            parsed.query
        )

        # ATT genera cientos de páginas del HOME:
        # /?page=0
        # /?page=1
        # /en?page=0
        #
        # No son necesarias para mapear los datasets/documentos.
        if "page" in query:
            if path in {
                "/",
                "/en",
                "/en/",
            }:
                return False

            # Tampoco queremos consumir el crawl recorriendo
            # cientos de noticias.
            if (
                "notas-prensa" in path
                or "nota-prensa" in path
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

        # Máxima prioridad.
        if any(
            keyword in searchable
            for keyword in DATA_KEYWORDS
        ):
            return 2

        # Documentación institucional que también interesa mapear.
        if any(
            keyword in searchable
            for keyword in DOCUMENT_KEYWORDS
        ):
            return 10

        # Páginas útiles pero no prioritarias.
        if any(
            keyword in searchable
            for keyword in LOW_VALUE_KEYWORDS
        ):
            return 90

        return super().priority(
            url,
            text,
        )