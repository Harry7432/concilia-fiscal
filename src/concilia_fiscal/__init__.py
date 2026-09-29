"""Public interface for Concilia Fiscal validation."""

from concilia_fiscal.excel import read_workbook
from concilia_fiscal.models import ErrorCode, FileKind, ValidationError, ValidationResult
from concilia_fiscal.validation import validate_file

__all__ = [
    "ErrorCode",
    "FileKind",
    "ValidationError",
    "ValidationResult",
    "read_workbook",
    "validate_file",
]
