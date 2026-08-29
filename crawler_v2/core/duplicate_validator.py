from __future__ import annotations

"""
Validador conservador de duplicados.

Combina varias señales independientes antes de decidir que dos recursos
representan el mismo dataset/publicación:

1. identidad semántica;
2. familia de página de origen;
3. periodo explícito compatible;
4. formato comparable;
5. contenido lógico (XLSX/ODS/CSV/TSV).

Regla principal:
- ante duda -> conservar ambos;
- solo se confirma duplicidad cuando la evidencia es fuerte.

Este módulo NO hace peticiones HTTP y NO elimina recursos.
"""

from dataclasses import dataclass
import re
from typing import Iterable

from core.content_fingerprint import (
    ContentComparison,
    ContentFingerprint,
    compare_fingerprints,
    fingerprint_bytes,
)
from core.resource_dedupe import (
    DeduplicationDecision,
    RepresentationCandidate,
    RepresentationDeduper,
    SPREADSHEET_FORMATS,
    normalize_origin_family,
    normalize_semantic_text,
)


PERIOD_PATTERNS = (
    # YYYY-MM-DD / YYYY-MM
    re.compile(
        r"\b(20\d{2})[-_/](0?[1-9]|1[0-2])(?:[-_/](0?[1-9]|[12]\d|3[01]))?\b"
    ),

    # YYYY-T1 / YYYY-Q1
    re.compile(
        r"\b(20\d{2})[-_/ ]?(?:t|q)([1-4])\b",
        re.IGNORECASE,
    ),

    # T1 2026 / Q1 2026
    re.compile(
        r"\b(?:t|q)([1-4])[-_/ ]?(20\d{2})\b",
        re.IGNORECASE,
    ),
)

MONTHS = {
    "enero": "01",
    "ene": "01",
    "january": "01",
    "jan": "01",

    "febrero": "02",
    "feb": "02",
    "february": "02",

    "marzo": "03",
    "mar": "03",
    "march": "03",

    "abril": "04",
    "abr": "04",
    "april": "04",
    "apr": "04",

    "mayo": "05",
    "may": "05",

    "junio": "06",
    "jun": "06",
    "june": "06",

    "julio": "07",
    "jul": "07",
    "july": "07",

    "agosto": "08",
    "ago": "08",
    "august": "08",
    "aug": "08",

    "septiembre": "09",
    "setiembre": "09",
    "sep": "09",
    "sept": "09",
    "september": "09",

    "octubre": "10",
    "oct": "10",
    "october": "10",

    "noviembre": "11",
    "nov": "11",
    "november": "11",

    "diciembre": "12",
    "dic": "12",
    "december": "12",
    "dec": "12",
}


@dataclass(frozen=True)
class ValidationSignal:
    name: str
    passed: bool | None
    detail: str
    weight: int


@dataclass(frozen=True)
class DuplicateValidationResult:
    status: str
    confidence: float
    winner: RepresentationCandidate | None
    loser: RepresentationCandidate | None
    semantic_identity: str
    content_status: str
    signals: tuple[ValidationSignal, ...]
    reasons: tuple[str, ...]


def _first_non_empty(
    values: Iterable[object],
) -> str:
    for value in values:
        text = str(
            value
            or ""
        ).strip()

        if text:
            return text

    return ""


