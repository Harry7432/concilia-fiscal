import re
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

import polars as pl

from concilia_fiscal.selection import SelectionResult

MARKER_PATTERN = re.compile(
    r"(?<!\w)(?:N\.F\.|NF|NOTA(?:\s+FISCAL)?)(?!\w)",
    re.IGNORECASE,
)
DOCUMENT_PATTERN = re.compile(
    r"(?<!\w)(?:N\.F\.|NF|NOTA(?:\s+FISCAL)?)(?!\w)"
    r"[\s:#-]*"
    r"(?:(?:N[ÚU]MERO|N[º°]|NO|N\.)[\s:#-]*)?"
    r"([0-9]+)(?!\w)",
    re.IGNORECASE,
)
NUMERIC_CONTINUATION_PATTERN = re.compile(r"^\s*[^\w\s]\s*[0-9]")


class DocumentExtractionStatus(StrEnum):
    EXTRACTED = "extracted"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"


class DocumentExtractionReasonCode(StrEnum):
    DOCUMENT_EXTRACTED = "document_extracted"
    HISTORY_MISSING = "history_missing"
    DOCUMENT_MARKER_NOT_FOUND = "document_marker_not_found"
    DOCUMENT_NUMBER_NOT_FOUND = "document_number_not_found"
    MULTIPLE_DOCUMENTS = "multiple_documents"


@dataclass(frozen=True, slots=True)
class DocumentExtractionReason:
    code: DocumentExtractionReasonCode
    message: str
    matched_value: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentExtractionDecision:
    source_row: int
    extracted_document: str | None
    candidates: tuple[str, ...]
    status: DocumentExtractionStatus
    reason: DocumentExtractionReason


@dataclass(frozen=True, slots=True)
class DocumentExtractionResult:
    classified: pl.DataFrame
    extracted: pl.DataFrame
    decisions: tuple[DocumentExtractionDecision, ...]


def _collect_candidates(history: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for match in DOCUMENT_PATTERN.finditer(history):
        suffix = history[match.end() :]
        if NUMERIC_CONTINUATION_PATTERN.match(suffix):
            continue
        candidate = match.group(1)
        if candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _evaluate_history(
    history: object,
) -> tuple[
    str | None,
    tuple[str, ...],
    DocumentExtractionStatus,
    DocumentExtractionReason,
]:
    if history is None or (isinstance(history, str) and not history.strip()):
        return (
            None,
            (),
            DocumentExtractionStatus.NOT_FOUND,
            DocumentExtractionReason(
                DocumentExtractionReasonCode.HISTORY_MISSING,
                "O histórico contábil não está disponível.",
            ),
        )

    normalized_history = cast(str, history)
    candidates = _collect_candidates(normalized_history)
    if len(candidates) == 1:
        extracted_document = candidates[0]
        return (
            extracted_document,
            candidates,
            DocumentExtractionStatus.EXTRACTED,
            DocumentExtractionReason(
                DocumentExtractionReasonCode.DOCUMENT_EXTRACTED,
                "Um documento fiscal foi extraído do histórico contábil.",
                extracted_document,
            ),
        )
    if len(candidates) > 1:
        return (
            None,
            candidates,
            DocumentExtractionStatus.AMBIGUOUS,
            DocumentExtractionReason(
                DocumentExtractionReasonCode.MULTIPLE_DOCUMENTS,
                "Mais de um documento fiscal distinto foi encontrado no histórico contábil.",
            ),
        )
    if MARKER_PATTERN.search(normalized_history):
        return (
            None,
            (),
            DocumentExtractionStatus.NOT_FOUND,
            DocumentExtractionReason(
                DocumentExtractionReasonCode.DOCUMENT_NUMBER_NOT_FOUND,
                "Nenhum número de documento confiável foi encontrado após o marcador fiscal.",
            ),
        )
    return (
        None,
        (),
        DocumentExtractionStatus.NOT_FOUND,
        DocumentExtractionReason(
            DocumentExtractionReasonCode.DOCUMENT_MARKER_NOT_FOUND,
            "Nenhum marcador explícito de documento fiscal foi encontrado no histórico contábil.",
        ),
    )


def _validate_contract(accounting: pl.DataFrame) -> None:
    expected = {
        "source_row": pl.Int64,
        "history": pl.String,
        "selection_status": pl.String,
        "selection_reason_codes": pl.List(pl.String),
    }
    for column, expected_type in expected.items():
        if column not in accounting.columns:
            raise ValueError(f'Coluna obrigatória ausente no frame contábil: "{column}".')
        actual_type = accounting.schema[column]
        if actual_type != expected_type:
            raise ValueError(
                f'Tipo inválido para a coluna contábil "{column}": '
                f"esperado {expected_type}, recebido {actual_type}."
            )
    if accounting["source_row"].null_count() > 0:
        raise ValueError('A coluna contábil "source_row" não pode conter valores nulos.')
    if accounting.filter(pl.col("selection_status").ne_missing("selected")).height > 0:
        raise ValueError(
            'Todas as linhas de entrada devem ter selection_status igual a "selected".'
        )


def extract_documents(selection: SelectionResult) -> DocumentExtractionResult:
    accounting = selection.selected
    _validate_contract(accounting)
    decisions: list[DocumentExtractionDecision] = []
    for row in accounting.iter_rows(named=True):
        extracted_document, candidates, status, reason = _evaluate_history(row["history"])
        decisions.append(
            DocumentExtractionDecision(
                source_row=cast(int, row["source_row"]),
                extracted_document=extracted_document,
                candidates=candidates,
                status=status,
                reason=reason,
            )
        )

    immutable_decisions = tuple(decisions)
    classified = accounting.with_columns(
        pl.Series(
            "extracted_document",
            [decision.extracted_document for decision in immutable_decisions],
            dtype=pl.String,
        ),
        pl.Series(
            "document_extraction_status",
            [decision.status.value for decision in immutable_decisions],
            dtype=pl.String,
        ),
        pl.Series(
            "document_extraction_reason_codes",
            [[decision.reason.code.value] for decision in immutable_decisions],
            dtype=pl.List(pl.String),
        ),
    )
    extracted = classified.filter(
        pl.col("document_extraction_status") == DocumentExtractionStatus.EXTRACTED.value
    )
    return DocumentExtractionResult(
        classified=classified,
        extracted=extracted,
        decisions=immutable_decisions,
    )
