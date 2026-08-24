from __future__ import annotations

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

    attempts: list[ResolutionAttempt] = field(
        default_factory=list
    )


# ============================================================
# RESOLVER
# ============================================================

class SourceResolver:
    """
    Resuelve la URL de entrada utilizable de una fuente.

    Puede probar:

    1. base_url original.
    2. variantes HTTPS / HTTP.
    3. variantes www / sin www.
    4. fallback_urls declaradas explícitamente.

    Esto permite recuperar fuentes migradas o con cambios
    simples sin desarrollar adapters específicos.
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

        value = str(
            url or ""
        ).strip()

        if not value:
            return None

        if not value.startswith(
            (
                "http://",
                "https://",
            )
        ):
            value = (
                "https://"
                + value
            )

        parsed = urlparse(
            value
        )

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
        Genera variantes seguras de la misma URL.

        Ejemplo:

            https://www.ejemplo.bo/

        puede generar:

            https://www.ejemplo.bo/
            https://ejemplo.bo/
            http://www.ejemplo.bo/
            http://ejemplo.bo/

        No inventa dominios diferentes.
        """

        parsed = urlparse(
            url
        )

        hostname = (
            parsed.hostname
            or ""
        )

        if not hostname:
            return [
                url
            ]

        host_variants = [
            hostname
        ]

        if hostname.startswith(
            "www."
        ):

            without_www = (
                hostname[4:]
            )

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

                    # No conserva puertos estándar cuando
                    # cambia el protocolo automáticamente.
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

        candidates: list[str] = []

        base_url = (
            self._normalize_candidate(
                config.get(
                    "base_url",
                    ""
                )
            )
        )

        fallback_urls = (
            config.get(
                "fallback_urls",
                []
            )
            or []
        )

        auto_variants = bool(
            config.get(
                "auto_url_variants",
                True,
            )
        )

        raw_candidates = []

        if base_url:

            raw_candidates.append(
                base_url
            )

        for fallback in fallback_urls:

            normalized = (
                self._normalize_candidate(
                    str(
                        fallback
                    )
                )
            )

            if normalized:

                raw_candidates.append(
                    normalized
                )

        for raw_url in raw_candidates:

            if auto_variants:

                variants = (
                    self._url_variants(
                        raw_url
                    )
                )

            else:

                variants = [
                    raw_url
                ]

            for variant in variants:

                if (
                    variant
                    not in candidates
                ):
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
    ) -> ResolutionAttempt:

        response = None

        try:

            response = (
                self.client.get(
                    url,
                    raise_for_status=False,
                )
            )

            status_code = (
                response.status_code
            )

            final_url = (
                response.url
            )

            if (
                200
                <= status_code
                < 400
            ):

                return ResolutionAttempt(
                    url=url,
                    status="usable",
                    status_code=(
                        status_code
                    ),
                    final_url=(
                        final_url
                    ),
                )

            if status_code == 403:

                return ResolutionAttempt(
                    url=url,
                    status="forbidden",
                    status_code=403,
                    final_url=(
                        final_url
                    ),
                )

            if status_code == 404:

                return ResolutionAttempt(
                    url=url,
                    status="not_found",
                    status_code=404,
                    final_url=(
                        final_url
                    ),
                )

            return ResolutionAttempt(
                url=url,
                status="http_error",
                status_code=(
                    status_code
                ),
                final_url=(
                    final_url
                ),
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

        original_url = str(
            config.get(
                "base_url",
                ""
            )
        ).strip()

        candidates = (
            self._build_candidates(
                config
            )
        )

        attempts: list[
            ResolutionAttempt
        ] = []

        for candidate in candidates:

            attempt = (
                self._probe(
                    candidate
                )
            )

            attempts.append(
                attempt
            )

            if (
                attempt.status
                == "usable"
            ):

                selected_url = (
                    candidate
                )

                final_url = (
                    attempt.final_url
                    or candidate
                )

                used_fallback = (
                    selected_url
                    != original_url
                    or final_url
                    != original_url
                )

                return SourceResolutionResult(
                    original_url=(
                        original_url
                    ),
                    selected_url=(
                        selected_url
                    ),
                    final_url=(
                        final_url
                    ),
                    used_fallback=(
                        used_fallback
                    ),
                    attempts=attempts,
                )

        return SourceResolutionResult(
            original_url=(
                original_url
            ),
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
    Devuelve una copia de la configuración utilizando la URL
    resuelta.

    También amplía allowed_domains cuando la URL final cambia
    legítimamente de host.
    """

    resolved = dict(
        config
    )

    if not result.final_url:

        return resolved

    original_base = str(
        config.get(
            "base_url",
            ""
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
            []
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
        and final_hostname
        not in allowed_domains
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
            and root_hostname
            not in allowed_domains
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
            []
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

        # Si el entrypoint era exactamente la base URL vieja
        # no tiene sentido volver a agregarlo cuando ya hemos
        # resuelto una URL mejor.

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
        "original_url": (
            result.original_url
        ),
        "selected_url": (
            result.selected_url
        ),
        "final_url": (
            result.final_url
        ),
        "used_fallback": (
            result.used_fallback
        ),
        "attempts": [
            {
                "url": attempt.url,
                "status": (
                    attempt.status
                ),
                "status_code": (
                    attempt.status_code
                ),
                "final_url": (
                    attempt.final_url
                ),
                "error": (
                    attempt.error
                ),
            }
            for attempt
            in result.attempts
        ],
    }

    return resolved