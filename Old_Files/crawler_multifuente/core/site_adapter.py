from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from Crawler_BCB.Old_Files.crawler_multifuente.core.source_config import SourceConfig


LISTING_KEYWORDS = (
    "estadística",
    "estadistica",
    "datos",
    "serie",
    "indicador",
    "boletín",
    "boletin",
    "informe",
    "publicación",
    "publicacion",
    "resolución",
    "resolucion",
    "circular",
    "anuario",
    "memoria",
)


@dataclass(frozen=True)
class CrawlSeed:
    url: str
    path: tuple[str, ...]


class SiteAdapter:
    """
    Comportamiento genérico de una fuente.

    Los adapters específicos solamente deben sobrescribir aquello
    que realmente dependa de la estructura HTML de una institución.
    """

    def __init__(
        self,
        config: SourceConfig,
    ) -> None:
        self.config = config

    def build_seeds(
        self,
        client,
    ) -> list[CrawlSeed]:
        seeds: list[CrawlSeed] = []

        for url in self.config.get_entrypoints():
            seeds.append(
                CrawlSeed(
                    url=url,
                    path=(
                        self._label_from_url(url),
                    ),
                )
            )

        return seeds

    def is_listing_page(
        self,
        soup: BeautifulSoup,
    ) -> bool:
        title = ""

        if soup.title:
            title = soup.title.get_text(
                " ",
                strip=True,
            ).lower()

        if any(
            keyword in title
            for keyword in LISTING_KEYWORDS
        ):
            return True

        downloadable_links = 0

        for anchor in soup.find_all(
            "a",
            href=True,
        ):
            href = str(
                anchor.get("href", "")
            ).lower()

            path = urlparse(href).path.lower()

            if any(
                path.endswith(extension)
                for extension in self.config.extensions
            ):
                downloadable_links += 1

        if downloadable_links >= 3:
            return True

        if soup.select(
            "ul.pager, "
            "li.pager__item, "
            ".pagination, "
            "nav.pagination"
        ):
            return True

        return False

    def pagination_links(
        self,
        soup: BeautifulSoup,
        current_url: str,
    ) -> list[str]:
        links: list[str] = []
        seen: set[str] = set()

        selectors = (
            "ul.pager li a, "
            "li.pager__item a, "
            ".pagination a, "
            "nav.pagination a, "
            "a[rel='next']"
        )

        for anchor in soup.select(selectors):
            href = anchor.get("href")

            if not href:
                continue

            absolute = urljoin(
                current_url,
                str(href).strip(),
            )

            if absolute == current_url:
                continue

            if not self.config.domain_is_allowed(
                absolute
            ):
                continue

            if absolute in seen:
                continue

            seen.add(absolute)
            links.append(absolute)

        return links

    def derive_child_path(
        self,
        current_path: tuple[str, ...],
        url: str,
        link_text: str,
    ) -> tuple[str, ...]:
        label = link_text.strip()

        if not label:
            label = self._label_from_url(url)

        if not label:
            return current_path

        if current_path and label == current_path[-1]:
            return current_path

        return current_path + (
            label,
        )

    @staticmethod
    def _label_from_url(
        url: str,
    ) -> str:
        parsed = urlparse(url)

        path = unquote(
            parsed.path
        ).strip("/")

        if not path:
            return "INICIO"

        segment = path.split("/")[-1]

        return (
            segment
            .replace("-", " ")
            .replace("_", " ")
            .strip()
            or "GENERAL"
        )