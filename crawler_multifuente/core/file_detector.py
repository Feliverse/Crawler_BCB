from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Mapping, Optional
from urllib.parse import unquote, urlparse

from core.source_config import SourceConfig


MIME_TYPE_TO_EXTENSION = {
    "application/pdf": ".pdf",

    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "text/csv": ".csv",
    "application/csv": ".csv",

    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",

    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",

    "application/vnd.oasis.opendocument.spreadsheet": ".ods",

    "text/plain": ".txt",

    "text/html": ".html",
    "application/xhtml+xml": ".html",
}


@dataclass(frozen=True)
class FileDetectionResult:
    """
    Resultado normalizado de la detección de un recurso.
    """

    url: str
    is_downloadable: bool
    file_type: Optional[str]
    extension: Optional[str]
    content_type: Optional[str]
    detected_by: Optional[str]


class FileDetector:
    """
    Detecta si una URL representa un archivo descargable.

    La detección puede realizarse utilizando:

    1. La extensión presente en la URL.
    2. El Content-Type devuelto por el servidor.

    Content-Type tiene prioridad cuando está disponible porque permite
    reconocer descargas incluso cuando la URL no contiene una extensión.

    Esta clase no contiene reglas específicas de ASFI, BCB u otra fuente.
    """

    def __init__(self, config: SourceConfig) -> None:
        self.config = config
        self.allowed_extensions = {
            extension.lower()
            for extension in config.extensions
        }

    @staticmethod
    def normalize_content_type(
        content_type: Optional[str],
    ) -> Optional[str]:
        """
        Elimina charset y parámetros adicionales de Content-Type.

        Ejemplo:
            text/html; charset=UTF-8
        se convierte en:
            text/html
        """
        if not content_type:
            return None

        normalized = content_type.split(";", 1)[0].strip().lower()

        return normalized or None

    @staticmethod
    def extension_from_url(url: str) -> Optional[str]:
        """
        Extrae la extensión real del path de una URL.

        Los query parameters no afectan la detección.
        """
        parsed = urlparse(url)
        path = unquote(parsed.path)

        suffix = PurePosixPath(path).suffix.lower()

        return suffix or None

    @staticmethod
    def extension_from_content_type(
        content_type: Optional[str],
    ) -> Optional[str]:
        """
        Convierte un Content-Type conocido en una extensión.
        """
        normalized = FileDetector.normalize_content_type(content_type)

        if not normalized:
            return None

        return MIME_TYPE_TO_EXTENSION.get(normalized)

    def extension_is_allowed(
        self,
        extension: Optional[str],
    ) -> bool:
        if not extension:
            return False

        return extension.lower() in self.allowed_extensions

    def detect_from_url(
        self,
        url: str,
    ) -> FileDetectionResult:
        """
        Clasifica únicamente utilizando la extensión de la URL.
        """
        extension = self.extension_from_url(url)

        if self.extension_is_allowed(extension):
            return FileDetectionResult(
                url=url,
                is_downloadable=True,
                file_type=extension.lstrip("."),
                extension=extension,
                content_type=None,
                detected_by="url_extension",
            )

        return FileDetectionResult(
            url=url,
            is_downloadable=False,
            file_type=None,
            extension=extension,
            content_type=None,
            detected_by=None,
        )

    def detect(
        self,
        url: str,
        headers: Optional[Mapping[str, str]] = None,
    ) -> FileDetectionResult:
        """
        Detecta el tipo de recurso combinando URL y cabeceras HTTP.

        Prioridad:

        1. Content-Type válido y descargable.
        2. Content-Type HTML -> recurso no descargable.
        3. Extensión válida de la URL.
        4. Recurso desconocido.
        """
        headers = headers or {}

        raw_content_type = headers.get("Content-Type")
        content_type = self.normalize_content_type(raw_content_type)

        extension_by_mime = self.extension_from_content_type(
            content_type
        )

        extension_by_url = self.extension_from_url(url)

        # Content-Type identifica explícitamente un archivo permitido.
        if self.extension_is_allowed(extension_by_mime):
            return FileDetectionResult(
                url=url,
                is_downloadable=True,
                file_type=extension_by_mime.lstrip("."),
                extension=extension_by_mime,
                content_type=content_type,
                detected_by="content_type",
            )

        # Si el servidor declara explícitamente HTML,
        # no debemos tratarlo como PDF o cualquier otro archivo.
        if extension_by_mime == ".html":
            return FileDetectionResult(
                url=url,
                is_downloadable=False,
                file_type="html",
                extension=".html",
                content_type=content_type,
                detected_by="content_type",
            )

        # Si Content-Type no resolvió nada, usamos la URL.
        if self.extension_is_allowed(extension_by_url):
            return FileDetectionResult(
                url=url,
                is_downloadable=True,
                file_type=extension_by_url.lstrip("."),
                extension=extension_by_url,
                content_type=content_type,
                detected_by="url_extension",
            )

        return FileDetectionResult(
            url=url,
            is_downloadable=False,
            file_type=None,
            extension=extension_by_url,
            content_type=content_type,
            detected_by=None,
        )