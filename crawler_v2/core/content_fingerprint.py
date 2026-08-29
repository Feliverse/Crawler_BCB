from __future__ import annotations

"""
Huella lógica de contenido para validar posibles duplicados de datos.

Este módulo NO hace peticiones HTTP y NO decide por sí solo eliminar archivos.
Recibe bytes o archivos locales y genera una huella comparable.

Formatos soportados:
- XLSX
- ODS
- CSV
- TSV

Uso previsto:
1. El crawler detecta dos candidatos semánticamente equivalentes.
2. Solo para ese par, descarga/verifica de forma acotada.
3. Este módulo compara el CONTENIDO lógico.
4. La deduplicación final exige varias señales coincidentes.

No se soporta XLS binario aquí porque requiere un parser adicional.
"""

from collections import Counter
from dataclasses import dataclass
import csv
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import io
from pathlib import Path
import re
import unicodedata
from typing import Iterable
import xml.etree.ElementTree as ET
import zipfile


MAX_ARCHIVE_MEMBERS = 4096
MAX_TOTAL_UNCOMPRESSED_BYTES = 192 * 1024 * 1024
MAX_XML_MEMBER_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_CELLS = 25000
DEFAULT_MAX_TOKEN_LENGTH = 512
DEFAULT_SAMPLE_TOKENS = 12000


XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XLSX_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XLSX_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

ODS_TABLE_NS = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
ODS_TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
ODS_OFFICE_NS = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"


@dataclass(frozen=True)
class ContentFingerprint:
    format: str
    sheet_names: tuple[str, ...]
    sheet_count: int
    sampled_cells: int
    non_empty_cells_seen: int
    truncated: bool
    ordered_digest: str
    bag_digest: str
    sample_tokens: tuple[str, ...]
    error: str = ""


@dataclass(frozen=True)
class ContentComparison:
    status: str
    confidence: float
    similarity: float
    reasons: tuple[str, ...]


def _ascii_text(value: str) -> str:
    value = unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )

    return "".join(
        char
        for char in value
        if not unicodedata.combining(char)
    )


def normalize_cell_value(
    value: object,
    *,
    max_length: int = DEFAULT_MAX_TOKEN_LENGTH,
) -> str:
    """
    Normaliza valores para comparar contenido entre formatos diferentes.

    Principios:
    - preserva texto real;
    - normaliza booleanos;
    - normaliza números con Decimal, evitando diferencias como
      1, 1.0, 1.000000;
    - normaliza fechas ISO;
    - no intenta convertir texto ambiguo con separadores regionales.
    """

    if value is None:
        return ""

    text = _ascii_text(
        str(value)
    )

    text = text.replace(
        "\u00a0",
        " ",
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    if not text:
        return ""

    lowered = text.lower()

    if lowered in {
        "true",
        "verdadero",
        "yes",
        "si",
        "sí",
    }:
        return "true"

    if lowered in {
        "false",
        "falso",
        "no",
    }:
        return "false"

    # Fecha ISO. Conservamos solo fecha cuando la hora es medianoche.
    iso_match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2})(?:[tT ]00:00(?::00(?:\.0+)?)?)?",
        text,
    )

    if iso_match:
        return iso_match.group(
            1
        )

    # Número canónico. Solo aceptamos punto decimal para evitar
    # interpretar erróneamente textos regionales.
    if re.fullmatch(
        r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?",
        text,
    ):
        try:
            number = Decimal(
                text
            )

            if number.is_finite():
                normalized_number = format(
                    number.normalize(),
                    "f",
                )

                if "." in normalized_number:
                    normalized_number = normalized_number.rstrip(
                        "0"
                    ).rstrip(
                        "."
                    )

                if normalized_number in {
                    "-0",
                    "+0",
                    "",
                }:
                    normalized_number = "0"

                return normalized_number

        except InvalidOperation:
            pass

    if len(text) > max_length:
        text = text[
            :max_length
        ]

    return text


