from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import (
    parse_qsl,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

from bs4 import BeautifulSoup
from requests import RequestException

from Crawler_BCB.Old_Files.crawler_multifuente.core.archive_inspector import ArchiveInspector
from Crawler_BCB.Old_Files.crawler_multifuente.core.file_detector import FileDetector
from Crawler_BCB.Old_Files.crawler_multifuente.core.http_client import HttpClient
from Crawler_BCB.Old_Files.crawler_multifuente.core.site_adapter import (
    CrawlSeed,
    SiteAdapter,
)
from Crawler_BCB.Old_Files.crawler_multifuente.core.source_config import SourceConfig


IGNORED_SCHEMES = (
    "mailto:",
    "tel:",
    "javascript:",
    "data:",
)


DATE_PATH_PATTERN = re.compile(
    r"/(\d{4}-(?:0[1-9]|1[0-2]))(?:/|$)"
)


@dataclass(frozen=True)
class DiscoveredPage:
    url: str
    depth: int
    parent_url: Optional[str]
    title: Optional[str]
    path: tuple[str, ...] = ()
    is_listing: bool = False


@dataclass(frozen=True)
class DiscoveredFile:
    url: str
    file_type: Optional[str]
    extension: Optional[str]
    detected_by: Optional[str]
    source_page: Optional[str]

    link_text: str = ""
    path: tuple[str, ...] = ()

    fecha_actualizacion: str = "No disponible"

    contenido_zip: tuple[str, ...] = ()


@dataclass
class NavigationResult:
    pages: list[DiscoveredPage] = field(
        default_factory=list
    )

    files: list[DiscoveredFile] = field(
        default_factory=list
    )

    errors: list[str] = field(
        default_factory=list
    )

    stop_reason: Optional[str] = None

    @property
    def total_pages(self) -> int:
        return len(self.pages)

    @property
    def total_files(self) -> int:
        return len(self.files)

    @property
    def total_errors(self) -> int:
        return len(self.errors)


class Navigator:
    """
    Motor genérico de navegación.

    No contiene reglas particulares de ninguna institución.
    """

    def __init__(
        self,
        config: SourceConfig,
        client: HttpClient,
        file_detector: FileDetector,
        adapter: SiteAdapter | None = None,
        archive_inspector: ArchiveInspector | None = None,
    ) -> None:

        self.config = config
        self.client = client
        self.file_detector = file_detector

        self.adapter = (
            adapter
            or SiteAdapter(config)
        )

        self.archive_inspector = (
            archive_inspector
        )

        self._visited_pages: set[str] = set()
        self._registered_files: set[str] = set()
        self._queued_pages: set[str] = set()

    def _reset_state(self) -> None:
        self._visited_pages.clear()
        self._registered_files.clear()
        self._queued_pages.clear()

    def _page_limit_reached(
        self,
        result: NavigationResult,
    ) -> bool:

        return (
            self.config.max_pages is not None
            and result.total_pages
            >= self.config.max_pages
        )

    def _file_limit_reached(
        self,
        result: NavigationResult,
    ) -> bool:

        return (
            self.config.max_files is not None
            and result.total_files
            >= self.config.max_files
        )

    @staticmethod
    def normalize_url(
        url: str,
        base_url: Optional[str] = None,
    ) -> Optional[str]:

        if not url:
            return None

        raw_url = url.strip()

        if not raw_url:
            return None

        lowered = raw_url.lower()

        if lowered.startswith(
            IGNORED_SCHEMES
        ):
            return None

        if raw_url.startswith("#"):
            return None

        if base_url:
            raw_url = urljoin(
                base_url,
                raw_url,
            )

        parsed = urlparse(
            raw_url
        )

        if parsed.scheme.lower() not in {
            "http",
            "https",
        }:
            return None

        if not parsed.netloc:
            return None

        scheme = parsed.scheme.lower()

        hostname = (
            parsed.hostname
            or ""
        ).lower()

        if not hostname:
            return None

        try:
            port = parsed.port
        except ValueError:
            return None

        if (
            port is None
            or (
                scheme == "http"
                and port == 80
            )
            or (
                scheme == "https"
                and port == 443
            )
        ):
            netloc = hostname
        else:
            netloc = (
                f"{hostname}:{port}"
            )

        path = parsed.path or "/"

        query_pairs = parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )

        normalized_query = urlencode(
            sorted(query_pairs),
            doseq=True,
        )

        return urlunparse(
            (
                scheme,
                netloc,
                path,
                "",
                normalized_query,
                "",
            )
        )

    @staticmethod
    def extract_update_date(
        url: str,
    ) -> str:

        match = DATE_PATH_PATTERN.search(
            urlparse(url).path
        )

        if not match:
            return "No disponible"

        return match.group(1)

    def _is_allowed_url(
        self,
        url: str,
    ) -> bool:

        return self.config.domain_is_allowed(
            url
        )

    def _register_file(
        self,
        result: NavigationResult,
        *,
        url: str,
        source_page: Optional[str],
        link_text: str,
        path: tuple[str, ...],
        headers=None,
    ) -> bool:

        if self._file_limit_reached(
            result
        ):
            result.stop_reason = "max_files"
            return False

        normalized = self.normalize_url(
            url
        )

        if not normalized:
            return False

        if normalized in self._registered_files:
            return False

        detection = self.file_detector.detect(
            normalized,
            headers=headers,
        )

        if not detection.is_downloadable:
            return False

        contenido_zip: tuple[str, ...] = ()

        if (
            detection.file_type == "zip"
            and self.config.inspect_zips
            and self.archive_inspector is not None
        ):
            inspection = (
                self.archive_inspector.inspect(
                    normalized
                )
            )

            contenido_zip = inspection.files

            if inspection.error:
                result.errors.append(
                    inspection.error
                )

        self._registered_files.add(
            normalized
        )

        result.files.append(
            DiscoveredFile(
                url=normalized,
                file_type=detection.file_type,
                extension=detection.extension,
                detected_by=detection.detected_by,
                source_page=source_page,
                link_text=link_text.strip(),
                path=path,
                fecha_actualizacion=(
                    self.extract_update_date(
                        normalized
                    )
                ),
                contenido_zip=contenido_zip,
            )
        )

        if (
            result.total_files <= 10
            or result.total_files % 25 == 0
        ):
            print(
                f"[{self.config.id_fuente.upper()}] "
                f"ARCHIVOS={result.total_files} | "
                f"último={detection.file_type or '?'} | "
                f"{normalized}",
                flush=True,
            )

        if self._file_limit_reached(
            result
        ):
            result.stop_reason = "max_files"

        return True

    def _extract_links(
        self,
        html: str,
        current_url: str,
    ) -> list[tuple[str, str]]:

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        links: list[tuple[str, str]] = []

        seen: set[str] = set()

        for anchor in soup.find_all(
            "a",
            href=True,
        ):
            href = str(
                anchor.get(
                    "href",
                    "",
                )
            ).strip()

            normalized = self.normalize_url(
                href,
                base_url=current_url,
            )

            if not normalized:
                continue

            if normalized in seen:
                continue

            seen.add(
                normalized
            )

            text = anchor.get_text(
                " ",
                strip=True,
            )

            links.append(
                (
                    normalized,
                    text,
                )
            )

        return links

    @staticmethod
    def _extract_title(
        soup: BeautifulSoup,
    ) -> Optional[str]:

        if not soup.title:
            return None

        title = soup.title.get_text(
            " ",
            strip=True,
        )

        return title or None

    def crawl(
        self,
        start_urls: Optional[
            list[str] | tuple[str, ...]
        ] = None,
    ) -> NavigationResult:

        self._reset_state()
        crawl_started_at = time.monotonic()
        result = NavigationResult()

        if start_urls is not None:
            seeds = [
                CrawlSeed(
                    url=url,
                    path=("RAIZ",),
                )
                for url in start_urls
            ]
        else:
            seeds = self.adapter.build_seeds(
                self.client
            )

        if not seeds:
            raise ValueError(
                "No existen puntos de entrada "
                "para iniciar el crawler."
            )

        queue = deque()

        for seed in seeds:

            normalized = self.normalize_url(
                seed.url
            )

            if not normalized:
                continue

            if not self._is_allowed_url(
                normalized
            ):
                continue

            if normalized in self._queued_pages:
                continue

            queue.append(
                (
                    normalized,
                    0,
                    None,
                    seed.path,
                )
            )

            self._queued_pages.add(
                normalized
            )

        while queue:

            if self._file_limit_reached(
                result
            ):
                result.stop_reason = "max_files"
                break

            if self._page_limit_reached(
                result
            ):
                result.stop_reason = "max_pages"
                break

            (
                current_url,
                depth,
                parent_url,
                current_path,
            ) = queue.popleft()

            elapsed = time.monotonic() - crawl_started_at

            print(
                f"[{self.config.id_fuente.upper()}] "
                f"t={elapsed:7.1f}s | "
                f"páginas={result.total_pages:4} | "
                f"archivos={result.total_files:4} | "
                f"cola={len(queue):4} | "
                f"prof={depth} | "
                f"{current_url}",
                flush=True,
            )
            self._queued_pages.discard(
                current_url
            )

            if current_url in self._visited_pages:
                continue

            if depth > self.config.max_depth:
                continue

            direct_detection = (
                self.file_detector.detect_from_url(
                    current_url
                )
            )

            if direct_detection.is_downloadable:
                self._register_file(
                    result,
                    url=current_url,
                    source_page=parent_url,
                    link_text="",
                    path=current_path,
                )
                continue

            try:
                response = self.client.get(
                    current_url
                )

            except (
                RequestException,
                ValueError,
            ) as exc:

                result.errors.append(
                    f"{current_url} -> {exc}"
                )

                continue

            final_url = self.normalize_url(
                response.url
            )

            if not final_url:
                result.errors.append(
                    f"{current_url} -> URL final inválida."
                )
                continue

            if not self._is_allowed_url(
                final_url
            ):
                result.errors.append(
                    f"{current_url} -> redirect "
                    f"fuera de dominio: {final_url}"
                )
                continue

            response_detection = (
                self.file_detector.detect(
                    final_url,
                    headers=response.headers,
                )
            )

            if response_detection.is_downloadable:
                self._register_file(
                    result,
                    url=final_url,
                    source_page=parent_url,
                    link_text="",
                    path=current_path,
                    headers=response.headers,
                )
                continue

            content_type = (
                response.headers
                .get(
                    "Content-Type",
                    "",
                )
                .split(
                    ";",
                    1,
                )[0]
                .strip()
                .lower()
            )

            if content_type not in {
                "text/html",
                "application/xhtml+xml",
                "",
            }:
                continue

            if final_url in self._visited_pages:
                continue

            self._visited_pages.add(
                final_url
            )

            soup = BeautifulSoup(
                response.text,
                "html.parser",
            )

            title = self._extract_title(
                soup
            )

            is_listing = (
                self.adapter.is_listing_page(
                    soup
                )
            )

            result.pages.append(
                DiscoveredPage(
                    url=final_url,
                    depth=depth,
                    parent_url=parent_url,
                    title=title,
                    path=current_path,
                    is_listing=is_listing,
                )
            )

            # Primero registramos todos los documentos
            # presentes en la página.
            links = self._extract_links(
                response.text,
                final_url,
            )

            for link_url, link_text in links:

                if not self._is_allowed_url(
                    link_url
                ):
                    continue

                detection = (
                    self.file_detector.detect_from_url(
                        link_url
                    )
                )

                if detection.is_downloadable:
                    self._register_file(
                        result,
                        url=link_url,
                        source_page=final_url,
                        link_text=link_text,
                        path=current_path,
                    )

            if depth >= self.config.max_depth:
                continue

            # Paginación mantiene la misma ruta jerárquica.
            pagination_urls = (
                self.adapter.pagination_links(
                    soup,
                    final_url,
                )
            )

            for page_url in pagination_urls:

                normalized_page = self.normalize_url(
                    page_url
                )

                if not normalized_page:
                    continue

                if normalized_page in self._visited_pages:
                    continue

                if normalized_page in self._queued_pages:
                    continue

                queue.appendleft(
                    (
                        normalized_page,
                        depth,
                        final_url,
                        current_path,
                    )
                )

                self._queued_pages.add(
                    normalized_page
                )

            # Después seguimos páginas HTML.
            for link_url, link_text in links:

                if not self._is_allowed_url(
                    link_url
                ):
                    continue

                detection = (
                    self.file_detector.detect_from_url(
                        link_url
                    )
                )

                if detection.is_downloadable:
                    continue

                if link_url in self._visited_pages:
                    continue

                if link_url in self._queued_pages:
                    continue

                if is_listing:
                    next_path = (
                        self.adapter.derive_child_path(
                            current_path,
                            link_url,
                            link_text,
                        )
                    )
                else:
                    next_path = current_path

                queue.append(
                    (
                        link_url,
                        depth + 1,
                        final_url,
                        next_path,
                    )
                )

                self._queued_pages.add(
                    link_url
                )

        return result