def extract_period_token(
    candidate: RepresentationCandidate,
) -> str:
    """
    Extrae un periodo explícito y conservador.

    Prioridad:
    1. metadatos estructurados;
    2. descripción;
    3. URL.

    No inventa periodos.
    """

    metadata = (
        candidate.metadata
        or {}
    )

    structured = _first_non_empty(
        (
            metadata.get(
                "fecha_referencia"
            ),
            metadata.get(
                "periodo"
            ),
            metadata.get(
                "fecha_actualizacion"
            ),
            metadata.get(
                "fecha_publicacion"
            ),
        )
    )

    search_values = (
        structured,
        candidate.description,
        candidate.url,
    )

    for raw in search_values:
        text = normalize_semantic_text(
            raw
        )

        if not text:
            continue

        # YYYY-MM(-DD)
        match = PERIOD_PATTERNS[
            0
        ].search(
            text
        )

        if match:
            year = match.group(
                1
            )

            month = int(
                match.group(
                    2
                )
            )

            return (
                f"{year}-{month:02d}"
            )

        # YYYY-Tn / YYYY-Qn
        match = PERIOD_PATTERNS[
            1
        ].search(
            text
        )

        if match:
            return (
                f"{match.group(1)}-T{match.group(2)}"
            )

        # Tn YYYY / Qn YYYY
        match = PERIOD_PATTERNS[
            2
        ].search(
            text
        )

        if match:
            return (
                f"{match.group(2)}-T{match.group(1)}"
            )

        # Mes + año de 4 dígitos.
        for month_name, month_number in MONTHS.items():
            month_match = re.search(
                rf"\b{re.escape(month_name)}\b.*?\b(20\d{{2}})\b",
                text,
            )

            if month_match:
                return (
                    f"{month_match.group(1)}-{month_number}"
                )

        # Año + mes.
        for month_name, month_number in MONTHS.items():
            month_match = re.search(
                rf"\b(20\d{{2}})\b.*?\b{re.escape(month_name)}\b",
                text,
            )

            if month_match:
                return (
                    f"{month_match.group(1)}-{month_number}"
                )

        # Formatos abreviados del tipo ENERO_24, JULIO-21, etc.
        for month_name, month_number in MONTHS.items():
            short_match = re.search(
                rf"\b{re.escape(month_name)}\b[^0-9]{{0,4}}(\d{{2}})\b",
                text,
            )

            if short_match:
                short_year = int(
                    short_match.group(
                        1
                    )
                )

                # Los reportes históricos modernos que estamos tratando
                # corresponden a 2000-2099.
                year = (
                    2000
                    + short_year
                )

                return (
                    f"{year:04d}-{month_number}"
                )

    return ""


