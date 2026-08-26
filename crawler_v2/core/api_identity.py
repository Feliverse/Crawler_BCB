from __future__ import annotations

from urllib.parse import (
    parse_qsl,
    unquote,
    urlencode,
    urlparse,
    urlunparse,
)


REPRESENTATION_QUERY_KEYS = {
    "f",
    "format",
    "output",
    "outputformat",
    "responseformat",
}


REPRESENTATION_VALUES = {
    "html",
    "json",
    "jsonld",
    "geojson",
    "xml",
    "csv",
    "application/json",
    "application/geo+json",
    "application/xml",
    "text/xml",
    "text/csv",
    "text/html",
}


# Estos parámetros representan páginas o ventanas del MISMO
# dataset y por eso no forman parte de su identidad semántica.
PAGINATION_QUERY_KEYS = {
    "page",
    "page_number",
    "pagenumber",
    "current_page",
    "currentpage",
    "offset",
    "start",
    "limit",
    "page_size",
    "pagesize",
    "per_page",
    "perpage",
    "cursor",
}


class ApiIdentity:
    """
    Genera la identidad semántica de un dataset API.

    Unifica:

        /stations?f=html
        /stations?f=json

    y también:

        /datos?page=1
        /datos?page=2

    sin eliminar filtros de negocio como:

        year
        date
        category
        departamento
        indicador
        bbox

    porque esos sí pueden representar consultas diferentes.
    """

    # ========================================================
    # IDENTIDAD
    # ========================================================

    @classmethod
    def canonical_key(
        cls,
        url: str,
    ) -> str:

        parsed = urlparse(
            url
        )

        scheme = (
            parsed.scheme.lower()
        )

        hostname = (
            parsed.hostname
            or ""
        ).lower()

        try:
            port = parsed.port

        except ValueError:
            port = None

        if (
            port is None
            or (
                scheme == "http"
                and port == 80
            )
            or (
                scheme == "https"
                and port == 443
            )
        ):

            netloc = hostname

        else:

            netloc = (
                f"{hostname}:{port}"
            )

        path = unquote(
            parsed.path
            or "/"
        )

        if (
            len(path) > 1
            and path.endswith("/")
        ):
            path = (
                path.rstrip("/")
            )

        query_pairs = []

        for (
            key,
            value,
        ) in parse_qsl(
            parsed.query,
            keep_blank_values=True,
        ):

            lowered_key = (
                key.lower()
                .strip()
            )

            lowered_value = (
                value.lower()
                .strip()
            )

            # ------------------------------------------------
            # REPRESENTACIÓN
            # ------------------------------------------------

            if (
                lowered_key
                in REPRESENTATION_QUERY_KEYS

                and lowered_value
                in REPRESENTATION_VALUES
            ):
                continue

            # ------------------------------------------------
            # PAGINACIÓN
            # ------------------------------------------------

            if (
                lowered_key
                in PAGINATION_QUERY_KEYS
            ):
                continue

            query_pairs.append(
                (
                    key,
                    value,
                )
            )

        query = urlencode(
            sorted(
                query_pairs
            ),
            doseq=True,
        )

        return urlunparse(
            (
                scheme,
                netloc,
                path,
                "",
                query,
                "",
            )
        )

    # ========================================================
    # CALIDAD
    # ========================================================

    @staticmethod
    def representation_score(
        record,
    ) -> int:

        resource_type = str(
            getattr(
                record,
                "tipo_recurso",
                "web",
            )
            or "web"
        ).lower()

        data_format = str(
            getattr(
                record,
                "formato",
                "",
            )
            or ""
        ).lower()

        score = 0

        if data_format == "geojson":
            score = 600

        elif data_format == "json":
            score = 550

        elif data_format == "csv":
            score = 500

        elif data_format == "xml":
            score = 450

        elif data_format == "jsonld":
            score = 350

        elif resource_type == "api":
            score = 300

        else:
            score = 100

        if resource_type == "api":
            score += 20

        records_count = getattr(
            record,
            "registros_detectados",
            None,
        )

        if records_count is not None:
            score += 10

        if getattr(
            record,
            "permite_exportar",
            False,
        ):
            score += 5

        return score

    @classmethod
    def should_replace(
        cls,
        existing,
        candidate,
    ) -> bool:

        return (
            cls.representation_score(
                candidate
            )
            >
            cls.representation_score(
                existing
            )
        )