def _safe_zip(
    payload: bytes,
) -> zipfile.ZipFile:
    archive = zipfile.ZipFile(
        io.BytesIO(payload),
        "r",
    )

    infos = archive.infolist()

    if len(infos) > MAX_ARCHIVE_MEMBERS:
        archive.close()
        raise ValueError(
            "archive_member_limit_exceeded"
        )

    total_uncompressed = sum(
        max(
            0,
            int(
                info.file_size
            ),
        )
        for info in infos
    )

    if (
        total_uncompressed
        > MAX_TOTAL_UNCOMPRESSED_BYTES
    ):
        archive.close()
        raise ValueError(
            "archive_uncompressed_limit_exceeded"
        )

    return archive


def _read_zip_member(
    archive: zipfile.ZipFile,
    name: str,
    *,
    max_bytes: int = MAX_XML_MEMBER_BYTES,
) -> bytes:
    info = archive.getinfo(
        name
    )

    if info.file_size > max_bytes:
        raise ValueError(
            f"zip_member_too_large:{name}"
        )

    with archive.open(
        info,
        "r",
    ) as handle:
        data = handle.read(
            max_bytes + 1
        )

    if len(data) > max_bytes:
        raise ValueError(
            f"zip_member_too_large:{name}"
        )

    return data


def _finalize_fingerprint(
    *,
    format_name: str,
    sheet_names: Iterable[str],
    ordered_tokens: list[str],
    value_tokens: list[str],
    non_empty_seen: int,
    truncated: bool,
    error: str = "",
    sample_limit: int = DEFAULT_SAMPLE_TOKENS,
) -> ContentFingerprint:

    ordered_hasher = hashlib.sha256()

    for token in ordered_tokens:
        ordered_hasher.update(
            token.encode(
                "utf-8",
                errors="replace",
            )
        )
        ordered_hasher.update(
            b"\x1e"
        )

    bag_hasher = hashlib.sha256()

    counts = Counter(
        value_tokens
    )

    for token, count in sorted(
        counts.items()
    ):
        bag_hasher.update(
            token.encode(
                "utf-8",
                errors="replace",
            )
        )
        bag_hasher.update(
            b"\x1f"
        )
        bag_hasher.update(
            str(
                count
            ).encode(
                "ascii"
            )
        )
        bag_hasher.update(
            b"\x1e"
        )

    names = tuple(
        str(name or "")
        for name in sheet_names
    )

    return ContentFingerprint(
        format=format_name.lower(),
        sheet_names=names,
        sheet_count=len(
            names
        ),
        sampled_cells=len(
            value_tokens
        ),
        non_empty_cells_seen=max(
            non_empty_seen,
            len(
                value_tokens
            ),
        ),
        truncated=bool(
            truncated
        ),
        ordered_digest=ordered_hasher.hexdigest(),
        bag_digest=bag_hasher.hexdigest(),
        sample_tokens=tuple(
            value_tokens[
                :sample_limit
            ]
        ),
        error=str(
            error
            or ""
        ),
    )


# ============================================================
# XLSX
# ============================================================


def _xlsx_shared_strings(
    archive: zipfile.ZipFile,
) -> list[str]:
    name = "xl/sharedStrings.xml"

    if name not in archive.namelist():
        return []

    data = _read_zip_member(
        archive,
        name,
    )

    root = ET.fromstring(
        data
    )

    result: list[str] = []

    for item in root.findall(
        f".//{{{XLSX_MAIN_NS}}}si"
    ):
        text_parts = [
            node.text or ""
            for node in item.findall(
                f".//{{{XLSX_MAIN_NS}}}t"
            )
        ]

        result.append(
            "".join(
                text_parts
            )
        )

    return result


