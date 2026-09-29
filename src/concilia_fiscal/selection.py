import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import cast

import polars as pl

from concilia_fiscal.enrichment import EnrichmentIssue, EnrichmentResult

RESULT_ACCOUNT_NATURE = "04 - CONTAS DE RESULTADO"
ANALYTICAL_ACCOUNT_TYPE = "A - ANALITICA"
DEFAULT_EXCLUDED_CATEGORIES = ("MATERIAL", "MULTAS")
WHITESPACE_PATTERN = re.compile(r"\s+")


class SelectionStatus(StrEnum):
    SELECTED = "selected"
    EXCLUDED = "excluded"
    REVIEW = "review"


class SelectionReasonCode(StrEnum):
    MISSING_HISTORY = "missing_history"
    MISSING_DEBIT_CREDIT = "missing_debit_credit"
    INVALID_DEBIT_CREDIT = "invalid_debit_credit"
    CREDIT_ENTRY = "credit_entry"
    NON_POSITIVE_AMOUNT = "non_positive_amount"
    INVALID_AMOUNT = "invalid_amount"
    ENRICHMENT_UNAVAILABLE = "enrichment_unavailable"
    NON_RESULT_ACCOUNT = "non_result_account"
    NON_ANALYTICAL_ACCOUNT = "non_analytical_account"
    EXCLUDED_CATEGORY = "excluded_category"


@dataclass(frozen=True, slots=True)
class SelectionConfig:
    excluded_categories: tuple[str, ...] = DEFAULT_EXCLUDED_CATEGORIES


@dataclass(frozen=True, slots=True)
class SelectionReason:
    code: SelectionReasonCode
    message: str
    matched_value: str | None = None


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    source_row: int
    entry_number: str
    account_code: str
    status: SelectionStatus
    reasons: tuple[SelectionReason, ...]


@dataclass(frozen=True, slots=True)
class SelectionResult:
    classified: pl.DataFrame
    selected: pl.DataFrame
    decisions: tuple[SelectionDecision, ...]
    enrichment_issues: tuple[EnrichmentIssue, ...]
    is_valid: bool


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _evaluate_history(value: object) -> SelectionReason | None:
    if _is_blank(value):
        return SelectionReason(
            SelectionReasonCode.MISSING_HISTORY,
            "O histórico do lançamento é obrigatório.",
        )
    return None


def _evaluate_missing_debit_credit(value: object) -> SelectionReason | None:
    if _is_blank(value):
        return SelectionReason(
            SelectionReasonCode.MISSING_DEBIT_CREDIT,
            "A indicação de débito ou crédito é obrigatória.",
        )
    return None


def _evaluate_invalid_debit_credit(value: object) -> SelectionReason | None:
    if not _is_blank(value) and value not in {"D", "C"}:
        return SelectionReason(
            SelectionReasonCode.INVALID_DEBIT_CREDIT,
            'A indicação de débito ou crédito deve ser "D" ou "C".',
            str(value),
        )
    return None


def _evaluate_credit(value: object) -> SelectionReason | None:
    if value == "C":
        return SelectionReason(
            SelectionReasonCode.CREDIT_ENTRY,
            "O lançamento é de crédito.",
            "C",
        )
    return None


def _evaluate_amount(value: object) -> SelectionReason | None:
    if not isinstance(value, Decimal):
        return SelectionReason(
            SelectionReasonCode.INVALID_AMOUNT,
            "O saldo final não está disponível como valor decimal.",
            None if value is None else str(value),
        )
    if value <= Decimal("0.00"):
        return SelectionReason(
            SelectionReasonCode.NON_POSITIVE_AMOUNT,
            "O saldo final deve ser maior que zero.",
            str(value),
        )
    return None


def _evaluate_enrichment(row: dict[str, object]) -> SelectionReason | None:
    required_values = (
        row["account_source_row"],
        row["account_nature"],
        row["account_description"],
        row["account_type"],
    )
    if any(_is_blank(value) for value in required_values):
        return SelectionReason(
            SelectionReasonCode.ENRICHMENT_UNAVAILABLE,
            "Os atributos do plano de contas não estão disponíveis de forma unívoca.",
            cast(str, row["account_code"]),
        )
    return None


