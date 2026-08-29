from __future__ import annotations

"""
Deduplicación conservadora de representaciones equivalentes.

Objetivo:
- evitar guardar la misma publicación/dataset en varios formatos cuando
  representan exactamente el mismo recurso;
- preferir la representación más útil para transformación automática;
- nunca eliminar recursos solo porque "se parecen".

La deduplicación genérica es intencionalmente conservadora. Los adapters
pueden aportar una identidad semántica más precisa para cada fuente.
"""

from dataclasses import dataclass, field
from pathlib import PurePosixPath
import re
import unicodedata
from typing import Any, Callable
from urllib.parse import unquote, urlparse


SPREADSHEET_FORMATS = {
    "xlsx",
    "xls",
    "ods",
    "csv",
    "tsv",
}

FORMAT_PREFERENCE = {
    "xlsx": 100,
    "csv": 95,
    "ods": 90,
    "xls": 80,
    "tsv": 75,
}

GENERIC_LABELS = {
    "",
    "archivo",
    "descargar",
    "download",
    "excel",
    "ods",
    "xlsx",
    "xls",
    "csv",
    "ver",
    "ver archivo",
    "ver archivo excel",
    "ver archivo ods",
    "ver excel",
    "ver ods",
}

FORMAT_WORDS = {
    "excel",
    "xlsx",
    "xls",
    "ods",
    "csv",
    "tsv",
    "download",
    "descargar",
}


def _ascii_text(value: str) -> str:
    value = unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )

    value = "".join(
        char
        for char in value
        if not unicodedata.combining(char)
    )

    return value.lower()


