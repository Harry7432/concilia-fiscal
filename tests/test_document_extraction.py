from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from concilia_fiscal import (
    DocumentExtractionReasonCode,
    DocumentExtractionStatus,
    FileKind,
    SelectionResult,
    enrich_accounting,
    extract_documents,
    normalize_data,
    select_accounting,
    validate_file,
)
from concilia_fiscal.document_extraction import _evaluate_history

FIXTURES = Path(__file__).parent / "fixtures"
SELECTED_SCHEMA = pl.Schema(
    {
        "source_row": pl.Int64,
        "history": pl.String,
        "selection_status": pl.String,
        "selection_reason_codes": pl.List(pl.String),
        "entry_number": pl.String,
    }
)


def _row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "source_row": 2,
        "history": "NF 12345",
        "selection_status": "selected",
        "selection_reason_codes": [],
        "entry_number": "L001",
    }
    row.update(changes)
    return row


def _selection(rows: list[dict[str, object]]) -> SelectionResult:
    selected = pl.DataFrame(rows, schema=SELECTED_SCHEMA)
    return SelectionResult(
        classified=selected,
        selected=selected,
        decisions=(),
        enrichment_issues=(),
        is_valid=True,
    )


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        ("NF 12345", "12345"),
        ("nf: 12345", "12345"),
        ("N.F. #12345", "12345"),
        ("NOTA 12345", "12345"),
        ("NOTA FISCAL 12345", "12345"),
        ("NF NUMERO 12345", "12345"),
        ("NF NÚMERO: 12345", "12345"),
        ("NF Nº 12345", "12345"),
        ("NF N°: 12345", "12345"),
        ("NF NO 12345", "12345"),
        ("NF N. 12345", "12345"),
        ("NF - 000123", "000123"),
    ],
)
def test_extracts_document_after_explicit_markers(history: str, expected: str) -> None:
    extracted, candidates, status, reason = _evaluate_history(history)

    assert extracted == expected
    assert candidates == (expected,)
    assert status is DocumentExtractionStatus.EXTRACTED
    assert reason.code is DocumentExtractionReasonCode.DOCUMENT_EXTRACTED
    assert reason.matched_value == expected


@pytest.mark.parametrize("history", [None, "", "   "])
def test_missing_history_is_not_found(history: object) -> None:
    extracted, candidates, status, reason = _evaluate_history(history)

    assert extracted is None
    assert candidates == ()
    assert status is DocumentExtractionStatus.NOT_FOUND
    assert reason.code is DocumentExtractionReasonCode.HISTORY_MISSING


@pytest.mark.parametrize(
    "history",
    [
        "388 - RACE AUDIO CFOP: 1407",
        "PAGAMENTO 12345",
        "VENCIMENTO 12/03/2026",
        "NFE 12345",
        "NFS-E 12345",
    ],
)
def test_numbers_without_an_accepted_marker_are_not_extracted(history: str) -> None:
    extracted, candidates, status, reason = _evaluate_history(history)

    assert extracted is None
    assert candidates == ()
    assert status is DocumentExtractionStatus.NOT_FOUND
    assert reason.code is DocumentExtractionReasonCode.DOCUMENT_MARKER_NOT_FOUND


@pytest.mark.parametrize(
    "history",
    [
        "NF SEM NUMERO",
        "NF REFERENTE A COMPRA 12345",
        "NF 12/03/2026",
        "NF 12.345",
        "NF 12-345",
    ],
)
def test_marker_without_a_safe_adjacent_number_is_not_extracted(history: str) -> None:
    extracted, candidates, status, reason = _evaluate_history(history)

    assert extracted is None
    assert candidates == ()
    assert status is DocumentExtractionStatus.NOT_FOUND
    assert reason.code is DocumentExtractionReasonCode.DOCUMENT_NUMBER_NOT_FOUND


def test_repeated_candidate_is_a_single_reliable_extraction() -> None:
    extracted, candidates, status, _ = _evaluate_history("NF 12345 E NOTA FISCAL 12345")

    assert extracted == "12345"
    assert candidates == ("12345",)
    assert status is DocumentExtractionStatus.EXTRACTED


def test_distinct_candidates_are_ambiguous_in_appearance_order() -> None:
    extracted, candidates, status, reason = _evaluate_history("NF 67890 E NF 12345 E NF 67890")

    assert extracted is None
    assert candidates == ("67890", "12345")
    assert status is DocumentExtractionStatus.AMBIGUOUS
    assert reason.code is DocumentExtractionReasonCode.MULTIPLE_DOCUMENTS
    assert reason.matched_value is None