def _xlsx_sheet_map(
    archive: zipfile.ZipFile,
) -> list[tuple[str, str]]:
    workbook_name = "xl/workbook.xml"
    rels_name = "xl/_rels/workbook.xml.rels"

    workbook = ET.fromstring(
        _read_zip_member(
            archive,
            workbook_name,
        )
    )

    rels = ET.fromstring(
        _read_zip_member(
            archive,
            rels_name,
        )
    )

    relation_targets: dict[str, str] = {}

    for relation in rels.findall(
        f".//{{{XLSX_PKG_REL_NS}}}Relationship"
    ):
        relation_id = relation.attrib.get(
            "Id",
            "",
        )

        target = relation.attrib.get(
            "Target",
            "",
        )

        if relation_id and target:
            target = target.replace(
                "\\",
                "/",
            )

            if target.startswith(
                "/"
            ):
                normalized = target.lstrip(
                    "/"
                )

            elif target.startswith(
                "xl/"
            ):
                normalized = target

            else:
                normalized = (
                    "xl/"
                    + target.lstrip(
                        "./"
                    )
                )

            relation_targets[
                relation_id
            ] = normalized

    sheets: list[tuple[str, str]] = []

    for sheet in workbook.findall(
        f".//{{{XLSX_MAIN_NS}}}sheet"
    ):
        name = sheet.attrib.get(
            "name",
            "",
        )

        relation_id = sheet.attrib.get(
            f"{{{XLSX_DOC_REL_NS}}}id",
            "",
        )

        target = relation_targets.get(
            relation_id,
            "",
        )

        if target:
            sheets.append(
                (
                    name,
                    target,
                )
            )

    return sheets


XLSX_BUILTIN_DATE_FORMAT_IDS = {
    14,
    15,
    16,
    17,
    18,
    19,
    20,
    21,
    22,
    27,
    28,
    29,
    30,
    31,
    32,
    33,
    34,
    35,
    36,
    45,
    46,
    47,
    50,
    51,
    52,
    53,
    54,
    55,
    56,
    57,
    58,
}


def _xlsx_uses_1904_date_system(
    archive: zipfile.ZipFile,
) -> bool:
    name = "xl/workbook.xml"

    if name not in archive.namelist():
        return False

    root = ET.fromstring(
        _read_zip_member(
            archive,
            name,
        )
    )

    workbook_pr = root.find(
        f".//{{{XLSX_MAIN_NS}}}workbookPr"
    )

    if workbook_pr is None:
        return False

    value = (
        workbook_pr.attrib.get(
            "date1904",
            ""
        )
        .strip()
        .lower()
    )

    return value in {
        "1",
        "true",
    }


def _xlsx_style_formats(
    archive: zipfile.ZipFile,
) -> dict[int, str]:
    """
    Mapea índice de estilo de celda -> formato lógico:
    - "date"
    - ""
    """

    name = "xl/styles.xml"

    if name not in archive.namelist():
        return {}

    root = ET.fromstring(
        _read_zip_member(
            archive,
            name,
        )
    )

    custom_formats: dict[int, str] = {}

    for num_fmt in root.findall(
        f".//{{{XLSX_MAIN_NS}}}numFmt"
    ):
        try:
            num_fmt_id = int(
                num_fmt.attrib.get(
                    "numFmtId",
                    "-1",
                )
            )
        except ValueError:
            continue

        custom_formats[
            num_fmt_id
        ] = num_fmt.attrib.get(
            "formatCode",
            "",
        )

    style_map: dict[int, str] = {}

    cell_xfs = root.find(
        f".//{{{XLSX_MAIN_NS}}}cellXfs"
    )

    if cell_xfs is None:
        return style_map

    for style_index, xf in enumerate(
        list(
            cell_xfs
        )
    ):
        try:
            num_fmt_id = int(
                xf.attrib.get(
                    "numFmtId",
                    "0",
                )
            )
        except ValueError:
            num_fmt_id = 0

        format_code = custom_formats.get(
            num_fmt_id,
            "",
        )

        is_date = (
            num_fmt_id
            in XLSX_BUILTIN_DATE_FORMAT_IDS
            or _xlsx_format_code_is_date(
                format_code
            )
        )

        style_map[
            style_index
        ] = (
            "date"
            if is_date
            else ""
        )

    return style_map


