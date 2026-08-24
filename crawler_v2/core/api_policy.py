from __future__ import annotations

import re

from dataclasses import dataclass

from urllib.parse import (
    parse_qs,
    unquote,
    urlparse,
)


UUID_PATTERN = re.compile(
    (
        r"^[0-9a-f]{8}-"
        r"[0-9a-f]{4}-"
        r"[1-5][0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-"
        r"[0-9a-f]{12}$"
    ),
    re.IGNORECASE,
)


AUXILIARY_SEGMENTS = {
    "queryables",
    "schema",
    "conformance",
}


@dataclass(frozen=True)
class ApiPolicyDecision:
    allowed: bool
    reason: str


class ApiPolicy:
    """
    Política genérica para controlar la navegación y registro
    de endpoints API.

    ApiDetector responde:

        ¿qué tipo de respuesta recibí?

    ApiPolicy responde:

        ¿vale la pena seguir o registrar este endpoint como
        dataset?

    Evita explosiones de navegación provocadas por:

    - jobs dinámicos
    - schemas
    - queryables
    - conformance
    - ejecuciones
    - procesos operativos OGC
    - items individuales
    - representaciones JSON-LD redundantes
    """

    # ========================================================
    # URL
    # ========================================================

    @staticmethod
    def _segments(
        url: str,
    ) -> list[str]:

        path = unquote(
            urlparse(
                url
            ).path
            or ""
        )

        return [
            segment.lower()
            for segment
            in path.split("/")
            if segment
        ]

    @staticmethod
    def _query(
        url: str,
    ) -> dict[
        str,
        list[str],
    ]:

        return {
            str(key).lower(): [
                str(value).lower()
                for value
                in values
            ]
            for (
                key,
                values,
            ) in parse_qs(
                urlparse(
                    url
                ).query,
                keep_blank_values=True,
            ).items()
        }

    # ========================================================
    # CONTEXTO OGC
    # ========================================================

    @classmethod
    def _is_ogc_context(
        cls,
        url: str,
    ) -> bool:

        segments = (
            cls._segments(
                url
            )
        )

        return (
            "oapi"
            in segments
            or "ogcapi"
            in segments
        )

    # ========================================================
    # ENDPOINTS AUXILIARES
    # ========================================================

    @classmethod
    def _is_auxiliary_endpoint(
        cls,
        url: str,
    ) -> bool:

        segments = (
            cls._segments(
                url
            )
        )

        if not segments:
            return False

        if (
            segments[-1]
            in AUXILIARY_SEGMENTS
        ):
            return True

        return any(
            segment
            in AUXILIARY_SEGMENTS
            for segment
            in segments
        )

    # ========================================================
    # PROCESOS OGC
    # ========================================================

    @classmethod
    def _is_ogc_process_endpoint(
        cls,
        url: str,
    ) -> bool:

        segments = (
            cls._segments(
                url
            )
        )

        if not cls._is_ogc_context(
            url
        ):
            return False

        return (
            "processes"
            in segments
        )

    # ========================================================
    # JOBS OGC
    # ========================================================

    @classmethod
    def _is_ogc_job_endpoint(
        cls,
        url: str,
    ) -> bool:

        segments = (
            cls._segments(
                url
            )
        )

        if not cls._is_ogc_context(
            url
        ):
            return False

        return (
            "jobs"
            in segments
        )

    # ========================================================
    # JOB INDIVIDUAL
    # ========================================================

    @classmethod
    def _is_individual_job(
        cls,
        url: str,
    ) -> bool:

        segments = (
            cls._segments(
                url
            )
        )

        if "jobs" not in segments:
            return False

        index = (
            segments.index(
                "jobs"
            )
        )

        if (
            index + 1
            >= len(
                segments
            )
        ):
            return False

        candidate = (
            segments[
                index + 1
            ]
        )

        return bool(
            UUID_PATTERN.match(
                candidate
            )
        )

    # ========================================================
    # EJECUCIONES
    # ========================================================

    @classmethod
    def _is_execution_endpoint(
        cls,
        url: str,
    ) -> bool:

        segments = (
            cls._segments(
                url
            )
        )

        return (
            "execution"
            in segments
        )

    # ========================================================
    # ITEMS OGC
    # ========================================================

    @classmethod
    def _is_individual_ogc_item(
        cls,
        url: str,
    ) -> bool:
        """
        Permite:

            /collections/stations/items

        pero bloquea:

            /collections/stations/items/123
        """

        segments = (
            cls._segments(
                url
            )
        )

        if (
            "collections"
            not in segments
        ):
            return False

        if "items" not in segments:
            return False

        index = (
            segments.index(
                "items"
            )
        )

        return (
            index + 1
            < len(
                segments
            )
        )

    # ========================================================
    # JSON-LD
    # ========================================================

    @classmethod
    def _is_redundant_jsonld(
        cls,
        url: str,
    ) -> bool:

        query = (
            cls._query(
                url
            )
        )

        values = (
            query.get(
                "f",
                [],
            )
        )

        return (
            "jsonld"
            in values
        )

    # ========================================================
    # NAVEGACIÓN
    # ========================================================

    @classmethod
    def should_follow_discovered(
        cls,
        url: str,
        *,
        declared: bool = False,
    ) -> ApiPolicyDecision:
        """
        Decide si una URL descubierta dentro de una página
        debe ingresar a la cola.

        Los endpoints declarados explícitamente en
        api_endpoints tienen prioridad.
        """

        if declared:

            return ApiPolicyDecision(
                allowed=True,
                reason=(
                    "declared_api_endpoint"
                ),
            )

        if cls._is_auxiliary_endpoint(
            url
        ):

            return ApiPolicyDecision(
                allowed=False,
                reason=(
                    "api_auxiliary_endpoint"
                ),
            )

        if cls._is_individual_job(
            url
        ):

            return ApiPolicyDecision(
                allowed=False,
                reason=(
                    "api_individual_job"
                ),
            )

        if cls._is_ogc_job_endpoint(
            url
        ):

            return ApiPolicyDecision(
                allowed=False,
                reason=(
                    "ogc_jobs_endpoint"
                ),
            )

        if cls._is_ogc_process_endpoint(
            url
        ):

            return ApiPolicyDecision(
                allowed=False,
                reason=(
                    "ogc_process_endpoint"
                ),
            )

        if cls._is_execution_endpoint(
            url
        ):

            return ApiPolicyDecision(
                allowed=False,
                reason=(
                    "api_execution_endpoint"
                ),
            )

        if cls._is_individual_ogc_item(
            url
        ):

            return ApiPolicyDecision(
                allowed=False,
                reason=(
                    "ogc_individual_item"
                ),
            )

        if cls._is_redundant_jsonld(
            url
        ):

            return ApiPolicyDecision(
                allowed=False,
                reason=(
                    "redundant_jsonld_representation"
                ),
            )

        return ApiPolicyDecision(
            allowed=True,
            reason=(
                "api_navigation_allowed"
            ),
        )

    # ========================================================
    # REGISTRO COMO DATASET
    # ========================================================

    @classmethod
    def should_register_api(
        cls,
        url: str,
        detection,
        *,
        declared: bool = False,
    ) -> ApiPolicyDecision:
        """
        Decide si una respuesta API representa realmente
        un dataset que debe entrar al catálogo.
        """

        # ----------------------------------------------------
        # OPENAPI
        # ----------------------------------------------------

        if getattr(
            detection,
            "is_openapi",
            False,
        ):

            return ApiPolicyDecision(
                allowed=False,
                reason=(
                    "openapi_documentation"
                ),
            )

        # ----------------------------------------------------
        # AUXILIARES
        # ----------------------------------------------------

        if cls._is_auxiliary_endpoint(
            url
        ):

            return ApiPolicyDecision(
                allowed=False,
                reason=(
                    "api_auxiliary_endpoint"
                ),
            )

        # ----------------------------------------------------
        # JOB
        # ----------------------------------------------------

        if cls._is_individual_job(
            url
        ):

            return ApiPolicyDecision(
                allowed=False,
                reason=(
                    "api_individual_job"
                ),
            )

        if cls._is_ogc_job_endpoint(
            url
        ):

            return ApiPolicyDecision(
                allowed=False,
                reason=(
                    "ogc_jobs_endpoint"
                ),
            )

        # ----------------------------------------------------
        # PROCESOS
        # ----------------------------------------------------

        if cls._is_ogc_process_endpoint(
            url
        ):

            return ApiPolicyDecision(
                allowed=False,
                reason=(
                    "ogc_process_endpoint"
                ),
            )

        # ----------------------------------------------------
        # EXECUTION
        # ----------------------------------------------------

        if cls._is_execution_endpoint(
            url
        ):

            return ApiPolicyDecision(
                allowed=False,
                reason=(
                    "api_execution_endpoint"
                ),
            )

        # ----------------------------------------------------
        # ITEM INDIVIDUAL
        # ----------------------------------------------------

        if cls._is_individual_ogc_item(
            url
        ):

            return ApiPolicyDecision(
                allowed=False,
                reason=(
                    "ogc_individual_item"
                ),
            )

        # ----------------------------------------------------
        # JSON-LD DUPLICADO
        # ----------------------------------------------------

        if cls._is_redundant_jsonld(
            url
        ):

            return ApiPolicyDecision(
                allowed=False,
                reason=(
                    "redundant_jsonld_representation"
                ),
            )

        # ----------------------------------------------------
        # ENDPOINT DECLARADO
        # ----------------------------------------------------

        if declared:

            return ApiPolicyDecision(
                allowed=True,
                reason=(
                    "declared_api_dataset"
                ),
            )

        # ----------------------------------------------------
        # GEOJSON
        # ----------------------------------------------------

        if getattr(
            detection,
            "is_geojson",
            False,
        ):

            return ApiPolicyDecision(
                allowed=True,
                reason=(
                    "geojson_dataset"
                ),
            )

        # ----------------------------------------------------
        # RESPUESTA CON REGISTROS
        # ----------------------------------------------------

        records_count = getattr(
            detection,
            "records_count",
            None,
        )

        if (
            records_count
            is not None
        ):

            return ApiPolicyDecision(
                allowed=True,
                reason=(
                    "structured_records"
                ),
            )

        # ----------------------------------------------------
        # COLECCIONES OGC
        # ----------------------------------------------------

        segments = (
            cls._segments(
                url
            )
        )

        if (
            "collections"
            in segments
        ):

            return ApiPolicyDecision(
                allowed=True,
                reason=(
                    "ogc_collection_resource"
                ),
            )

        # ----------------------------------------------------
        # RUTAS GENÉRICAS DE DATOS
        # ----------------------------------------------------

        if any(
            segment
            in {
                "data",
                "datos",
                "dataset",
                "datasets",
                "statistics",
                "estadisticas",
                "indicators",
                "indicadores",
                "series",
            }
            for segment
            in segments
        ):

            return ApiPolicyDecision(
                allowed=True,
                reason=(
                    "api_data_path"
                ),
            )

        # ----------------------------------------------------
        # NO DATASET
        # ----------------------------------------------------

        return ApiPolicyDecision(
            allowed=False,
            reason=(
                "api_not_dataset"
            ),
        )