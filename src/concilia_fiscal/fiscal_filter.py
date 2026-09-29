from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import cast

import polars as pl


class FiscalStatus(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


class FiscalReasonCode(StrEnum):
    PIS_POSITIVE = "pis_positive"
    PIS_ZERO = "pis_zero"
    PIS_NEGATIVE = "pis_negative"
    PIS_INVALID = "pis_invalid"


@dataclass(frozen=True, slots=True)
class FiscalReason:
    code: FiscalReasonCode
    message: str
    matched_value: str | None = None


@dataclass(frozen=True, slots=True)
class FiscalDecision:
    source_row: int
    status: FiscalStatus
    reasons: tuple[FiscalReason, ...]


@dataclass(frozen=True, slots=True)
class FiscalFilterResult:
    classified: pl.DataFrame
    eligible: pl.DataFrame
    decisions: tuple[FiscalDecision, ...]


def _evaluate_pis(value: object) -> tuple[FiscalStatus, FiscalReason]:
    if not isinstance(value, Decimal):
        return FiscalStatus.INELIGIBLE, FiscalReason(
            FiscalReasonCode.PIS_INVALID,
            "Alíquota de PIS inválida.",
        )
    if value > Decimal("0.00"):
        return FiscalStatus.ELIGIBLE, FiscalReason(
            FiscalReasonCode.PIS_POSITIVE,
            "Alíquota de PIS positiva.",
            str(value),
        )
    if value == Decimal("0.00"):
        return FiscalStatus.INELIGIBLE, FiscalReason(
            FiscalReasonCode.PIS_ZERO,
            "Alíquota de PIS igual a zero.",
            str(value),
        )
    return FiscalStatus.INELIGIBLE, FiscalReason(
        FiscalReasonCode.PIS_NEGATIVE,
        "Alíquota de PIS negativa.",
        str(value),
    )


def _validate_contract(fiscal: pl.DataFrame) -> None:
    expected = {
        "source_row": pl.Int64,
        "pis_rate": pl.Decimal(18, 2),
    }
    for column, expected_type in expected.items():
        if column not in fiscal.columns:
            raise ValueError(f'Coluna obrigatória ausente no frame fiscal: "{column}".')
        actual_type = fiscal.schema[column]
        if actual_type != expected_type:
            raise ValueError(
                f'Tipo inválido para a coluna fiscal "{column}": '
                f"esperado {expected_type}, recebido {actual_type}."
            )
    if fiscal["source_row"].null_count() > 0:
        raise ValueError('A coluna fiscal "source_row" não pode conter valores nulos.')


def classify_fiscal(fiscal: pl.DataFrame) -> FiscalFilterResult:
    _validate_contract(fiscal)
    decisions: list[FiscalDecision] = []
    for row in fiscal.iter_rows(named=True):
        status, reason = _evaluate_pis(row["pis_rate"])
        decisions.append(
            FiscalDecision(
                source_row=cast(int, row["source_row"]),
                status=status,
                reasons=(reason,),
            )
        )

    immutable_decisions = tuple(decisions)
    classified = fiscal.with_columns(
        pl.Series(
            "fiscal_status",
            [decision.status.value for decision in immutable_decisions],
            dtype=pl.String,
        ),
        pl.Series(
            "fiscal_reason_codes",
            [
                [reason.code.value for reason in decision.reasons]
                for decision in immutable_decisions
            ],
            dtype=pl.List(pl.String),
        ),
    )
    eligible = classified.filter(pl.col("fiscal_status") == FiscalStatus.ELIGIBLE.value)
    return FiscalFilterResult(
        classified=classified,
        eligible=eligible,
        decisions=immutable_decisions,
    )