def _xlsx_format_code_is_date(
    format_code: str,
) -> bool:
    if not format_code:
        return False

    code = _ascii_text(
        format_code
    ).lower()

    # Quitamos literales entre comillas y escapes.
    code = re.sub(
        r'"[^"]*"',
        "",
        code,
    )

    code = re.sub(
        r"\\.",
        "",
        code,
    )

    code = re.sub(
        r"\[[^\]]+\]",
        "",
        code,
    )

    # y/d son señales fuertes. h/s también indican fecha-hora.
    if re.search(
        r"[yd]",
        code,
    ):
        return True

    if re.search(
        r"[hs]",
        code,
    ):
        return True

    # m aislada es ambigua (mes/minuto), así que no basta sola.
    return False


def _xlsx_excel_serial_to_iso(
    raw_value: str,
    *,
    date1904: bool,
) -> str:
    try:
        serial = float(
            raw_value
        )
    except ValueError:
        return raw_value

    base = (
        datetime(
            1904,
            1,
            1,
        )
        if date1904
        else datetime(
            1899,
            12,
            30,
        )
    )

    value = base + timedelta(
        days=serial
    )

    if (
        value.hour == 0
        and value.minute == 0
        and value.second == 0
        and value.microsecond == 0
    ):
        return value.date().isoformat()

    return value.isoformat(
        timespec="seconds"
    )


def fingerprint_xlsx(
    payload: bytes,
    *,
    max_cells: int = DEFAULT_MAX_CELLS,
) -> ContentFingerprint:
    ordered_tokens: list[str] = []
    value_tokens: list[str] = []
    sheet_names: list[str] = []
    non_empty_seen = 0
    truncated = False

    try:
        with _safe_zip(
            payload
        ) as archive:
            shared_strings = (
                _xlsx_shared_strings(
                    archive
                )
            )

            sheets = _xlsx_sheet_map(
                archive
            )

            style_formats = (
                _xlsx_style_formats(
                    archive
                )
            )

            date1904 = (
                _xlsx_uses_1904_date_system(
                    archive
                )
            )

            for sheet_index, (
                sheet_name,
                member_name,
            ) in enumerate(
                sheets
            ):
                sheet_names.append(
                    sheet_name
                )

                if member_name not in archive.namelist():
                    continue

                data = _read_zip_member(
                    archive,
                    member_name,
                )

                root = ET.fromstring(
                    data
                )

                for cell_index, cell in enumerate(
                    root.findall(
                        f".//{{{XLSX_MAIN_NS}}}c"
                    )
                ):
                    cell_type = cell.attrib.get(
                        "t",
                        "",
                    )

                    try:
                        style_index = int(
                            cell.attrib.get(
                                "s",
                                "0",
                            )
                        )
                    except ValueError:
                        style_index = 0

                    style_kind = style_formats.get(
                        style_index,
                        "",
                    )

                    value_node = cell.find(
                        f"{{{XLSX_MAIN_NS}}}v"
                    )

                    formula_node = cell.find(
                        f"{{{XLSX_MAIN_NS}}}f"
                    )

                    raw_value = ""

                    if cell_type == "inlineStr":
                        text_parts = [
                            node.text or ""
                            for node in cell.findall(
                                f".//{{{XLSX_MAIN_NS}}}t"
                            )
                        ]

                        raw_value = "".join(
                            text_parts
                        )

                    elif value_node is not None:
                        raw_value = (
                            value_node.text
                            or ""
                        )

                        if cell_type == "s":
                            try:
                                raw_value = (
                                    shared_strings[
                                        int(
                                            raw_value
                                        )
                                    ]
                                )
                            except (
                                ValueError,
                                IndexError,
                            ):
                                pass

                        elif cell_type == "b":
                            raw_value = (
                                "true"
                                if raw_value == "1"
                                else "false"
                            )

                        elif (
                            style_kind == "date"
                            and cell_type
                            not in {
                                "s",
                                "inlineStr",
                                "str",
                                "e",
                            }
                        ):
                            raw_value = (
                                _xlsx_excel_serial_to_iso(
                                    raw_value,
                                    date1904=date1904,
                                )
                            )

                    elif formula_node is not None:
                        raw_value = (
                            "="
                            + (
                                formula_node.text
                                or ""
                            )
                        )

                    normalized = normalize_cell_value(
                        raw_value
                    )

                    if not normalized:
                        continue

                    non_empty_seen += 1

                    if len(
                        value_tokens
                    ) >= max_cells:
                        truncated = True
                        break

                    value_tokens.append(
                        normalized
                    )

                    ordered_tokens.append(
                        "|".join(
                            (
                                str(
                                    sheet_index
                                ),
                                str(
                                    cell_index
                                ),
                                normalized,
                            )
                        )
                    )

                if truncated:
                    break

        return _finalize_fingerprint(
            format_name="xlsx",
            sheet_names=sheet_names,
            ordered_tokens=ordered_tokens,
            value_tokens=value_tokens,
            non_empty_seen=non_empty_seen,
            truncated=truncated,
        )

    except Exception as exc:
        return _finalize_fingerprint(
            format_name="xlsx",
            sheet_names=sheet_names,
            ordered_tokens=ordered_tokens,
            value_tokens=value_tokens,
            non_empty_seen=non_empty_seen,
            truncated=truncated,
            error=f"{type(exc).__name__}:{exc}",
        )


