from __future__ import annotations

from urllib.parse import (
    unquote,
    urlparse,
)

from adapters.generic import GenericAdapter


# ============================================================
# BCB - RUTAS / TÉRMINOS DE DATOS
# ============================================================

DATA_KEYWORDS = (
    "estadistic",
    "reporte-estadistico",
    "boletin-estadistico",
    "serie",
    "series",
    "tipo-de-cambio",
    "ufv",
    "balanza-pagos",
    "balanza-de-pagos",
    "deuda-externa",
    "reservas",
    "reservas-internacionales",
    "mercado-diario",
    "mercado-semanal",
    "mercado-monetario",
    "sistema-pagos",
    "sistema-de-pagos",
    "estabilidad-financiera",
    "operaciones-mercado-abierto",
    "indicador",
    "indicadores",
    "sector-externo",
    "sector-monetario",
    "sector-fiscal",
    "inflacion",
    "inflación",
    "webdocs/sector_externo",
    "webdocs/sector_monetario",
)

# Términos que solo reciben prioridad media. No significan
# automáticamente que el recurso deba catalogarse.
MEDIUM_PRIORITY = (
    "boletin",
    "boletín",
    "informe",
    "anuario",
    "compendio",
)

# Contenido institucional / normativo que no aporta datasets por sí mismo.
LOW_PRIORITY = (
    "auditoria",
    "auditoría",
    "mision",
    "misión",
    "vision",
    "visión",
    "directorio",
    "personal",
    "historia",
    "transparencia",
    "reglamento",
    "normativa",
    "resolucion",
    "resolución",
    "convocatoria",
    "formulario",
    "rendicion-de-cuentas",
    "rendición-de-cuentas",
    "oportunidades-de-empleo",
    "memoria-institucional",
)

# Señales fuertes para descartar una URL de sitemap ANTES de hacer GET.
# Se mantienen conservadoras para no perder datos por un filtro demasiado
# agresivo.
SITEMAP_DROP_PATTERNS = (
    "/transparencia",
    "/auditoria",
    "/auditoría",
    "/mision",
    "/vision",
    "/historia",
    "/contacto",
    "/autoridades",
    "/organigrama",
    "/convocatoria",
    "/oportunidades-de-empleo",
    "/noticias",
    "/galeria",
)

# Contextos BCB que aumentan la confianza de que un recurso es de datos.
RELEVANCE_BOOST_PATTERNS = (
    "/webdocs/sector_externo/",
    "/webdocs/sector_monetario/",
    "/estadisticas",
    "/estadística",
    "/series",
    "/tipo-de-cambio",
    "/indicadores",
    "/balanza",
    "/reservas",
    "/sistema-de-pagos",
)

# Contextos que reducen relevancia aunque el recurso sea PDF/documento.
RELEVANCE_DROP_PATTERNS = (
    "/transparencia",
    "/auditoria",
    "/auditoría",
    "/reglamento",
    "/normativa",
    "/resoluciones",
    "/convocatoria",
    "/formularios",
    "/memorias-institucionales",
)

# Recursos administrativos/editoriales propios del BCB que pueden
# presentarse en formatos tabulares, pero no constituyen datasets
# estadísticos para el catálogo.
BCB_NON_DATA_PATTERNS = (
    "cronograma_anual_de_publicaciones",
    "cronograma anual de publicaciones",
    "descargar cronograma",
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
    """
    Adapter del Banco Central de Bolivia.

    El core continúa siendo responsable de HTTP, crawling, detección,
    relevancia y exportación. Este adapter solamente aporta conocimiento
    estructural del BCB mediante hooks.
    """

    # ========================================================
    # PRIORIDAD
    # ========================================================

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
            return 25

        if any(
            keyword in searchable
            for keyword in LOW_PRIORITY
        ):
            return 95

        return super().priority(
            url,
            text,
        )

    # ========================================================
    # RUTA
    # ========================================================

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

    # ========================================================
    # SITEMAP
    # ========================================================

    def should_follow_sitemap_url(
        self,
        url: str,
    ) -> bool:
        if not super().should_follow_sitemap_url(
            url
        ):
            return False

        lowered = unquote(
            url
        ).lower()

        if any(
            pattern in lowered
            for pattern in SITEMAP_DROP_PATTERNS
        ):
            return False

        return True

    # ========================================================
    # RELEVANCIA
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
        adjustment = super().relevance_adjustment(
            url=url,
            description=description,
            origin_url=origin_url,
            path=path,
            resource_type=resource_type,
        )

        searchable = " ".join(
            (
                unquote(str(url or "")),
                unquote(str(origin_url or "")),
                str(description or ""),
                " ".join(
                    str(item or "")
                    for item in path
                ),
            )
        ).lower()

        for pattern in RELEVANCE_BOOST_PATTERNS:
            if pattern in searchable:
                adjustment += 25

        for pattern in RELEVANCE_DROP_PATTERNS:
            if pattern in searchable:
                adjustment -= 80

        # Un XLSX puede ser técnicamente tabular y aun así no ser
        # un dataset. El cronograma de publicaciones del BCB es un
        # ejemplo concreto de contenido editorial/administrativo.
        for pattern in BCB_NON_DATA_PATTERNS:
            if pattern in searchable:
                adjustment -= 120

        # Las "memorias" dejaron de ser una señal positiva general.
        # Solo sobreviven si el motor encuentra evidencia estadística real.
        if (
            "memoria" in searchable
            and not any(
                keyword in searchable
                for keyword in (
                    "estadistic",
                    "serie",
                    "indicador",
                    "datos",
                    "data",
                    "cuadro",
                    "cifras",
                )
            )
        ):
            adjustment -= 50

        return adjustment

    # ========================================================
    # RUTA DE RECURSO
    # ========================================================

    def normalize_resource_path(
        self,
        *,
        path: tuple[str, ...] | list[str],
        url: str,
        description: str = "",
    ) -> tuple[str, ...]:
        normalized = list(
            super().normalize_resource_path(
                path=path,
                url=url,
                description=description,
            )
        )

        # Evitar etiquetas de paginación / números como carpetas finales.
        cleaned: list[str] = []

        for item in normalized:
            lowered = item.lower().strip()

            if lowered in PAGINATION_LABELS:
                continue

            if lowered.isdigit():
                continue

            if (
                cleaned
                and cleaned[-1].lower()
                == lowered
            ):
                continue

            cleaned.append(
                item
            )

        return tuple(
            cleaned
        )

    # ========================================================
    # AYUDA DE DIAGNÓSTICO
    # ========================================================

    @staticmethod
    def section_hint(
        url: str,
    ) -> str | None:
        """
        Devuelve una pista estructural sencilla del BCB.
        No afecta al contrato de salida.
        """

        path = unquote(
            urlparse(
                url
            ).path
            or ""
        ).lower()

        if "sector_externo" in path:
            return "SECTOR_EXTERNO"

        if "sector_monetario" in path:
            return "SECTOR_MONETARIO"

        if "sistema" in path and "pago" in path:
            return "SISTEMA_DE_PAGOS"

        return None