def _evaluate_nature(value: object) -> SelectionReason | None:
    if value != RESULT_ACCOUNT_NATURE:
        return SelectionReason(
            SelectionReasonCode.NON_RESULT_ACCOUNT,
            f'A natureza da conta deve ser "{RESULT_ACCOUNT_NATURE}".',
            str(value),
        )
    return None


def _evaluate_account_type(value: object) -> SelectionReason | None:
    if value != ANALYTICAL_ACCOUNT_TYPE:
        return SelectionReason(
            SelectionReasonCode.NON_ANALYTICAL_ACCOUNT,
            f'O tipo da conta deve ser "{ANALYTICAL_ACCOUNT_TYPE}".',
            str(value),
        )
    return None


def _normalize_categories(categories: tuple[str, ...]) -> tuple[str, ...]:
    normalized_categories: list[str] = []
    for category in categories:
        normalized = (
            WHITESPACE_PATTERN.sub(" ", unicodedata.normalize("NFC", category)).strip().upper()
        )
        if not normalized:
            raise ValueError("Categorias excluídas não podem ser vazias.")
        if normalized not in normalized_categories:
            normalized_categories.append(normalized)
    return tuple(normalized_categories)


def _evaluate_categories(
    description: object,
    categories: tuple[str, ...],
) -> tuple[SelectionReason, ...]:
    account_description = cast(str, description)
    return tuple(
        SelectionReason(
            SelectionReasonCode.EXCLUDED_CATEGORY,
            f'A descrição da conta contém a categoria excluída "{category}".',
            category,
        )
        for category in categories
        if category in account_description
    )


def _reason_status(reasons: tuple[SelectionReason, ...]) -> SelectionStatus:
    review_codes = {
        SelectionReasonCode.INVALID_DEBIT_CREDIT,
        SelectionReasonCode.INVALID_AMOUNT,
        SelectionReasonCode.ENRICHMENT_UNAVAILABLE,
    }
    if any(reason.code in review_codes for reason in reasons):
        return SelectionStatus.REVIEW
    if reasons:
        return SelectionStatus.EXCLUDED
    return SelectionStatus.SELECTED


def _evaluate_row(
    row: dict[str, object],
    categories: tuple[str, ...],
) -> SelectionDecision:
    reasons: list[SelectionReason] = []
    for evaluator, value in (
        (_evaluate_history, row["history"]),
        (_evaluate_missing_debit_credit, row["debit_credit"]),
        (_evaluate_invalid_debit_credit, row["debit_credit"]),
        (_evaluate_credit, row["debit_credit"]),
        (_evaluate_amount, row["amount"]),
    ):
        if reason := evaluator(value):
            reasons.append(reason)

    if enrichment_reason := _evaluate_enrichment(row):
        reasons.append(enrichment_reason)
    else:
        if nature_reason := _evaluate_nature(row["account_nature"]):
            reasons.append(nature_reason)
        if type_reason := _evaluate_account_type(row["account_type"]):
            reasons.append(type_reason)
        reasons.extend(_evaluate_categories(row["account_description"], categories))

    immutable_reasons = tuple(reasons)
    return SelectionDecision(
        source_row=cast(int, row["source_row"]),
        entry_number=cast(str, row["entry_number"]),
        account_code=cast(str, row["account_code"]),
        status=_reason_status(immutable_reasons),
        reasons=immutable_reasons,
    )


def select_accounting(
    enrichment: EnrichmentResult,
    config: SelectionConfig | None = None,
) -> SelectionResult:
    if config is None:
        config = SelectionConfig()
    categories = _normalize_categories(config.excluded_categories)
    decisions = tuple(
        _evaluate_row(row, categories) for row in enrichment.accounting.iter_rows(named=True)
    )
    classified = enrichment.accounting.with_columns(
        pl.Series(
            "selection_status",
            [decision.status.value for decision in decisions],
            dtype=pl.String,
        ),
        pl.Series(
            "selection_reason_codes",
            [[reason.code.value for reason in decision.reasons] for decision in decisions],
            dtype=pl.List(pl.String),
        ),
    )
    selected = classified.filter(pl.col("selection_status") == SelectionStatus.SELECTED.value)
    return SelectionResult(
        classified=classified,
        selected=selected,
        decisions=decisions,
        enrichment_issues=enrichment.issues,
        is_valid=all(decision.status is not SelectionStatus.REVIEW for decision in decisions),
    )
