from __future__ import annotations

import gzip
import ipaddress
import time
import xml.etree.ElementTree as ET

from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse, urlunparse

from requests.exceptions import RequestException

from core.http_client import HttpClient


# ============================================================
# RESULTADO
# ============================================================

@dataclass
class SitemapDiscoveryResult:
    sitemap_documents: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ============================================================
# SITEMAP DISCOVERY
# ============================================================

class SitemapDiscovery:
    """
    Descubre URLs públicas a partir de:

    - robots.txt -> Sitemap:
    - /sitemap.xml
    - /sitemap_index.xml
    - /sitemap-index.xml
    - /sitemap.xml.gz
    - índices de sitemap anidados

    No amplía dominios fuera de allowed_domains.
    No sustituye la navegación HTML: añade semillas adicionales.
    """

    DEFAULT_SITEMAPS = (
        "/sitemap.xml",
        "/sitemap_index.xml",
        "/sitemap-index.xml",
        "/sitemap.xml.gz",
    )

    def __init__(
        self,
        client: HttpClient,
    ) -> None:
        self.client = client

    # ========================================================
    # URL
    # ========================================================

    @staticmethod
    def _origin(
        url: str,
    ) -> str:
        parsed = urlparse(url)

        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                "",
                "",
                "",
                "",
            )
        )

    @staticmethod
    def _normalize(
        url: str,
        base_url: str | None = None,
    ) -> str | None:
        value = str(url or "").strip()

        if not value:
            return None

        if base_url:
            value = urljoin(base_url, value)

        parsed = urlparse(value)

        if parsed.scheme.lower() not in {
            "http",
            "https",
        }:
            return None

        if not parsed.hostname:
            return None

        return urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path or "/",
                "",
                parsed.query,
                "",
            )
        )

    @staticmethod
    def _public_host(
        hostname: str,
    ) -> bool:
        hostname = str(hostname or "").strip().lower()

        if not hostname:
            return False

        if hostname in {
            "localhost",
            "localhost.localdomain",
        }:
            return False

        if hostname.endswith(".local"):
            return False

        try:
            ip = ipaddress.ip_address(hostname)

        except ValueError:
            return True

        return not any(
            (
                ip.is_private,
                ip.is_loopback,
                ip.is_link_local,
                ip.is_multicast,
                ip.is_unspecified,
                ip.is_reserved,
            )
        )

    @classmethod
    def _allowed(
        cls,
        url: str,
        allowed_domains: tuple[str, ...],
    ) -> bool:
        hostname = (
            urlparse(url).hostname
            or ""
        ).lower()

        if not cls._public_host(hostname):
            return False

        for domain in allowed_domains:
            domain = str(domain).lower().strip()

            if not domain:
                continue

            if hostname == domain:
                return True

            if hostname.endswith(
                f".{domain}"
            ):
                return True

        return False

    # ========================================================
    # XML
    # ========================================================

    @staticmethod
    def _local_name(
        tag: str,
    ) -> str:
        if "}" in tag:
            return tag.rsplit("}", 1)[-1].lower()

        return tag.lower()

    @classmethod
    def _loc_values(
        cls,
        root: ET.Element,
    ) -> list[str]:
        values: list[str] = []

        for element in root.iter():
            if cls._local_name(
                element.tag
            ) != "loc":
                continue

            value = str(
                element.text
                or ""
            ).strip()

            if value:
                values.append(value)

        return values

    @staticmethod
    def _decode_xml(
        content: bytes,
        url: str,
        content_type: str,
    ) -> bytes:
        lowered_type = (
            content_type
            or ""
        ).lower()

        should_try_gzip = (
            url.lower().endswith(".gz")
            or "gzip" in lowered_type
            or content[:2] == b"\x1f\x8b"
        )

        if not should_try_gzip:
            return content

        try:
            return gzip.decompress(content)

        except (
            OSError,
            EOFError,
        ):
            return content

    # ========================================================
    # ROBOTS
    # ========================================================

    def _robots_sitemaps(
        self,
        base_url: str,
        allowed_domains: tuple[str, ...],
        *,
        request_timeout: float | None = None,
    ) -> list[str]:
        origin = self._origin(base_url)

        robots_url = (
            origin.rstrip("/")
            + "/robots.txt"
        )

        try:
            response = self.client.get(
                robots_url,
                raise_for_status=False,
                timeout=request_timeout,
            )

        except RequestException:
            return []

        try:
            if not (
                200
                <= response.status_code
                < 300
            ):
                return []

            try:
                text = response.text

            except RequestException:
                return []

            results: list[str] = []

            for raw_line in text.splitlines():
                line = raw_line.strip()

                if not line:
                    continue

                if ":" not in line:
                    continue

                key, value = line.split(
                    ":",
                    1,
                )

                if key.strip().lower() != "sitemap":
                    continue

                candidate = self._normalize(
                    value.strip(),
                    robots_url,
                )

                if not candidate:
                    continue

                if not self._allowed(
                    candidate,
                    allowed_domains,
                ):
                    continue

                if candidate not in results:
                    results.append(candidate)

            return results

        finally:
            response.close()

    # ========================================================
    # LECTURA LIMITADA
    # ========================================================

    @staticmethod
    def _read_limited(
        response,
        max_bytes: int,
    ) -> bytes:
        """
        Lee como máximo max_bytes + 1 bytes.

        Evita descargar un documento enorme cuando el servidor no declara
        Content-Length o lo declara incorrectamente.
        """

        limit = max(
            1,
            int(
                max_bytes
            ),
        )

        content = bytearray()

        for chunk in response.iter_content(
            chunk_size=64 * 1024
        ):
            if not chunk:
                continue

            content.extend(
                chunk
            )

            if len(content) > limit:
                break

        return bytes(
            content
        )

    # ========================================================
    # DISCOVERY
    # ========================================================

    def discover(
        self,
        *,
        base_url: str,
        allowed_domains: tuple[str, ...],
        max_sitemaps: int = 100,
        max_urls: int = 10000,
        max_document_bytes: int = 20_000_000,
        request_timeout: float | None = None,
        max_seconds: float = 20.0,
    ) -> SitemapDiscoveryResult:
        result = SitemapDiscoveryResult()

        try:
            default_request_timeout = min(
                float(
                    self.client.timeout
                ),
                5.0,
            )
        except (
            TypeError,
            ValueError,
        ):
            default_request_timeout = 5.0

        if request_timeout is None:
            request_timeout = (
                default_request_timeout
            )

        try:
            request_timeout = max(
                0.5,
                float(
                    request_timeout
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            request_timeout = (
                default_request_timeout
            )

        try:
            max_seconds = max(
                1.0,
                float(
                    max_seconds
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            max_seconds = 20.0

        started = time.monotonic()

        normalized_base = self._normalize(
            base_url
        )

        if not normalized_base:
            return result

        origin = self._origin(
            normalized_base
        )

        # (url, explícito)
        pending: deque[
            tuple[str, bool]
        ] = deque()

        queued_sitemaps: set[str] = set()
        processed_sitemaps: set[str] = set()
        seen_urls: set[str] = set()

        # ----------------------------------------------------
        # robots.txt
        # ----------------------------------------------------

        remaining = (
            max_seconds
            - (
                time.monotonic()
                - started
            )
        )

        robots_timeout = max(
            0.5,
            min(
                request_timeout,
                max(
                    0.5,
                    remaining,
                ),
            ),
        )

        for sitemap_url in self._robots_sitemaps(
            normalized_base,
            allowed_domains,
            request_timeout=robots_timeout,
        ):
            pending.append(
                (
                    sitemap_url,
                    True,
                )
            )

            queued_sitemaps.add(
                sitemap_url
            )

        # ----------------------------------------------------
        # ubicaciones estándar
        # ----------------------------------------------------

        for suffix in self.DEFAULT_SITEMAPS:
            candidate = self._normalize(
                suffix,
                origin,
            )

            if not candidate:
                continue

            if not self._allowed(
                candidate,
                allowed_domains,
            ):
                continue

            if candidate in queued_sitemaps:
                continue

            pending.append(
                (
                    candidate,
                    False,
                )
            )

            queued_sitemaps.add(
                candidate
            )

        # ----------------------------------------------------
        # sitemap / índices
        # ----------------------------------------------------

        while (
            pending
            and len(processed_sitemaps)
            < max_sitemaps
            and len(result.urls)
            < max_urls
        ):
            (
                sitemap_url,
                explicit,
            ) = pending.popleft()

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

            if sitemap_url in processed_sitemaps:
                continue

            processed_sitemaps.add(
                sitemap_url
            )

            try:
                effective_timeout = max(
                    0.5,
                    min(
                        request_timeout,
                        remaining,
                    ),
                )

                response = self.client.get(
                    sitemap_url,
                    raise_for_status=False,
                    timeout=effective_timeout,
                )

            except RequestException as exc:
                if explicit:
                    result.errors.append(
                        (
                            f"{sitemap_url} -> "
                            f"{type(exc).__name__}: {exc}"
                        )
                    )

                continue

            try:
                if not (
                    200
                    <= response.status_code
                    < 300
                ):
                    if explicit:
                        result.errors.append(
                            (
                                f"{sitemap_url} -> "
                                f"HTTP {response.status_code}"
                            )
                        )

                    continue

                raw_length = response.headers.get(
                    "Content-Length"
                )

                if raw_length:
                    try:
                        announced_length = int(
                            raw_length
                        )

                    except ValueError:
                        announced_length = 0

                    if (
                        announced_length
                        > max_document_bytes
                    ):
                        result.errors.append(
                            (
                                f"{sitemap_url} -> "
                                "sitemap demasiado grande "
                                f"({announced_length} bytes)"
                            )
                        )

                        continue

                try:
                    content = self._read_limited(
                        response,
                        max_document_bytes,
                    )

                except RequestException as exc:
                    result.errors.append(
                        (
                            f"{sitemap_url} -> "
                            "error leyendo sitemap: "
                            f"{type(exc).__name__}: {exc}"
                        )
                    )

                    continue

                if (
                    len(content)
                    > max_document_bytes
                ):
                    result.errors.append(
                        (
                            f"{sitemap_url} -> "
                            "sitemap demasiado grande "
                            f"({len(content)} bytes)"
                        )
                    )

                    continue

                content = self._decode_xml(
                    content,
                    sitemap_url,
                    response.headers.get(
                        "Content-Type",
                        "",
                    ),
                )

                if (
                    len(content)
                    > max_document_bytes
                ):
                    result.errors.append(
                        (
                            f"{sitemap_url} -> "
                            "sitemap descomprimido demasiado grande "
                            f"({len(content)} bytes)"
                        )
                    )

                    continue

                try:
                    root = ET.fromstring(
                        content
                    )

                except ET.ParseError:
                    # Las rutas estándar pueden devolver una
                    # página HTML 200. No la consideramos error.
                    if explicit:
                        result.errors.append(
                            (
                                f"{sitemap_url} -> "
                                "XML inválido"
                            )
                        )

                    continue

                root_type = self._local_name(
                    root.tag
                )

                if root_type not in {
                    "sitemapindex",
                    "urlset",
                }:
                    continue

                result.sitemap_documents.append(
                    sitemap_url
                )

                loc_values = self._loc_values(
                    root
                )

                # --------------------------------------------
                # ÍNDICE DE SITEMAPS
                # --------------------------------------------

                if root_type == "sitemapindex":
                    for value in loc_values:
                        candidate = self._normalize(
                            value,
                            sitemap_url,
                        )

                        if not candidate:
                            continue

                        if not self._allowed(
                            candidate,
                            allowed_domains,
                        ):
                            continue

                        if candidate in queued_sitemaps:
                            continue

                        if (
                            len(queued_sitemaps)
                            >= max_sitemaps
                        ):
                            break

                        pending.append(
                            (
                                candidate,
                                True,
                            )
                        )

                        queued_sitemaps.add(
                            candidate
                        )

                    continue

                # --------------------------------------------
                # URLSET
                # --------------------------------------------

                for value in loc_values:
                    candidate = self._normalize(
                        value,
                        sitemap_url,
                    )

                    if not candidate:
                        continue

                    if not self._allowed(
                        candidate,
                        allowed_domains,
                    ):
                        continue

                    if candidate in seen_urls:
                        continue

                    seen_urls.add(
                        candidate
                    )

                    result.urls.append(
                        candidate
                    )

                    if (
                        len(result.urls)
                        >= max_urls
                    ):
                        break

            finally:
                response.close()

        return result