def test_preserves_input_order_lineage_extra_columns_and_frame() -> None:
    selection = _selection(
        [
            _row(source_row=8, entry_number="L008", history="CFOP: 1407"),
            _row(source_row=3, entry_number="L003", history="NF 000123"),
            _row(source_row=8, entry_number="L009", history="NF 1 E NF 2"),
        ]
    )
    selection = SelectionResult(
        classified=selection.classified,
        selected=selection.selected.with_columns(pl.lit("rastreável").alias("extra")),
        decisions=selection.decisions,
        enrichment_issues=selection.enrichment_issues,
        is_valid=False,
    )
    original = selection.selected.clone()

    result = extract_documents(selection)
    repeated = extract_documents(selection)

    assert result.classified["source_row"].to_list() == [8, 3, 8]
    assert result.classified["document_extraction_status"].to_list() == [
        "not_found",
        "extracted",
        "ambiguous",
    ]
    assert result.classified["document_extraction_reason_codes"].to_list() == [
        ["document_marker_not_found"],
        ["document_extracted"],
        ["multiple_documents"],
    ]
    assert result.extracted["entry_number"].to_list() == ["L003"]
    assert result.extracted.columns == result.classified.columns
    assert result.classified["extra"].to_list() == ["rastreável"] * 3
    assert result.decisions == repeated.decisions
    assert_frame_equal(result.classified, repeated.classified)
    assert_frame_equal(result.extracted, repeated.extracted)
    assert_frame_equal(selection.selected, original)


def test_empty_selection_returns_typed_empty_result() -> None:
    result = extract_documents(_selection([]))

    assert result.classified.is_empty()
    assert result.extracted.is_empty()
    assert result.decisions == ()
    assert result.classified.schema["extracted_document"] == pl.String
    assert result.classified.schema["document_extraction_status"] == pl.String
    assert result.classified.schema["document_extraction_reason_codes"] == pl.List(pl.String)


@pytest.mark.parametrize(
    "missing",
    ["source_row", "history", "selection_status", "selection_reason_codes"],
)
def test_rejects_missing_contract_columns(missing: str) -> None:
    selection = _selection([_row()])
    invalid = SelectionResult(
        classified=selection.classified,
        selected=selection.selected.drop(missing),
        decisions=(),
        enrichment_issues=(),
        is_valid=True,
    )

    with pytest.raises(ValueError, match=f'Coluna obrigatória ausente.*"{missing}"'):
        extract_documents(invalid)


@pytest.mark.parametrize(
    ("column", "data_type"),
    [
        ("source_row", pl.Int32),
        ("history", pl.Categorical),
        ("selection_status", pl.Categorical),
        ("selection_reason_codes", pl.Array(pl.String, 0)),
    ],
)
def test_rejects_invalid_contract_types(column: str, data_type: pl.DataType) -> None:
    selection = _selection([_row()])
    invalid = SelectionResult(
        classified=selection.classified,
        selected=selection.selected.with_columns(pl.col(column).cast(data_type)),
        decisions=(),
        enrichment_issues=(),
        is_valid=True,
    )

    with pytest.raises(ValueError, match=f'Tipo inválido.*"{column}"'):
        extract_documents(invalid)


def test_rejects_null_source_row_and_non_selected_rows() -> None:
    null_source_row = _selection([_row(source_row=None)])
    non_selected = _selection([_row(selection_status="review")])
    null_status = _selection([_row(selection_status=None)])

    with pytest.raises(ValueError, match='"source_row" não pode conter valores nulos'):
        extract_documents(null_source_row)
    with pytest.raises(ValueError, match='selection_status igual a "selected"'):
        extract_documents(non_selected)
    with pytest.raises(ValueError, match='selection_status igual a "selected"'):
        extract_documents(null_status)


def test_baseline_fixture_extracts_only_explicit_documents() -> None:
    accounting = validate_file(
        FIXTURES / "contabil_teste.xlsx",
        file_name="contabil_teste.xlsx",
        file_kind=FileKind.ACCOUNTING,
    )
    fiscal = validate_file(
        FIXTURES / "fiscal_teste.xlsx",
        file_name="fiscal_teste.xlsx",
        file_kind=FileKind.FISCAL,
    )
    accounts = validate_file(
        FIXTURES / "plano_contas_teste.xlsx",
        file_name="plano_contas_teste.xlsx",
        file_kind=FileKind.ACCOUNTS,
    )
    normalized = normalize_data(accounting, fiscal, accounts)
    selection = select_accounting(enrich_accounting(normalized))

    result = extract_documents(selection)

    assert result.classified.select(
        "entry_number",
        "extracted_document",
        "document_extraction_status",
    ).rows() == [
        ("L001", "12345", "extracted"),
        ("L002", "23456", "extracted"),
        ("L003", "34567", "extracted"),
        ("L004", "45678", "extracted"),
        ("L011", None, "not_found"),
        ("L012", None, "not_found"),
    ]
    assert result.decisions[4].reason.code is DocumentExtractionReasonCode.DOCUMENT_MARKER_NOT_FOUND
    assert result.decisions[5].reason.code is DocumentExtractionReasonCode.DOCUMENT_NUMBER_NOT_FOUND
