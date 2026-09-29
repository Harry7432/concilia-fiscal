import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import cast

from concilia_fiscal.contracts import CONTRACTS, ValueKind
from concilia_fiscal.excel import (
    DuplicateColumnError,
    ExcelSource,
    MissingExpectedSheetError,
    UnreadableWorkbookError,
    WorkbookTooComplexError,
    WorkbookTooLargeError,
    read_workbook,
)
from concilia_fiscal.models import ErrorCode, FileKind, ValidationError, ValidationResult

ISO_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
DECIMAL_PATTERN = re.compile(r"[+-]?\d+(?:[.,]\d{1,2})?")


def _is_valid_value(value: object, value_kind: ValueKind) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if value_kind is ValueKind.TEXT:
        return isinstance(value, str) and bool(value.strip())
    if value_kind is ValueKind.DATE:
        if not isinstance(value, str) or ISO_DATE_PATTERN.fullmatch(value) is None:
            return False
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True

    decimal_text = str(value).strip()
    if DECIMAL_PATTERN.fullmatch(decimal_text) is None:
        return False
    try:
        decimal = Decimal(decimal_text.replace(",", "."))
    except (InvalidOperation, ValueError):
        return False
    return decimal.is_finite() and cast(int, decimal.as_tuple().exponent) >= -2


def validate_file(
    source: ExcelSource,
    *,
    file_name: str,
    file_kind: FileKind,
) -> ValidationResult:
    contract = CONTRACTS[file_kind]
    errors: list[ValidationError] = []

    if not file_name.lower().endswith(".xlsx"):
        errors.append(
            ValidationError(
                file_name,
                None,
                None,
                ErrorCode.INVALID_FILE_EXTENSION,
                "O arquivo deve estar no formato .xlsx.",
            )
        )
        return ValidationResult(file_name, file_kind, False, 0, (), (), tuple(errors), None)

    try:
        data = read_workbook(source, contract.sheet_name)
    except MissingExpectedSheetError:
        errors.append(
            ValidationError(
                file_name,
                None,
                None,
                ErrorCode.MISSING_EXPECTED_SHEET,
                f'A aba esperada "{contract.sheet_name}" não foi encontrada.',
            )
        )
        return ValidationResult(file_name, file_kind, False, 0, (), (), tuple(errors), None)
    except DuplicateColumnError as error:
        errors.append(
            ValidationError(
                file_name,
                1,
                error.column,
                ErrorCode.DUPLICATE_COLUMN,
                f'A coluna "{error.column}" aparece mais de uma vez.',
            )
        )
        return ValidationResult(file_name, file_kind, False, 0, (), (), tuple(errors), None)
    except WorkbookTooLargeError:
        errors.append(
            ValidationError(
                file_name,
                None,
                None,
                ErrorCode.WORKBOOK_TOO_LARGE,
                "A planilha excede o limite seguro de tamanho.",
            )
        )
        return ValidationResult(file_name, file_kind, False, 0, (), (), tuple(errors), None)
    except WorkbookTooComplexError:
        errors.append(
            ValidationError(
                file_name,
                None,
                None,
                ErrorCode.WORKBOOK_TOO_COMPLEX,
                "A planilha possui uma estrutura interna excessivamente complexa.",
            )
        )
        return ValidationResult(file_name, file_kind, False, 0, (), (), tuple(errors), None)
    except UnreadableWorkbookError:
        errors.append(
            ValidationError(
                file_name,
                None,
                None,
                ErrorCode.UNREADABLE_WORKBOOK,
                "Não foi possível ler a planilha.",
            )
        )
        return ValidationResult(file_name, file_kind, False, 0, (), (), tuple(errors), None)

    expected_names = tuple(column.name for column in contract.columns)
    recognized = tuple(name for name in expected_names if name in data.columns)
    extra = tuple(name for name in data.columns if name not in expected_names)

    for name in expected_names:
        if name not in data.columns:
            errors.append(
                ValidationError(
                    file_name,
                    1,
                    name,
                    ErrorCode.MISSING_REQUIRED_COLUMN,
                    f'A coluna obrigatória "{name}" não foi encontrada.',
                )
            )

    meaningful_rows = []
    for row_index, row in enumerate(data.iter_rows(named=True), start=2):
        if not any(
            value is not None and (not isinstance(value, str) or value.strip())
            for value in row.values()
        ):
            continue
        meaningful_rows.append((row_index, row))

    for row_index, row in meaningful_rows:
        for column in contract.columns:
            if column.name not in data.columns:
                continue
            value = row[column.name]
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(
                    ValidationError(
                        file_name,
                        row_index,
                        column.name,
                        ErrorCode.MISSING_REQUIRED_VALUE,
                        f'A coluna obrigatória "{column.name}" está vazia.',
                    )
                )
            elif not _is_valid_value(value, column.value_kind):
                errors.append(
                    ValidationError(
                        file_name,
                        row_index,
                        column.name,
                        ErrorCode.INVALID_VALUE_TYPE,
                        f'O valor da coluna "{column.name}" possui tipo ou formato inválido.',
                    )
                )

    return ValidationResult(
        file_name=file_name,
        file_kind=file_kind,
        is_valid=not errors,
        row_count=len(meaningful_rows),
        recognized_columns=recognized,
        extra_columns=extra,
        errors=tuple(errors),
        data=data,
    )
