from __future__ import annotations

import time

import requests
from requests import Response


class HttpClient:
    """
    Cliente HTTP común para todas las fuentes.

    No descarga documentos deliberadamente.
    Solo obtiene HTML y respuestas necesarias para descubrir recursos.
    """

    def __init__(
        self,
        *,
        timeout: int = 10,
        delay_seconds: float = 0.3,
    ) -> None:
        self.timeout = timeout
        self.delay_seconds = delay_seconds

        self.session = requests.Session()

        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/120.0.0.0 "
                    "Safari/537.36"
                ),
                "Accept": (
                    "text/html,"
                    "application/xhtml+xml,"
                    "application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),
                "Accept-Language": "es-BO,es;q=0.9,en;q=0.7",
            }
        )

        self._last_request = 0.0

    def _wait(self) -> None:
        if self.delay_seconds <= 0:
            return

        elapsed = time.monotonic() - self._last_request
        remaining = self.delay_seconds - elapsed

        if remaining > 0:
            time.sleep(remaining)

    def get(self, url: str) -> Response:
        self._wait()

        response = self.session.get(
            url,
            timeout=self.timeout,
            allow_redirects=True,
            stream=True,
        )

        self._last_request = time.monotonic()

        response.raise_for_status()

        return response

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        self.close()