def normalize_semantic_text(value: str) -> str:
    """
    Normalización estable para construir identidades semánticas.
    """

    value = unquote(
        str(value or "")
    )

    value = _ascii_text(
        value
    )

    value = re.sub(
        r"\.(xlsx|xls|ods|csv|tsv)$",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"[_\-]+",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    return value


def normalized_filename_stem(
    url: str,
) -> str:
    parsed = urlparse(
        str(url or "")
    )

    path = unquote(
        parsed.path
        or ""
    )

    name = PurePosixPath(
        path
    ).name

    if not name:
        return ""

    stem = re.sub(
        r"\.(xlsx|xls|ods|csv|tsv)$",
        "",
        name,
        flags=re.IGNORECASE,
    )

    return normalize_semantic_text(
        stem
    )


def normalize_description(
    description: str,
) -> str:
    value = normalize_semantic_text(
        description
    )

    if value in GENERIC_LABELS:
        return ""

    words = [
        word
        for word in value.split()
        if word not in FORMAT_WORDS
    ]

    value = " ".join(
        words
    ).strip()

    if value in GENERIC_LABELS:
        return ""

    return value


def normalize_origin_family(
    origin_url: str,
) -> str:
    """
    Normaliza la página de origen sin usar la paginación como identidad.

    Ejemplo:
        ?page=4&q=reporte-estadistico
    y:
        ?page=7&q=reporte-estadistico

    pertenecen a la misma familia de colección.
    """

    parsed = urlparse(
        str(origin_url or "")
    )

    host = (
        parsed.hostname
        or ""
    ).lower()

    path = unquote(
        parsed.path
        or "/"
    )

    query = parsed.query or ""

    # page=N es navegación, no identidad del dataset.
    query = re.sub(
        r"(^|&)page=\d+(&|$)",
        lambda match: (
            "&"
            if (
                match.group(1)
                and match.group(2)
            )
            else ""
        ),
        query,
        flags=re.IGNORECASE,
    )

    query = query.strip(
        "&"
    )

    base = (
        f"{host}{path}"
    )

    if query:
        base += (
            "?"
            + query
        )

    return normalize_semantic_text(
        base
    )


@dataclass(frozen=True)
class RepresentationCandidate:
    url: str
    resource_type: str
    description: str = ""
    origin_url: str = ""
    semantic_id: str = ""
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def normalized_type(
        self,
    ) -> str:
        return (
            str(
                self.resource_type
                or ""
            )
            .lower()
            .strip()
            .lstrip(".")
        )


@dataclass(frozen=True)
class DeduplicationDecision:
    duplicate: bool
    winner: RepresentationCandidate
    loser: RepresentationCandidate | None
    identity: str
    reason: str


IdentityResolver = Callable[
    [RepresentationCandidate],
    str | None,
]


class RepresentationDeduper:
    """
    Deduplicador de representaciones equivalentes.

    El motor NO hace deduplicación difusa agresiva.
    Solo deduplica cuando existe una identidad semántica suficientemente
    fuerte y ambos candidatos son formatos de datos comparables.
    """

    def __init__(
        self,
        *,
        identity_resolver: IdentityResolver | None = None,
        format_preference: dict[str, int] | None = None,
    ) -> None:

        self.identity_resolver = (
            identity_resolver
        )

        self.format_preference = dict(
            FORMAT_PREFERENCE
        )

        if format_preference:
            self.format_preference.update(
                {
                    str(key).lower().lstrip("."): int(value)
                    for key, value
                    in format_preference.items()
                }
            )

    # ========================================================
    # IDENTIDAD
    # ========================================================

    def default_identity(
        self,
        candidate: RepresentationCandidate,
    ) -> str:
        """
        Identidad genérica segura.

        Por defecto exige que el nombre de archivo tenga un stem
        significativo. No usa solamente "misma fecha + mismo origen",
        porque una página puede publicar muchos datasets diferentes
        del mismo periodo.
        """

        resource_type = (
            candidate.normalized_type
        )

        if resource_type not in SPREADSHEET_FORMATS:
            return ""

        stem = normalized_filename_stem(
            candidate.url
        )

        if not stem:
            return ""

        # Evitar identidades demasiado débiles como "1", "01", "02".
        compact = re.sub(
            r"[^a-z0-9]+",
            "",
            _ascii_text(
                stem
            ),
        )

        if (
            not compact
            or compact.isdigit()
            or len(compact) < 4
        ):
            return ""

        origin = normalize_origin_family(
            candidate.origin_url
        )

        return (
            f"generic|{origin}|{stem}"
        )

    def identity_for(
        self,
        candidate: RepresentationCandidate,
    ) -> str:
        explicit = normalize_semantic_text(
            candidate.semantic_id
        )

        if explicit:
            return (
                "adapter|"
                + explicit
            )

        if self.identity_resolver:
            resolved = self.identity_resolver(
                candidate
            )

            resolved = normalize_semantic_text(
                resolved
                or ""
            )

            if resolved:
                return (
                    "adapter|"
                    + resolved
                )

        return self.default_identity(
            candidate
        )

    # ========================================================
    # PREFERENCIA
    # ========================================================

    def quality_score(
        self,
        candidate: RepresentationCandidate,
    ) -> int:
        resource_type = (
            candidate.normalized_type
        )

        score = self.format_preference.get(
            resource_type,
            0,
        )

        # Una descripción real es una pequeña señal de calidad,
        # pero nunca domina la preferencia de formato.
        if normalize_description(
            candidate.description
        ):
            score += 2

        return score

    def choose(
        self,
        existing: RepresentationCandidate,
        incoming: RepresentationCandidate,
    ) -> DeduplicationDecision:

        existing_type = (
            existing.normalized_type
        )

        incoming_type = (
            incoming.normalized_type
        )

        if (
            existing_type
            not in SPREADSHEET_FORMATS
            or incoming_type
            not in SPREADSHEET_FORMATS
        ):
            return DeduplicationDecision(
                duplicate=False,
                winner=existing,
                loser=None,
                identity="",
                reason="non_comparable_resource_types",
            )

        existing_identity = self.identity_for(
            existing
        )

        incoming_identity = self.identity_for(
            incoming
        )

        if (
            not existing_identity
            or not incoming_identity
        ):
            return DeduplicationDecision(
                duplicate=False,
                winner=existing,
                loser=None,
                identity="",
                reason="insufficient_semantic_identity",
            )

        if (
            existing_identity
            != incoming_identity
        ):
            return DeduplicationDecision(
                duplicate=False,
                winner=existing,
                loser=None,
                identity="",
                reason="different_semantic_identity",
            )

        # Si ambas URLs son idénticas, es duplicación exacta.
        if (
            str(existing.url).strip()
            == str(incoming.url).strip()
        ):
            return DeduplicationDecision(
                duplicate=True,
                winner=existing,
                loser=incoming,
                identity=existing_identity,
                reason="exact_same_url",
            )

        existing_score = self.quality_score(
            existing
        )

        incoming_score = self.quality_score(
            incoming
        )

        if incoming_score > existing_score:
            winner = incoming
            loser = existing

        else:
            # En empate se conserva el primero para mantener estabilidad
            # entre ejecuciones.
            winner = existing
            loser = incoming

        return DeduplicationDecision(
            duplicate=True,
            winner=winner,
            loser=loser,
            identity=existing_identity,
            reason=(
                "equivalent_representation_prefer_"
                + winner.normalized_type
            ),
        )


__all__ = [
    "DeduplicationDecision",
    "RepresentationCandidate",
    "RepresentationDeduper",
    "SPREADSHEET_FORMATS",
    "normalize_description",
    "normalize_origin_family",
    "normalize_semantic_text",
    "normalized_filename_stem",
]
