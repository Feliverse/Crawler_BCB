from __future__ import annotations

from dataclasses import dataclass

from urllib.parse import (
    parse_qsl,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

from requests import Response


# ============================================================
# RESULTADO
# ============================================================

@dataclass
class ApiPaginationResult:
    has_pagination: bool

    next_url: str | None = None

    method: str | None = None

    current_page: int | None = None

    total_pages: int | None = None


# ============================================================
# PAGINACIÓN
# ============================================================

class ApiPagination:
    """
    Detecta de forma conservadora la siguiente página de una
    respuesta API.

    Soporta inicialmente:

    1. Enlaces explícitos:
       - next
       - next_url
       - nextUrl
       - links.next
       - links [{rel: "next", href: "..."}]
       - pagination.next

    2. Paginación numérica cuando la propia respuesta declara:
       - page / total_pages
       - current_page / last_page
       - page / pages

    No inventa offsets o cursores cuando la API no proporciona
    información suficiente.
    """

    # ========================================================
    # JSON
    # ========================================================

    @staticmethod
    def _json(
        response: Response,
    ) -> dict | list | None:

        try:
            data = response.json()

        except ValueError:
            return None

        if isinstance(
            data,
            (
                dict,
                list,
            ),
        ):
            return data

        return None

    # ========================================================
    # URL
    # ========================================================

    @staticmethod
    def _absolute_url(
        current_url: str,
        candidate,
    ) -> str | None:

        if candidate is None:
            return None

        # Algunos frameworks devuelven:
        #
        # "next": {
        #     "href": "..."
        # }
        #
        if isinstance(
            candidate,
            dict,
        ):

            candidate = (
                candidate.get(
                    "href"
                )
                or candidate.get(
                    "url"
                )
            )

        if not isinstance(
            candidate,
            str,
        ):
            return None

        candidate = (
            candidate.strip()
        )

        if not candidate:
            return None

        value = urljoin(
            current_url,
            candidate,
        )

        parsed = urlparse(
            value
        )

        if parsed.scheme not in {
            "http",
            "https",
        }:
            return None

        if not parsed.hostname:
            return None

        return value

    # ========================================================
    # NEXT EXPLÍCITO
    # ========================================================

    def _explicit_next(
        self,
        data,
        current_url: str,
    ) -> str | None:

        if not isinstance(
            data,
            dict,
        ):
            return None

        # ----------------------------------------------------
        # top-level
        # ----------------------------------------------------

        for key in (
            "next",
            "next_url",
            "nextUrl",
        ):

            if key not in data:
                continue

            value = (
                self._absolute_url(
                    current_url,
                    data.get(
                        key
                    ),
                )
            )

            if value:
                return value

        # ----------------------------------------------------
        # pagination.next
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

                if key not in pagination:
                    continue

                value = (
                    self._absolute_url(
                        current_url,
                        pagination.get(
                            key
                        ),
                    )
                )

                if value:
                    return value

        # ----------------------------------------------------
        # links
        # ----------------------------------------------------

        links = (
            data.get(
                "links"
            )
        )

        # Django REST / Laravel / etc.
        if isinstance(
            links,
            dict,
        ):

            value = (
                self._absolute_url(
                    current_url,
                    links.get(
                        "next"
                    ),
                )
            )

            if value:
                return value

        # OGC / JSON:API:
        #
        # "links": [
        #   {
        #       "rel": "next",
        #       "href": "..."
        #   }
        # ]
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

                value = (
                    self._absolute_url(
                        current_url,
                        (
                            link.get(
                                "href"
                            )
                            or link.get(
                                "url"
                            )
                        ),
                    )
                )

                if value:
                    return value

        return None

    # ========================================================
    # ENTEROS
    # ========================================================

    @staticmethod
    def _as_int(
        value,
    ) -> int | None:

        if isinstance(
            value,
            bool,
        ):
            return None

        try:
            parsed = int(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return None

        if parsed < 0:
            return None

        return parsed

    # ========================================================
    # PAGE / TOTAL
    # ========================================================

    @classmethod
    def _find_numeric_pagination(
        cls,
        data,
    ) -> tuple[
        str,
        int,
        int,
    ] | None:

        if not isinstance(
            data,
            dict,
        ):
            return None

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

        patterns = (
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

            for (
                current_key,
                total_keys,
            ) in patterns:

                if (
                    current_key
                    not in container
                ):
                    continue

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

                    if (
                        total_key
                        not in container
                    ):
                        continue

                    total_pages = (
                        cls._as_int(
                            container.get(
                                total_key
                            )
                        )
                    )

                    if total_pages is None:
                        continue

                    if total_pages <= 0:
                        continue

                    return (
                        current_key,
                        current_page,
                        total_pages,
                    )

        return None

    # ========================================================
    # CONSTRUIR PAGE=N
    # ========================================================

    @staticmethod
    def _replace_page_parameter(
        current_url: str,
        parameter_name: str,
        next_page: int,
    ) -> str:

        parsed = urlparse(
            current_url
        )

        query_pairs = (
            parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
        )

        names = {
            key
            for (
                key,
                _
            )
            in query_pairs
        }

        # En el JSON puede llamarse current_page,
        # pero normalmente el parámetro HTTP sigue siendo page.
        if parameter_name in {
            "current_page",
            "currentPage",
        }:

            if "page" in names:
                parameter_name = "page"

        new_pairs = []

        replaced = False

        for (
            key,
            value,
        ) in query_pairs:

            if (
                key
                == parameter_name
            ):

                new_pairs.append(
                    (
                        key,
                        str(
                            next_page
                        ),
                    )
                )

                replaced = True

            else:

                new_pairs.append(
                    (
                        key,
                        value,
                    )
                )

        # Solamente añadimos el parámetro si la propia
        # respuesta declaró explícitamente una página.
        if not replaced:

            if parameter_name in {
                "current_page",
                "currentPage",
            }:

                parameter_name = "page"

            new_pairs.append(
                (
                    parameter_name,
                    str(
                        next_page
                    ),
                )
            )

        new_query = urlencode(
            new_pairs,
            doseq=True,
        )

        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                "",
            )
        )

    # ========================================================
    # DETECTAR SIGUIENTE
    # ========================================================

    def detect(
        self,
        response: Response,
        current_url: str,
    ) -> ApiPaginationResult:

        data = (
            self._json(
                response
            )
        )

        if data is None:

            return ApiPaginationResult(
                has_pagination=False,
            )

        # ====================================================
        # NEXT EXPLÍCITO
        # ====================================================

        next_url = (
            self._explicit_next(
                data,
                current_url,
            )
        )

        if next_url:

            if (
                next_url.rstrip("/")
                == current_url.rstrip("/")
            ):

                return ApiPaginationResult(
                    has_pagination=True,
                    next_url=None,
                    method=(
                        "explicit_next_same_url"
                    ),
                )

            return ApiPaginationResult(
                has_pagination=True,
                next_url=next_url,
                method="explicit_next",
            )

        # ====================================================
        # PAGE / TOTAL
        # ====================================================

        numeric = (
            self._find_numeric_pagination(
                data
            )
        )

        if numeric is None:

            return ApiPaginationResult(
                has_pagination=False,
            )

        (
            parameter_name,
            current_page,
            total_pages,
        ) = numeric

        if (
            current_page
            >= total_pages
        ):

            return ApiPaginationResult(
                has_pagination=True,
                next_url=None,
                method="last_page",
                current_page=(
                    current_page
                ),
                total_pages=(
                    total_pages
                ),
            )

        next_page = (
            current_page
            + 1
        )

        next_url = (
            self._replace_page_parameter(
                current_url,
                parameter_name,
                next_page,
            )
        )

        return ApiPaginationResult(
            has_pagination=True,

            next_url=next_url,

            method=(
                "page_total_pages"
            ),

            current_page=(
                current_page
            ),

            total_pages=(
                total_pages
            ),
        )