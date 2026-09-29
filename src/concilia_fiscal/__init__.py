"""Public interface for Concilia Fiscal."""

from concilia_fiscal.enrichment import (
    EnrichmentErrorCode,
    EnrichmentIssue,
    EnrichmentResult,
    enrich_accounting,
)
from concilia_fiscal.excel import read_workbook
from concilia_fiscal.models import ErrorCode, FileKind, ValidationError, ValidationResult
from concilia_fiscal.normalization import (
    NormalizationError,
    NormalizationErrorCode,
    NormalizationIssue,
    NormalizedData,
    normalize_data,
)
from concilia_fiscal.selection import (
    SelectionConfig,
    SelectionDecision,
    SelectionReason,
    SelectionReasonCode,
    SelectionResult,
    SelectionStatus,
    select_accounting,
)
from concilia_fiscal.validation import validate_file

__all__ = [
    "ErrorCode",
    "EnrichmentErrorCode",
    "EnrichmentIssue",
    "EnrichmentResult",
    "FileKind",
    "NormalizationError",
    "NormalizationErrorCode",
    "NormalizationIssue",
    "NormalizedData",
    "SelectionConfig",
    "SelectionDecision",
    "SelectionReason",
    "SelectionReasonCode",
    "SelectionResult",
    "SelectionStatus",
    "ValidationError",
    "ValidationResult",
    "enrich_accounting",
    "normalize_data",
    "read_workbook",
    "select_accounting",
    "validate_file",
]
