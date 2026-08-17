from __future__ import annotations

from urllib.parse import (
    unquote,
    urlparse,
)

from adapters.generic import GenericAdapter


HIGH_PRIORITY = (
    "dataindex.asp",
    "databaseinfo.asp",
    "databasetables.asp",
    "fields.asp",
    "download.asp",
    "tableinfo.asp",
    "/employment/",
    "database",
    "data tables",
    "download",
    "statistics",
    "data index",
)


MEDIUM_PRIORITY = (
    "aviation",
    "maritime",
    "highway",
    "transit",
    "rail",
    "pipeline",
    "freight",
    "passenger",
    "economic",
    "energy",
    "environment",
    "safety",
)


LOW_PRIORITY = (
    "showhelp.asp",
    "glossary",
    "advancedsearch",
    "datarelease",
    "releasehistory",
    "contact",
    "about",
    "news",
)


# Solo estas páginas representan realmente
# datasets, tablas o interfaces estadísticas.
DATA_PAGE_HINTS = (
    "databaseinfo.asp",
    "databasetables.asp",
    "fields.asp",
    "download.asp",
    "tableinfo.asp",
    "/employment/",
)


class TranstatsAdapter(GenericAdapter):

    def should_follow(
        self,
        url: str,
    ) -> bool:

        if not super().should_follow(url):
            return False

        parsed = urlparse(url)

        hostname = (
            parsed.hostname
            or ""
        ).lower()

        if hostname not in {
            "transtats.bts.gov",
            "www.transtats.bts.gov",
        }:
            return False

        searchable = unquote(url).lower()

        if any(
            token in searchable
            for token in LOW_PRIORITY
        ):
            return False

        return True

    def priority(
        self,
        url: str,
        text: str,
    ) -> int:

        searchable = (
            unquote(url)
            + " "
            + text
        ).lower()

        if any(
            token in searchable
            for token in HIGH_PRIORITY
        ):
            return 1

        if any(
            token in searchable
            for token in MEDIUM_PRIORITY
        ):
            return 10

        if any(
            token in searchable
            for token in LOW_PRIORITY
        ):
            return 95

        return super().priority(
            url,
            text,
        )

    def should_detect_data(
        self,
        url: str,
        title: str,
    ) -> bool:
        """
        Evita que TranStats marque como dataset todas
        las páginas auxiliares del portal.

        Solamente permitimos al DataDetector analizar
        páginas que representan bases, tablas,
        campos, descargas o reportes estadísticos.
        """

        searchable = (
            unquote(url)
            + " "
            + title
        ).lower()

        return any(
            hint in searchable
            for hint in DATA_PAGE_HINTS
        )

    def extend_path(
        self,
        current_path: tuple[str, ...],
        text: str,
        url: str,
    ) -> tuple[str, ...]:

        cleaned = " ".join(
            text.split()
        ).strip()

        lowered = cleaned.lower()

        if cleaned.isdigit():
            return current_path

        if lowered in {
            "next",
            "prev",
            "<<prev",
            "next>>",
            "profile",
            "details",
        }:
            return current_path

        if (
            len(cleaned) == 1
            and cleaned.isalpha()
        ):
            return current_path

        return super().extend_path(
            current_path,
            text,
            url,
        )