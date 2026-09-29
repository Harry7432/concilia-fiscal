import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import cast

import polars as pl

from concilia_fiscal.models import FileKind, ValidationResult
from concilia_fiscal.values import parse_decimal, parse_iso_date

type Transformer = Callable[[object], object]

WHITESPACE_PATTERN = re.compile(r"\s+")
INTERNAL_WHITESPACE_PATTERN = re.compile(r"\s")
DIGITS_PATTERN = re.compile(r"[0-9]+")
MASKED_CNPJ_PATTERN = re.compile(r"[0-9]{2}\.[0-9]{3}\.[0-9]{3}/[0-9]{4}-[0-9]{2}")
DECIMAL_QUANTUM = Decimal("0.01")
MAX_DECIMAL_INTEGER_DIGITS = 16


class NormalizationErrorCode(StrEnum):
    INVALID_NORMALIZATION_INPUT = "invalid_normalization_input"
    INVALID_ACCOUNT_CODE = "invalid_account_code"
    INVALID_DOCUMENT_NUMBER = "invalid_document_number"
    INVALID_CNPJ = "invalid_cnpj"
    INVALID_ENTRY_NUMBER = "invalid_entry_number"
    NORMALIZATION_FAILED = "normalization_failed"


@dataclass(frozen=True, slots=True)
class NormalizationIssue:
    file_kind: FileKind
    source_row: int | None
    column: str | None
    code: NormalizationErrorCode
    message: str


class NormalizationError(Exception):
    def __init__(self, errors: tuple[NormalizationIssue, ...]) -> None:
        self.errors = errors
        super().__init__(f"A normalização falhou com {len(errors)} erro(s).")


@dataclass(frozen=True, slots=True)
class NormalizedData:
    accounting: pl.DataFrame
    fiscal: pl.DataFrame
    accounts: pl.DataFrame


@dataclass(frozen=True, slots=True)
class FieldRule:
    source: str
    target: str
    dtype: pl.DataType | type[pl.DataType]
    transform: Transformer
    error_code: NormalizationErrorCode = NormalizationErrorCode.NORMALIZATION_FAILED


def _normalize_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError
    normalized = unicodedata.normalize("NFC", value)
    return WHITESPACE_PATTERN.sub(" ", normalized).strip().upper()


def _normalize_identifier(value: object) -> str:
    normalized = _normalize_text(value)
    if INTERNAL_WHITESPACE_PATTERN.search(normalized):
        raise ValueError
    return normalized


def _normalize_document_number(value: object) -> str:
    normalized = _normalize_identifier(value)
    if DIGITS_PATTERN.fullmatch(normalized) is None:
        raise ValueError
    return normalized