# ============================================================
# ODS
# ============================================================


def _ods_cell_text(
    cell: ET.Element,
) -> str:
    """
    Obtiene el valor lógico de una celda ODS.

    Antes se tomaba primero text:p, es decir, el valor VISUAL/formateado.
    Eso provocaba diferencias artificiales frente al valor interno XLSX.

    Ahora priorizamos los atributos tipados de ODF:
    - office:value
    - office:date-value
    - office:boolean-value
    - office:string-value

    y solo usamos text:p como fallback.
    """

    value_type = (
        cell.attrib.get(
            f"{{{ODS_OFFICE_NS}}}value-type",
            "",
        )
        or ""
    ).lower()

    if value_type in {
        "float",
        "currency",
        "percentage",
    }:
        value = cell.attrib.get(
            f"{{{ODS_OFFICE_NS}}}value"
        )

        if value not in (
            None,
            "",
        ):
            return str(
                value
            )

    if value_type == "date":
        value = cell.attrib.get(
            f"{{{ODS_OFFICE_NS}}}date-value"
        )

        if value not in (
            None,
            "",
        ):
            return str(
                value
            )

    if value_type == "time":
        value = cell.attrib.get(
            f"{{{ODS_OFFICE_NS}}}time-value"
        )

        if value not in (
            None,
            "",
        ):
            return str(
                value
            )

    if value_type == "boolean":
        value = cell.attrib.get(
            f"{{{ODS_OFFICE_NS}}}boolean-value"
        )

        if value not in (
            None,
            "",
        ):
            return str(
                value
            )

    if value_type == "string":
        value = cell.attrib.get(
            f"{{{ODS_OFFICE_NS}}}string-value"
        )

        if value not in (
            None,
            "",
        ):
            return str(
                value
            )

    # Algunos productores ODS no colocan value-type correctamente.
    # Probamos atributos lógicos antes del texto de presentación.
    for attribute in (
        f"{{{ODS_OFFICE_NS}}}value",
        f"{{{ODS_OFFICE_NS}}}date-value",
        f"{{{ODS_OFFICE_NS}}}time-value",
        f"{{{ODS_OFFICE_NS}}}boolean-value",
        f"{{{ODS_OFFICE_NS}}}string-value",
    ):
        value = cell.attrib.get(
            attribute
        )

        if value not in (
            None,
            "",
        ):
            return str(
                value
            )

    text_parts: list[str] = []

    for paragraph in cell.findall(
        f".//{{{ODS_TEXT_NS}}}p"
    ):
        for part in paragraph.itertext():
            text_parts.append(
                part
            )

    return " ".join(
        text_parts
    ).strip()


