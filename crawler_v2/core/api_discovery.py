from __future__ import annotations

import html
import re

from dataclasses import dataclass

from urllib.parse import (
    unquote,
    urljoin,
    urlparse,
)

from bs4 import BeautifulSoup


# ============================================================
# PATRONES
# ============================================================

API_HINTS = (
    "/api/",
    "/api?",
    "/oapi/",
    "/ogcapi/",
    "/rest/",
    "/v1/",
    "/v2/",
    "/v3/",
    "/v4/",
    "/graphql",
    "/openapi",
    "/swagger",
    "/api-docs",
    "/v3/api-docs",
    "/geoserver/",
    "/arcgis/rest/",
    "api.",
    "format=json",
    "format=geojson",
    "f=json",
    "f=geojson",
    "service=wms",
    "service=wfs",
    "service=wcs",
    "request=getcapabilities",
)

# Captura una URL absoluta, pero la validación fuerte se realiza después.
# La expresión se mantiene relativamente amplia para soportar URLs dentro de
# JavaScript/JSON sin introducir reglas particulares por institución.
ABSOLUTE_URL_PATTERN = re.compile(
    r"https?:(?:\\?/\\?/|//)[^\"'<>\\\s)]+",
    re.IGNORECASE,
)

RELATIVE_API_PATTERN = re.compile(
    (
        r"[\"']"
        r"("
        r"/(?:"
        r"api(?:/|\?)|"
        r"oapi(?:/|\?)|"
        r"ogcapi(?:/|\?)|"
        r"rest(?:/|\?)|"
        r"v[1-9](?:/|\?)|"
        r"graphql(?:/|\?)|"
        r"openapi(?:[./?]|$)|"
        r"swagger(?:[./?]|$)|"
        r"api-docs(?:[/?]|$)|"
        r"geoserver(?:/|\?)|"
        r"arcgis/rest(?:/|\?)"
        r")"
        r"[^\"']*"
        r")"
        r"[\"']"
    ),
    re.IGNORECASE,
)

DATA_ATTRIBUTES = (
    "data-api",
    "data-api-url",
    "data-endpoint",
    "data-url",
    "data-source",
    "data-feed",
    "data-json",
    "data-service",
)

# Límites conservadores para una referencia descubierta dentro de HTML/JS.
# No afectan a endpoints declarados en sources/*.json: únicamente al
# descubrimiento automático de referencias.
MAX_REFERENCE_LENGTH = 2048
MAX_QUERY_LENGTH = 1200
MAX_QUERY_SEPARATORS = 24

# Señales inequívocas de que el extractor capturó texto serializado o una
# plantilla en lugar de una URL ejecutable. Fueron definidas de forma
# genérica para HTML/JS y no para una fuente concreta.
INVALID_LITERAL_MARKERS = (
    "${",
    "{{",
    "}}",
    "&q;",
    "&quot;",
    "&#34;",
    "&#x22;",
)

INVALID_ENCODED_MARKERS = (
    "%24%7b",  # ${
    "%7b",     # {
    "%7d",     # }
    "q%3b",    # residuo de &q;
    "%26q%3b",
)


# ============================================================
# MODELO
# ============================================================

@dataclass(frozen=True)
class ApiReferenceCandidate:
    url: str
    reason: str


# ============================================================
# DISCOVERY
# ============================================================

