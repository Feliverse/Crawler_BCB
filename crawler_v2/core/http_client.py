from __future__ import annotations

import random
import time

from collections.abc import Mapping

import requests
from requests import Response
from requests.exceptions import RequestException


class HttpClient:
    """
    Cliente HTTP común para todas las fuentes.

    Centraliza:
    - Sesión HTTP reutilizable.
    - Cabeceras comunes.
    - Timeout.
    - Redirecciones.
    - Temporización aleatoria.
    - Solicitudes HTTP utilizadas por HTML, APIs y ZIP.

    Toda solicitud HTTP del crawler debe pasar por esta clase.
    """

    def __init__(
        self,
        *,
        timeout: int = 10,
        delay_seconds: float = 0.3,
        random_delay_min: float | None = None,
        random_delay_max: float | None = None,
    ) -> None:

        self.timeout = timeout

        # ====================================================
        # RETARDO
        # ====================================================

        self.delay_seconds = max(
            0.0,
            float(delay_seconds),
        )

        # Compatibilidad con configuraciones antiguas.
        if random_delay_min is None:
            random_delay_min = (
                self.delay_seconds
            )

        if random_delay_max is None:

            if self.delay_seconds > 0:
                random_delay_max = (
                    self.delay_seconds
                    * 3
                )

            else:
                random_delay_max = 0.0

        self.random_delay_min = max(
            0.0,
            float(random_delay_min),
        )

        self.random_delay_max = max(
            0.0,
            float(random_delay_max),
        )

        if (
            self.random_delay_min
            > self.random_delay_max
        ):
            raise ValueError(
                "random_delay_min no puede ser mayor "
                "que random_delay_max"
            )

        self._random = random.Random()

        self._last_request = 0.0

        self._last_delay = 0.0

        # ====================================================
        # SESIÓN
        # ====================================================

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
                "Accept-Language": (
                    "es-BO,es;q=0.9,en;q=0.7"
                ),
                "Connection": "keep-alive",
            }
        )

    # ========================================================
    # RETARDO ALEATORIO
    # ========================================================

    def _generate_delay(
        self,
    ) -> float:
        """
        Genera un intervalo aleatorio entre el mínimo
        y máximo configurados.
        """

        if self.random_delay_max <= 0:
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
        """
        Espera el intervalo necesario antes de una nueva
        solicitud HTTP.

        La primera petición no espera.
        """

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
    # HTTP GET
    # ========================================================

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        raise_for_status: bool = True,
    ) -> Response:
        """
        Ejecuta una solicitud GET respetando siempre
        el temporizador aleatorio.

        `headers` permite realizar solicitudes especiales,
        por ejemplo:

            Range: bytes=-65557

        Esto es utilizado por ZipInspector sin necesidad de
        acceder directamente a session.get().

        También puede utilizarse posteriormente para APIs.

        Parameters
        ----------
        url:
            URL solicitada.

        headers:
            Cabeceras adicionales para esta petición.

        raise_for_status:
            Si es True, respuestas HTTP 4xx/5xx generan
            RequestException.
        """

        self._wait()

        response: Response | None = None

        try:

            response = self.session.get(
                url,
                headers=(
                    dict(headers)
                    if headers
                    else None
                ),
                timeout=self.timeout,
                allow_redirects=True,
                stream=True,
            )

            if raise_for_status:

                try:
                    response.raise_for_status()

                except RequestException:

                    response.close()

                    raise

            return response

        finally:

            # Se actualiza incluso cuando ocurre:
            #
            # - timeout
            # - DNS
            # - SSL
            # - HTTP 4xx / 5xx
            #
            # para evitar solicitudes consecutivas
            # demasiado rápidas después de un error.

            self._last_request = (
                time.monotonic()
            )

    # ========================================================
    # INFORMACIÓN
    # ========================================================

    @property
    def last_delay(
        self,
    ) -> float:
        """
        Último intervalo aleatorio seleccionado.
        """

        return self._last_delay

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