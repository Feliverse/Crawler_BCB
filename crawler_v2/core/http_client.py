from __future__ import annotations

import random
import time

from collections.abc import Mapping

import requests
import urllib3

from requests import Response
from requests.exceptions import RequestException
from urllib3.exceptions import InsecureRequestWarning


class HttpClient:
    """
    Cliente HTTP común para todas las fuentes.

    Centraliza:
    - sesión HTTP reutilizable;
    - cabeceras comunes;
    - timeout;
    - redirecciones;
    - temporización aleatoria;
    - verificación TLS configurable por fuente;
    - CA bundle opcional;
    - GET/HEAD usados por HTML, APIs, ZIP y probes;
    - contador absoluto de solicitudes HTTP.

    Toda solicitud HTTP del crawler debe pasar por esta clase.
    """

    def __init__(
        self,
        *,
        timeout: int = 10,
        delay_seconds: float = 0.3,
        random_delay_min: float | None = None,
        random_delay_max: float | None = None,
        verify_ssl: bool = True,
        ca_bundle: str | None = None,
    ) -> None:

        self.timeout = max(
            1,
            int(
                timeout
            ),
        )

        # ====================================================
        # TLS
        # ====================================================

        self.verify_ssl = bool(
            verify_ssl
        )

        bundle = str(
            ca_bundle
            or ""
        ).strip()

        self.ca_bundle = (
            bundle
            or None
        )

        # requests acepta:
        # - True: verificar con CA por defecto
        # - False: no verificar
        # - str: ruta de CA bundle personalizado
        if self.ca_bundle:
            self._verify = (
                self.ca_bundle
            )
        else:
            self._verify = (
                self.verify_ssl
            )

        # Si una fuente fue configurada explícitamente con
        # verify_ssl=false, evitamos llenar la terminal con
        # InsecureRequestWarning. La excepción queda limitada
        # al proceso de esa fuente.
        if (
            self._verify
            is False
        ):
            urllib3.disable_warnings(
                InsecureRequestWarning
            )

        # ====================================================
        # RETARDO
        # ====================================================

        self.delay_seconds = max(
            0.0,
            float(
                delay_seconds
            ),
        )

        if random_delay_min is None:
            random_delay_min = (
                self.delay_seconds
            )

        if random_delay_max is None:

            if (
                self.delay_seconds
                > 0
            ):
                random_delay_max = (
                    self.delay_seconds
                    * 3
                )

            else:
                random_delay_max = 0.0

        self.random_delay_min = max(
            0.0,
            float(
                random_delay_min
            ),
        )

        self.random_delay_max = max(
            0.0,
            float(
                random_delay_max
            ),
        )

        if (
            self.random_delay_min
            > self.random_delay_max
        ):
            raise ValueError(
                "random_delay_min no puede ser mayor "
                "que random_delay_max"
            )

        self._random = (
            random.Random()
        )

        self._last_request = 0.0
        self._last_delay = 0.0

        # ====================================================
        # MÉTRICAS HTTP ABSOLUTAS
        # ====================================================

        self._request_count = 0
        self._requests_by_method: dict[
            str,
            int,
        ] = {}

        # ====================================================
        # SESIÓN
        # ====================================================

        self.session = (
            requests.Session()
        )

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
                "Accept-Language": (
                    "es-BO,es;q=0.9,en;q=0.7"
                ),
                "Connection": (
                    "keep-alive"
                ),
            }
        )

    # ========================================================
    # RETARDO ALEATORIO
    # ========================================================

    def _generate_delay(
        self,
    ) -> float:

        if (
            self.random_delay_max
            <= 0
        ):
            return 0.0

        if (
            self.random_delay_min
            == self.random_delay_max
        ):
            return (
                self.random_delay_min
            )

        return self._random.uniform(
            self.random_delay_min,
            self.random_delay_max,
        )

    def _wait(
        self,
    ) -> None:

        target_delay = (
            self._generate_delay()
        )

        self._last_delay = (
            target_delay
        )

        if target_delay <= 0:
            return

        if self._last_request <= 0:
            return

        elapsed = (
            time.monotonic()
            - self._last_request
        )

        remaining = (
            target_delay
            - elapsed
        )

        if remaining > 0:
            time.sleep(
                remaining
            )

    # ========================================================
    # REQUEST COMÚN
    # ========================================================

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        raise_for_status: bool = True,
        timeout: float | tuple[float, float] | None = None,
        stream: bool = True,
    ) -> Response:
        """
        Ejecuta una solicitud usando siempre la misma política HTTP/TLS.

        El contador se incrementa antes de abrir la conexión, por lo que
        también contabiliza timeouts, errores DNS/TLS y HTTP fallidos.
        """

        normalized_method = str(
            method
            or "GET"
        ).strip().upper()

        self._wait()

        self._request_count += 1

        self._requests_by_method[
            normalized_method
        ] = (
            self._requests_by_method.get(
                normalized_method,
                0,
            )
            + 1
        )

        response: Response | None = None

        try:

            response = (
                self.session.request(
                    method=normalized_method,
                    url=url,
                    headers=(
                        dict(
                            headers
                        )
                        if headers
                        else None
                    ),
                    timeout=(
                        self.timeout
                        if timeout is None
                        else timeout
                    ),
                    allow_redirects=True,
                    stream=stream,
                    verify=(
                        self._verify
                    ),
                )
            )

            if raise_for_status:

                try:
                    response.raise_for_status()

                except RequestException:
                    response.close()
                    raise

            return response

        finally:

            # Se actualiza aun con timeout, DNS, SSL o HTTP error
            # para no golpear el servidor inmediatamente después.
            self._last_request = (
                time.monotonic()
            )

    # ========================================================
    # HTTP GET
    # ========================================================

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        raise_for_status: bool = True,
        timeout: float | tuple[float, float] | None = None,
    ) -> Response:
        """
        Ejecuta GET usando siempre la política HTTP/TLS común.

        `headers` permite solicitudes especiales, por ejemplo Range
        para ZipInspector.

        `timeout` permite que tareas auxiliares como SourceResolver o
        SitemapDiscovery usen un timeout corto sin modificar el timeout
        normal configurado para el crawl de la fuente.
        """

        return self._request(
            "GET",
            url,
            headers=headers,
            raise_for_status=raise_for_status,
            timeout=timeout,
            stream=True,
        )

    # ========================================================
    # HTTP HEAD
    # ========================================================

    def head(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        raise_for_status: bool = True,
        timeout: float | tuple[float, float] | None = None,
    ) -> Response:
        """
        Comprueba cabeceras/existencia sin descargar el cuerpo.

        Se usa de forma conservadora para candidatos que un adapter puede
        inferir pero que no aparecen literalmente en el HTML.
        """

        return self._request(
            "HEAD",
            url,
            headers=headers,
            raise_for_status=raise_for_status,
            timeout=timeout,
            stream=True,
        )

    # ========================================================
    # INFORMACIÓN
    # ========================================================

    @property
    def last_delay(
        self,
    ) -> float:

        return (
            self._last_delay
        )

    @property
    def tls_verification(
        self,
    ) -> bool | str:
        """
        Valor real enviado a requests mediante `verify=`.
        """

        return (
            self._verify
        )

    @property
    def request_count(
        self,
    ) -> int:
        """
        Total absoluto de solicitudes intentadas por esta instancia.
        """

        return int(
            self._request_count
        )

    @property
    def requests_by_method(
        self,
    ) -> dict[str, int]:
        """
        Copia de los contadores por método para diagnóstico/auditoría.
        """

        return dict(
            self._requests_by_method
        )

    # ========================================================
    # CICLO DE VIDA
    # ========================================================

    def close(
        self,
    ) -> None:

        self.session.close()

    def __enter__(
        self,
    ) -> "HttpClient":

        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:

        self.close()
