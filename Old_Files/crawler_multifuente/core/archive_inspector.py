from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass


DEFAULT_MAX_ZIP_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_ENTRIES = 10_000


@dataclass(frozen=True)
class ArchiveInspectionResult:
    files: tuple[str, ...]
    error: str | None = None


class ArchiveInspector:
    """
    Inspecciona archivos ZIP sin escribirlos en disco.

    No extrae físicamente el contenido; solamente lee el directorio
    interno del ZIP y devuelve los nombres de sus archivos.
    """

    def __init__(
        self,
        client,
        *,
        max_zip_bytes: int = DEFAULT_MAX_ZIP_BYTES,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self.client = client
        self.max_zip_bytes = max_zip_bytes
        self.max_entries = max_entries

    def inspect(
        self,
        url: str,
    ) -> ArchiveInspectionResult:
        try:
            response = self.client.get(
                url
            )

            content = response.content

            if len(content) > self.max_zip_bytes:
                return ArchiveInspectionResult(
                    files=(),
                    error=(
                        "ZIP omitido por superar el límite "
                        f"de {self.max_zip_bytes} bytes: {url}"
                    ),
                )

            with zipfile.ZipFile(
                io.BytesIO(content)
            ) as archive:

                entries = [
                    info.filename
                    for info in archive.infolist()
                    if not info.is_dir()
                ]

                if len(entries) > self.max_entries:
                    return ArchiveInspectionResult(
                        files=tuple(
                            entries[
                                :self.max_entries
                            ]
                        ),
                        error=(
                            "ZIP contiene más entradas que "
                            f"el límite permitido ({self.max_entries}): "
                            f"{url}"
                        ),
                    )

                return ArchiveInspectionResult(
                    files=tuple(entries)
                )

        except zipfile.BadZipFile:
            return ArchiveInspectionResult(
                files=(),
                error=(
                    "El recurso identificado como ZIP "
                    f"no contiene un ZIP válido: {url}"
                ),
            )

        except Exception as exc:
            return ArchiveInspectionResult(
                files=(),
                error=(
                    f"No se pudo inspeccionar ZIP {url}: {exc}"
                ),
            )