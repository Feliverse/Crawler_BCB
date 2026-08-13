from __future__ import annotations

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

from core.file_detector import FileDetector
from core.http_client import HttpClient
from core.source_config import SourceConfig


IGNORED_SCHEMES = (
    "mailto:",
    "tel:",
    "javascript:",
    "data:",
)


@dataclass(frozen=True)
class DiscoveredPage:
    url: str
    depth: int
    parent_url: Optional[str]
    title: Optional[str]


@dataclass(frozen=True)
class DiscoveredFile:
    url: str
    file_type: Optional[str]
    extension: Optional[str]
    detected_by: Optional[str]
    source_page: Optional[str]
    link_text: str = ""


@dataclass
class NavigationResult:
    pages: list[DiscoveredPage] = field(default_factory=list)
    files: list[DiscoveredFile] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

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
    Navegador web genérico del crawler multi-fuente.

    Recorre páginas HTML dentro de los dominios permitidos,
    evita ciclos y registra archivos descargables encontrados.

    No contiene selectores ni reglas específicas de ninguna institución.
    """

    def __init__(
        self,
        config: SourceConfig,
        client: HttpClient,
        file_detector: FileDetector,
    ) -> None:
        self.config = config
        self.client = client
        self.file_detector = file_detector

        self._visited_pages: set[str] = set()
        self._registered_files: set[str] = set()
        self._queued_pages: set[str] = set()

    @staticmethod
    def normalize_url(
        url: str,
        base_url: Optional[str] = None,
    ) -> Optional[str]:
        """
        Convierte una URL en una representación estable.

        - Resuelve URLs relativas.
        - Elimina fragmentos (#...).
        - Normaliza scheme y dominio a minúsculas.
        - Elimina puertos estándar.
        - Ordena query parameters para reducir duplicados.
        """

        if not url:
            return None

        raw_url = url.strip()

        if not raw_url:
            return None

        lowered = raw_url.lower()

        if lowered.startswith(IGNORED_SCHEMES):
            return None

        if raw_url.startswith("#"):
            return None

        if base_url:
            raw_url = urljoin(base_url, raw_url)

        parsed = urlparse(raw_url)

        if parsed.scheme.lower() not in {"http", "https"}:
            return None

        if not parsed.netloc:
            return None

        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower()

        if not hostname:
            return None

        port = parsed.port

        if (
            port is None
            or (scheme == "http" and port == 80)
            or (scheme == "https" and port == 443)
        ):
            netloc = hostname
        else:
            netloc = f"{hostname}:{port}"

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

    def _is_allowed_url(self, url: str) -> bool:
        return self.config.domain_is_allowed(url)

    def _register_file(
        self,
        result: NavigationResult,
        *,
        url: str,
        source_page: Optional[str],
        link_text: str,
        headers=None,
    ) -> None:
        normalized = self.normalize_url(url)

        if not normalized:
            return

        if normalized in self._registered_files:
            return

        detection = self.file_detector.detect(
            normalized,
            headers=headers,
        )

        if not detection.is_downloadable:
            return

        self._registered_files.add(normalized)

        result.files.append(
            DiscoveredFile(
                url=normalized,
                file_type=detection.file_type,
                extension=detection.extension,
                detected_by=detection.detected_by,
                source_page=source_page,
                link_text=link_text.strip(),
            )
        )

    def _extract_links(
        self,
        html: str,
        current_url: str,
    ) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")

        links: list[tuple[str, str]] = []

        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href", "")).strip()

            normalized = self.normalize_url(
                href,
                base_url=current_url,
            )

            if not normalized:
                continue

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
    def _extract_title(html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")

        if not soup.title:
            return None

        title = soup.title.get_text(
            " ",
            strip=True,
        )

        return title or None

    def crawl(
        self,
        start_url: Optional[str] = None,
    ) -> NavigationResult:
        """
        Recorre una fuente desde la URL inicial utilizando BFS.

        BFS permite controlar la profundidad de forma natural y evita
        entrar demasiado pronto en ramas muy profundas.
        """

        result = NavigationResult()

        initial_url = self.normalize_url(
            start_url or self.config.base_url
        )

        if not initial_url:
            raise ValueError(
                "No se pudo normalizar la URL inicial."
            )

        if not self._is_allowed_url(initial_url):
            raise ValueError(
                f"La URL inicial pertenece a un dominio no permitido: "
                f"{initial_url}"
            )

        queue = deque(
            [
                (
                    initial_url,
                    0,
                    None,
                )
            ]
        )

        self._queued_pages.add(initial_url)

        while queue:
            current_url, depth, parent_url = queue.popleft()

            self._queued_pages.discard(current_url)

            if current_url in self._visited_pages:
                continue

            if depth > self.config.max_depth:
                continue

            # Caso sencillo: URL ya contiene una extensión conocida.
            direct_detection = self.file_detector.detect_from_url(
                current_url
            )

            if direct_detection.is_downloadable:
                self._register_file(
                    result,
                    url=current_url,
                    source_page=parent_url,
                    link_text="",
                )
                continue

            try:
                response = self.client.get(current_url)

            except (RequestException, ValueError) as exc:
                result.errors.append(
                    f"{current_url} -> {exc}"
                )
                continue

            final_url = self.normalize_url(response.url)

            if not final_url:
                result.errors.append(
                    f"{current_url} -> URL final inválida."
                )
                continue

            # Un redirect podría llevarnos a otro dominio.
            if not self._is_allowed_url(final_url):
                result.errors.append(
                    f"{current_url} -> redirect fuera de dominio: "
                    f"{final_url}"
                )
                continue

            # El servidor puede devolver un archivo aunque la URL
            # no tenga una extensión visible.
            response_detection = self.file_detector.detect(
                final_url,
                headers=response.headers,
            )

            if response_detection.is_downloadable:
                self._register_file(
                    result,
                    url=final_url,
                    source_page=parent_url,
                    link_text="",
                    headers=response.headers,
                )
                continue

            content_type = (
                response.headers
                .get("Content-Type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )

            if content_type not in {
                "text/html",
                "application/xhtml+xml",
                "",
            }:
                continue

            self._visited_pages.add(final_url)

            title = self._extract_title(
                response.text
            )

            result.pages.append(
                DiscoveredPage(
                    url=final_url,
                    depth=depth,
                    parent_url=parent_url,
                    title=title,
                )
            )

            if depth >= self.config.max_depth:
                continue

            links = self._extract_links(
                response.text,
                final_url,
            )

            for link_url, link_text in links:

                if not self._is_allowed_url(link_url):
                    continue

                detection = self.file_detector.detect_from_url(
                    link_url
                )

                if detection.is_downloadable:
                    self._register_file(
                        result,
                        url=link_url,
                        source_page=final_url,
                        link_text=link_text,
                    )
                    continue

                if link_url in self._visited_pages:
                    continue

                if link_url in self._queued_pages:
                    continue

                queue.append(
                    (
                        link_url,
                        depth + 1,
                        final_url,
                    )
                )

                self._queued_pages.add(link_url)

        return result