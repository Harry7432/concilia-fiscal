from datetime import date
from decimal import Decimal

import polars as pl
from polars.testing import assert_frame_equal

from concilia_fiscal import (
    EnrichmentErrorCode,
    NormalizedData,
    enrich_accounting,
)

ACCOUNTING_SCHEMA = pl.Schema(
    {
        "source_row": pl.Int64,
        "account_code": pl.String,
        "history": pl.String,
        "debit_credit": pl.String,
        "amount": pl.Decimal(18, 2),
        "cnpj": pl.String,
        "date": pl.Date,
        "entry_number": pl.String,
    }
)
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
ACCOUNTS_SCHEMA = pl.Schema(
    {
        "source_row": pl.Int64,
        "account_code": pl.String,
        "account_nature": pl.String,
        "account_description": pl.String,
        "account_type": pl.String,
    }
)


def _normalized_data(
    accounting: list[tuple[int, str]],
    accounts: list[tuple[int, str, str, str, str]],
) -> NormalizedData:
    accounting_rows = [
        {
            "source_row": source_row,
            "account_code": account_code,
            "history": f"LANÇAMENTO {source_row}",
            "debit_credit": "D",
            "amount": Decimal("10.00"),
            "cnpj": "12345678000110",
            "date": date(2026, 1, 15),
            "entry_number": f"L{source_row}",
        }
        for source_row, account_code in accounting
    ]
    account_rows = [
        {
            "source_row": source_row,
            "account_code": account_code,
            "account_nature": nature,
            "account_description": description,
            "account_type": account_type,
        }
        for source_row, account_code, nature, description, account_type in accounts
    ]
    return NormalizedData(
        accounting=pl.DataFrame(accounting_rows, schema=ACCOUNTING_SCHEMA),
        fiscal=pl.DataFrame(schema=FISCAL_SCHEMA),
        accounts=pl.DataFrame(account_rows, schema=ACCOUNTS_SCHEMA),
    )


def test_enriches_without_changing_cardinality_order_or_inputs() -> None:
    data = _normalized_data(
        accounting=[(7, "002"), (3, "001"), (9, "002")],
        accounts=[
            (20, "001", "RESULTADO", "SERVIÇOS", "ANALÍTICA"),
            (21, "002", "ATIVO", "MÁQUINAS", "SINTÉTICA"),
        ],
    )
    originals = (data.accounting.clone(), data.fiscal.clone(), data.accounts.clone())

    result = enrich_accounting(data)

    assert result.is_valid
    assert result.issues == ()
    assert result.accounting is not data.accounting
    assert result.accounting["source_row"].to_list() == [7, 3, 9]
    assert result.accounting["account_nature"].to_list() == ["ATIVO", "RESULTADO", "ATIVO"]
    assert result.accounting["account_description"].to_list() == [
        "MÁQUINAS",
        "SERVIÇOS",
        "MÁQUINAS",
    ]
    assert result.accounting["account_type"].to_list() == [
        "SINTÉTICA",
        "ANALÍTICA",
        "SINTÉTICA",
    ]
    assert result.accounting["account_source_row"].to_list() == [21, 20, 21]
    assert result.accounting.columns[-4:] == [
        "account_nature",
        "account_description",
        "account_type",
        "account_source_row",
    ]
    assert_frame_equal(data.accounting, originals[0])
    assert_frame_equal(data.fiscal, originals[1])
    assert_frame_equal(data.accounts, originals[2])


def test_groups_missing_accounts_and_preserves_affected_rows_with_nulls() -> None:
    data = _normalized_data(
        accounting=[(8, "999"), (2, "001"), (5, "999")],
        accounts=[(10, "001", "RESULTADO", "SERVIÇOS", "ANALÍTICA")],
    )

    result = enrich_accounting(data)

    assert not result.is_valid
    assert len(result.accounting) == len(data.accounting)
    assert result.accounting["account_description"].to_list() == [None, "SERVIÇOS", None]
    assert result.accounting["account_source_row"].to_list() == [None, 10, None]
    assert len(result.issues) == 1
    assert result.issues[0].code is EnrichmentErrorCode.ACCOUNT_NOT_FOUND
    assert result.issues[0].account_code == "999"
    assert result.issues[0].accounting_source_rows == (5, 8)
    assert result.issues[0].account_source_rows == ()


def test_reports_all_duplicates_before_missing_accounts_without_multiplying_rows() -> None:
    data = _normalized_data(
        accounting=[(9, "B"), (3, "C"), (4, "B")],
        accounts=[
            (8, "B", "RESULTADO", "SERVIÇOS", "ANALÍTICA"),
            (2, "A", "ATIVO", "CAIXA", "ANALÍTICA"),
            (6, "B", "ATIVO", "SERVIÇOS", "ANALÍTICA"),
            (5, "A", "ATIVO", "CAIXA", "ANALÍTICA"),
        ],
    )

    result = enrich_accounting(data)

    assert not result.is_valid
    assert len(result.accounting) == 3
    assert result.accounting["account_nature"].to_list() == [None, None, None]
    assert [issue.code for issue in result.issues] == [
        EnrichmentErrorCode.DUPLICATE_ACCOUNT_CODE,
        EnrichmentErrorCode.DUPLICATE_ACCOUNT_CODE,
        EnrichmentErrorCode.ACCOUNT_NOT_FOUND,
    ]
    assert [issue.account_code for issue in result.issues] == ["A", "B", "C"]
    assert result.issues[0].accounting_source_rows == ()
    assert result.issues[0].account_source_rows == (2, 5)
    assert result.issues[1].accounting_source_rows == (4, 9)
    assert result.issues[1].account_source_rows == (6, 8)
    assert result.issues[2].accounting_source_rows == (3,)


def test_empty_accounting_is_valid_and_keeps_typed_enrichment_columns() -> None:
    data = _normalized_data(
        accounting=[],
        accounts=[(2, "001", "RESULTADO", "SERVIÇOS", "ANALÍTICA")],
    )

    result = enrich_accounting(data)

    assert result.is_valid
    assert result.accounting.is_empty()
    assert result.accounting.schema["account_nature"] == pl.String
    assert result.accounting.schema["account_description"] == pl.String
    assert result.accounting.schema["account_type"] == pl.String
    assert result.accounting.schema["account_source_row"] == pl.Int64


def test_empty_accounts_reports_each_missing_code_in_code_order() -> None:
    data = _normalized_data(accounting=[(2, "002"), (3, "001")], accounts=[])

    result = enrich_accounting(data)

    assert not result.is_valid
    assert [issue.account_code for issue in result.issues] == ["001", "002"]
    assert result.accounting["account_source_row"].to_list() == [None, None]