def fingerprint_ods(
    payload: bytes,
    *,
    max_cells: int = DEFAULT_MAX_CELLS,
) -> ContentFingerprint:
    ordered_tokens: list[str] = []
    value_tokens: list[str] = []
    sheet_names: list[str] = []
    non_empty_seen = 0
    truncated = False

    try:
        with _safe_zip(
            payload
        ) as archive:
            member_name = "content.xml"

            if member_name not in archive.namelist():
                raise ValueError(
                    "ods_content_xml_missing"
                )

            root = ET.fromstring(
                _read_zip_member(
                    archive,
                    member_name,
                )
            )

            tables = root.findall(
                f".//{{{ODS_TABLE_NS}}}table"
            )

            for sheet_index, table in enumerate(
                tables
            ):
                sheet_name = table.attrib.get(
                    f"{{{ODS_TABLE_NS}}}name",
                    "",
                )

                sheet_names.append(
                    sheet_name
                )

                logical_cell_index = 0

                for row in table.findall(
                    f"{{{ODS_TABLE_NS}}}table-row"
                ):
                    row_repeat = int(
                        row.attrib.get(
                            f"{{{ODS_TABLE_NS}}}number-rows-repeated",
                            "1",
                        )
                        or "1"
                    )

                    # No expandimos miles de filas vacías/repetidas.
                    row_repeat = min(
                        max(
                            row_repeat,
                            1,
                        ),
                        100,
                    )

                    row_values: list[tuple[str, int]] = []

                    for cell in list(
                        row
                    ):
                        local_name = (
                            cell.tag.rsplit(
                                "}",
                                1,
                            )[-1]
                        )

                        if local_name not in {
                            "table-cell",
                            "covered-table-cell",
                        }:
                            continue

                        cell_repeat = int(
                            cell.attrib.get(
                                f"{{{ODS_TABLE_NS}}}number-columns-repeated",
                                "1",
                            )
                            or "1"
                        )

                        cell_repeat = min(
                            max(
                                cell_repeat,
                                1,
                            ),
                            1000,
                        )

                        normalized = normalize_cell_value(
                            _ods_cell_text(
                                cell
                            )
                        )

                        row_values.append(
                            (
                                normalized,
                                cell_repeat,
                            )
                        )

                    for _ in range(
                        row_repeat
                    ):
                        for normalized, repeat in row_values:
                            if normalized:
                                non_empty_seen += repeat

                            for _ in range(
                                repeat
                            ):
                                if normalized:
                                    if len(
                                        value_tokens
                                    ) >= max_cells:
                                        truncated = True
                                        break

                                    value_tokens.append(
                                        normalized
                                    )

                                    ordered_tokens.append(
                                        "|".join(
                                            (
                                                str(
                                                    sheet_index
                                                ),
                                                str(
                                                    logical_cell_index
                                                ),
                                                normalized,
                                            )
                                        )
                                    )

                                logical_cell_index += 1

                            if truncated:
                                break

                        if truncated:
                            break

                    if truncated:
                        break

                if truncated:
                    break

        return _finalize_fingerprint(
            format_name="ods",
            sheet_names=sheet_names,
            ordered_tokens=ordered_tokens,
            value_tokens=value_tokens,
            non_empty_seen=non_empty_seen,
            truncated=truncated,
        )

    except Exception as exc:
        return _finalize_fingerprint(
            format_name="ods",
            sheet_names=sheet_names,
            ordered_tokens=ordered_tokens,
            value_tokens=value_tokens,
            non_empty_seen=non_empty_seen,
            truncated=truncated,
            error=f"{type(exc).__name__}:{exc}",
        )


# ============================================================
# CSV / TSV
# ============================================================


