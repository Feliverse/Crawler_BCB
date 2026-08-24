from __future__ import annotations

import struct

from dataclasses import dataclass

from requests.exceptions import RequestException


EOCD_SIGNATURE = (
    b"PK\x05\x06"
)

CENTRAL_SIGNATURE = (
    b"PK\x01\x02"
)

# EOCD:
#
# 22 bytes mínimos
# +
# comentario ZIP máximo de 65535 bytes
#
MAX_EOCD_SEARCH = 65557


# ============================================================
# RESULTADO
# ============================================================

@dataclass
class ZipInspectionResult:
    files: list[str]

    status: str

    bytes_downloaded: int = 0


# ============================================================
# ZIP INSPECTOR
# ============================================================

class ZipInspector:
    """
    Inspecciona archivos ZIP remotos mediante HTTP Range.

    El objetivo es obtener el índice interno del ZIP sin
    descargar deliberadamente el archivo completo.

    Todas las solicitudes pasan por HttpClient para respetar:

    - timeout
    - sesión común
    - User-Agent
    - temporizador aleatorio
    - futuras políticas HTTP del crawler
    """

    def __init__(
        self,
        client,
    ) -> None:

        self.client = client

    # ========================================================
    # INSPECCIÓN
    # ========================================================

    def inspect(
        self,
        url: str,
    ) -> ZipInspectionResult:
        """
        Obtiene el listado interno del ZIP utilizando
        solicitudes HTTP Range.

        Flujo:

        1. Descarga solamente el final del ZIP.
        2. Localiza EOCD.
        3. Obtiene ubicación del directorio central.
        4. Descarga únicamente ese rango.
        5. Extrae nombres de archivos.

        No descarga deliberadamente el ZIP completo.
        """

        try:

            tail_result = (
                self._get_tail(
                    url
                )
            )

            if tail_result is None:

                return ZipInspectionResult(
                    files=[],
                    status=(
                        "range_not_supported"
                    ),
                )

            (
                tail,
                total_size,
                downloaded,
            ) = tail_result

            # =================================================
            # EOCD
            # =================================================

            eocd_position = (
                tail.rfind(
                    EOCD_SIGNATURE
                )
            )

            if eocd_position < 0:

                return ZipInspectionResult(
                    files=[],
                    status=(
                        "eocd_not_found"
                    ),
                    bytes_downloaded=(
                        downloaded
                    ),
                )

            if (
                len(tail)
                < eocd_position + 22
            ):

                return ZipInspectionResult(
                    files=[],
                    status=(
                        "invalid_eocd"
                    ),
                    bytes_downloaded=(
                        downloaded
                    ),
                )

            (
                signature,
                disk_number,
                central_disk,
                entries_disk,
                entries_total,
                central_size,
                central_offset,
                comment_length,
            ) = struct.unpack_from(
                "<4s4H2IH",
                tail,
                eocd_position,
            )

            if (
                signature
                != EOCD_SIGNATURE
            ):

                return ZipInspectionResult(
                    files=[],
                    status=(
                        "invalid_eocd"
                    ),
                    bytes_downloaded=(
                        downloaded
                    ),
                )

            # =================================================
            # ZIP MULTIDISCO
            # =================================================

            if (
                disk_number != 0
                or central_disk != 0
            ):

                return ZipInspectionResult(
                    files=[],
                    status=(
                        "multidisk_not_supported"
                    ),
                    bytes_downloaded=(
                        downloaded
                    ),
                )

            # =================================================
            # ZIP64
            # =================================================

            if (
                central_size
                == 0xFFFFFFFF
                or central_offset
                == 0xFFFFFFFF
                or entries_total
                == 0xFFFF
            ):

                return ZipInspectionResult(
                    files=[],
                    status=(
                        "zip64_not_supported"
                    ),
                    bytes_downloaded=(
                        downloaded
                    ),
                )

            # =================================================
            # VACÍO
            # =================================================

            if central_size <= 0:

                return ZipInspectionResult(
                    files=[],
                    status=(
                        "empty_zip"
                    ),
                    bytes_downloaded=(
                        downloaded
                    ),
                )

            # =================================================
            # DIRECTORIO CENTRAL
            # =================================================

            central_end = (
                central_offset
                + central_size
                - 1
            )

            if (
                central_offset < 0
                or central_end
                >= total_size
            ):

                return ZipInspectionResult(
                    files=[],
                    status=(
                        "invalid_central_directory"
                    ),
                    bytes_downloaded=(
                        downloaded
                    ),
                )

            central_data = (
                self._get_range(
                    url,
                    central_offset,
                    central_end,
                )
            )

            if central_data is None:

                return ZipInspectionResult(
                    files=[],
                    status=(
                        "central_directory_unavailable"
                    ),
                    bytes_downloaded=(
                        downloaded
                    ),
                )

            downloaded += len(
                central_data
            )

            names = (
                self._parse_central_directory(
                    central_data
                )
            )

            return ZipInspectionResult(
                files=names,
                status="ok",
                bytes_downloaded=(
                    downloaded
                ),
            )

        except RequestException:

            return ZipInspectionResult(
                files=[],
                status="http_error",
            )

        except Exception:

            return ZipInspectionResult(
                files=[],
                status=(
                    "inspection_error"
                ),
            )

    # ========================================================
    # OBTENER FINAL DEL ZIP
    # ========================================================

    def _get_tail(
        self,
        url: str,
    ) -> tuple[
        bytes,
        int,
        int,
    ] | None:

        headers = {
            "Range": (
                f"bytes=-"
                f"{MAX_EOCD_SEARCH}"
            )
        }

        # IMPORTANTE:
        #
        # Antes:
        #
        # self.client.session.get(...)
        #
        # Eso evitaba HttpClient._wait().
        #
        # Ahora TODA solicitud pasa por HttpClient.get()
        # y por lo tanto respeta el random delay.

        response = (
            self.client.get(
                url,
                headers=headers,
            )
        )

        try:

            # Un servidor que soporta Range debe responder 206.
            #
            # Si devuelve 200, podría estar enviando el archivo
            # completo. No lo procesamos para evitar descargar
            # deliberadamente todo el ZIP.

            if (
                response.status_code
                != 206
            ):
                return None

            content_range = (
                response.headers.get(
                    "Content-Range",
                    "",
                )
            )

            total_size = (
                self._total_size_from_content_range(
                    content_range
                )
            )

            if total_size is None:
                return None

            data = (
                response.content
            )

            return (
                data,
                total_size,
                len(data),
            )

        finally:

            response.close()

    # ========================================================
    # OBTENER RANGO
    # ========================================================

    def _get_range(
        self,
        url: str,
        start: int,
        end: int,
    ) -> bytes | None:

        if start < 0:
            return None

        if end < start:
            return None

        headers = {
            "Range": (
                f"bytes="
                f"{start}-"
                f"{end}"
            )
        }

        response = (
            self.client.get(
                url,
                headers=headers,
            )
        )

        try:

            if (
                response.status_code
                != 206
            ):
                return None

            return response.content

        finally:

            response.close()

    # ========================================================
    # CONTENT-RANGE
    # ========================================================

    @staticmethod
    def _total_size_from_content_range(
        value: str,
    ) -> int | None:
        """
        Ejemplo esperado:

            Content-Range:
            bytes 100-200/5000

        Devuelve:

            5000
        """

        if "/" not in value:
            return None

        total_text = (
            value.rsplit(
                "/",
                1,
            )[1]
            .strip()
        )

        if (
            not total_text
            or total_text == "*"
        ):
            return None

        try:

            total_size = int(
                total_text
            )

        except ValueError:

            return None

        if total_size <= 0:
            return None

        return total_size

    # ========================================================
    # DIRECTORIO CENTRAL
    # ========================================================

    @staticmethod
    def _parse_central_directory(
        data: bytes,
    ) -> list[str]:

        files: list[str] = []

        position = 0

        while (
            position + 46
            <= len(data)
        ):

            # Cada entrada del directorio central debe iniciar
            # con PK\x01\x02.

            if (
                data[
                    position:
                    position + 4
                ]
                != CENTRAL_SIGNATURE
            ):
                break

            flags = (
                struct.unpack_from(
                    "<H",
                    data,
                    position + 8,
                )[0]
            )

            filename_length = (
                struct.unpack_from(
                    "<H",
                    data,
                    position + 28,
                )[0]
            )

            extra_length = (
                struct.unpack_from(
                    "<H",
                    data,
                    position + 30,
                )[0]
            )

            comment_length = (
                struct.unpack_from(
                    "<H",
                    data,
                    position + 32,
                )[0]
            )

            filename_start = (
                position + 46
            )

            filename_end = (
                filename_start
                + filename_length
            )

            if (
                filename_end
                > len(data)
            ):
                break

            raw_name = data[
                filename_start:
                filename_end
            ]

            # Bit 11:
            # nombre codificado en UTF-8.

            if flags & 0x800:

                encoding = "utf-8"

            else:

                encoding = "cp437"

            try:

                filename = (
                    raw_name.decode(
                        encoding
                    )
                )

            except UnicodeDecodeError:

                filename = (
                    raw_name.decode(
                        "utf-8",
                        errors="replace",
                    )
                )

            filename = (
                filename
                .replace(
                    "\\",
                    "/",
                )
                .strip()
            )

            # No guardamos entradas que sean únicamente
            # directorios.

            if (
                filename
                and not filename.endswith(
                    "/"
                )
            ):
                files.append(
                    filename
                )

            position = (
                filename_end
                + extra_length
                + comment_length
            )

        return files