from __future__ import annotations

import re

from urllib.parse import (
    unquote,
    urlparse,
)

from adapters.generic import GenericAdapter


# ============================================================
# ESTRUCTURA ASOFIN
# ============================================================

BULLETIN_POST_PATTERN = re.compile(
    r"/index\.php/"
    r"\d{4}/"
    r"\d{2}/"
    r"\d{2}/"
    r"no-?\d+/?$",
    re.IGNORECASE,
)


DATED_POST_PATTERN = re.compile(
    r"/index\.php/"
    r"\d{4}/"
    r"\d{2}/"
    r"\d{2}/",
    re.IGNORECASE,
)


BULLETIN_PAGINATION_PATTERN = re.compile(
    r"/(?:index\.php/)?"
    r"(?:category/boletin_(?:financiero|social)|boletines)"
    r"/page/\d+/?$",
    re.IGNORECASE,
)


FINANCIAL_REPORT_PATTERNS = (
    "/graficos/indicadores_financieros/reporte-financiero.html",
)


SOCIAL_REPORT_PATTERNS = (
    "/graficos/indicadores_sociales/reporte-social.html",
)


PAF_REPORT_PATTERNS = (
    "/graficos/cobertura_paf/bolivia.html",
)


BENCHMARKING_REPORT_PATTERNS = (
    "/graficos/benchmarking/benchmar.html",
)


INDICATOR_REPORT_PATTERNS = (
    *FINANCIAL_REPORT_PATTERNS,
    *SOCIAL_REPORT_PATTERNS,
    *PAF_REPORT_PATTERNS,
    *BENCHMARKING_REPORT_PATTERNS,
)


INDICATOR_PAGE_PATTERNS = (
    "/index.php/indicadores-financieros-2/",
    "/index.php/indicadores-sociales/",
    "/index.php/cobertura-paf/",
    "/index.php/benchmarking/",
)


HIGH_PRIORITY = (
    "indicadores-financieros",
    "indicadores-sociales",
    "indicadores_financieros",
    "indicadores_sociales",
    "reporte-financiero",
    "reporte-social",
    "cobertura-paf",
    "cobertura_paf",
    "benchmarking",
    "boletin_financiero",
    "boletin_social",
    "/boletines/",
    "boletin mensual",
    "boletín mensual",
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
    "wp-login",
    "wp-admin",
)


PAGINATION_LABELS = {
    "older",
    "newer",
    "← older",
    "older →",
    "« anterior",
    "anterior",
    "siguiente",
    "siguiente »",
    "«",
    "»",
}


DATA_FILE_TYPES = {
    "csv",
    "tsv",
    "xlsx",
    "xls",
    "xlsm",
    "xlsb",
    "ods",
    "json",
    "xml",
    "zip",
}


# ============================================================
# ADAPTER
# ============================================================