def fingerprint_delimited(
    payload: bytes,
    *,
    delimiter: str | None = None,
    format_name: str = "csv",
    max_cells: int = DEFAULT_MAX_CELLS,
) -> ContentFingerprint:
    ordered_tokens: list[str] = []
    value_tokens: list[str] = []
    non_empty_seen = 0
    truncated = False

    try:
        text = payload.decode(
            "utf-8-sig",
            errors="replace",
        )

        if delimiter is None:
            try:
                dialect = csv.Sniffer().sniff(
                    text[:8192],
                    delimiters=",;\t|",
                )

                delimiter = dialect.delimiter

            except csv.Error:
                delimiter = (
                    "\t"
                    if format_name == "tsv"
                    else ","
                )

        reader = csv.reader(
            io.StringIO(
                text
            ),
            delimiter=delimiter,
        )

        logical_cell_index = 0

        for row in reader:
            for raw_value in row:
                normalized = normalize_cell_value(
                    raw_value
                )

                if normalized:
                    non_empty_seen += 1

                    if len(
                        value_tokens
                    ) >= max_cells:
                        truncated = True
                        break

                    value_tokens.append(
                        normalized
                    )

                    ordered_tokens.append(
                        "|".join(
                            (
                                "0",
                                str(
                                    logical_cell_index
                                ),
                                normalized,
                            )
                        )
                    )

                logical_cell_index += 1

            if truncated:
                break

        return _finalize_fingerprint(
            format_name=format_name,
            sheet_names=(
                "data",
            ),
            ordered_tokens=ordered_tokens,
            value_tokens=value_tokens,
            non_empty_seen=non_empty_seen,
            truncated=truncated,
        )

    except Exception as exc:
        return _finalize_fingerprint(
            format_name=format_name,
            sheet_names=(
                "data",
            ),
            ordered_tokens=ordered_tokens,
            value_tokens=value_tokens,
            non_empty_seen=non_empty_seen,
            truncated=truncated,
            error=f"{type(exc).__name__}:{exc}",
        )


# ============================================================
# API PÚBLICA DEL MÓDULO
# ============================================================


def fingerprint_bytes(
    payload: bytes,
    *,
    format_name: str,
    max_cells: int = DEFAULT_MAX_CELLS,
) -> ContentFingerprint:
    normalized_format = (
        str(
            format_name
            or ""
        )
        .lower()
        .strip()
        .lstrip(".")
    )

    if normalized_format == "xlsx":
        return fingerprint_xlsx(
            payload,
            max_cells=max_cells,
        )

    if normalized_format == "ods":
        return fingerprint_ods(
            payload,
            max_cells=max_cells,
        )

    if normalized_format == "csv":
        return fingerprint_delimited(
            payload,
            format_name="csv",
            max_cells=max_cells,
        )

    if normalized_format == "tsv":
        return fingerprint_delimited(
            payload,
            delimiter="\t",
            format_name="tsv",
            max_cells=max_cells,
        )

    return ContentFingerprint(
        format=normalized_format,
        sheet_names=(),
        sheet_count=0,
        sampled_cells=0,
        non_empty_cells_seen=0,
        truncated=False,
        ordered_digest="",
        bag_digest="",
        sample_tokens=(),
        error="unsupported_format",
    )


def fingerprint_file(
    path: str | Path,
    *,
    format_name: str | None = None,
    max_cells: int = DEFAULT_MAX_CELLS,
) -> ContentFingerprint:
    file_path = Path(
        path
    )

    payload = file_path.read_bytes()

    detected_format = (
        format_name
        or file_path.suffix.lstrip(
            "."
        )
    )

    return fingerprint_bytes(
        payload,
        format_name=detected_format,
        max_cells=max_cells,
    )


def _counter_similarity(
    left: tuple[str, ...],
    right: tuple[str, ...],
) -> float:
    if not left and not right:
        return 1.0

    if not left or not right:
        return 0.0

    left_counter = Counter(
        left
    )

    right_counter = Counter(
        right
    )

    intersection = sum(
        (
            left_counter
            & right_counter
        ).values()
    )

    union = sum(
        (
            left_counter
            | right_counter
        ).values()
    )

    if union <= 0:
        return 0.0

    return (
        intersection
        / union
    )


