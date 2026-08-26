from __future__ import annotations

import time

from dataclasses import dataclass


# ============================================================
# RESULTADO
# ============================================================

@dataclass(frozen=True)
class BudgetDecision:
    stop: bool
    reason: str | None = None


# ============================================================
# PRESUPUESTO DE CRAWL
# ============================================================

class CrawlBudget:
    """
    Presupuesto operacional de una fuente.

    Objetivos:
    - ninguna fuente debe exceder el hard runtime;
    - evitar miles de requests sin valor;
    - permitir una exploración amplia cuando realmente encuentra datos;
    - exponer métricas para trazabilidad y batch.

    Este componente NO hace HTTP. Solamente lleva el estado.
    HttpClient/Crawler lo alimentan con eventos.
    """

    def __init__(
        self,
        *,
        soft_runtime_seconds: float = 1500.0,
        hard_runtime_seconds: float = 1800.0,
        max_requests: int | None = 1200,
        max_consecutive_errors: int = 12,
        max_requests_without_value: int = 100,
        min_requests_before_stagnation: int = 40,
    ) -> None:
        self.soft_runtime_seconds = max(
            1.0,
            float(soft_runtime_seconds),
        )

        self.hard_runtime_seconds = max(
            self.soft_runtime_seconds,
            float(hard_runtime_seconds),
        )

        self.max_requests = (
            None
            if max_requests is None
            else max(
                1,
                int(max_requests),
            )
        )

        self.max_consecutive_errors = max(
            1,
            int(max_consecutive_errors),
        )

        self.max_requests_without_value = max(
            1,
            int(max_requests_without_value),
        )

        self.min_requests_before_stagnation = max(
            0,
            int(min_requests_before_stagnation),
        )

        self.started_at = time.monotonic()

        self.requests = 0
        self.successful_requests = 0
        self.failed_requests = 0

        self.pages = 0
        self.files_kept = 0
        self.datasets_kept = 0
        self.resources_rejected = 0

        self.consecutive_errors = 0
        self.requests_without_value = 0

        self.last_value_request = 0

    # ========================================================
    # CONFIG
    # ========================================================

    @classmethod
    def from_config(
        cls,
        config: dict | None,
    ) -> "CrawlBudget":
        config = config or {}

        def _float(
            key: str,
            default: float,
        ) -> float:
            try:
                return float(
                    config.get(
                        key,
                        default,
                    )
                )
            except (TypeError, ValueError):
                return default

        def _int_or_none(
            key: str,
            default: int | None,
        ) -> int | None:
            value = config.get(
                key,
                default,
            )

            if value is None:
                return None

            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        def _int(
            key: str,
            default: int,
        ) -> int:
            try:
                return int(
                    config.get(
                        key,
                        default,
                    )
                )
            except (TypeError, ValueError):
                return default

        return cls(
            soft_runtime_seconds=_float(
                "crawl_soft_runtime_seconds",
                1500.0,
            ),
            hard_runtime_seconds=_float(
                "crawl_hard_runtime_seconds",
                1800.0,
            ),
            max_requests=_int_or_none(
                "crawl_max_requests",
                1200,
            ),
            max_consecutive_errors=_int(
                "crawl_max_consecutive_errors",
                12,
            ),
            max_requests_without_value=_int(
                "crawl_max_requests_without_value",
                100,
            ),
            min_requests_before_stagnation=_int(
                "crawl_min_requests_before_stagnation",
                40,
            ),
        )

    # ========================================================
    # TIEMPO
    # ========================================================

    @property
    def elapsed_seconds(
        self,
    ) -> float:
        return (
            time.monotonic()
            - self.started_at
        )

    @property
    def useful_resources(
        self,
    ) -> int:
        return (
            self.files_kept
            + self.datasets_kept
        )

    # ========================================================
    # EVENTOS
    # ========================================================

    def note_request(
        self,
        *,
        success: bool,
    ) -> None:
        self.requests += 1

        if success:
            self.successful_requests += 1
            self.consecutive_errors = 0
        else:
            self.failed_requests += 1
            self.consecutive_errors += 1

        self.requests_without_value += 1

    def note_page(
        self,
    ) -> None:
        self.pages += 1

    def note_file_kept(
        self,
    ) -> None:
        self.files_kept += 1
        self._note_value()

    def note_dataset_kept(
        self,
    ) -> None:
        self.datasets_kept += 1
        self._note_value()

    def note_rejected_resource(
        self,
    ) -> None:
        self.resources_rejected += 1

    def _note_value(
        self,
    ) -> None:
        self.requests_without_value = 0
        self.last_value_request = self.requests

    # ========================================================
    # DECISIÓN
    # ========================================================

    def decision(
        self,
    ) -> BudgetDecision:
        elapsed = self.elapsed_seconds

        # Hard stop absoluto.
        if elapsed >= self.hard_runtime_seconds:
            return BudgetDecision(
                stop=True,
                reason="hard_runtime_budget",
            )

        if (
            self.max_requests is not None
            and self.requests >= self.max_requests
        ):
            return BudgetDecision(
                stop=True,
                reason="request_budget",
            )

        if (
            self.consecutive_errors
            >= self.max_consecutive_errors
        ):
            return BudgetDecision(
                stop=True,
                reason="consecutive_errors_budget",
            )

        # Parada por estancamiento:
        # solamente después de haber explorado una cantidad mínima.
        if (
            self.requests
            >= self.min_requests_before_stagnation
            and self.requests_without_value
            >= self.max_requests_without_value
        ):
            return BudgetDecision(
                stop=True,
                reason="no_relevant_resources_budget",
            )

        # El soft limit NO corta automáticamente una fuente productiva.
        # A partir de aquí solo corta si además está estancada.
        if (
            elapsed >= self.soft_runtime_seconds
            and self.requests_without_value
            >= max(
                10,
                self.max_requests_without_value // 2,
            )
        ):
            return BudgetDecision(
                stop=True,
                reason="soft_runtime_stagnation",
            )

        return BudgetDecision(
            stop=False,
            reason=None,
        )

    # ========================================================
    # SNAPSHOT
    # ========================================================

    def metrics(
        self,
    ) -> dict:
        return {
            "elapsed_seconds": round(
                self.elapsed_seconds,
                3,
            ),
            "requests": self.requests,
            "successful_requests": (
                self.successful_requests
            ),
            "failed_requests": (
                self.failed_requests
            ),
            "pages": self.pages,
            "files_kept": self.files_kept,
            "datasets_kept": (
                self.datasets_kept
            ),
            "resources_rejected": (
                self.resources_rejected
            ),
            "useful_resources": (
                self.useful_resources
            ),
            "consecutive_errors": (
                self.consecutive_errors
            ),
            "requests_without_value": (
                self.requests_without_value
            ),
            "soft_runtime_seconds": (
                self.soft_runtime_seconds
            ),
            "hard_runtime_seconds": (
                self.hard_runtime_seconds
            ),
            "max_requests": self.max_requests,
        }