class ApiReferenceDiscovery:
    """
    Descubre referencias a APIs que ya están expuestas por el propio
    HTML de una fuente.

    No inventa endpoints ni prueba rutas al azar. Solamente extrae
    referencias observables en:

    - enlaces <link>
    - scripts src
    - atributos data-*
    - meta content
    - JavaScript inline

    Antes de devolver una referencia aplica una validación conservadora
    para evitar que fragmentos de HTML, estado serializado, plantillas o
    cadenas escapadas sean tratados como URLs reales.

    El Crawler sigue siendo responsable de:
    - validar dominio permitido
    - aplicar ApiPolicy
    - ejecutar GET
    - detectar el formato real con ApiDetector
    - registrar solamente datasets útiles

    Esta clase mejora el descubrimiento genérico sin introducir lógica
    específica por fuente.
    """

    # ========================================================
    # NORMALIZACIÓN
    # ========================================================

    @staticmethod
    def _html_unescape_repeated(
        value: str,
        *,
        rounds: int = 2,
    ) -> str:

        result = str(value or "")

        for _ in range(max(1, rounds)):
            decoded = html.unescape(result)

            if decoded == result:
                break

            result = decoded

        return result

    @classmethod
    def _clean_reference(
        cls,
        value: str,
    ) -> str:

        cleaned = cls._html_unescape_repeated(
            str(value or "").strip()
        )

        cleaned = (
            cleaned
            .replace(r"\/", "/")
            .strip(
                " \t\r\n\"'<>),;"
            )
        )

        return cleaned

    # ========================================================
    # SANIDAD
    # ========================================================

    @classmethod
    def _is_sane_reference(
        cls,
        value: str,
    ) -> bool:

        candidate = str(value or "").strip()

        if not candidate:
            return False

        if len(candidate) > MAX_REFERENCE_LENGTH:
            return False

        lowered = candidate.lower()

        if any(
            marker in lowered
            for marker in INVALID_LITERAL_MARKERS
        ):
            return False

        if any(
            marker in lowered
            for marker in INVALID_ENCODED_MARKERS
        ):
            return False

        # Una referencia descubierta debe ser una URL concreta, no una
        # plantilla del tipo /items/{id} o /find{?q}.
        if "{" in candidate or "}" in candidate:
            return False

        # El extractor nunca debe convertir un bloque serializado completo
        # en una URL. Estas señales normalmente aparecen cuando la captura
        # atravesó el cierre real de una cadena JavaScript/HTML.
        if any(
            token in candidate
            for token in (
                "\\n",
                "\\r",
                "\\t",
            )
        ):
            return False

        if any(
            ch in candidate
            for ch in (
                "\n",
                "\r",
                "\t",
                "<",
                ">",
                '"',
                "'",
            )
        ):
            return False

        parsed = urlparse(candidate)

        if parsed.query:

            if len(parsed.query) > MAX_QUERY_LENGTH:
                return False

            if parsed.query.count("&") > MAX_QUERY_SEPARATORS:
                return False

        return True

    @classmethod
    def _absolute(
        cls,
        value: str,
        page_url: str,
    ) -> str | None:

        cleaned = cls._clean_reference(
            value
        )

        if not cls._is_sane_reference(
            cleaned
        ):
            return None

        try:
            absolute = urljoin(
                page_url,
                cleaned,
            )
        except ValueError:
            return None

        if not cls._is_sane_reference(
            absolute
        ):
            return None

        parsed = urlparse(
            absolute
        )

        if (
            parsed.scheme.lower()
            not in {
                "http",
                "https",
            }
        ):
            return None

        if not parsed.hostname:
            return None

        # Un hostname válido no contiene llaves, espacios ni residuos de
        # entidades HTML.
        hostname = parsed.hostname.lower()

        if any(
            marker in hostname
            for marker in (
                "{",
                "}",
                "&",
                "%",
            )
        ):
            return None

        return absolute

    # ========================================================
    # HEURÍSTICA
    # ========================================================

    @staticmethod
    def looks_like_api_reference(
        value: str,
    ) -> bool:

        lowered = unquote(
            str(
                value
                or ""
            )
        ).lower()

        return any(
            hint in lowered
            for hint in API_HINTS
        )

    # ========================================================
    # AGREGAR
    # ========================================================

    @classmethod
    def _add_candidate(
        cls,
        candidates: dict[str, ApiReferenceCandidate],
        *,
        raw_value: str,
        page_url: str,
        reason: str,
        require_hint: bool = True,
    ) -> None:

        cleaned = cls._clean_reference(
            raw_value
        )

        if not cls._is_sane_reference(
            cleaned
        ):
            return

        if (
            require_hint
            and not cls.looks_like_api_reference(
                cleaned
            )
        ):
            return

        absolute = cls._absolute(
            cleaned,
            page_url,
        )

        if not absolute:
            return

        if absolute not in candidates:

            candidates[
                absolute
            ] = ApiReferenceCandidate(
                url=absolute,
                reason=reason,
            )

    # ========================================================
    # TEXTO / JS INLINE
    # ========================================================

    @classmethod
    def _from_text(
        cls,
        candidates: dict[str, ApiReferenceCandidate],
        *,
        text: str,
        page_url: str,
        reason: str,
    ) -> None:

        if not text:
            return

        # Decodificar entidades antes del regex reduce el riesgo de que una
        # URL se extienda artificialmente a través de texto HTML serializado.
        scan_text = cls._html_unescape_repeated(
            str(text)
        )

        for match in ABSOLUTE_URL_PATTERN.finditer(
            scan_text
        ):

            cls._add_candidate(
                candidates,
                raw_value=match.group(0),
                page_url=page_url,
                reason=reason,
                require_hint=True,
            )

        for match in RELATIVE_API_PATTERN.finditer(
            scan_text
        ):

            cls._add_candidate(
                candidates,
                raw_value=match.group(1),
                page_url=page_url,
                reason=reason,
                require_hint=False,
            )

    # ========================================================
    # DESCUBRIR
    # ========================================================

    def discover(
        self,
        soup: BeautifulSoup,
        page_url: str,
        *,
        max_candidates: int = 50,
    ) -> list[ApiReferenceCandidate]:

        limit = max(
            0,
            int(
                max_candidates
            ),
        )

        if limit <= 0:
            return []

        candidates: dict[
            str,
            ApiReferenceCandidate,
        ] = {}

        # ----------------------------------------------------
        # <link href="...">
        # ----------------------------------------------------

        for tag in soup.find_all(
            "link",
            href=True,
        ):

            self._add_candidate(
                candidates,
                raw_value=str(
                    tag.get(
                        "href"
                    )
                ),
                page_url=page_url,
                reason="html_link_reference",
            )

            if len(
                candidates
            ) >= limit:
                return list(
                    candidates.values()
                )[:limit]

        # ----------------------------------------------------
        # <script src="...">
        # ----------------------------------------------------

        for tag in soup.find_all(
            "script",
            src=True,
        ):

            self._add_candidate(
                candidates,
                raw_value=str(
                    tag.get(
                        "src"
                    )
                ),
                page_url=page_url,
                reason="script_src_reference",
            )

            if len(
                candidates
            ) >= limit:
                return list(
                    candidates.values()
                )[:limit]

        # ----------------------------------------------------
        # data-* conocidos
        # ----------------------------------------------------

        for tag in soup.find_all(
            True
        ):

            for attribute in DATA_ATTRIBUTES:

                value = tag.get(
                    attribute
                )

                if value is None:
                    continue

                self._add_candidate(
                    candidates,
                    raw_value=str(
                        value
                    ),
                    page_url=page_url,
                    reason=f"html_{attribute}",
                )

                if len(
                    candidates
                ) >= limit:
                    return list(
                        candidates.values()
                    )[:limit]

        # ----------------------------------------------------
        # <meta content="...">
        # ----------------------------------------------------

        for tag in soup.find_all(
            "meta",
            content=True,
        ):

            value = str(
                tag.get(
                    "content"
                )
            )

            self._from_text(
                candidates,
                text=value,
                page_url=page_url,
                reason="meta_content_reference",
            )

            if len(
                candidates
            ) >= limit:
                return list(
                    candidates.values()
                )[:limit]

        # ----------------------------------------------------
        # JS INLINE
        # ----------------------------------------------------

        for tag in soup.find_all(
            "script"
        ):

            if tag.get(
                "src"
            ):
                continue

            text = tag.string

            if text is None:

                text = tag.get_text(
                    " ",
                    strip=False,
                )

            self._from_text(
                candidates,
                text=str(
                    text
                    or ""
                ),
                page_url=page_url,
                reason="inline_script_reference",
            )

            if len(
                candidates
            ) >= limit:
                break

        return list(
            candidates.values()
        )[:limit]