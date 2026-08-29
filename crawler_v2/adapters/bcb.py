from __future__ import annotations

from urllib.parse import (
    unquote,
    urlparse,
)

from adapters.generic import GenericAdapter
from core.duplicate_validator import extract_period_token
from core.resource_dedupe import RepresentationCandidate


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

# Páginas web del BCB que pueden contener controles/filtros de interfaz,
# pero cuyo objetivo es publicar documentos, no exponer un dataset.
NON_DATA_WEB_PAGE_PATTERNS = (
    "pub_documentos-trabajo",
    "documentos-trabajo",
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
    # PROFUNDIDAD ADAPTATIVA
    # ========================================================

    def should_follow_at_depth(
        self,
        *,
        url: str,
        text: str,
        next_depth: int,
        soft_max_depth: int | None,
    ) -> bool:
        # Primero se respetan todas las reglas genéricas y el hard limit.
        generic_decision = super().should_follow_at_depth(
            url=url,
            text=text,
            next_depth=next_depth,
            soft_max_depth=soft_max_depth,
        )

        if generic_decision:
            return True

        if soft_max_depth is None:
            return False

        try:
            soft_limit = max(
                0,
                int(
                    soft_max_depth
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            return False

        if next_depth <= soft_limit:
            return False

        if not bool(
            self.config.get(
                "adaptive_depth_enabled",
                False,
            )
        ):
            return False

        try:
            hard_limit = max(
                soft_limit,
                int(
                    self.config.get(
                        "adaptive_max_depth",
                        soft_limit,
                    )
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            hard_limit = soft_limit

        if next_depth > hard_limit:
            return False

        if not self.should_follow(
            url
        ):
            return False

        searchable = (
            unquote(
                str(
                    url
                    or ""
                )
            )
            + " "
            + str(
                text
                or ""
            )
        ).lower()

        # Nunca profundizamos más allá del límite normal en ramas
        # institucionales, normativas o administrativas.
        if any(
            keyword in searchable
            for keyword in LOW_PRIORITY
        ):
            return False

        # BCB sí puede profundizar en una rama cuando la propia URL/texto
        # mantiene una señal estadística fuerte.
        if any(
            keyword in searchable
            for keyword in DATA_KEYWORDS
        ):
            return True

        if any(
            pattern in searchable
            for pattern in RELEVANCE_BOOST_PATTERNS
        ):
            return True

        return False

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
    # DATA PAGES
    # ========================================================

    def should_keep_data_page(
        self,
        *,
        decision,
        url: str,
        description: str,
        origin_url: str | None,
        path: tuple[str, ...] | list[str],
        resource_type: str,
    ) -> bool:
        searchable = " ".join(
            (
                unquote(str(url or "")),
                unquote(str(origin_url or "")),
                str(description or ""),
                " ".join(
                    str(item or "")
                    for item in path
                ),
                str(resource_type or ""),
            )
        ).lower()

        # "Serie de Documentos de Trabajo" puede verse técnicamente como
        # una página exportable por sus controles HTML, pero no representa
        # un dataset estadístico reutilizable.
        if any(
            pattern in searchable
            for pattern in NON_DATA_WEB_PAGE_PATTERNS
        ):
            return False

        return super().should_keep_data_page(
            decision=decision,
            url=url,
            description=description,
            origin_url=origin_url,
            path=path,
            resource_type=resource_type,
        )

    # ========================================================
    # IDENTIDAD SEMÁNTICA DE RECURSOS
    # ========================================================

    def semantic_resource_identity(
        self,
        candidate: RepresentationCandidate,
    ) -> str | None:
        """
        Devuelve una identidad semántica conservadora para candidatos
        que el BCB publica en más de una representación.

        Importante:
        - esta identidad NO elimina nada;
        - solamente permite formar un par candidato;
        - la decisión final exige comparación de contenido real.

        En Sistema de Pagos, el BCB publica el mismo reporte mensual
        normalmente como XLSX y ODS, y los nombres técnicos pueden variar
        entre ambos formatos. Por eso la identidad se basa en:
            colección + periodo

        No hacemos esto para Boletín Mensual, Boletín Estadístico, BOP,
        PII, etc., porque una misma fecha/periodo puede contener muchos
        datasets distintos.
        """

        searchable = " ".join(
            (
                unquote(
                    str(
                        candidate.url
                        or ""
                    )
                ),
                unquote(
                    str(
                        candidate.origin_url
                        or ""
                    )
                ),
                str(
                    candidate.description
                    or ""
                ),
            )
        ).lower()

        is_system_payments_report = (
            "/webdocs/sistema_pagos/"
            in searchable
            or "q=reporte-estadistico"
            in searchable
            or "q=reporte estadistico"
            in searchable
        )

        if not is_system_payments_report:
            return None

        period = extract_period_token(
            candidate
        )

        if not period:
            # Sin periodo explícito no existe evidencia suficiente para
            # agrupar dos nombres distintos. El motor genérico todavía
            # podrá reconocer pares cuyo nombre base sea exactamente igual.
            return None

        return (
            "bcb|"
            "sistema_pagos|"
            "reporte_estadistico|"
            + period
        )

    # ========================================================
    # RUTA DE RECURSO
    # ========================================================

    def normalize_resource_path(
        self,
        *,
        path: tuple[str, ...] | list[str],
        url: str,
        description: str = "",
        origin_url: str = "",
    ) -> tuple[str, ...]:
        normalized = list(
            super().normalize_resource_path(
                path=path,
                url=url,
                description=description,
                origin_url=origin_url,
            )
        )

        searchable = " ".join(
            (
                unquote(str(url or "")),
                unquote(str(origin_url or "")),
                str(description or ""),
            )
        ).lower()

        # ----------------------------------------------------
        # CLASIFICACIÓN ESTRUCTURAL BCB
        # ----------------------------------------------------
        #
        # No se enumeran archivos individuales. Se usan patrones de las
        # secciones/hubs oficiales para evitar que datasets valiosos
        # terminen en OTROS > DOCUMENTOS_GENERALES > VARIOS.
        #
        section: tuple[str, ...] | None = None

        if (
            "/webdocs/sector_externo/" in searchable
            or "sector-externo" in searchable
            or "sector_externo" in searchable
        ):
            section = (
                "Sector_Externo",
            )

        elif (
            "/webdocs/sector_monetario/" in searchable
            or "sector-monetario" in searchable
            or "sector_monetario" in searchable
        ):
            section = (
                "Sector_Monetario",
            )

        elif (
            "/webdocs/sistema_pagos/" in searchable
            or "reporte-estadistico" in searchable
            or "sistema-de-pagos" in searchable
            or "sistema_pagos" in searchable
        ):
            section = (
                "Sistema_de_Pagos",
            )

        elif (
            "pub_boletin-mensual" in searchable
            or "boletin-mensual" in searchable
        ):
            section = (
                "Boletin_Mensual",
            )

        elif (
            "pub_boletin-estadistico" in searchable
            or "boletin-estadistico" in searchable
        ):
            section = (
                "Boletin_Estadistico",
            )

        elif (
            "indicadores_inflacion" in searchable
            or "reporte-inflacion-politica-monetaria" in searchable
            or "/webdocs/ripm/" in searchable
            or "ripom" in searchable
        ):
            section = (
                "Inflacion_y_Politica_Monetaria",
            )

        elif (
            "sector-financiero-embed" in searchable
            or "sector-financiero" in searchable
        ):
            section = (
                "Sector_Financiero",
            )

        elif (
            "tipo-de-cambio" in searchable
            or "tipo de cambio" in searchable
            or "cotizacion" in searchable
            or "cotización" in searchable
        ):
            section = (
                "Tipo_de_Cambio",
            )

        elif (
            "servicios/ufv" in searchable
            or "calculadora-ufv" in searchable
            or " ufv " in f" {searchable} "
        ):
            section = (
                "UFV",
            )

        elif (
            "operaciones-mercado-abierto" in searchable
            or "mercado-abierto" in searchable
        ):
            section = (
                "Operaciones_de_Mercado_Abierto",
            )

        elif (
            "pub_reporte-balanza-pagos" in searchable
            or "balanza-pagos" in searchable
        ):
            section = (
                "Sector_Externo",
                "Balanza_de_Pagos",
            )

        elif (
            "deuda-externa" in searchable
            or "deuda_externa" in searchable
        ):
            section = (
                "Sector_Externo",
                "Deuda_Externa",
            )

        # Si el BCB nos da una señal estructural fuerte, esa clasificación
        # tiene prioridad sobre la ruta genérica acumulada.
        if section is not None:
            return section

        # ----------------------------------------------------
        # LIMPIEZA DE RUTA GENÉRICA
        # ----------------------------------------------------

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
