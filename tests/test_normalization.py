from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from concilia_fiscal import (
    FileKind,
    NormalizationError,
    NormalizationErrorCode,
    ValidationResult,
    normalize_data,
    validate_file,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _validated_fixture(file_name: str, file_kind: FileKind):
    return validate_file(
        FIXTURES / file_name,
        file_name=file_name,
        file_kind=file_kind,
    )


def _validation_result(file_kind: FileKind, data: pl.DataFrame) -> ValidationResult:
    return ValidationResult(
        file_name=f"{file_kind}.xlsx",
        file_kind=file_kind,
        is_valid=True,
        row_count=data.height,
        recognized_columns=tuple(data.columns),
        extra_columns=(),
        errors=(),
        data=data,
    )


def _accounting_data(*rows: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame(rows)


def _fiscal_data(
    *,
    document_number: str = "000123",
    pis_rate: object = "1,65",
    amount: object = "10,50",
    date_value: str = "2026-01-15",
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "Alíquota PIS": [pis_rate],
            "Número Documento": [document_number],
            "Vlr Documento": [amount],
            "Fornecedor": ["  fornecedor\táguia  "],
            "Data Fiscal": [date_value],
        }
    )


def _accounts_data(account_code: str = " 01.001 ") -> pl.DataFrame:
    return pl.DataFrame(
        {
            "Conta": [account_code],
            "Natureza Conta": ["  contas\n de resultado "],
            "Descrição Conta Societária": [" prestação  de serviços "],
            "Tipo Conta": [" analítica "],
        }
    )


def test_normalizes_validated_fixtures_without_mutating_raw_data() -> None:
    accounting = _validated_fixture("contabil_teste.xlsx", FileKind.ACCOUNTING)
    fiscal = _validated_fixture("fiscal_teste.xlsx", FileKind.FISCAL)
    accounts = _validated_fixture("plano_contas_teste.xlsx", FileKind.ACCOUNTS)
    assert accounting.data is not None
    assert fiscal.data is not None
    assert accounts.data is not None
    raw_frames = (
        accounting.data.clone(),
        fiscal.data.clone(),
        accounts.data.clone(),
    )

    normalized = normalize_data(accounting, fiscal, accounts)

    assert normalized.accounting.schema == pl.Schema(
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
    assert normalized.fiscal.schema == pl.Schema(
        {
            "source_row": pl.Int64,
            "pis_rate": pl.Decimal(18, 2),
            "document_number": pl.String,
            "amount": pl.Decimal(18, 2),
            "supplier": pl.String,
            "date": pl.Date,
        }
    )
    assert normalized.accounts.schema == pl.Schema(
        {
            "source_row": pl.Int64,
            "account_code": pl.String,
            "account_nature": pl.String,
            "account_description": pl.String,
            "account_type": pl.String,
        }
    )
    assert normalized.accounting.row(0, named=True) == {
        "source_row": 2,
        "account_code": "1001",
        "history": "COMPRA CONFORME NF NUMERO 12345 - FORNECEDOR ALFA",
        "debit_credit": "D",
        "amount": Decimal("1000.00"),
        "cnpj": "12345678000110",
        "date": date(2026, 1, 15),
        "entry_number": "L001",
    }
    assert normalized.fiscal.row(0, named=True) == {
        "source_row": 2,
        "pis_rate": Decimal("1.65"),
        "document_number": "12345",
        "amount": Decimal("1000.00"),
        "supplier": "FORNECEDOR ALFA",
        "date": date(2026, 1, 15),
    }
    assert normalized.accounts.row(0, named=True)["account_description"] == (
        "SERVICOS DE TERCEIROS"
    )
    assert_frame_equal(accounting.data, raw_frames[0])
    assert_frame_equal(fiscal.data, raw_frames[1])
    assert_frame_equal(accounts.data, raw_frames[2])


def test_normalizes_text_identifiers_and_source_rows_without_extra_columns() -> None:
    accounting_data = _accounting_data(
        {
            "Código": " 001.02 ",
            "Histórico": "  ac\u0327a\u0303o\t fiscal\nurgente ",
            "D/C": " d ",
            "Vlr Saldo Final": "10,50",
            "CNPJ": "12.345.678/0001-10",
            "Data": "2026-01-15",
            "Número Lançamento": " ab-01 ",
            "Observação": "não normalizar",
        },
        {
            "Código": None,
            "Histórico": None,
            "D/C": None,
            "Vlr Saldo Final": None,
            "CNPJ": None,
            "Data": None,
            "Número Lançamento": None,
            "Observação": None,
        },
        {
            "Código": "0002",
            "Histórico": " serviço ",
            "D/C": "c",
            "Vlr Saldo Final": 2,
            "CNPJ": "12345678000110",
            "Data": "2026-01-16",
            "Número Lançamento": "l002",
            "Observação": "descartar",
        },
    )

    normalized = normalize_data(
        _validation_result(FileKind.ACCOUNTING, accounting_data),
        _validation_result(FileKind.FISCAL, _fiscal_data()),
        _validation_result(FileKind.ACCOUNTS, _accounts_data()),
    )

    assert normalized.accounting["source_row"].to_list() == [2, 4]
    assert normalized.accounting["history"].to_list() == ["AÇÃO FISCAL URGENTE", "SERVIÇO"]
    assert normalized.accounting["account_code"].to_list() == ["001.02", "0002"]
    assert normalized.accounting["entry_number"].to_list() == ["AB-01", "L002"]
    assert normalized.accounting["cnpj"].to_list() == [
        "12345678000110",
        "12345678000110",
    ]
    assert "Observação" not in normalized.accounting.columns
    assert normalized.fiscal.row(0, named=True) == {
        "source_row": 2,
        "pis_rate": Decimal("1.65"),
        "document_number": "000123",
        "amount": Decimal("10.50"),
        "supplier": "FORNECEDOR ÁGUIA",
        "date": date(2026, 1, 15),
    }
    assert normalized.accounts.row(0, named=True) == {
        "source_row": 2,
        "account_code": "01.001",
        "account_nature": "CONTAS DE RESULTADO",
        "account_description": "PRESTAÇÃO DE SERVIÇOS",
        "account_type": "ANALÍTICA",
    }


def test_accumulates_ambiguous_identifier_errors_across_all_sources() -> None:
    accounting_data = _accounting_data(
        {
            "Código": "10 01",
            "Histórico": "histórico",
            "D/C": "D",
            "Vlr Saldo Final": 10,
            "CNPJ": "12.345.678/0001 10",
            "Data": "2026-01-15",
            "Número Lançamento": "L 001",
        }
    )

    with pytest.raises(NormalizationError) as caught:
        normalize_data(
            _validation_result(FileKind.ACCOUNTING, accounting_data),
            _validation_result(
                FileKind.FISCAL,
                _fiscal_data(document_number="12-3"),
            ),
            _validation_result(FileKind.ACCOUNTS, _accounts_data("10 02")),
        )

    assert [
        (error.file_kind, error.source_row, error.column, error.code)
        for error in caught.value.errors
    ] == [
        (FileKind.ACCOUNTING, 2, "Código", NormalizationErrorCode.INVALID_ACCOUNT_CODE),
        (FileKind.ACCOUNTING, 2, "CNPJ", NormalizationErrorCode.INVALID_CNPJ),
        (
            FileKind.ACCOUNTING,
            2,
            "Número Lançamento",
            NormalizationErrorCode.INVALID_ENTRY_NUMBER,
        ),
        (
            FileKind.FISCAL,
            2,
            "Número Documento",
            NormalizationErrorCode.INVALID_DOCUMENT_NUMBER,
        ),
        (FileKind.ACCOUNTS, 2, "Conta", NormalizationErrorCode.INVALID_ACCOUNT_CODE),
    ]


def test_rejects_invalid_and_misplaced_validation_results() -> None:
    accounting = _validated_fixture("contabil_teste.xlsx", FileKind.ACCOUNTING)
    fiscal = _validated_fixture("fiscal_teste.xlsx", FileKind.FISCAL)
    accounts = _validated_fixture("plano_contas_teste.xlsx", FileKind.ACCOUNTS)

    with pytest.raises(NormalizationError) as caught:
        normalize_data(
            replace(accounting, is_valid=False),
            replace(fiscal, file_kind=FileKind.ACCOUNTING),
            replace(accounts, is_valid=False, data=None),
        )

    assert [error.code for error in caught.value.errors] == [
        NormalizationErrorCode.INVALID_NORMALIZATION_INPUT,
        NormalizationErrorCode.INVALID_NORMALIZATION_INPUT,
        NormalizationErrorCode.INVALID_NORMALIZATION_INPUT,
    ]
    assert all(error.source_row is None for error in caught.value.errors)


def test_reports_values_that_contradict_prior_validation() -> None:
    with pytest.raises(NormalizationError) as caught:
        normalize_data(
            _validated_fixture("contabil_teste.xlsx", FileKind.ACCOUNTING),
            _validation_result(
                FileKind.FISCAL,
                _fiscal_data(pis_rate="1e2", date_value="2026-W01-1"),
            ),
            _validated_fixture("plano_contas_teste.xlsx", FileKind.ACCOUNTS),
        )

    assert [(error.source_row, error.column, error.code) for error in caught.value.errors] == [
        (2, "Alíquota PIS", NormalizationErrorCode.NORMALIZATION_FAILED),
        (2, "Data Fiscal", NormalizationErrorCode.NORMALIZATION_FAILED),
    ]


def test_accumulates_values_that_exceed_decimal_precision() -> None:
    accounting_data = _accounting_data(
        {
            "Código": "1001",
            "Histórico": "histórico",
            "D/C": "D",
            "Vlr Saldo Final": "10000000000000000.00",
            "CNPJ": "12345678000110",
            "Data": "2026-01-15",
            "Número Lançamento": "L001",
        }
    )

    with pytest.raises(NormalizationError) as caught:
        normalize_data(
            _validation_result(FileKind.ACCOUNTING, accounting_data),
            _validation_result(
                FileKind.FISCAL,
                _fiscal_data(amount="10000000000000000.00"),
            ),
            _validation_result(FileKind.ACCOUNTS, _accounts_data()),
        )

    assert [(error.file_kind, error.column, error.code) for error in caught.value.errors] == [
        (
            FileKind.ACCOUNTING,
            "Vlr Saldo Final",
            NormalizationErrorCode.NORMALIZATION_FAILED,
        ),
        (
            FileKind.FISCAL,
            "Vlr Documento",
            NormalizationErrorCode.NORMALIZATION_FAILED,
        ),
    ]


def test_reports_missing_normalization_input() -> None:
    with pytest.raises(NormalizationError) as caught:
        normalize_data(
            None,
            _validated_fixture("fiscal_teste.xlsx", FileKind.FISCAL),
            _validated_fixture("plano_contas_teste.xlsx", FileKind.ACCOUNTS),
        )

    assert len(caught.value.errors) == 1
    assert caught.value.errors[0].file_kind is FileKind.ACCOUNTING
    assert caught.value.errors[0].source_row is None
    assert caught.value.errors[0].code is NormalizationErrorCode.INVALID_NORMALIZATION_INPUT
