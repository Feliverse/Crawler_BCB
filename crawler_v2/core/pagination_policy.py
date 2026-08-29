from __future__ import annotations

"""
Política genérica de paginación basada en rendimiento real.

Objetivo:
- seguir paginaciones que continúan aportando datasets/archivos útiles;
- detener familias de paginación que consumen páginas sin aportar valor;
- no depender de reglas específicas de una fuente.

La política es deliberadamente conservadora:
- nunca bloquea una URL que no parezca paginación;
- no juzga por similitud de nombres;
- aprende únicamente del rendimiento observado en la ejecución actual.
"""

from dataclasses import dataclass, field
import re
from urllib.parse import (
    parse_qsl,
    urlencode,
    urlparse,
    urlunparse,
)


QUERY_PAGE_KEYS = {
    "page",
    "pagina",
    "__pagina__",
    "p",
    "paged",
    "pageindex",
    "page_index",
    "start",
    "offset",
    "limitstart",
}

PATH_PAGE_PATTERNS = (
    re.compile(
        r"(?i)(/page/)\d+(?=/|$)"
    ),
    re.compile(
        r"(?i)(/pagina/)\d+(?=/|$)"
    ),
    re.compile(
        r"(?i)(/p/)\d+(?=/|$)"
    ),
)


@dataclass(frozen=True)
class PaginationIdentity:
    is_pagination: bool
    family: str
    marker: str
    value: int | None


@dataclass
class PaginationFamilyState:
    pages_observed: int = 0
    total_yield: int = 0
    consecutive_zero_yield: int = 0
    last_yield: int = 0
    max_yield: int = 0
    yields: list[int] = field(
        default_factory=list
    )

    @property
    def average_yield(
        self,
    ) -> float:
        if self.pages_observed <= 0:
            return 0.0

        return (
            self.total_yield
            / self.pages_observed
        )


@dataclass(frozen=True)
class PaginationDecision:
    allow: bool
    reason: str
    family: str = ""


