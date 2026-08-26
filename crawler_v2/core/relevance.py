from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse


# ============================================================
# VOCABULARIO GENÉRICO DE RELEVANCIA
# ============================================================

STRONG_DATA_TERMS = (
    "estadistica",
    "estadística",
    "estadisticas",
    "estadísticas",
    "statistic",
    "statistics",
    "statistical",
    "datos",
    "data",
    "dataset",
    "datasets",
    "base de datos",
    "database",
    "serie",
    "series",
    "serie historica",
    "serie histórica",
    "historico",
    "histórico",
    "indicador",
    "indicadores",
    "indicator",
    "indicators",
    "cuadro estadistico",
    "cuadro estadístico",
    "tabla estadistica",
    "tabla estadística",
    "microdatos",
    "microdata",
    "censo",
    "encuesta",
    "survey",
    "observaciones",
    "observations",
)

CONDITIONAL_STATISTICAL_TERMS = (
    "boletin estadistico",
    "boletín estadístico",
    "reporte estadistico",
    "reporte estadístico",
    "informe estadistico",
    "informe estadístico",
    "anuario estadistico",
    "anuario estadístico",
    "resumen estadistico",
    "resumen estadístico",
    "cifras",
)

NEGATIVE_TERMS = (
    "reglamento",
    "normativa",
    "resolucion",
    "resolución",
    "convocatoria",
    "auditoria",
    "auditoría",
    "transparencia",
    "formulario",
    "denuncia",
    "manual",
    "metodologia",
    "metodología",
    "guia metodologica",
    "guía metodológica",
    "mision",
    "misión",
    "vision",
    "visión",
    "historia institucional",
    "organigrama",
    "autoridades",
    "directorio",
    "contacto",
    "quienes somos",
    "quiénes somos",
    "noticia",
    "noticias",
    "evento",
    "eventos",
    "galeria",
    "galería",
    "rendicion de cuentas",
    "rendición de cuentas",
    "viajes oficiales",
    "oportunidades de empleo",
)

VERY_NEGATIVE_TERMS = (
    "login",
    "logout",
    "wp-admin",
    "wp-login",
    "manual de usuario",
    "terminos y condiciones",
    "términos y condiciones",
    "politica de privacidad",
    "política de privacidad",
)

# Archivos que por naturaleza suelen representar datos reutilizables.
DIRECT_DATA_TYPES = {
    "csv",
    "tsv",
    "xlsx",
    "xls",
    "xlsm",
    "xlsb",
    "ods",
    "json",
    "geojson",
    "parquet",
    "feather",
    "ndjson",
    "jsonl",
    "sav",
    "dta",
    "sas7bdat",
    "rdata",
    "rds",
    "shp",
    "kml",
    "kmz",
    "gpx",
    "sql",
    "db",
    "sqlite",
    "sqlite3",
}

ARCHIVE_TYPES = {
    "zip",
    "rar",
    "7z",
    "gz",
    "tgz",
    "tar",
    "bz2",
}

DOCUMENT_TYPES = {
    "pdf",
    "doc",
    "docx",
    "odt",
    "rtf",
    "ppt",
    "pptx",
    "txt",
}


# ============================================================
# RESULTADO
# ============================================================

@dataclass(frozen=True)
class RelevanceDecision:
    keep: bool
    score: int
    category: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    penalties: tuple[str, ...] = field(default_factory=tuple)


# ============================================================
# MOTOR
# ============================================================

