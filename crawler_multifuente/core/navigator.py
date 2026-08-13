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

    # Motivo por el cual terminó anticipadamente la navegación.
    # Valores posibles:
    # - None
    # - "max_pages"
    # - "max_files"
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
    Navegador web genérico del crawler multi-fuente.

    Responsabilidades:
    - Recorrer páginas HTML mediante BFS.
    - Comenzar desde uno o varios entrypoints.
    - Respetar los dominios permitidos.
    - Evitar ciclos y URLs duplicadas.
    - Controlar profundidad máxima.
    - Controlar límites de páginas y archivos.
    - Detectar y registrar documentos.
    - Mantener cada ejecución independiente.

    No contiene reglas específicas de ASFI, AETN, BCB
    ni de ninguna otra fuente.
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

    def _reset_state(self) -> None:
        """
        Reinicia todo el estado interno de navegación.

        Esto permite reutilizar una misma instancia de Navigator
        en ejecuciones independientes.
        """
        self._visited_pages.clear()
        self._registered_files.clear()
        self._queued_pages.clear()

    def _page_limit_reached(
        self,
        result: NavigationResult,
    ) -> bool:
        if self.config.max_pages is None:
            return False

        return result.total_pages >= self.config.max_pages

    def _file_limit_reached(
        self,
        result: NavigationResult,
    ) -> bool:
        if self.config.max_files is None:
            return False

        return result.total_files >= self.config.max_files

    @staticmethod
    def normalize_url(
        url: str,
        base_url: Optional[str] = None,
    ) -> Optional[str]:
        """
        Convierte una URL en una representación estable.

        - Resuelve URLs relativas.
        - Elimina fragmentos.
        - Normaliza scheme y dominio.
        - Elimina puertos HTTP/HTTPS estándar.
        - Ordena parámetros query.
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
            raw_url = urljoin(
                base_url,
                raw_url,
            )

        parsed = urlparse(raw_url)

        if parsed.scheme.lower() not in {
            "http",
            "https",
        }:
            return None

        if not parsed.netloc:
            return None

        scheme = parsed.scheme.lower()

        hostname = (
            parsed.hostname or ""
        ).lower()

        if not hostname:
            return None

        port = parsed.port

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
        headers=None,
    ) -> bool:
        """
        Intenta registrar un archivo.

        Devuelve True únicamente cuando el archivo fue agregado.
        """

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
            )
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
        """
        Extrae y normaliza todos los enlaces navegables
        presentes en una página HTML.
        """

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        links: list[tuple[str, str]] = []

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
        html: str,
    ) -> Optional[str]:
        """
        Extrae el título HTML de una página.
        """

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

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
        """
        Recorre una fuente mediante búsqueda en anchura (BFS).

        Puede comenzar desde múltiples entrypoints configurados.
        Cada llamada constituye una ejecución independiente.
        """

        self._reset_state()

        result = NavigationResult()

        raw_entrypoints = (
            tuple(start_urls)
            if start_urls is not None
            else self.config.get_entrypoints()
        )

        if not raw_entrypoints:
            raise ValueError(
                "No existen puntos de entrada "
                "para iniciar el crawler."
            )

        queue = deque()

        for raw_url in raw_entrypoints:
            normalized = self.normalize_url(
                raw_url
            )

            if not normalized:
                raise ValueError(
                    "No se pudo normalizar el "
                    f"entrypoint: {raw_url}"
                )

            if not self._is_allowed_url(
                normalized
            ):
                raise ValueError(
                    "El entrypoint pertenece a un dominio "
                    f"no permitido: {normalized}"
                )

            if normalized in self._queued_pages:
                continue

            queue.append(
                (
                    normalized,
                    0,
                    None,
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

            current_url, depth, parent_url = (
                queue.popleft()
            )

            self._queued_pages.discard(
                current_url
            )

            if current_url in self._visited_pages:
                continue

            if depth > self.config.max_depth:
                continue

            # Si la URL ya contiene una extensión conocida,
            # puede ser registrada como candidata a documento.
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
                    f"{current_url} -> "
                    "URL final inválida."
                )
                continue

            # Los redirects tampoco pueden escapar
            # de los dominios permitidos.
            if not self._is_allowed_url(
                final_url
            ):
                result.errors.append(
                    f"{current_url} -> "
                    "redirect fuera de dominio: "
                    f"{final_url}"
                )
                continue

            # Una URL sin extensión puede devolver
            # directamente un documento.
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
                if self._file_limit_reached(
                    result
                ):
                    result.stop_reason = "max_files"
                    break

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

                self._queued_pages.add(
                    link_url
                )

        return result