class PaginationYieldPolicy:
    """
    Aprende si una familia paginada vale la pena.

    Ejemplo:

        ?page=1&q=reporte-estadistico   -> +20 archivos
        ?page=2&q=reporte-estadistico   -> +20 archivos
        => seguir

        ?page=1&q=indicadores_inflacion -> +0
        ?page=2&q=indicadores_inflacion -> +0
        ?page=3&q=indicadores_inflacion -> +0
        => detener páginas posteriores
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        zero_yield_stop_after: int = 3,
        min_pages_before_stop: int = 3,
        high_yield_threshold: int = 5,
        max_tracked_yields: int = 20,
    ) -> None:

        self.enabled = bool(
            enabled
        )

        self.zero_yield_stop_after = max(
            1,
            int(
                zero_yield_stop_after
            ),
        )

        self.min_pages_before_stop = max(
            1,
            int(
                min_pages_before_stop
            ),
        )

        self.high_yield_threshold = max(
            1,
            int(
                high_yield_threshold
            ),
        )

        self.max_tracked_yields = max(
            1,
            int(
                max_tracked_yields
            ),
        )

        self.states: dict[
            str,
            PaginationFamilyState,
        ] = {}

        self.skipped_pages = 0

    # ========================================================
    # IDENTIDAD DE PAGINACIÓN
    # ========================================================

    def identify(
        self,
        url: str,
    ) -> PaginationIdentity:

        parsed = urlparse(
            str(
                url
                or ""
            )
        )

        query_items = parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )

        pagination_items: list[
            tuple[str, str]
        ] = []

        retained_items: list[
            tuple[str, str]
        ] = []

        for key, value in query_items:
            normalized_key = (
                str(
                    key
                    or ""
                )
                .strip()
                .lower()
            )

            if normalized_key in QUERY_PAGE_KEYS:
                pagination_items.append(
                    (
                        normalized_key,
                        value,
                    )
                )
            else:
                retained_items.append(
                    (
                        key,
                        value,
                    )
                )

        if pagination_items:
            marker, raw_value = (
                pagination_items[
                    0
                ]
            )

            try:
                numeric_value = int(
                    raw_value
                )
            except (
                TypeError,
                ValueError,
            ):
                numeric_value = None

            family_query = urlencode(
                sorted(
                    retained_items
                ),
                doseq=True,
            )

            family = urlunparse(
                (
                    parsed.scheme.lower(),
                    parsed.netloc.lower(),
                    parsed.path,
                    "",
                    family_query,
                    "",
                )
            )

            return PaginationIdentity(
                is_pagination=True,
                family=family,
                marker=marker,
                value=numeric_value,
            )

        normalized_path = (
            parsed.path
            or "/"
        )

        for pattern in PATH_PAGE_PATTERNS:
            match = pattern.search(
                normalized_path
            )

            if not match:
                continue

            raw_number = re.search(
                r"\d+",
                match.group(
                    0
                ),
            )

            numeric_value = (
                int(
                    raw_number.group(
                        0
                    )
                )
                if raw_number
                else None
            )

            family_path = pattern.sub(
                r"\g<1>{page}",
                normalized_path,
            )

            family = urlunparse(
                (
                    parsed.scheme.lower(),
                    parsed.netloc.lower(),
                    family_path,
                    "",
                    parsed.query,
                    "",
                )
            )

            return PaginationIdentity(
                is_pagination=True,
                family=family,
                marker="path_page",
                value=numeric_value,
            )

        return PaginationIdentity(
            is_pagination=False,
            family="",
            marker="",
            value=None,
        )

    # ========================================================
    # APRENDIZAJE
    # ========================================================

    def note_page_yield(
        self,
        url: str,
        *,
        useful_resources: int,
    ) -> None:

        if not self.enabled:
            return

        identity = self.identify(
            url
        )

        if not identity.is_pagination:
            return

        useful_resources = max(
            0,
            int(
                useful_resources
            ),
        )

        state = self.states.setdefault(
            identity.family,
            PaginationFamilyState(),
        )

        state.pages_observed += 1
        state.total_yield += (
            useful_resources
        )
        state.last_yield = (
            useful_resources
        )
        state.max_yield = max(
            state.max_yield,
            useful_resources,
        )

        if useful_resources == 0:
            state.consecutive_zero_yield += 1
        else:
            state.consecutive_zero_yield = 0

        state.yields.append(
            useful_resources
        )

        if (
            len(
                state.yields
            )
            > self.max_tracked_yields
        ):
            del state.yields[
                :len(
                    state.yields
                )
                - self.max_tracked_yields
            ]

    # ========================================================
    # DECISIÓN
    # ========================================================

    def should_visit(
        self,
        url: str,
    ) -> PaginationDecision:

        if not self.enabled:
            return PaginationDecision(
                allow=True,
                reason="pagination_policy_disabled",
            )

        identity = self.identify(
            url
        )

        if not identity.is_pagination:
            return PaginationDecision(
                allow=True,
                reason="not_pagination",
            )

        state = self.states.get(
            identity.family
        )

        if state is None:
            return PaginationDecision(
                allow=True,
                reason="pagination_family_unseen",
                family=identity.family,
            )

        if (
            state.pages_observed
            < self.min_pages_before_stop
        ):
            return PaginationDecision(
                allow=True,
                reason="pagination_learning",
                family=identity.family,
            )

        # Una familia que históricamente está dando varios recursos
        # por página no se corta por una única página vacía.
        if (
            state.max_yield
            >= self.high_yield_threshold
            and state.consecutive_zero_yield
            < self.zero_yield_stop_after
        ):
            return PaginationDecision(
                allow=True,
                reason="pagination_high_yield_family",
                family=identity.family,
            )

        if (
            state.consecutive_zero_yield
            >= self.zero_yield_stop_after
        ):
            self.skipped_pages += 1

            return PaginationDecision(
                allow=False,
                reason=(
                    "pagination_zero_yield_streak"
                ),
                family=identity.family,
            )

        return PaginationDecision(
            allow=True,
            reason="pagination_continue",
            family=identity.family,
        )

    # ========================================================
    # MÉTRICAS
    # ========================================================

    def metrics(
        self,
    ) -> dict[str, object]:

        productive = 0
        stagnant = 0

        for state in self.states.values():
            if state.total_yield > 0:
                productive += 1

            if (
                state.consecutive_zero_yield
                >= self.zero_yield_stop_after
            ):
                stagnant += 1

        return {
            "families_observed": len(
                self.states
            ),
            "productive_families": (
                productive
            ),
            "stagnant_families": (
                stagnant
            ),
            "pages_skipped": (
                self.skipped_pages
            ),
        }


__all__ = [
    "PaginationDecision",
    "PaginationFamilyState",
    "PaginationIdentity",
    "PaginationYieldPolicy",
]
