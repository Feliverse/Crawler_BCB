from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from requests import Response


# ============================================================
# FORMATOS SOPORTADOS
# ============================================================

EXTENSION_TYPES = {
    # Documentos
    ".pdf": "pdf",
    ".doc": "doc",
    ".docx": "docx",
    ".odt": "odt",
    ".rtf": "rtf",
    ".ppt": "ppt",
    ".pptx": "pptx",

    # Hojas / datos tabulares
    ".xlsx": "xlsx",
    ".xls": "xls",
    ".xlsm": "xlsm",
    ".xlsb": "xlsb",
    ".ods": "ods",
    ".csv": "csv",
    ".tsv": "tsv",
    ".txt": "txt",

    # Datos estructurados
    ".json": "json",
    ".geojson": "geojson",
    ".xml": "xml",
    ".parquet": "parquet",
    ".feather": "feather",
    ".ndjson": "ndjson",
    ".jsonl": "jsonl",

    # GIS
    ".shp": "shp",
    ".kml": "kml",
    ".kmz": "kmz",
    ".gpx": "gpx",

    # Estadística / ciencia de datos
    ".sav": "sav",
    ".dta": "dta",
    ".sas7bdat": "sas7bdat",
    ".rdata": "rdata",
    ".rds": "rds",

    # Bases de datos / SQL
    ".sql": "sql",
    ".db": "db",
    ".sqlite": "sqlite",
    ".sqlite3": "sqlite",

    # Comprimidos
    ".zip": "zip",
    ".rar": "rar",
    ".7z": "7z",
    ".gz": "gz",
    ".tgz": "tgz",
    ".tar": "tar",
    ".bz2": "bz2",
}


MIME_TYPES = {
    "application/pdf": ("pdf", ".pdf"),

    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        "xlsx",
        ".xlsx",
    ),
    "application/vnd.ms-excel": ("xls", ".xls"),
    "application/vnd.ms-excel.sheet.macroenabled.12": ("xlsm", ".xlsm"),
    "application/vnd.ms-excel.sheet.binary.macroenabled.12": ("xlsb", ".xlsb"),
    "application/vnd.oasis.opendocument.spreadsheet": ("ods", ".ods"),

    "text/csv": ("csv", ".csv"),
    "text/tab-separated-values": ("tsv", ".tsv"),
    "text/plain": ("txt", ".txt"),

    "application/msword": ("doc", ".doc"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "docx",
        ".docx",
    ),
    "application/vnd.oasis.opendocument.text": ("odt", ".odt"),
    "application/rtf": ("rtf", ".rtf"),
    "text/rtf": ("rtf", ".rtf"),

    "application/vnd.ms-powerpoint": ("ppt", ".ppt"),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        "pptx",
        ".pptx",
    ),

    "application/json": ("json", ".json"),
    "application/geo+json": ("geojson", ".geojson"),
    "application/x-ndjson": ("ndjson", ".ndjson"),
    "application/ndjson": ("ndjson", ".ndjson"),
    "application/xml": ("xml", ".xml"),
    "text/xml": ("xml", ".xml"),

    "application/vnd.apache.parquet": ("parquet", ".parquet"),
    "application/x-parquet": ("parquet", ".parquet"),

    "application/vnd.google-earth.kml+xml": ("kml", ".kml"),
    "application/vnd.google-earth.kmz": ("kmz", ".kmz"),
    "application/gpx+xml": ("gpx", ".gpx"),

    "application/zip": ("zip", ".zip"),
    "application/x-zip-compressed": ("zip", ".zip"),
    "application/vnd.rar": ("rar", ".rar"),
    "application/x-rar-compressed": ("rar", ".rar"),
    "application/x-7z-compressed": ("7z", ".7z"),
    "application/gzip": ("gz", ".gz"),
    "application/x-gzip": ("gz", ".gz"),
    "application/x-tar": ("tar", ".tar"),
    "application/x-bzip2": ("bz2", ".bz2"),

    "application/x-sql": ("sql", ".sql"),
    "application/vnd.sqlite3": ("sqlite", ".sqlite"),
}


