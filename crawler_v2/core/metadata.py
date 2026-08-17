from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse


DATE_YMD = re.compile(
    r"(?<!\d)"
    r"(20\d{2})"
    r"[-_/]"
    r"(0?[1-9]|1[0-2])"
    r"[-_/]"
    r"(0?[1-9]|[12]\d|3[01])"
    r"(?!\d)"
)

DATE_DMY = re.compile(
    r"(?<!\d)"
    r"(0?[1-9]|[12]\d|3[01])"
    r"[-_/]"
    r"(0?[1-9]|1[0-2])"
    r"[-_/]"
    r"(20\d{2})"
    r"(?!\d)"
)

DATE_COMPACT = re.compile(
    r"(?<!\d)"
    r"(20\d{2})"
    r"(0[1-9]|1[0-2])"
    r"(0[1-9]|[12]\d|3[01])"
    r"(?!\d)"
)

DATE_YM = re.compile(
    r"(?<!\d)"
    r"(20\d{2})"
    r"[-_/]"
    r"(0?[1-9]|1[0-2])"
    r"(?!\d)"
)


def clean_text(
    value: str | None,
) -> str:
    if not value:
        return ""

    return " ".join(
        value.split()
    ).strip()


def filename_from_url(
    url: str,
) -> str:
    parsed = urlparse(
        url
    )

    path = unquote(
        parsed.path
    )

    name = Path(
        path
    ).name

    return (
        name
        or "recurso"
    )


def extract_date(
    url: str,
    text: str = "",
) -> str | None:
    """
    Intenta obtener una fecha descriptiva del recurso sin
    descargar el documento.

    Prioridad:
    1. Fecha completa en URL.
    2. Fecha compacta en URL.
    3. Año/mes en URL.
    4. Fecha completa en texto/nombre.
    """

    decoded_url = unquote(
        url
    )

    combined = (
        decoded_url
        + " "
        + clean_text(text)
    )

    match = DATE_YMD.search(
        decoded_url
    )

    if match:
        year, month, day = (
            match.groups()
        )

        return (
            f"{int(year):04d}-"
            f"{int(month):02d}-"
            f"{int(day):02d}"
        )

    match = DATE_COMPACT.search(
        decoded_url
    )

    if match:
        year, month, day = (
            match.groups()
        )

        return (
            f"{int(year):04d}-"
            f"{int(month):02d}-"
            f"{int(day):02d}"
        )

    match = DATE_YM.search(
        decoded_url
    )

    if match:
        year, month = (
            match.groups()
        )

        return (
            f"{int(year):04d}-"
            f"{int(month):02d}"
        )

    match = DATE_YMD.search(
        combined
    )

    if match:
        year, month, day = (
            match.groups()
        )

        return (
            f"{int(year):04d}-"
            f"{int(month):02d}-"
            f"{int(day):02d}"
        )

    match = DATE_DMY.search(
        combined
    )

    if match:
        day, month, year = (
            match.groups()
        )

        return (
            f"{int(year):04d}-"
            f"{int(month):02d}-"
            f"{int(day):02d}"
        )

    match = DATE_COMPACT.search(
        combined
    )

    if match:
        year, month, day = (
            match.groups()
        )

        return (
            f"{int(year):04d}-"
            f"{int(month):02d}-"
            f"{int(day):02d}"
        )

    return None