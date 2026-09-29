"""Public interface for Concilia Fiscal."""

from concilia_fiscal.enrichment import (
    EnrichmentErrorCode,
    EnrichmentIssue,
    EnrichmentResult,
    enrich_accounting,
)
from concilia_fiscal.excel import read_workbook
from concilia_fiscal.fiscal_filter import (
    FiscalDecision,
    FiscalFilterResult,
    FiscalReason,
    FiscalReasonCode,
    FiscalStatus,
    classify_fiscal,
)
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
    "FiscalDecision",
    "FiscalFilterResult",
    "FiscalReason",
    "FiscalReasonCode",
    "FiscalStatus",
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
    "classify_fiscal",
    "enrich_accounting",
    "normalize_data",
    "read_workbook",
    "select_accounting",
    "validate_file",
]
