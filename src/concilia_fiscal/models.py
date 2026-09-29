from dataclasses import dataclass
from enum import StrEnum

import polars as pl


class FileKind(StrEnum):
    ACCOUNTING = "accounting"
    FISCAL = "fiscal"
    ACCOUNTS = "accounts"


class ErrorCode(StrEnum):
    INVALID_FILE_EXTENSION = "invalid_file_extension"
    UNREADABLE_WORKBOOK = "unreadable_workbook"
    WORKBOOK_TOO_LARGE = "workbook_too_large"
    WORKBOOK_TOO_COMPLEX = "workbook_too_complex"
    MISSING_EXPECTED_SHEET = "missing_expected_sheet"
    DUPLICATE_COLUMN = "duplicate_column"
    MISSING_REQUIRED_COLUMN = "missing_required_column"
    MISSING_REQUIRED_VALUE = "missing_required_value"
    INVALID_VALUE_TYPE = "invalid_value_type"


@dataclass(frozen=True, slots=True)
class ValidationError:
    file_name: str
    line: int | None
    column: str | None
    code: ErrorCode
    message: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    file_name: str
    file_kind: FileKind
    is_valid: bool
    row_count: int
    recognized_columns: tuple[str, ...]
    extra_columns: tuple[str, ...]
    errors: tuple[ValidationError, ...]
    data: pl.DataFrame | None
