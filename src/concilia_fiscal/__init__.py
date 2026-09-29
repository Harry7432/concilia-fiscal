"""Public interface for Concilia Fiscal validation."""

from concilia_fiscal.excel import read_workbook
from concilia_fiscal.models import ErrorCode, FileKind, ValidationError, ValidationResult
from concilia_fiscal.normalization import (
    NormalizationError,
    NormalizationErrorCode,
    NormalizationIssue,
    NormalizedData,
    normalize_data,
)
from concilia_fiscal.validation import validate_file

__all__ = [
    "ErrorCode",
    "FileKind",
    "NormalizationError",
    "NormalizationErrorCode",
    "NormalizationIssue",
    "NormalizedData",
    "ValidationError",
    "ValidationResult",
    "normalize_data",
    "read_workbook",
    "validate_file",
]