class RelevanceEngine:
    """
    Decide si un recurso descubierto merece entrar al catálogo final.

    IMPORTANTE:
    - FileDetector responde "qué es técnicamente".
    - DataDetector responde "si una página contiene datos".
    - RelevanceEngine responde "si vale la pena catalogarlo".

    No conoce instituciones concretas. Las reglas particulares deben
    añadirse mediante adapters usando `adjustment` o configuración.
    """

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}

        try:
            self.keep_threshold = int(
                self.config.get(
                    "relevance_keep_threshold",
                    45,
                )
            )
        except (TypeError, ValueError):
            self.keep_threshold = 45

        self.extra_positive_terms = self._tokens(
            self.config.get(
                "relevance_positive_keywords",
                [],
            )
        )

        self.extra_negative_terms = self._tokens(
            self.config.get(
                "relevance_negative_keywords",
                [],
            )
        )

        self.force_keep_patterns = self._tokens(
            self.config.get(
                "force_keep_url_patterns",
                [],
            )
        )

        self.force_drop_patterns = self._tokens(
            self.config.get(
                "force_drop_url_patterns",
                [],
            )
        )

    @staticmethod
    def _tokens(values) -> tuple[str, ...]:
        if isinstance(values, str):
            values = [values]

        if not isinstance(values, (list, tuple, set)):
            return ()

        result: list[str] = []

        for value in values:
            token = str(value or "").strip().lower()

            if token and token not in result:
                result.append(token)

        return tuple(result)

    @staticmethod
    def _searchable(
        *,
        url: str,
        description: str = "",
        origin_url: str = "",
        route: list[str] | tuple[str, ...] | None = None,
    ) -> str:
        route_text = " ".join(
            str(item or "")
            for item in (route or ())
        )

        return " ".join(
            (
                unquote(str(url or "")),
                unquote(str(origin_url or "")),
                str(description or ""),
                route_text,
            )
        ).lower()

    @staticmethod
    def _normalized_type(
        file_type: str | None,
        extension: str | None,
    ) -> str:
        value = str(file_type or "").strip().lower()

        if value:
            return value

        extension_value = str(extension or "").strip().lower()

        if extension_value.startswith("."):
            extension_value = extension_value[1:]

        return extension_value

    def _forced_decision(
        self,
        searchable: str,
    ) -> RelevanceDecision | None:
        for pattern in self.force_drop_patterns:
            if pattern in searchable:
                return RelevanceDecision(
                    keep=False,
                    score=-100,
                    category="IRRELEVANT",
                    reasons=(),
                    penalties=(
                        f"force_drop:{pattern}",
                    ),
                )

        for pattern in self.force_keep_patterns:
            if pattern in searchable:
                return RelevanceDecision(
                    keep=True,
                    score=100,
                    category="FORCED_DATASET",
                    reasons=(
                        f"force_keep:{pattern}",
                    ),
                    penalties=(),
                )

        return None

    def evaluate_file(
        self,
        *,
        url: str,
        description: str = "",
        origin_url: str = "",
        route: list[str] | tuple[str, ...] | None = None,
        file_type: str | None = None,
        extension: str | None = None,
        zip_content: list[str] | None = None,
        adjustment: int = 0,
    ) -> RelevanceDecision:
        searchable = self._searchable(
            url=url,
            description=description,
            origin_url=origin_url,
            route=route,
        )

        forced = self._forced_decision(
            searchable
        )

        if forced is not None:
            return forced

        resource_type = self._normalized_type(
            file_type,
            extension,
        )

        score = 0
        reasons: list[str] = []
        penalties: list[str] = []

        # ----------------------------------------------------
        # TIPO DE ARCHIVO
        # ----------------------------------------------------

        if resource_type in DIRECT_DATA_TYPES:
            score += 55
            reasons.append(
                f"direct_data_type:{resource_type}"
            )

        elif resource_type in ARCHIVE_TYPES:
            score += 20
            reasons.append(
                f"archive_type:{resource_type}"
            )

        elif resource_type in DOCUMENT_TYPES:
            # Un PDF/Word/PowerPoint por sí solo NO es dataset.
            score += 5
            reasons.append(
                f"document_type:{resource_type}"
            )

        # ----------------------------------------------------
        # CONTEXTO DE DATOS
        # ----------------------------------------------------

        strong_matches = [
            term
            for term in (
                *STRONG_DATA_TERMS,
                *self.extra_positive_terms,
            )
            if term in searchable
        ]

        if strong_matches:
            score += min(
                45,
                18 + (len(strong_matches) - 1) * 6,
            )
            reasons.append(
                "data_context:"
                + ",".join(
                    strong_matches[:5]
                )
            )

        conditional_matches = [
            term
            for term in CONDITIONAL_STATISTICAL_TERMS
            if term in searchable
        ]

        if conditional_matches:
            score += 25
            reasons.append(
                "statistical_document_context:"
                + ",".join(
                    conditional_matches[:4]
                )
            )

        # ----------------------------------------------------
        # ZIP CON DATOS INTERNOS
        # ----------------------------------------------------

        if resource_type in ARCHIVE_TYPES and zip_content:
            data_inside = 0

            for name in zip_content:
                suffix = (
                    urlparse(
                        str(name or "")
                    ).path.rsplit(".", 1)[-1].lower()
                    if "." in str(name or "")
                    else ""
                )

                if suffix in DIRECT_DATA_TYPES:
                    data_inside += 1

            if data_inside > 0:
                score += 45
                reasons.append(
                    f"archive_contains_data:{data_inside}"
                )

        # ----------------------------------------------------
        # PENALIZACIONES
        # ----------------------------------------------------

        negative_matches = [
            term
            for term in (
                *NEGATIVE_TERMS,
                *self.extra_negative_terms,
            )
            if term in searchable
        ]

        if negative_matches:
            penalty = min(
                95,
                65 + (len(negative_matches) - 1) * 5,
            )
            score -= penalty
            penalties.append(
                "non_data_context:"
                + ",".join(
                    negative_matches[:5]
                )
            )

        very_negative_matches = [
            term
            for term in VERY_NEGATIVE_TERMS
            if term in searchable
        ]

        if very_negative_matches:
            score -= 100
            penalties.append(
                "blocked_context:"
                + ",".join(
                    very_negative_matches[:4]
                )
            )

        score += int(adjustment)

        # ----------------------------------------------------
        # CATEGORÍA
        # ----------------------------------------------------

        if resource_type in DIRECT_DATA_TYPES:
            category = "DATASET"

        elif resource_type in ARCHIVE_TYPES:
            category = "DATA_ARCHIVE"

        elif resource_type in DOCUMENT_TYPES:
            category = "STATISTICAL_DOCUMENT"

        else:
            category = "FILE"

        keep = score >= self.keep_threshold

        # Un documento tradicional debe tener contexto estadístico fuerte.
        if resource_type in DOCUMENT_TYPES:
            has_data_context = bool(
                strong_matches
                or conditional_matches
            )

            if not has_data_context:
                keep = False

        return RelevanceDecision(
            keep=keep,
            score=score,
            category=category,
            reasons=tuple(reasons),
            penalties=tuple(penalties),
        )

    def evaluate_data_page(
        self,
        *,
        url: str,
        description: str = "",
        origin_url: str = "",
        route: list[str] | tuple[str, ...] | None = None,
        resource_type: str = "web",
        data_format: str | None = None,
        has_table: bool = False,
        has_export: bool = False,
        has_filters: bool = False,
        records_count: int | None = None,
        adjustment: int = 0,
    ) -> RelevanceDecision:
        searchable = self._searchable(
            url=url,
            description=description,
            origin_url=origin_url,
            route=route,
        )

        forced = self._forced_decision(
            searchable
        )

        if forced is not None:
            return forced

        score = 0
        reasons: list[str] = []
        penalties: list[str] = []

        normalized_resource_type = str(
            resource_type or "web"
        ).strip().lower()

        normalized_format = str(
            data_format or ""
        ).strip().lower()

        if normalized_resource_type == "api":
            score += 60
            reasons.append("api_resource")

        if normalized_format in {
            "json",
            "geojson",
            "csv",
            "xml",
        }:
            score += 25
            reasons.append(
                f"structured_format:{normalized_format}"
            )

        if has_table:
            score += 45
            reasons.append("html_data_table")

        if has_export:
            score += 30
            reasons.append("export_control")

        if has_filters:
            score += 10
            reasons.append("interactive_filters")

        if records_count is not None:
            score += 15
            reasons.append("structured_records")

        positive_matches = [
            term
            for term in (
                *STRONG_DATA_TERMS,
                *self.extra_positive_terms,
            )
            if term in searchable
        ]

        if positive_matches:
            score += min(
                35,
                15 + (len(positive_matches) - 1) * 5,
            )
            reasons.append(
                "data_context:"
                + ",".join(
                    positive_matches[:5]
                )
            )

        negative_matches = [
            term
            for term in (
                *NEGATIVE_TERMS,
                *self.extra_negative_terms,
            )
            if term in searchable
        ]

        if negative_matches:
            score -= 70
            penalties.append(
                "non_data_context:"
                + ",".join(
                    negative_matches[:5]
                )
            )

        score += int(adjustment)

        if normalized_resource_type == "api":
            category = "API"

        elif has_table:
            category = "TABLE"

        else:
            category = "DATA_PAGE"

        return RelevanceDecision(
            keep=(
                score
                >= self.keep_threshold
            ),
            score=score,
            category=category,
            reasons=tuple(reasons),
            penalties=tuple(penalties),
        )
