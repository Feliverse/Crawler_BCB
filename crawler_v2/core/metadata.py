from __future__ import annotations

import re
import unicodedata

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse


# ============================================================
# FECHAS NUMÉRICAS
# ============================================================

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


# ============================================================
# MESES EN TEXTO
# ============================================================

MONTHS = {
    # Español completo
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,

    # Español abreviado
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "set": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,

    # Inglés, útil para otras fuentes del proyecto
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,

    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

MONTH_TOKEN_PATTERN = (
    "|".join(
        sorted(
            (
                re.escape(name)
                for name in MONTHS
            ),
            key=len,
            reverse=True,
        )
    )
)

MONTH_YEAR = re.compile(
    rf"(?<![a-z])"
    rf"({MONTH_TOKEN_PATTERN})"
    rf"\.?"
    rf"\s+(?:de\s+)?"
    rf"(20\d{{2}})"
    rf"(?!\d)",
    re.IGNORECASE,
)

YEAR_MONTH_TEXT = re.compile(
    rf"(?<!\d)"
    rf"(20\d{{2}})"
    rf"\s*[-_/ ]\s*"
    rf"({MONTH_TOKEN_PATTERN})"
    rf"\.?"
    rf"(?![a-z])",
    re.IGNORECASE,
)


# ============================================================
# TRIMESTRES
# ============================================================

QUARTER_YEAR = re.compile(
    r"(?<![a-z0-9])"
    r"(?:t|q|trim(?:estre)?)"
    r"[\s._/-]*"
    r"([1-4])"
    r"[\s._/-]+"
    r"(20\d{2})"
    r"(?!\d)",
    re.IGNORECASE,
)

YEAR_QUARTER = re.compile(
    r"(?<!\d)"
    r"(20\d{2})"
    r"[\s._/-]+"
    r"(?:t|q|trim(?:estre)?)"
    r"[\s._/-]*"
    r"([1-4])"
    r"(?![a-z0-9])",
    re.IGNORECASE,
)


# ============================================================
# AÑOS
# ============================================================

YEAR_PATTERN = re.compile(
    r"(?<!\d)"
    r"(20\d{2})"
    r"(?!\d)"
)


# ============================================================
# MODELO INTERNO
# ============================================================

@dataclass(frozen=True)
class _DateCandidate:
    year: int
    month: int
    day: int
    value: str
    precision: int

    @property
    def sort_key(self) -> tuple[int, int, int, int]:
        return (
            self.year,
            self.month,
            self.day,
            self.precision,
        )


# ============================================================
# TEXTO
# ============================================================

def clean_text(
    value: str | None,
) -> str:
    if not value:
        return ""

    return " ".join(
        value.split()
    ).strip()


def _normalize_search_text(
    value: str,
) -> str:
    """
    Normaliza únicamente para DETECCIÓN.

    El valor original de URL/descripción no se modifica.
    """

    decoded = unquote(
        str(value or "")
    )

    normalized = unicodedata.normalize(
        "NFKD",
        decoded,
    )

    without_accents = "".join(
        char
        for char in normalized
        if not unicodedata.combining(char)
    )

    return (
        without_accents
        .lower()
        .replace("_", " ")
    )


# ============================================================
# ARCHIVO
# ============================================================

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


# ============================================================
# RECOLECCIÓN DE FECHAS
# ============================================================

def _numeric_candidates(
    text: str,
) -> list[_DateCandidate]:
    candidates: list[_DateCandidate] = []

    # YYYY-MM-DD
    for match in DATE_YMD.finditer(
        text
    ):
        year, month, day = (
            int(value)
            for value in match.groups()
        )

        candidates.append(
            _DateCandidate(
                year=year,
                month=month,
                day=day,
                value=(
                    f"{year:04d}-"
                    f"{month:02d}-"
                    f"{day:02d}"
                ),
                precision=3,
            )
        )

    # DD-MM-YYYY
    for match in DATE_DMY.finditer(
        text
    ):
        day, month, year = (
            int(value)
            for value in match.groups()
        )

        candidates.append(
            _DateCandidate(
                year=year,
                month=month,
                day=day,
                value=(
                    f"{year:04d}-"
                    f"{month:02d}-"
                    f"{day:02d}"
                ),
                precision=3,
            )
        )

    # YYYYMMDD
    for match in DATE_COMPACT.finditer(
        text
    ):
        year, month, day = (
            int(value)
            for value in match.groups()
        )

        candidates.append(
            _DateCandidate(
                year=year,
                month=month,
                day=day,
                value=(
                    f"{year:04d}-"
                    f"{month:02d}-"
                    f"{day:02d}"
                ),
                precision=3,
            )
        )

    # YYYY-MM
    for match in DATE_YM.finditer(
        text
    ):
        year, month = (
            int(value)
            for value in match.groups()
        )

        candidates.append(
            _DateCandidate(
                year=year,
                month=month,
                day=0,
                value=(
                    f"{year:04d}-"
                    f"{month:02d}"
                ),
                precision=2,
            )
        )

    return candidates


def _text_month_candidates(
    text: str,
) -> list[_DateCandidate]:
    candidates: list[_DateCandidate] = []

    for match in MONTH_YEAR.finditer(
        text
    ):
        month_name = (
            match.group(1)
            .lower()
            .strip(".")
        )

        year = int(
            match.group(2)
        )

        month = MONTHS.get(
            month_name
        )

        if month is None:
            continue

        candidates.append(
            _DateCandidate(
                year=year,
                month=month,
                day=0,
                value=(
                    f"{year:04d}-"
                    f"{month:02d}"
                ),
                precision=2,
            )
        )

    for match in YEAR_MONTH_TEXT.finditer(
        text
    ):
        year = int(
            match.group(1)
        )

        month_name = (
            match.group(2)
            .lower()
            .strip(".")
        )

        month = MONTHS.get(
            month_name
        )

        if month is None:
            continue

        candidates.append(
            _DateCandidate(
                year=year,
                month=month,
                day=0,
                value=(
                    f"{year:04d}-"
                    f"{month:02d}"
                ),
                precision=2,
            )
        )

    return candidates


def _quarter_candidates(
    text: str,
) -> list[_DateCandidate]:
    candidates: list[_DateCandidate] = []

    for match in QUARTER_YEAR.finditer(
        text
    ):
        quarter = int(
            match.group(1)
        )

        year = int(
            match.group(2)
        )

        candidates.append(
            _DateCandidate(
                year=year,
                month=quarter * 3,
                day=0,
                value=(
                    f"{year:04d}-T{quarter}"
                ),
                precision=2,
            )
        )

    for match in YEAR_QUARTER.finditer(
        text
    ):
        year = int(
            match.group(1)
        )

        quarter = int(
            match.group(2)
        )

        candidates.append(
            _DateCandidate(
                year=year,
                month=quarter * 3,
                day=0,
                value=(
                    f"{year:04d}-T{quarter}"
                ),
                precision=2,
            )
        )

    return candidates


# ============================================================
# EXTRAER FECHA DE REFERENCIA
# ============================================================

def extract_date(
    url: str,
    text: str = "",
) -> str | None:
    """
    Obtiene la fecha/periodo MÁS RECIENTE visible en la URL o
    descripción del recurso, sin descargar el archivo.

    Soporta:
    - YYYY-MM-DD
    - DD-MM-YYYY
    - YYYYMMDD
    - YYYY-MM
    - "Julio 2026"
    - "diciembre de 2025"
    - "jun 2024 - jun 2025"
    - "T2 2026" / "Q2 2026"
    - año aislado como último fallback

    IMPORTANTE:
    esta fecha representa el PERIODO DE REFERENCIA inferido del
    nombre/URL. No equivale necesariamente a la fecha HTTP de
    modificación del archivo.
    """

    normalized_url = _normalize_search_text(
        url
    )

    normalized_text = _normalize_search_text(
        clean_text(
            text
        )
    )

    combined = (
        normalized_url
        + " "
        + normalized_text
    )

    precise_candidates: list[
        _DateCandidate
    ] = []

    precise_candidates.extend(
        _numeric_candidates(
            combined
        )
    )

    precise_candidates.extend(
        _text_month_candidates(
            combined
        )
    )

    precise_candidates.extend(
        _quarter_candidates(
            combined
        )
    )

    if precise_candidates:
        best = max(
            precise_candidates,
            key=lambda item: item.sort_key,
        )

        return best.value

    # Último fallback: año visible. Si hay un rango como
    # 2023-2024, devuelve 2024.
    years = [
        int(
            match.group(1)
        )
        for match in YEAR_PATTERN.finditer(
            combined
        )
    ]

    if years:
        return str(
            max(
                years
            )
        )

    return None
