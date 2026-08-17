from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from requests import Response


EXTENSION_TYPES = {
    ".pdf": "pdf",
    ".xlsx": "xlsx",
    ".xls": "xls",
    ".csv": "csv",
    ".doc": "doc",
    ".docx": "docx",
    ".zip": "zip",
    ".ods": "ods",
    ".txt": "txt",
    ".json": "json",
    ".xml": "xml",
    ".rar": "rar",
    ".7z": "7z",
}

MIME_TYPES = {
    "application/pdf": ("pdf", ".pdf"),

    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        "xlsx",
        ".xlsx",
    ),

    "application/vnd.ms-excel": (
        "xls",
        ".xls",
    ),

    "text/csv": (
        "csv",
        ".csv",
    ),

    "application/msword": (
        "doc",
        ".doc",
    ),

    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "docx",
        ".docx",
    ),

    "application/zip": (
        "zip",
        ".zip",
    ),

    "application/x-zip-compressed": (
        "zip",
        ".zip",
    ),

    "application/vnd.oasis.opendocument.spreadsheet": (
        "ods",
        ".ods",
    ),

    "text/plain": (
        "txt",
        ".txt",
    ),

    "application/json": (
        "json",
        ".json",
    ),
}

DOWNLOAD_PATTERN = re.compile(
    r"\.(pdf|xlsx|xls|csv|doc|docx|zip|ods|txt|json|xml|rar|7z)"
    r"(?:$|[?&#])",
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
    def detect_url(
        self,
        url: str,
    ) -> FileDetection:
        decoded = unquote(url)

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

        match = DOWNLOAD_PATTERN.search(
            decoded
        )

        if match:
            extension = (
                "."
                + match.group(1).lower()
            )

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

        mime_detection = MIME_TYPES.get(
            content_type
        )

        if mime_detection:
            file_type, extension = (
                mime_detection
            )

            return FileDetection(
                is_file=True,
                file_type=file_type,
                extension=extension,
                method="content_type",
                content_type=content_type,
            )

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