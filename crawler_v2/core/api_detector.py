from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from requests import Response


# ============================================================
# MIME TYPES
# ============================================================

JSON_CONTENT_TYPES = (
    "application/json",
    "application/geo+json",
    "application/problem+json",
    "application/ld+json",
)

XML_CONTENT_TYPES = (
    "application/xml",
    "text/xml",
    "application/gml+xml",
)

CSV_CONTENT_TYPES = (
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
)


# ============================================================
# RESULTADO
# ============================================================

@dataclass
class ApiDetection:
    is_api: bool

    format: str | None = None

    reason: str | None = None

    records_count: int | None = None

    is_openapi: bool = False

    is_geojson: bool = False

    has_pagination: bool = False


# ============================================================
# API DETECTOR
# ============================================================

class ApiDetector:
    """
    Detecta respuestas correspondientes a APIs o datos
    estructurados.

    Soporta:

    - JSON
    - GeoJSON
    - OpenAPI / Swagger
    - XML
    - CSV
    - OGC JSON
    - paginación real

    No considera que la mera existencia de "links" implique
    paginación.
    """

    # ========================================================
    # CONTENT TYPE
    # ========================================================

    @staticmethod
    def _content_type(
        response: Response,
    ) -> str:

        return (
            response.headers
            .get(
                "Content-Type",
                "",
            )
            .split(
                ";",
                1,
            )[0]
            .strip()
            .lower()
        )

    # ========================================================
    # JSON
    # ========================================================

    @staticmethod
    def _safe_json(
        response: Response,
    ) -> Any | None:

        try:

            return response.json()

        except ValueError:

            return None

    # ========================================================
    # OPENAPI
    # ========================================================

    @staticmethod
    def _is_openapi(
        data: Any,
    ) -> bool:

        if not isinstance(
            data,
            dict,
        ):
            return False

        if "openapi" in data:
            return True

        if "swagger" in data:
            return True

        if (
            "paths" in data
            and isinstance(
                data["paths"],
                dict,
            )
        ):
            return True

        return False

    # ========================================================
    # GEOJSON
    # ========================================================

    @staticmethod
    def _is_geojson(
        data: Any,
    ) -> bool:

        if not isinstance(
            data,
            dict,
        ):
            return False

        geo_type = str(
            data.get(
                "type",
                "",
            )
        ).lower()

        return geo_type in {
            "feature",
            "featurecollection",
            "geometrycollection",
            "point",
            "multipoint",
            "linestring",
            "multilinestring",
            "polygon",
            "multipolygon",
        }

    # ========================================================
    # CONTEO DE REGISTROS
    # ========================================================

    @staticmethod
    def _records_count(
        data: Any,
    ) -> int | None:

        if isinstance(
            data,
            list,
        ):

            return len(
                data
            )

        if not isinstance(
            data,
            dict,
        ):
            return None

        # ----------------------------------------------------
        # GEOJSON
        # ----------------------------------------------------

        features = (
            data.get(
                "features"
            )
        )

        if isinstance(
            features,
            list,
        ):

            return len(
                features
            )

        # ----------------------------------------------------
        # FORMATOS COMUNES
        # ----------------------------------------------------

        candidates = (
            "data",
            "results",
            "items",
            "records",
            "rows",
            "values",
        )

        for key in candidates:

            value = (
                data.get(
                    key
                )
            )

            if isinstance(
                value,
                list,
            ):

                return len(
                    value
                )

        return None

    # ========================================================
    # UTILIDADES PAGINACIÓN
    # ========================================================

    @staticmethod
    def _has_value(
        value: Any,
    ) -> bool:

        if value is None:
            return False

        if isinstance(
            value,
            str,
        ):

            return bool(
                value.strip()
            )

        if isinstance(
            value,
            dict,
        ):

            return bool(
                value.get("href")
                or value.get("url")
            )

        return bool(
            value
        )

    @staticmethod
    def _as_int(
        value: Any,
    ) -> int | None:

        if isinstance(
            value,
            bool,
        ):
            return None

        try:

            number = int(
                value
            )

        except (
            TypeError,
            ValueError,
        ):

            return None

        if number < 0:
            return None

        return number

    # ========================================================
    # NEXT EXPLÍCITO
    # ========================================================

    @classmethod
    def _has_explicit_next(
        cls,
        data: dict,
    ) -> bool:

        # ----------------------------------------------------
        # ROOT
        # ----------------------------------------------------

        for key in (
            "next",
            "next_url",
            "nextUrl",
        ):

            if cls._has_value(
                data.get(
                    key
                )
            ):

                return True

        # ----------------------------------------------------
        # PAGINATION
        # ----------------------------------------------------

        pagination = (
            data.get(
                "pagination"
            )
        )

        if isinstance(
            pagination,
            dict,
        ):

            for key in (
                "next",
                "next_url",
                "nextUrl",
            ):

                if cls._has_value(
                    pagination.get(
                        key
                    )
                ):

                    return True

        # ----------------------------------------------------
        # LINKS COMO OBJETO
        # ----------------------------------------------------

        links = (
            data.get(
                "links"
            )
        )

        if isinstance(
            links,
            dict,
        ):

            if cls._has_value(
                links.get(
                    "next"
                )
            ):

                return True

        # ----------------------------------------------------
        # LINKS OGC / JSON:API
        # ----------------------------------------------------

        if isinstance(
            links,
            list,
        ):

            for link in links:

                if not isinstance(
                    link,
                    dict,
                ):
                    continue

                relation = str(
                    link.get(
                        "rel",
                        "",
                    )
                ).strip().lower()

                if relation != "next":
                    continue

                if cls._has_value(
                    link.get(
                        "href"
                    )
                    or link.get(
                        "url"
                    )
                ):

                    return True

        return False

    # ========================================================
    # PAGE / TOTAL PAGES
    # ========================================================

    @classmethod
    def _has_numeric_pagination(
        cls,
        data: dict,
    ) -> bool:

        containers = [
            data
        ]

        for key in (
            "pagination",
            "meta",
            "metadata",
            "page_info",
            "pageInfo",
        ):

            value = (
                data.get(
                    key
                )
            )

            if isinstance(
                value,
                dict,
            ):

                containers.append(
                    value
                )

        page_patterns = (
            (
                "page",
                (
                    "total_pages",
                    "totalPages",
                    "pages",
                ),
            ),
            (
                "current_page",
                (
                    "last_page",
                    "total_pages",
                    "pages",
                ),
            ),
            (
                "currentPage",
                (
                    "totalPages",
                    "pages",
                ),
            ),
        )

        for container in containers:

            # ------------------------------------------------
            # PAGE + TOTAL PAGES
            # ------------------------------------------------

            for (
                current_key,
                total_keys,
            ) in page_patterns:

                current_page = (
                    cls._as_int(
                        container.get(
                            current_key
                        )
                    )
                )

                if current_page is None:
                    continue

                for total_key in total_keys:

                    total_pages = (
                        cls._as_int(
                            container.get(
                                total_key
                            )
                        )
                    )

                    if (
                        total_pages
                        is not None
                        and total_pages > 0
                    ):

                        return True

            # ------------------------------------------------
            # OFFSET + LIMIT + TOTAL
            # ------------------------------------------------

            offset = (
                cls._as_int(
                    container.get(
                        "offset"
                    )
                )
            )

            limit = (
                cls._as_int(
                    container.get(
                        "limit"
                    )
                )
            )

            total = (
                cls._as_int(
                    container.get(
                        "total"
                    )
                )
            )

            if (
                offset is not None
                and limit is not None
                and limit > 0
                and total is not None
            ):

                return True

            # ------------------------------------------------
            # PAGE + SIZE + TOTAL RECORDS
            # ------------------------------------------------

            page = (
                cls._as_int(
                    container.get(
                        "page"
                    )
                )
            )

            size = None

            for key in (
                "page_size",
                "pageSize",
                "per_page",
                "perPage",
                "limit",
            ):

                size = (
                    cls._as_int(
                        container.get(
                            key
                        )
                    )
                )

                if size is not None:
                    break

            total = (
                cls._as_int(
                    container.get(
                        "total"
                    )
                )
            )

            if (
                page is not None
                and size is not None
                and size > 0
                and total is not None
            ):

                return True

        return False

    # ========================================================
    # PAGINACIÓN REAL
    # ========================================================

    @classmethod
    def _has_pagination(
        cls,
        data: Any,
    ) -> bool:

        if not isinstance(
            data,
            dict,
        ):

            return False

        if cls._has_explicit_next(
            data
        ):

            return True

        if cls._has_numeric_pagination(
            data
        ):

            return True

        return False

    # ========================================================
    # DETECCIÓN
    # ========================================================

    def detect(
        self,
        response: Response,
    ) -> ApiDetection:

        content_type = (
            self._content_type(
                response
            )
        )

        # ====================================================
        # JSON
        # ====================================================

        if (
            content_type
            in JSON_CONTENT_TYPES
            or "json"
            in content_type
        ):

            data = (
                self._safe_json(
                    response
                )
            )

            if data is None:

                return ApiDetection(
                    is_api=True,
                    format="json",
                    reason="json_response",
                )

            is_openapi = (
                self._is_openapi(
                    data
                )
            )

            is_geojson = (
                self._is_geojson(
                    data
                )
            )

            records_count = (
                self._records_count(
                    data
                )
            )

            has_pagination = (
                self._has_pagination(
                    data
                )
            )

            if is_openapi:

                reason = (
                    "openapi_document"
                )

            elif is_geojson:

                reason = (
                    "geojson_dataset"
                )

            else:

                reason = (
                    "json_api"
                )

            return ApiDetection(
                is_api=True,

                format=(
                    "geojson"
                    if is_geojson
                    else "json"
                ),

                reason=reason,

                records_count=(
                    records_count
                ),

                is_openapi=(
                    is_openapi
                ),

                is_geojson=(
                    is_geojson
                ),

                has_pagination=(
                    has_pagination
                ),
            )

        # ====================================================
        # XML
        # ====================================================

        if (
            content_type
            in XML_CONTENT_TYPES
            or "xml"
            in content_type
        ):

            return ApiDetection(
                is_api=True,
                format="xml",
                reason="xml_api",
            )

        # ====================================================
        # CSV
        # ====================================================

        if (
            content_type
            in CSV_CONTENT_TYPES
            or "csv"
            in content_type
        ):

            return ApiDetection(
                is_api=True,
                format="csv",
                reason="csv_api",
            )

        # ====================================================
        # NO API
        # ====================================================

        return ApiDetection(
            is_api=False,
        )