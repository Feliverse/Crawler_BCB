from __future__ import annotations

import struct
from dataclasses import dataclass
from urllib.parse import urlparse

from requests.exceptions import RequestException


EOCD_SIGNATURE = b"PK\x05\x06"
CENTRAL_SIGNATURE = b"PK\x01\x02"

MAX_EOCD_SEARCH = 65557


@dataclass
class ZipInspectionResult:
    files: list[str]
    status: str
    bytes_downloaded: int = 0


class ZipInspector:
    def __init__(self, client) -> None:
        self.client = client

    def inspect(self, url: str) -> ZipInspectionResult:
        """
        Obtiene el listado interno del ZIP intentando usar HTTP Range.

        NO descarga deliberadamente el ZIP completo.
        """

        try:
            tail_result = self._get_tail(url)

            if tail_result is None:
                return ZipInspectionResult(
                    files=[],
                    status="range_not_supported",
                )

            tail, total_size, downloaded = tail_result

            eocd_position = tail.rfind(
                EOCD_SIGNATURE
            )

            if eocd_position < 0:
                return ZipInspectionResult(
                    files=[],
                    status="eocd_not_found",
                    bytes_downloaded=downloaded,
                )

            if len(tail) < eocd_position + 22:
                return ZipInspectionResult(
                    files=[],
                    status="invalid_eocd",
                    bytes_downloaded=downloaded,
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

            if signature != EOCD_SIGNATURE:
                return ZipInspectionResult(
                    files=[],
                    status="invalid_eocd",
                    bytes_downloaded=downloaded,
                )

            # ZIP64 requiere otra lógica.
            if (
                central_size == 0xFFFFFFFF
                or central_offset == 0xFFFFFFFF
                or entries_total == 0xFFFF
            ):
                return ZipInspectionResult(
                    files=[],
                    status="zip64_not_supported",
                    bytes_downloaded=downloaded,
                )

            if central_size <= 0:
                return ZipInspectionResult(
                    files=[],
                    status="empty_zip",
                    bytes_downloaded=downloaded,
                )

            central_end = (
                central_offset
                + central_size
                - 1
            )

            if central_end >= total_size:
                return ZipInspectionResult(
                    files=[],
                    status="invalid_central_directory",
                    bytes_downloaded=downloaded,
                )

            central_data = self._get_range(
                url,
                central_offset,
                central_end,
            )

            if central_data is None:
                return ZipInspectionResult(
                    files=[],
                    status="central_directory_unavailable",
                    bytes_downloaded=downloaded,
                )

            downloaded += len(
                central_data
            )

            names = self._parse_central_directory(
                central_data
            )

            return ZipInspectionResult(
                files=names,
                status="ok",
                bytes_downloaded=downloaded,
            )

        except RequestException:
            return ZipInspectionResult(
                files=[],
                status="http_error",
            )

        except Exception:
            return ZipInspectionResult(
                files=[],
                status="inspection_error",
            )

    def _get_tail(
        self,
        url: str,
    ) -> tuple[bytes, int, int] | None:
        headers = {
            "Range": (
                f"bytes=-{MAX_EOCD_SEARCH}"
            )
        }

        response = self.client.session.get(
            url,
            headers=headers,
            timeout=self.client.timeout,
            allow_redirects=True,
            stream=True,
        )

        try:
            # Para garantizar que no descargamos todo,
            # exigimos HTTP 206.
            if response.status_code != 206:
                return None

            content_range = response.headers.get(
                "Content-Range",
                "",
            )

            total_size = self._total_size_from_content_range(
                content_range
            )

            if total_size is None:
                return None

            data = response.content

            return (
                data,
                total_size,
                len(data),
            )

        finally:
            response.close()

    def _get_range(
        self,
        url: str,
        start: int,
        end: int,
    ) -> bytes | None:
        headers = {
            "Range": (
                f"bytes={start}-{end}"
            )
        }

        response = self.client.session.get(
            url,
            headers=headers,
            timeout=self.client.timeout,
            allow_redirects=True,
            stream=True,
        )

        try:
            if response.status_code != 206:
                return None

            return response.content

        finally:
            response.close()

    @staticmethod
    def _total_size_from_content_range(
        value: str,
    ) -> int | None:
        # Ejemplo:
        # bytes 100-200/5000

        if "/" not in value:
            return None

        total_text = value.rsplit(
            "/",
            1,
        )[1].strip()

        if (
            not total_text
            or total_text == "*"
        ):
            return None

        try:
            return int(
                total_text
            )

        except ValueError:
            return None

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
            if (
                data[position:position + 4]
                != CENTRAL_SIGNATURE
            ):
                break

            flags = struct.unpack_from(
                "<H",
                data,
                position + 8,
            )[0]

            filename_length = struct.unpack_from(
                "<H",
                data,
                position + 28,
            )[0]

            extra_length = struct.unpack_from(
                "<H",
                data,
                position + 30,
            )[0]

            comment_length = struct.unpack_from(
                "<H",
                data,
                position + 32,
            )[0]

            filename_start = (
                position + 46
            )

            filename_end = (
                filename_start
                + filename_length
            )

            if filename_end > len(data):
                break

            raw_name = data[
                filename_start:
                filename_end
            ]

            if flags & 0x800:
                encoding = "utf-8"
            else:
                encoding = "cp437"

            try:
                filename = raw_name.decode(
                    encoding
                )

            except UnicodeDecodeError:
                filename = raw_name.decode(
                    "utf-8",
                    errors="replace",
                )

            filename = (
                filename
                .replace("\\", "/")
                .strip()
            )

            # No guardamos carpetas vacías.
            if (
                filename
                and not filename.endswith("/")
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