def _normalize_cnpj(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError
    normalized = value.strip()
    if DIGITS_PATTERN.fullmatch(normalized) is not None and len(normalized) == 14:
        return normalized
    if MASKED_CNPJ_PATTERN.fullmatch(normalized) is not None:
        return normalized.translate(str.maketrans("", "", "./-"))
    raise ValueError


def _normalize_decimal(value: object) -> Decimal:
    decimal = parse_decimal(value)
    try:
        normalized = decimal.quantize(DECIMAL_QUANTUM)
    except InvalidOperation as error:
        raise ValueError from error
    integer_digits = max(normalized.adjusted() + 1, 0)
    if integer_digits > MAX_DECIMAL_INTEGER_DIGITS:
        raise ValueError
    return normalized


ACCOUNTING_RULES = (
    FieldRule(
        "Código",
        "account_code",
        pl.String,
        _normalize_identifier,
        NormalizationErrorCode.INVALID_ACCOUNT_CODE,
    ),
    FieldRule("Histórico", "history", pl.String, _normalize_text),
    FieldRule("D/C", "debit_credit", pl.String, _normalize_text),
    FieldRule("Vlr Saldo Final", "amount", pl.Decimal(18, 2), _normalize_decimal),
    FieldRule("CNPJ", "cnpj", pl.String, _normalize_cnpj, NormalizationErrorCode.INVALID_CNPJ),
    FieldRule("Data", "date", pl.Date, parse_iso_date),
    FieldRule(
        "Número Lançamento",
        "entry_number",
        pl.String,
        _normalize_identifier,
        NormalizationErrorCode.INVALID_ENTRY_NUMBER,
    ),
)

FISCAL_RULES = (
    FieldRule("Alíquota PIS", "pis_rate", pl.Decimal(18, 2), _normalize_decimal),
    FieldRule(
        "Número Documento",
        "document_number",
        pl.String,
        _normalize_document_number,
        NormalizationErrorCode.INVALID_DOCUMENT_NUMBER,
    ),
    FieldRule("Vlr Documento", "amount", pl.Decimal(18, 2), _normalize_decimal),
    FieldRule("Fornecedor", "supplier", pl.String, _normalize_text),
    FieldRule("Data Fiscal", "date", pl.Date, parse_iso_date),
)

ACCOUNTS_RULES = (
    FieldRule(
        "Conta",
        "account_code",
        pl.String,
        _normalize_identifier,
        NormalizationErrorCode.INVALID_ACCOUNT_CODE,
    ),
    FieldRule("Natureza Conta", "account_nature", pl.String, _normalize_text),
    FieldRule("Descrição Conta Societária", "account_description", pl.String, _normalize_text),
    FieldRule("Tipo Conta", "account_type", pl.String, _normalize_text),
)


def _is_meaningful_row(row: dict[str, object]) -> bool:
    return any(
        value is not None and (not isinstance(value, str) or value.strip())
        for value in row.values()
    )


def _error_message(code: NormalizationErrorCode, column: str) -> str:
    messages = {
        NormalizationErrorCode.INVALID_ACCOUNT_CODE: (
            f'O código de conta em "{column}" é ambíguo.'
        ),
        NormalizationErrorCode.INVALID_DOCUMENT_NUMBER: (
            f'O número de documento em "{column}" deve conter somente dígitos.'
        ),
        NormalizationErrorCode.INVALID_CNPJ: (f'O CNPJ em "{column}" possui formato inválido.'),
        NormalizationErrorCode.INVALID_ENTRY_NUMBER: (
            f'O número de lançamento em "{column}" contém espaços internos.'
        ),
        NormalizationErrorCode.NORMALIZATION_FAILED: (
            f'Não foi possível normalizar o valor de "{column}".'
        ),
    }
    return messages[code]


def _normalize_frame(
    result: ValidationResult,
    rules: tuple[FieldRule, ...],
    errors: list[NormalizationIssue],
) -> pl.DataFrame:
    schema_fields: dict[str, pl.DataType | type[pl.DataType]] = {"source_row": pl.Int64}
    schema_fields.update({rule.target: rule.dtype for rule in rules})
    schema = pl.Schema(schema_fields)
    if result.data is None:
        return pl.DataFrame(schema=schema)

    missing_columns = [rule.source for rule in rules if rule.source not in result.data.columns]
    for column in missing_columns:
        errors.append(
            NormalizationIssue(
                result.file_kind,
                None,
                column,
                NormalizationErrorCode.NORMALIZATION_FAILED,
                f'A coluna validada "{column}" não está disponível para normalização.',
            )
        )
    if missing_columns:
        return pl.DataFrame(schema=schema)

    normalized_rows: list[dict[str, object]] = []
    for source_row, row in enumerate(result.data.iter_rows(named=True), start=2):
        if not _is_meaningful_row(row):
            continue
        normalized_row: dict[str, object] = {"source_row": source_row}
        row_has_error = False
        for rule in rules:
            try:
                normalized_row[rule.target] = rule.transform(row[rule.source])
            except (TypeError, ValueError):
                row_has_error = True
                errors.append(
                    NormalizationIssue(
                        result.file_kind,
                        source_row,
                        rule.source,
                        rule.error_code,
                        _error_message(rule.error_code, rule.source),
                    )
                )
        if not row_has_error:
            normalized_rows.append(normalized_row)

    return pl.DataFrame(normalized_rows, schema=schema)


def _validate_inputs(
    inputs: tuple[tuple[str, ValidationResult | None, FileKind], ...],
) -> list[NormalizationIssue]:
    errors: list[NormalizationIssue] = []
    for argument, result, expected_kind in inputs:
        if result is None:
            errors.append(
                NormalizationIssue(
                    expected_kind,
                    None,
                    None,
                    NormalizationErrorCode.INVALID_NORMALIZATION_INPUT,
                    f'O argumento "{argument}" precisa conter uma validação válida.',
                )
            )
            continue
        if result.file_kind is not expected_kind:
            errors.append(
                NormalizationIssue(
                    expected_kind,
                    None,
                    None,
                    NormalizationErrorCode.INVALID_NORMALIZATION_INPUT,
                    f'O argumento "{argument}" recebeu o tipo de arquivo incorreto.',
                )
            )
        if not result.is_valid or result.data is None:
            errors.append(
                NormalizationIssue(
                    expected_kind,
                    None,
                    None,
                    NormalizationErrorCode.INVALID_NORMALIZATION_INPUT,
                    f'O argumento "{argument}" precisa conter uma validação válida.',
                )
            )
    return errors


def normalize_data(
    accounting: ValidationResult | None,
    fiscal: ValidationResult | None,
    accounts: ValidationResult | None,
) -> NormalizedData:
    inputs = (
        ("accounting", accounting, FileKind.ACCOUNTING),
        ("fiscal", fiscal, FileKind.FISCAL),
        ("accounts", accounts, FileKind.ACCOUNTS),
    )
    errors = _validate_inputs(inputs)
    if errors:
        raise NormalizationError(tuple(errors))

    accounting_result = cast(ValidationResult, accounting)
    fiscal_result = cast(ValidationResult, fiscal)
    accounts_result = cast(ValidationResult, accounts)

    normalized = NormalizedData(
        accounting=_normalize_frame(accounting_result, ACCOUNTING_RULES, errors),
        fiscal=_normalize_frame(fiscal_result, FISCAL_RULES, errors),
        accounts=_normalize_frame(accounts_result, ACCOUNTS_RULES, errors),
    )
    if errors:
        raise NormalizationError(tuple(errors))
    return normalized