class DuplicateValidator:
    """
    Decide si dos representaciones pueden tratarse como duplicado real.
    """

    def __init__(
        self,
        *,
        deduper: RepresentationDeduper | None = None,
        min_content_confidence: float = 0.97,
    ) -> None:

        self.deduper = (
            deduper
            or RepresentationDeduper()
        )

        self.min_content_confidence = float(
            min_content_confidence
        )

    # ========================================================
    # SEÑALES
    # ========================================================

    def _semantic_signal(
        self,
        left: RepresentationCandidate,
        right: RepresentationCandidate,
    ) -> tuple[
        ValidationSignal,
        str,
    ]:
        left_id = self.deduper.identity_for(
            left
        )

        right_id = self.deduper.identity_for(
            right
        )

        if (
            left_id
            and right_id
            and left_id == right_id
        ):
            return (
                ValidationSignal(
                    name="semantic_identity",
                    passed=True,
                    detail=left_id,
                    weight=35,
                ),
                left_id,
            )

        if (
            left_id
            and right_id
            and left_id != right_id
        ):
            return (
                ValidationSignal(
                    name="semantic_identity",
                    passed=False,
                    detail=(
                        "different_semantic_identity"
                    ),
                    weight=35,
                ),
                "",
            )

        return (
            ValidationSignal(
                name="semantic_identity",
                passed=None,
                detail="insufficient_identity",
                weight=35,
            ),
            "",
        )

    def _origin_signal(
        self,
        left: RepresentationCandidate,
        right: RepresentationCandidate,
    ) -> ValidationSignal:
        left_origin = normalize_origin_family(
            left.origin_url
        )

        right_origin = normalize_origin_family(
            right.origin_url
        )

        if (
            left_origin
            and right_origin
        ):
            same = (
                left_origin
                == right_origin
            )

            return ValidationSignal(
                name="origin_family",
                passed=same,
                detail=(
                    left_origin
                    if same
                    else "different_origin_family"
                ),
                weight=15,
            )

        return ValidationSignal(
            name="origin_family",
            passed=None,
            detail="origin_not_available",
            weight=15,
        )

    def _period_signal(
        self,
        left: RepresentationCandidate,
        right: RepresentationCandidate,
    ) -> ValidationSignal:
        left_period = extract_period_token(
            left
        )

        right_period = extract_period_token(
            right
        )

        if (
            left_period
            and right_period
        ):
            same = (
                left_period
                == right_period
            )

            return ValidationSignal(
                name="period",
                passed=same,
                detail=(
                    left_period
                    if same
                    else (
                        f"{left_period}!={right_period}"
                    )
                ),
                weight=20,
            )

        return ValidationSignal(
            name="period",
            passed=None,
            detail="period_not_available",
            weight=20,
        )

    def _format_signal(
        self,
        left: RepresentationCandidate,
        right: RepresentationCandidate,
    ) -> ValidationSignal:
        left_type = (
            left.normalized_type
        )

        right_type = (
            right.normalized_type
        )

        comparable = (
            left_type
            in SPREADSHEET_FORMATS
            and right_type
            in SPREADSHEET_FORMATS
        )

        return ValidationSignal(
            name="comparable_formats",
            passed=comparable,
            detail=(
                f"{left_type}<->{right_type}"
            ),
            weight=10,
        )

    # ========================================================
    # CONTENIDO
    # ========================================================

    def compare_content(
        self,
        *,
        left: RepresentationCandidate,
        right: RepresentationCandidate,
        left_payload: bytes | None,
        right_payload: bytes | None,
    ) -> tuple[
        ContentComparison | None,
        ContentFingerprint | None,
        ContentFingerprint | None,
    ]:
        if (
            left_payload is None
            or right_payload is None
        ):
            return (
                None,
                None,
                None,
            )

        left_fp = fingerprint_bytes(
            left_payload,
            format_name=left.normalized_type,
        )

        right_fp = fingerprint_bytes(
            right_payload,
            format_name=right.normalized_type,
        )

        comparison = compare_fingerprints(
            left_fp,
            right_fp,
        )

        return (
            comparison,
            left_fp,
            right_fp,
        )

    # ========================================================
    # DECISIÓN
    # ========================================================

    def validate(
        self,
        *,
        left: RepresentationCandidate,
        right: RepresentationCandidate,
        left_payload: bytes | None = None,
        right_payload: bytes | None = None,
    ) -> DuplicateValidationResult:

        reasons: list[str] = []

        semantic_signal, identity = (
            self._semantic_signal(
                left,
                right,
            )
        )

        origin_signal = (
            self._origin_signal(
                left,
                right,
            )
        )

        period_signal = (
            self._period_signal(
                left,
                right,
            )
        )

        format_signal = (
            self._format_signal(
                left,
                right,
            )
        )

        signals: list[
            ValidationSignal
        ] = [
            semantic_signal,
            origin_signal,
            period_signal,
            format_signal,
        ]

        # Diferencias fuertes bloquean la deduplicación.
        if semantic_signal.passed is False:
            return DuplicateValidationResult(
                status="KEEP_BOTH",
                confidence=1.0,
                winner=None,
                loser=None,
                semantic_identity="",
                content_status="NOT_CHECKED",
                signals=tuple(
                    signals
                ),
                reasons=(
                    "semantic_identity_conflict",
                ),
            )

        if period_signal.passed is False:
            return DuplicateValidationResult(
                status="KEEP_BOTH",
                confidence=1.0,
                winner=None,
                loser=None,
                semantic_identity=identity,
                content_status="NOT_CHECKED",
                signals=tuple(
                    signals
                ),
                reasons=(
                    "period_conflict",
                ),
            )

        if format_signal.passed is False:
            return DuplicateValidationResult(
                status="KEEP_BOTH",
                confidence=1.0,
                winner=None,
                loser=None,
                semantic_identity=identity,
                content_status="NOT_CHECKED",
                signals=tuple(
                    signals
                ),
                reasons=(
                    "non_comparable_formats",
                ),
            )

        # URL idéntica sí es duplicación exacta sin volver a descargar.
        if (
            str(
                left.url
            ).strip()
            == str(
                right.url
            ).strip()
        ):
            dedupe_decision = self.deduper.choose(
                left,
                right,
            )

            return DuplicateValidationResult(
                status="CONFIRMED_DUPLICATE",
                confidence=1.0,
                winner=dedupe_decision.winner,
                loser=dedupe_decision.loser,
                semantic_identity=(
                    dedupe_decision.identity
                    or identity
                ),
                content_status="EXACT_URL",
                signals=tuple(
                    signals
                ),
                reasons=(
                    "exact_same_url",
                ),
            )

        # Para representaciones distintas exigimos identidad fuerte antes
        # de gastar una validación de contenido.
        if semantic_signal.passed is not True:
            return DuplicateValidationResult(
                status="KEEP_BOTH",
                confidence=0.0,
                winner=None,
                loser=None,
                semantic_identity="",
                content_status="NOT_CHECKED",
                signals=tuple(
                    signals
                ),
                reasons=(
                    "insufficient_semantic_evidence",
                ),
            )

        # Si todavía no llegaron bytes, el resultado explícito es que hace
        # falta comparar contenido. El caller decide si vale gastar esa
        # descarga según presupuesto.
        if (
            left_payload is None
            or right_payload is None
        ):
            return DuplicateValidationResult(
                status="NEEDS_CONTENT_CHECK",
                confidence=0.0,
                winner=None,
                loser=None,
                semantic_identity=identity,
                content_status="NOT_CHECKED",
                signals=tuple(
                    signals
                ),
                reasons=(
                    "content_required_before_deduplication",
                ),
            )

        (
            content_comparison,
            left_fp,
            right_fp,
        ) = self.compare_content(
            left=left,
            right=right,
            left_payload=left_payload,
            right_payload=right_payload,
        )

        if content_comparison is None:
            return DuplicateValidationResult(
                status="KEEP_BOTH",
                confidence=0.0,
                winner=None,
                loser=None,
                semantic_identity=identity,
                content_status="INCONCLUSIVE",
                signals=tuple(
                    signals
                ),
                reasons=(
                    "content_comparison_unavailable",
                ),
            )

        content_passed: bool | None

        if (
            content_comparison.status
            == "SAME_CONTENT"
            and content_comparison.confidence
            >= self.min_content_confidence
        ):
            content_passed = True

        elif (
            content_comparison.status
            == "LIKELY_SAME"
            and content_comparison.confidence
            >= self.min_content_confidence
        ):
            content_passed = True

        elif (
            content_comparison.status
            == "DIFFERENT"
        ):
            content_passed = False

        else:
            content_passed = None

        signals.append(
            ValidationSignal(
                name="logical_content",
                passed=content_passed,
                detail=(
                    f"{content_comparison.status}:"
                    f"{content_comparison.confidence:.4f}"
                ),
                weight=50,
            )
        )

        if content_passed is False:
            return DuplicateValidationResult(
                status="KEEP_BOTH",
                confidence=(
                    content_comparison.confidence
                ),
                winner=None,
                loser=None,
                semantic_identity=identity,
                content_status=(
                    content_comparison.status
                ),
                signals=tuple(
                    signals
                ),
                reasons=(
                    "logical_content_differs",
                ),
            )

        if content_passed is not True:
            return DuplicateValidationResult(
                status="KEEP_BOTH",
                confidence=(
                    content_comparison.confidence
                ),
                winner=None,
                loser=None,
                semantic_identity=identity,
                content_status=(
                    content_comparison.status
                ),
                signals=tuple(
                    signals
                ),
                reasons=(
                    "content_evidence_inconclusive",
                ),
            )

        # Señales mínimas adicionales:
        # - origen compatible o desconocido;
        # - periodo compatible o desconocido;
        # nunca permitimos un conflicto explícito.
        if origin_signal.passed is False:
            reasons.append(
                "origin_family_differs_but_content_matches"
            )

            # Dos fuentes/orígenes distintos pueden publicar copias del mismo
            # contenido, pero por seguridad no las colapsamos automáticamente.
            return DuplicateValidationResult(
                status="KEEP_BOTH",
                confidence=(
                    content_comparison.confidence
                ),
                winner=None,
                loser=None,
                semantic_identity=identity,
                content_status=(
                    content_comparison.status
                ),
                signals=tuple(
                    signals
                ),
                reasons=tuple(
                    reasons
                ),
            )

        dedupe_decision: DeduplicationDecision = (
            self.deduper.choose(
                left,
                right,
            )
        )

        if not dedupe_decision.duplicate:
            return DuplicateValidationResult(
                status="KEEP_BOTH",
                confidence=(
                    content_comparison.confidence
                ),
                winner=None,
                loser=None,
                semantic_identity=identity,
                content_status=(
                    content_comparison.status
                ),
                signals=tuple(
                    signals
                ),
                reasons=(
                    "deduper_did_not_confirm_equivalence",
                ),
            )

        reasons.extend(
            content_comparison.reasons
        )

        reasons.append(
            dedupe_decision.reason
        )

        return DuplicateValidationResult(
            status="CONFIRMED_DUPLICATE",
            confidence=(
                content_comparison.confidence
            ),
            winner=(
                dedupe_decision.winner
            ),
            loser=(
                dedupe_decision.loser
            ),
            semantic_identity=(
                dedupe_decision.identity
                or identity
            ),
            content_status=(
                content_comparison.status
            ),
            signals=tuple(
                signals
            ),
            reasons=tuple(
                reasons
            ),
        )


__all__ = [
    "DuplicateValidationResult",
    "DuplicateValidator",
    "ValidationSignal",
    "extract_period_token",
]