class AsofinAdapter(GenericAdapter):
    """
    Adapter específico de ASOFIN.

    El adapter NO realiza HTTP.

    Aporta únicamente semántica de la fuente:
    - priorización de indicadores;
    - navegación del histórico de boletines;
    - reconocimiento de publicaciones individuales;
    - relevancia de PDFs estadísticos;
    - reconocimiento de dashboards oficiales;
    - filtrado de ruido WordPress;
    - normalización de rutas del catálogo.

    El core sigue siendo responsable de:
    HTTP, detección, relevancia base, deduplicación,
    paginación, presupuesto y exportación.
    """

    # ========================================================
    # HELPERS
    # ========================================================

    @staticmethod
    def _lower_url(
        url: str,
    ) -> str:
        return unquote(
            str(
                url
                or ""
            )
        ).lower()

    @classmethod
    def _matches_any(
        cls,
        url: str,
        patterns: tuple[str, ...],
    ) -> bool:
        lowered = cls._lower_url(
            url
        )

        return any(
            pattern in lowered
            for pattern in patterns
        )

    @classmethod
    def _is_bulletin_post(
        cls,
        url: str,
    ) -> bool:
        path = (
            urlparse(
                str(
                    url
                    or ""
                )
            ).path
            or ""
        )

        return bool(
            BULLETIN_POST_PATTERN.search(
                path
            )
        )

    @classmethod
    def _is_dated_post(
        cls,
        url: str,
    ) -> bool:
        path = (
            urlparse(
                str(
                    url
                    or ""
                )
            ).path
            or ""
        )

        return bool(
            DATED_POST_PATTERN.search(
                path
            )
        )

    @classmethod
    def _is_bulletin_pagination(
        cls,
        url: str,
    ) -> bool:
        path = (
            urlparse(
                str(
                    url
                    or ""
                )
            ).path
            or ""
        )

        return bool(
            BULLETIN_PAGINATION_PATTERN.search(
                path
            )
        )

    @classmethod
    def _is_financial_report(
        cls,
        url: str,
    ) -> bool:
        return cls._matches_any(
            url,
            FINANCIAL_REPORT_PATTERNS,
        )

    @classmethod
    def _is_social_report(
        cls,
        url: str,
    ) -> bool:
        return cls._matches_any(
            url,
            SOCIAL_REPORT_PATTERNS,
        )

    @classmethod
    def _is_paf_report(
        cls,
        url: str,
    ) -> bool:
        return cls._matches_any(
            url,
            PAF_REPORT_PATTERNS,
        )

    @classmethod
    def _is_benchmarking_report(
        cls,
        url: str,
    ) -> bool:
        return cls._matches_any(
            url,
            BENCHMARKING_REPORT_PATTERNS,
        )

    @classmethod
    def _is_indicator_report(
        cls,
        url: str,
    ) -> bool:
        return cls._matches_any(
            url,
            INDICATOR_REPORT_PATTERNS,
        )

    @classmethod
    def _is_indicator_page(
        cls,
        url: str,
    ) -> bool:
        return cls._matches_any(
            url,
            INDICATOR_PAGE_PATTERNS,
        )

    # ========================================================
    # NAVEGACIÓN
    # ========================================================

    def should_follow(
        self,
        url: str,
    ) -> bool:
        if not super().should_follow(
            url
        ):
            return False

        lowered = self._lower_url(
            url
        )

        # Ruido típico de WordPress.
        if any(
            token in lowered
            for token in LOW_PRIORITY
        ):
            return False

        # El include scope permite /index.php/20... para poder
        # recorrer los posts históricos.
        #
        # ASOFIN tiene otros artículos con la misma estructura
        # cronológica. Solo dejamos pasar los posts cuyo slug
        # corresponde realmente a un boletín Nº.
        if (
            self._is_dated_post(
                url
            )
            and not self._is_bulletin_post(
                url
            )
        ):
            return False

        return True

    # ========================================================
    # PRIORIDAD
    # ========================================================

    def priority(
        self,
        url: str,
        text: str,
    ) -> int:
        searchable = (
            self._lower_url(
                url
            )
            + " "
            + str(
                text
                or ""
            ).lower()
        )

        # Dashboards / visualizaciones principales.
        if self._is_indicator_report(
            url
        ):
            return 0

        # Páginas contenedoras de indicadores.
        if self._is_indicator_page(
            url
        ):
            return 0

        # Paginación histórica de boletines.
        if self._is_bulletin_pagination(
            url
        ):
            return 1

        # Índices principales de boletines.
        if any(
            token in searchable
            for token in (
                "boletin_financiero",
                "boletin_social",
                "/boletines/",
                "boletin mensual",
                "boletín mensual",
            )
        ):
            return 1

        # Publicaciones individuales:
        # /2026/06/08/no-249/
        if self._is_bulletin_post(
            url
        ):
            return 2

        if any(
            token in searchable
            for token in HIGH_PRIORITY
        ):
            return 5

        if any(
            token in searchable
            for token in DOCUMENT_PRIORITY
        ):
            return 12

        if any(
            token in searchable
            for token in LOW_PRIORITY
        ):
            return 95

        return super().priority(
            url,
            text,
        )

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
                self._lower_url(
                    url
                ),
                self._lower_url(
                    origin_url
                ),
                str(
                    description
                    or ""
                ).lower(),
                " ".join(
                    str(
                        item
                        or ""
                    ).lower()
                    for item in path
                ),
                str(
                    resource_type
                    or ""
                ).lower(),
            )
        )

        # ----------------------------------------------------
        # BOLETINES
        # ----------------------------------------------------
        #
        # Muchos PDFs antiguos tienen nombres genéricos:
        #
        # 217_final_v8_compressed.pdf
        #
        # Su semántica viene de la página de origen No. XXX.
        if self._is_bulletin_post(
            origin_url
        ):
            adjustment += 80

        # ----------------------------------------------------
        # DASHBOARDS
        # ----------------------------------------------------

        if (
            self._is_indicator_report(
                url
            )
            or self._is_indicator_report(
                origin_url
            )
        ):
            adjustment += 80

        if (
            self._is_indicator_page(
                url
            )
            or self._is_indicator_page(
                origin_url
            )
        ):
            adjustment += 50

        # ----------------------------------------------------
        # ARCHIVOS DE DATOS DE ASOFIN
        # ----------------------------------------------------

        if (
            "/wp-content/uploads/"
            in searchable
            and any(
                token in searchable
                for token in (
                    "indicador",
                    "boletin",
                    "boletín",
                    "cartera",
                    "deposit",
                    "prestat",
                    "microfin",
                    "financier",
                    "social",
                )
            )
        ):
            adjustment += 35

        return adjustment

    # ========================================================
    # KEEP DE ARCHIVOS
    # ========================================================

    def should_keep_file(
        self,
        *,
        decision,
        url: str,
        description: str,
        origin_url: str,
        path: tuple[str, ...] | list[str],
        detection,
    ) -> bool:
        file_type = str(
            getattr(
                detection,
                "file_type",
                "",
            )
            or ""
        ).lower()

        # Los PDFs enlazados directamente desde los posts
        # numerados de ASOFIN son boletines estadísticos.
        if (
            file_type == "pdf"
            and self._is_bulletin_post(
                origin_url
            )
        ):
            return True

        # Si una visualización/indicador enlaza un formato
        # directamente explotable, lo conservamos.
        if (
            file_type in DATA_FILE_TYPES
            and (
                self._is_bulletin_post(
                    origin_url
                )
                or self._is_indicator_report(
                    origin_url
                )
                or self._is_indicator_page(
                    origin_url
                )
            )
        ):
            return True

        return super().should_keep_file(
            decision=decision,
            url=url,
            description=description,
            origin_url=origin_url,
            path=path,
            detection=detection,
        )

    # ========================================================
    # KEEP DE DATASETS WEB
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
        # Estos HTML son los dashboards finales reales.
        #
        # No forzamos las páginas WordPress contenedoras:
        # queremos catalogar la visualización subyacente.
        if self._is_indicator_report(
            url
        ):
            return True

        return super().should_keep_data_page(
            decision=decision,
            url=url,
            description=description,
            origin_url=origin_url,
            path=path,
            resource_type=resource_type,
        )

    # ========================================================
    # RUTA DE SALIDA
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
                self._lower_url(
                    url
                ),
                self._lower_url(
                    origin_url
                ),
                str(
                    description
                    or ""
                ).lower(),
                " ".join(
                    str(
                        item
                        or ""
                    ).lower()
                    for item in path
                ),
            )
        )

        # ----------------------------------------------------
        # BOLETINES
        # ----------------------------------------------------

        if self._is_bulletin_post(
            origin_url
        ):
            if (
                "social"
                in searchable
            ):
                return (
                    "Boletines",
                    "Boletín social",
                )

            return (
                "Boletines",
                "Boletín financiero",
            )

        # ----------------------------------------------------
        # INDICADORES
        # ----------------------------------------------------

        if (
            self._is_paf_report(
                url
            )
            or self._is_paf_report(
                origin_url
            )
        ):
            return (
                "Indicadores",
                "Cobertura PAF",
            )

        if (
            self._is_benchmarking_report(
                url
            )
            or self._is_benchmarking_report(
                origin_url
            )
        ):
            return (
                "Indicadores",
                "Benchmarking",
            )

        if (
            self._is_financial_report(
                url
            )
            or self._is_financial_report(
                origin_url
            )
        ):
            return (
                "Indicadores",
                "Indicadores financieros",
            )

        if (
            self._is_social_report(
                url
            )
            or self._is_social_report(
                origin_url
            )
        ):
            return (
                "Indicadores",
                "Indicadores sociales",
            )

        return tuple(
            normalized
        )

    # ========================================================
    # JERARQUÍA
    # ========================================================

    def extend_path(
        self,
        current_path: tuple[str, ...],
        text: str,
        url: str,
    ) -> tuple[str, ...]:
        cleaned = " ".join(
            str(
                text
                or ""
            ).split()
        ).strip()

        lowered = (
            cleaned.lower()
        )

        # Evitamos rutas como:
        #
        # Boletines > 2 > 3 > 49
        if cleaned.isdigit():
            return current_path

        if lowered in PAGINATION_LABELS:
            return current_path

        if self._is_bulletin_pagination(
            url
        ):
            return current_path

        return super().extend_path(
            current_path,
            text,
            url,
        )