DOWNLOAD_PATTERN = re.compile(
    r"\.(?:"
    + "|".join(
        re.escape(ext.lstrip("."))
        for ext in sorted(
            EXTENSION_TYPES,
            key=len,
            reverse=True,
        )
    )
    + r")(?:$|[?&#])",
    re.IGNORECASE,
)


FILENAME_STAR_RE = re.compile(
    r"filename\*\s*=\s*(?:UTF-8''|utf-8'')?([^;]+)",
    re.IGNORECASE,
)

FILENAME_RE = re.compile(
    r'filename\s*=\s*(?:"([^"]+)"|([^;]+))',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FileDetection:
    is_file: bool
    file_type: str | None = None
    extension: str | None = None
    method: str | None = None
    content_type: str | None = None


class FileDetector:
    # ========================================================
    # NOMBRE DESDE CONTENT-DISPOSITION
    # ========================================================

    @staticmethod
    def _filename_from_content_disposition(
        value: str,
    ) -> str | None:
        header = str(value or "").strip()

        if not header:
            return None

        match = FILENAME_STAR_RE.search(header)

        if match:
            filename = unquote(
                match.group(1).strip().strip('"\'')
            )

            if filename:
                return filename

        match = FILENAME_RE.search(header)

        if match:
            filename = (
                match.group(1)
                or match.group(2)
                or ""
            ).strip().strip('"\'')

            if filename:
                return filename

        return None

    # ========================================================
    # URL / NOMBRE
    # ========================================================

    def detect_url(
        self,
        url: str,
    ) -> FileDetection:
        decoded = unquote(
            str(url or "")
        )

        parsed = urlparse(decoded)

        suffix = (
            Path(parsed.path)
            .suffix
            .lower()
        )

        if suffix in EXTENSION_TYPES:
            return FileDetection(
                is_file=True,
                file_type=EXTENSION_TYPES[suffix],
                extension=suffix,
                method="url_extension",
            )

        match = DOWNLOAD_PATTERN.search(decoded)

        if match:
            matched_text = match.group(0)
            extension_match = re.search(
                r"\.[a-z0-9]+",
                matched_text,
                re.IGNORECASE,
            )

            if extension_match:
                extension = extension_match.group(0).lower()

                return FileDetection(
                    is_file=True,
                    file_type=EXTENSION_TYPES.get(
                        extension,
                        extension.lstrip("."),
                    ),
                    extension=extension,
                    method="url_pattern",
                )

        return FileDetection(
            is_file=False
        )

    # ========================================================
    # RESPUESTA HTTP
    # ========================================================

    def detect_response(
        self,
        response: Response,
    ) -> FileDetection:
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

        if content_type.startswith(
            "text/html"
        ):
            return FileDetection(
                is_file=False,
                content_type=content_type,
            )

        # ----------------------------------------------------
        # Content-Disposition tiene prioridad para endpoints
        # tipo /download?id=123 sin extensión visible.
        # ----------------------------------------------------

        disposition = response.headers.get(
            "Content-Disposition",
            "",
        )

        disposition_filename = (
            self._filename_from_content_disposition(
                disposition
            )
        )

        if disposition_filename:
            name_detection = self.detect_url(
                disposition_filename
            )

            if name_detection.is_file:
                return FileDetection(
                    is_file=True,
                    file_type=name_detection.file_type,
                    extension=name_detection.extension,
                    method="content_disposition",
                    content_type=content_type or None,
                )

        # ----------------------------------------------------
        # MIME
        # ----------------------------------------------------

        mime_detection = MIME_TYPES.get(
            content_type
        )

        if mime_detection:
            file_type, extension = mime_detection

            return FileDetection(
                is_file=True,
                file_type=file_type,
                extension=extension,
                method="content_type",
                content_type=content_type,
            )

        # ----------------------------------------------------
        # URL FINAL
        # ----------------------------------------------------

        url_detection = self.detect_url(
            response.url
        )

        if url_detection.is_file:
            return FileDetection(
                is_file=True,
                file_type=url_detection.file_type,
                extension=url_detection.extension,
                method=url_detection.method,
                content_type=content_type or None,
            )

        return FileDetection(
            is_file=False,
            content_type=content_type or None,
        )
