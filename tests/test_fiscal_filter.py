from datetime import date
from decimal import Decimal

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from concilia_fiscal import FiscalReasonCode, FiscalStatus, classify_fiscal
from concilia_fiscal.fiscal_filter import _evaluate_pis

FISCAL_SCHEMA = pl.Schema(
    {
        "source_row": pl.Int64,
        "pis_rate": pl.Decimal(18, 2),
        "document_number": pl.String,
        "amount": pl.Decimal(18, 2),
        "supplier": pl.String,
        "date": pl.Date,
    }
)


def _row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "source_row": 2,
        "pis_rate": Decimal("1.65"),
        "document_number": "12345",
        "amount": Decimal("100.00"),
        "supplier": "FORNECEDOR TESTE",
        "date": date(2026, 1, 15),
    }
    row.update(changes)
    return row


@pytest.mark.parametrize(
    ("value", "status", "code", "matched_value"),
    [
        (Decimal("1.65"), FiscalStatus.ELIGIBLE, FiscalReasonCode.PIS_POSITIVE, "1.65"),
        (Decimal("0.00"), FiscalStatus.INELIGIBLE, FiscalReasonCode.PIS_ZERO, "0.00"),
        (Decimal("-0.00"), FiscalStatus.INELIGIBLE, FiscalReasonCode.PIS_ZERO, "-0.00"),
        (Decimal("-0.01"), FiscalStatus.INELIGIBLE, FiscalReasonCode.PIS_NEGATIVE, "-0.01"),
        (None, FiscalStatus.INELIGIBLE, FiscalReasonCode.PIS_INVALID, None),
    ],
)
def test_pis_rule_returns_one_structured_reason(
    value: object,
    status: FiscalStatus,
    code: FiscalReasonCode,
    matched_value: str | None,
) -> None:
    actual_status, reason = _evaluate_pis(value)

    assert actual_status is status
    assert reason.code is code
    assert reason.matched_value == matched_value


def test_classifies_every_row_and_preserves_input_order_and_frame() -> None:
    fiscal = pl.DataFrame(
        [
            _row(source_row=8, pis_rate=Decimal("0.00")),
            _row(source_row=3, pis_rate=Decimal("1.65")),
            _row(source_row=8, pis_rate=Decimal("-0.01")),
            _row(source_row=6, pis_rate=None),
        ],
        schema=FISCAL_SCHEMA,
    )
    original = fiscal.clone()

    result = classify_fiscal(fiscal)

    assert result.classified["source_row"].to_list() == [8, 3, 8, 6]
    assert result.classified["fiscal_status"].to_list() == [
        "ineligible",
        "eligible",
        "ineligible",
        "ineligible",
    ]
    assert result.classified["fiscal_reason_codes"].to_list() == [
        ["pis_zero"],
        ["pis_positive"],
        ["pis_negative"],
        ["pis_invalid"],
    ]
    assert result.eligible["source_row"].to_list() == [3]
    assert result.eligible.columns == result.classified.columns
    assert len(result.decisions) == fiscal.height
    assert all(len(decision.reasons) == 1 for decision in result.decisions)
    assert_frame_equal(fiscal, original)


def test_preserves_extra_columns_and_is_deterministic() -> None:
    fiscal = pl.DataFrame(
        [_row()],
        schema=FISCAL_SCHEMA,
    ).with_columns(pl.lit("rastreável").alias("extra"))

    first = classify_fiscal(fiscal)
    second = classify_fiscal(fiscal)

    assert first.decisions == second.decisions
    assert first.classified["extra"].to_list() == ["rastreável"]
    assert_frame_equal(first.classified, second.classified)
    assert_frame_equal(first.eligible, second.eligible)


def test_empty_fiscal_returns_typed_empty_result() -> None:
    fiscal = pl.DataFrame([], schema=FISCAL_SCHEMA)

    result = classify_fiscal(fiscal)

    assert result.classified.is_empty()
    assert result.eligible.is_empty()
    assert result.decisions == ()
    assert result.classified.schema["fiscal_status"] == pl.String
    assert result.classified.schema["fiscal_reason_codes"] == pl.List(pl.String)


@pytest.mark.parametrize("missing", ["source_row", "pis_rate"])
def test_rejects_missing_contract_columns(missing: str) -> None:
    fiscal = pl.DataFrame([_row()], schema=FISCAL_SCHEMA).drop(missing)

    with pytest.raises(ValueError, match=f'Coluna obrigatória ausente.*"{missing}"'):
        classify_fiscal(fiscal)


@pytest.mark.parametrize(
    ("column", "data_type"),
    [("source_row", pl.Int32), ("pis_rate", pl.Float64)],
)
def test_rejects_invalid_contract_types(column: str, data_type: pl.DataType) -> None:
    fiscal = pl.DataFrame([_row()], schema=FISCAL_SCHEMA).with_columns(
        pl.col(column).cast(data_type)
    )

    with pytest.raises(ValueError, match=f'Tipo inválido.*"{column}"'):
        classify_fiscal(fiscal)


def test_rejects_null_source_row() -> None:
    fiscal = pl.DataFrame([_row(source_row=None)], schema=FISCAL_SCHEMA)

    with pytest.raises(ValueError, match='"source_row" não pode conter valores nulos'):
        classify_fiscal(fiscal)
