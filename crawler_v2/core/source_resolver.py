from __future__ import annotations

import time

from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse

from requests.exceptions import RequestException

from core.http_client import HttpClient


# ============================================================
# MODELOS
# ============================================================

@dataclass
class ResolutionAttempt:
    url: str
    status: str
    status_code: int | None = None
    final_url: str | None = None
    error: str | None = None


@dataclass
class SourceResolutionResult:
    original_url: str
    selected_url: str | None
    final_url: str | None
    used_fallback: bool
    attempts: list[ResolutionAttempt] = field(default_factory=list)


# ============================================================
# RESOLVER
# ============================================================

class SourceResolver:
    """
    Resuelve una URL institucional utilizable antes del crawl.

    Orden:
    1. base_url exacta.
    2. fallback_urls exactas, en el orden declarado.
    3. variantes seguras de esas mismas URLs (www/sin-www, http/https).

    Las URLs explícitas se prueban antes que variantes generadas para evitar
    consumir varios timeouts antes de llegar a un fallback real.

    Los entrypoints NO se resuelven aquí: son responsabilidad del Crawler.
    """

    def __init__(
        self,
        client: HttpClient,
    ) -> None:
        self.client = client

    # ========================================================
    # CANDIDATOS
    # ========================================================

    @staticmethod
    def _normalize_candidate(
        url: str,
    ) -> str | None:
        value = str(url or "").strip()

        if not value:
            return None

        if not value.startswith(
            (
                "http://",
                "https://",
            )
        ):
            value = "https://" + value

        parsed = urlparse(value)

        if not parsed.hostname:
            return None

        if parsed.scheme not in {
            "http",
            "https",
        }:
            return None

        return value

    @staticmethod
    def _url_variants(
        url: str,
    ) -> list[str]:
        """
        Genera variantes seguras de la MISMA URL.
        No cambia path/query ni inventa dominios.
        """

        parsed = urlparse(url)

        hostname = (
            parsed.hostname
            or ""
        )

        if not hostname:
            return [url]

        host_variants = [
            hostname
        ]

        if hostname.startswith("www."):
            without_www = hostname[4:]

            if without_www:
                host_variants.append(
                    without_www
                )
        else:
            host_variants.append(
                f"www.{hostname}"
            )

        scheme_variants = [
            parsed.scheme
        ]

        if parsed.scheme == "https":
            scheme_variants.append(
                "http"
            )

        elif parsed.scheme == "http":
            scheme_variants.append(
                "https"
            )

        results: list[str] = []

        for scheme in scheme_variants:
            for host in host_variants:
                netloc = host

                if parsed.port is not None:
                    if not (
                        (
                            scheme == "http"
                            and parsed.port == 80
                        )
                        or (
                            scheme == "https"
                            and parsed.port == 443
                        )
                    ):
                        netloc = (
                            f"{host}:{parsed.port}"
                        )

                candidate = urlunparse(
                    (
                        scheme,
                        netloc,
                        parsed.path or "/",
                        "",
                        parsed.query,
                        "",
                    )
                )

                if candidate not in results:
                    results.append(
                        candidate
                    )

        return results

    def _build_candidates(
        self,
        config: dict,
    ) -> list[str]:
        """
        Prueba primero TODAS las URLs explícitas:
        base_url, fallback 1, fallback 2...

        Solo después agrega variantes automáticas.
        """

        explicit: list[str] = []

        base_url = self._normalize_candidate(
            config.get(
                "base_url",
                "",
            )
        )

        if base_url:
            explicit.append(
                base_url
            )

        fallback_urls = (
            config.get(
                "fallback_urls",
                [],
            )
            or []
        )

        for fallback in fallback_urls:
            normalized = self._normalize_candidate(
                str(fallback)
            )

            if (
                normalized
                and normalized not in explicit
            ):
                explicit.append(
                    normalized
                )

        candidates = list(
            explicit
        )

        auto_variants = bool(
            config.get(
                "auto_url_variants",
                True,
            )
        )

        if not auto_variants:
            return candidates

        for raw_url in explicit:
            for variant in self._url_variants(
                raw_url
            ):
                if variant not in candidates:
                    candidates.append(
                        variant
                    )

        return candidates

    # ========================================================
    # PROBAR URL
    # ========================================================

    def _probe(
        self,
        url: str,
        *,
        timeout: float | None = None,
    ) -> ResolutionAttempt:
        response = None

        try:
            response = self.client.get(
                url,
                raise_for_status=False,
                timeout=timeout,
            )

            status_code = response.status_code
            final_url = response.url

            if 200 <= status_code < 400:
                return ResolutionAttempt(
                    url=url,
                    status="usable",
                    status_code=status_code,
                    final_url=final_url,
                )

            if status_code == 403:
                return ResolutionAttempt(
                    url=url,
                    status="forbidden",
                    status_code=403,
                    final_url=final_url,
                )

            if status_code == 404:
                return ResolutionAttempt(
                    url=url,
                    status="not_found",
                    status_code=404,
                    final_url=final_url,
                )

            return ResolutionAttempt(
                url=url,
                status="http_error",
                status_code=status_code,
                final_url=final_url,
            )

        except RequestException as exc:
            return ResolutionAttempt(
                url=url,
                status="request_error",
                error=(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            )

        finally:
            if response is not None:
                response.close()

    # ========================================================
    # RESOLVER
    # ========================================================

    def resolve(
        self,
        config: dict,
    ) -> SourceResolutionResult:
        """
        Resuelve la fuente como una comprobación de disponibilidad rápida.

        El resolver es una capa auxiliar. Nunca debe consumir minutos antes
        de que el Crawler tenga oportunidad de probar los entrypoints.

        Configuración opcional por fuente:
        - resolver_request_timeout: timeout máximo de cada probe.
        - resolver_max_seconds: presupuesto total del resolver.
        - resolver_max_attempts: número máximo de candidatos a probar.
        """

        original_url = str(
            config.get(
                "base_url",
                "",
            )
        ).strip()

        candidates = self._build_candidates(
            config
        )

        # ----------------------------------------------------
        # PRESUPUESTO DEL RESOLVER
        # ----------------------------------------------------

        try:
            default_probe_timeout = min(
                float(
                    self.client.timeout
                ),
                5.0,
            )
        except (
            TypeError,
            ValueError,
        ):
            default_probe_timeout = 5.0

        try:
            probe_timeout = max(
                0.5,
                float(
                    config.get(
                        "resolver_request_timeout",
                        default_probe_timeout,
                    )
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            probe_timeout = default_probe_timeout

        try:
            max_seconds = max(
                1.0,
                float(
                    config.get(
                        "resolver_max_seconds",
                        20.0,
                    )
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            max_seconds = 20.0

        try:
            max_attempts = max(
                1,
                int(
                    config.get(
                        "resolver_max_attempts",
                        8,
                    )
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            max_attempts = 8

        attempts: list[ResolutionAttempt] = []

        started = time.monotonic()

        for candidate in candidates:

            if (
                len(attempts)
                >= max_attempts
            ):
                break

            elapsed = (
                time.monotonic()
                - started
            )

            remaining = (
                max_seconds
                - elapsed
            )

            if remaining <= 0:
                break

            effective_timeout = max(
                0.5,
                min(
                    probe_timeout,
                    remaining,
                ),
            )

            attempt = self._probe(
                candidate,
                timeout=effective_timeout,
            )

            attempts.append(
                attempt
            )

            if attempt.status != "usable":
                continue

            selected_url = candidate

            final_url = (
                attempt.final_url
                or candidate
            )

            used_fallback = (
                selected_url.rstrip("/")
                != original_url.rstrip("/")
                or final_url.rstrip("/")
                != original_url.rstrip("/")
            )

            return SourceResolutionResult(
                original_url=original_url,
                selected_url=selected_url,
                final_url=final_url,
                used_fallback=used_fallback,
                attempts=attempts,
            )

        return SourceResolutionResult(
            original_url=original_url,
            selected_url=None,
            final_url=None,
            used_fallback=False,
            attempts=attempts,
        )


# ============================================================
# APLICAR RESOLUCIÓN
# ============================================================

def apply_source_resolution(
    config: dict,
    result: SourceResolutionResult,
) -> dict:
    """
    Devuelve una copia de la configuración usando la URL resuelta.

    Si no se resuelve una base utilizable, conserva la configuración
    original. El Crawler aún podrá intentar entrypoints y APIs.
    """

    resolved = dict(
        config
    )

    if not result.final_url:
        resolved[
            "_source_resolution"
        ] = {
            "original_url": result.original_url,
            "selected_url": None,
            "final_url": None,
            "used_fallback": False,
            "attempts": [
                {
                    "url": attempt.url,
                    "status": attempt.status,
                    "status_code": attempt.status_code,
                    "final_url": attempt.final_url,
                    "error": attempt.error,
                }
                for attempt in result.attempts
            ],
        }

        return resolved

    original_base = str(
        config.get(
            "base_url",
            "",
        )
    ).strip()

    final_url = (
        result.final_url
    )

    resolved[
        "base_url"
    ] = final_url

    # ========================================================
    # ALLOWED DOMAINS
    # ========================================================

    allowed_domains = list(
        config.get(
            "allowed_domains",
            [],
        )
        or []
    )

    final_hostname = (
        urlparse(
            final_url
        ).hostname
        or ""
    ).lower()

    if (
        final_hostname
        and final_hostname not in allowed_domains
    ):
        allowed_domains.append(
            final_hostname
        )

    if final_hostname.startswith(
        "www."
    ):
        root_hostname = (
            final_hostname[4:]
        )

        if (
            root_hostname
            and root_hostname not in allowed_domains
        ):
            allowed_domains.append(
                root_hostname
            )

    resolved[
        "allowed_domains"
    ] = allowed_domains

    # ========================================================
    # ENTRYPOINTS
    # ========================================================

    original_entrypoints = list(
        config.get(
            "entrypoints",
            [],
        )
        or []
    )

    entrypoints: list[str] = [
        final_url
    ]

    for entrypoint in original_entrypoints:
        value = str(
            entrypoint
        ).strip()

        if not value:
            continue

        if (
            original_base
            and value.rstrip("/")
            == original_base.rstrip("/")
        ):
            continue

        if value not in entrypoints:
            entrypoints.append(
                value
            )

    resolved[
        "entrypoints"
    ] = entrypoints

    # ========================================================
    # TRAZABILIDAD INTERNA
    # ========================================================

    resolved[
        "_source_resolution"
    ] = {
        "original_url": result.original_url,
        "selected_url": result.selected_url,
        "final_url": result.final_url,
        "used_fallback": result.used_fallback,
        "attempts": [
            {
                "url": attempt.url,
                "status": attempt.status,
                "status_code": attempt.status_code,
                "final_url": attempt.final_url,
                "error": attempt.error,
            }
            for attempt in result.attempts
        ],
    }

    return resolved