def compare_fingerprints(
    left: ContentFingerprint,
    right: ContentFingerprint,
) -> ContentComparison:
    reasons: list[str] = []

    if left.error or right.error:
        reasons.append(
            "fingerprint_error"
        )

        return ContentComparison(
            status="INCONCLUSIVE",
            confidence=0.0,
            similarity=0.0,
            reasons=tuple(
                reasons
            ),
        )

    if (
        left.sampled_cells == 0
        or right.sampled_cells == 0
    ):
        return ContentComparison(
            status="INCONCLUSIVE",
            confidence=0.0,
            similarity=0.0,
            reasons=(
                "empty_fingerprint",
            ),
        )

    if (
        left.ordered_digest
        and left.ordered_digest
        == right.ordered_digest
        and left.sampled_cells
        == right.sampled_cells
    ):
        return ContentComparison(
            status="SAME_CONTENT",
            confidence=1.0,
            similarity=1.0,
            reasons=(
                "ordered_content_digest_match",
            ),
        )

    if (
        left.bag_digest
        and left.bag_digest
        == right.bag_digest
        and left.sampled_cells
        == right.sampled_cells
    ):
        return ContentComparison(
            status="SAME_CONTENT",
            confidence=0.995,
            similarity=1.0,
            reasons=(
                "unordered_content_digest_match",
            ),
        )

    token_similarity = _counter_similarity(
        left.sample_tokens,
        right.sample_tokens,
    )

    cell_ratio = (
        min(
            left.sampled_cells,
            right.sampled_cells,
        )
        / max(
            left.sampled_cells,
            right.sampled_cells,
        )
    )

    if (
        left.sheet_count > 0
        and right.sheet_count > 0
    ):
        sheet_ratio = (
            min(
                left.sheet_count,
                right.sheet_count,
            )
            / max(
                left.sheet_count,
                right.sheet_count,
            )
        )

    else:
        sheet_ratio = 0.0

    similarity = (
        token_similarity
        * 0.78
        + cell_ratio
        * 0.17
        + sheet_ratio
        * 0.05
    )

    reasons.extend(
        (
            f"token_similarity={token_similarity:.4f}",
            f"cell_ratio={cell_ratio:.4f}",
            f"sheet_ratio={sheet_ratio:.4f}",
        )
    )

    if (
        token_similarity >= 0.995
        and cell_ratio >= 0.995
    ):
        status = "SAME_CONTENT"
        confidence = 0.99

    elif (
        token_similarity >= 0.975
        and cell_ratio >= 0.95
    ):
        status = "LIKELY_SAME"
        confidence = min(
            0.98,
            similarity,
        )

    elif (
        token_similarity <= 0.80
        or cell_ratio <= 0.70
    ):
        status = "DIFFERENT"
        confidence = max(
            0.80,
            1.0 - similarity,
        )

    else:
        status = "INCONCLUSIVE"
        confidence = similarity

    if (
        left.truncated
        or right.truncated
    ):
        reasons.append(
            "sample_truncated"
        )

        # Un resultado positivo basado en una muestra truncada no debe
        # tener confianza absoluta.
        if status in {
            "SAME_CONTENT",
            "LIKELY_SAME",
        }:
            confidence = min(
                confidence,
                0.97,
            )

    return ContentComparison(
        status=status,
        confidence=round(
            confidence,
            6,
        ),
        similarity=round(
            similarity,
            6,
        ),
        reasons=tuple(
            reasons
        ),
    )


__all__ = [
    "ContentComparison",
    "ContentFingerprint",
    "compare_fingerprints",
    "fingerprint_bytes",
    "fingerprint_delimited",
    "fingerprint_file",
    "fingerprint_ods",
    "fingerprint_xlsx",
    "normalize_cell_value",
]
