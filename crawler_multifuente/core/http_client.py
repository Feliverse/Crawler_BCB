from __future__ import annotations

import time
from typing import Optional

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.source_config import SourceConfig


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class HttpClient:
    """
    Cliente HTTP reutilizable para todas las fuentes del crawler.

    Responsabilidades:
    - Reutilizar conexiones mediante requests.Session.
    - Aplicar timeout.
    - Respetar la pausa configurada entre solicitudes.
    - Reintentar errores temporales.
    - Validar que la URL pertenezca a un dominio permitido.
    - Centralizar headers y manejo básico de errores HTTP.

    No contiene lógica específica de ASFI, BCB u otra institución.
    """

    def __init__(
        self,
        config: SourceConfig,
        user_agent: Optional[str] = None,
    ) -> None:
        self.config = config
        self.session = self._create_session(user_agent)
        self._last_request_at: Optional[float] = None

    def _create_session(self, user_agent: Optional[str]) -> Session:
        session = requests.Session()

        session.headers.update(
            {
                "User-Agent": user_agent or DEFAULT_USER_AGENT,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),
                "Accept-Language": "es-BO,es;q=0.9,en;q=0.7",
                "Connection": "keep-alive",
            }
        )

        retry_strategy = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            raise_on_status=False,
        )

        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=10,
        )

        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _wait_if_needed(self) -> None:
        """
        Garantiza una pausa mínima entre solicitudes consecutivas.
        """
        if self._last_request_at is None:
            return

        elapsed = time.monotonic() - self._last_request_at
        remaining = self.config.delay_seconds - elapsed

        if remaining > 0:
            time.sleep(remaining)

    def _validate_url(self, url: str) -> None:
        """
        Evita que el crawler navegue accidentalmente hacia dominios
        no autorizados por la configuración de la fuente.
        """
        if not self.config.domain_is_allowed(url):
            raise ValueError(
                f"Dominio no permitido para la fuente "
                f"'{self.config.id_fuente}': {url}"
            )

    def get(
        self,
        url: str,
        *,
        allow_redirects: bool = True,
        stream: bool = False,
    ) -> Response:
        """
        Ejecuta una petición GET controlada.
        """
        self._validate_url(url)
        self._wait_if_needed()

        try:
            response = self.session.get(
                url,
                timeout=self.config.request_timeout,
                allow_redirects=allow_redirects,
                stream=stream,
            )
        finally:
            self._last_request_at = time.monotonic()

        response.raise_for_status()

        return response

    def head(
        self,
        url: str,
        *,
        allow_redirects: bool = True,
    ) -> Response:
        """
        Ejecuta una petición HEAD.

        Será útil más adelante para identificar Content-Type,
        Content-Length y otros metadatos sin descargar el archivo completo.
        """
        self._validate_url(url)
        self._wait_if_needed()

        try:
            response = self.session.head(
                url,
                timeout=self.config.request_timeout,
                allow_redirects=allow_redirects,
            )
        finally:
            self._last_request_at = time.monotonic()

        response.raise_for_status()

        return response

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()