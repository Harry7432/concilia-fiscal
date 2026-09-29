from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from concilia_fiscal import (
    EnrichmentErrorCode,
    EnrichmentIssue,
    EnrichmentResult,
    FileKind,
    SelectionConfig,
    SelectionReasonCode,
    SelectionStatus,
    enrich_accounting,
    normalize_data,
    select_accounting,
    validate_file,
)
from concilia_fiscal.selection import (
    _evaluate_account_type,
    _evaluate_amount,
    _evaluate_categories,
    _evaluate_credit,
    _evaluate_enrichment,
    _evaluate_history,
    _evaluate_invalid_debit_credit,
    _evaluate_missing_debit_credit,
    _evaluate_nature,
    _normalize_categories,
)

FIXTURES = Path(__file__).parent / "fixtures"
ENRICHED_SCHEMA = pl.Schema(
    {
        "source_row": pl.Int64,
        "account_code": pl.String,
        "history": pl.String,
        "debit_credit": pl.String,
        "amount": pl.Decimal(18, 2),
        "cnpj": pl.String,
        "date": pl.Date,
        "entry_number": pl.String,
        "account_nature": pl.String,
        "account_description": pl.String,
        "account_type": pl.String,
        "account_source_row": pl.Int64,
    }
)


def _row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "source_row": 2,
        "account_code": "1001",
        "history": "SERVIÇO PRESTADO",
        "debit_credit": "D",
        "amount": Decimal("10.00"),
        "cnpj": "12345678000110",
        "date": date(2026, 1, 15),
        "entry_number": "L001",
        "account_nature": "04 - CONTAS DE RESULTADO",
        "account_description": "SERVIÇOS DE TERCEIROS",
        "account_type": "A - ANALITICA",
        "account_source_row": 2,
    }
    row.update(changes)
    return row


def _enrichment(
    rows: list[dict[str, object]],
    issues: tuple[EnrichmentIssue, ...] = (),
) -> EnrichmentResult:
    return EnrichmentResult(
        accounting=pl.DataFrame(rows, schema=ENRICHED_SCHEMA),
        is_valid=not issues,
        issues=issues,
    )


def test_history_rule_requires_a_non_empty_value() -> None:
    assert _evaluate_history("HISTÓRICO") is None
    reason = _evaluate_history(" ")
    assert reason is not None
    assert reason.code is SelectionReasonCode.MISSING_HISTORY


def test_debit_credit_required_rule_rejects_only_empty_values() -> None:
    assert _evaluate_missing_debit_credit("D") is None
    reason = _evaluate_missing_debit_credit(None)
    assert reason is not None
    assert reason.code is SelectionReasonCode.MISSING_DEBIT_CREDIT


def test_debit_credit_domain_rule_sends_unknown_values_to_review() -> None:
    assert _evaluate_invalid_debit_credit("D") is None
    assert _evaluate_invalid_debit_credit("C") is None
    assert _evaluate_invalid_debit_credit("") is None
    reason = _evaluate_invalid_debit_credit("X")
    assert reason is not None
    assert reason.code is SelectionReasonCode.INVALID_DEBIT_CREDIT
    assert reason.matched_value == "X"


def test_credit_rule_excludes_only_credit_entries() -> None:
    assert _evaluate_credit("D") is None
    reason = _evaluate_credit("C")
    assert reason is not None
    assert reason.code is SelectionReasonCode.CREDIT_ENTRY


@pytest.mark.parametrize("value", [Decimal("0.00"), Decimal("-0.00"), Decimal("-0.01")])
def test_amount_rule_excludes_zero_and_negative_values(value: Decimal) -> None:
    reason = _evaluate_amount(value)
    assert reason is not None
    assert reason.code is SelectionReasonCode.NON_POSITIVE_AMOUNT


def test_amount_rule_accepts_positive_values_and_reviews_missing_values() -> None:
    assert _evaluate_amount(Decimal("0.01")) is None
    reason = _evaluate_amount(None)
    assert reason is not None
    assert reason.code is SelectionReasonCode.INVALID_AMOUNT


def test_enrichment_rule_requires_all_account_attributes() -> None:
    assert _evaluate_enrichment(_row()) is None
    reason = _evaluate_enrichment(_row(account_description=None))
    assert reason is not None
    assert reason.code is SelectionReasonCode.ENRICHMENT_UNAVAILABLE
    assert reason.matched_value == "1001"


def test_nature_rule_uses_exact_canonical_value() -> None:
    assert _evaluate_nature("04 - CONTAS DE RESULTADO") is None
    reason = _evaluate_nature("01 - ATIVO")
    assert reason is not None
    assert reason.code is SelectionReasonCode.NON_RESULT_ACCOUNT


def test_account_type_rule_uses_exact_canonical_value() -> None:
    assert _evaluate_account_type("A - ANALITICA") is None
    reason = _evaluate_account_type("A - ANALÍTICA")
    assert reason is not None
    assert reason.code is SelectionReasonCode.NON_ANALYTICAL_ACCOUNT


def test_category_rule_matches_each_substring_in_configuration_order() -> None:
    reasons = _evaluate_categories(
        "MULTAS SOBRE MATERIAL DE ESCRITÓRIO",
        ("MATERIAL", "MULTAS"),
    )
    assert [reason.code for reason in reasons] == [
        SelectionReasonCode.EXCLUDED_CATEGORY,
        SelectionReasonCode.EXCLUDED_CATEGORY,
    ]
    assert [reason.matched_value for reason in reasons] == ["MATERIAL", "MULTAS"]


def test_normalizes_and_deduplicates_categories_without_changing_accents() -> None:
    assert _normalize_categories((" material ", "MULTAS", "material", "ação")) == (
        "MATERIAL",
        "MULTAS",
        "AÇÃO",
    )
    assert _normalize_categories(()) == ()


def test_rejects_empty_category_before_processing_rows() -> None:
    enrichment = _enrichment([_row()])

    with pytest.raises(ValueError, match="não podem ser vazias"):
        select_accounting(enrichment, SelectionConfig(("MATERIAL", " ")))


def test_records_all_reasons_in_rule_order_and_review_takes_precedence() -> None:
    enrichment = _enrichment(
        [
            _row(
                history="",
                debit_credit="X",
                amount=Decimal("0.00"),
                account_nature="01 - ATIVO",
                account_description="MULTAS E MATERIAL",
                account_type="S - SINTETICA",
            )
        ]
    )

    result = select_accounting(enrichment)

    assert not result.is_valid
    assert result.decisions[0].status is SelectionStatus.REVIEW
    assert [reason.code for reason in result.decisions[0].reasons] == [
        SelectionReasonCode.MISSING_HISTORY,
        SelectionReasonCode.INVALID_DEBIT_CREDIT,
        SelectionReasonCode.NON_POSITIVE_AMOUNT,
        SelectionReasonCode.NON_RESULT_ACCOUNT,
        SelectionReasonCode.NON_ANALYTICAL_ACCOUNT,
        SelectionReasonCode.EXCLUDED_CATEGORY,
        SelectionReasonCode.EXCLUDED_CATEGORY,
    ]
    assert result.classified["selection_reason_codes"].to_list() == [
        [
            "missing_history",
            "invalid_debit_credit",
            "non_positive_amount",
            "non_result_account",
            "non_analytical_account",
            "excluded_category",
            "excluded_category",
        ]
    ]


def test_unavailable_enrichment_skips_dependent_account_rules() -> None:
    result = select_accounting(
        _enrichment(
            [
                _row(
                    account_nature=None,
                    account_description=None,
                    account_type=None,
                    account_source_row=None,
                )
            ]
        )
    )

    assert [reason.code for reason in result.decisions[0].reasons] == [
        SelectionReasonCode.ENRICHMENT_UNAVAILABLE
    ]
    assert result.decisions[0].status is SelectionStatus.REVIEW


def test_preserves_input_lineage_order_and_enrichment_issues() -> None:
    issue = EnrichmentIssue(
        code=EnrichmentErrorCode.DUPLICATE_ACCOUNT_CODE,
        account_code="9999",
        accounting_source_rows=(),
        account_source_rows=(8, 9),
        message="Duplicidade não utilizada.",
    )
    enrichment = _enrichment(
        [
            _row(source_row=8, entry_number="L008", amount=Decimal("-1.00")),
            _row(source_row=3, entry_number="L003"),
            _row(source_row=6, entry_number="L006", debit_credit="C"),
        ],
        (issue,),
    )
    original = enrichment.accounting.clone()

    result = select_accounting(enrichment)

    assert result.is_valid
    assert result.enrichment_issues is enrichment.issues
    assert result.enrichment_issues == (issue,)
    assert result.classified["source_row"].to_list() == [8, 3, 6]
    assert result.selected["source_row"].to_list() == [3]
    assert result.selected.columns == result.classified.columns
    assert result.classified.height == enrichment.accounting.height
    assert result.classified["selection_status"].to_list() == [
        "excluded",
        "selected",
        "excluded",
    ]
    assert result.selected["selection_reason_codes"].to_list() == [[]]
    assert result.decisions[1].reasons == ()
    assert_frame_equal(enrichment.accounting, original)


def test_empty_accounting_returns_typed_empty_valid_result() -> None:
    issue = EnrichmentIssue(
        code=EnrichmentErrorCode.DUPLICATE_ACCOUNT_CODE,
        account_code="9999",
        accounting_source_rows=(),
        account_source_rows=(2, 3),
        message="Duplicidade não utilizada.",
    )

    result = select_accounting(_enrichment([], (issue,)))

    assert result.is_valid
    assert result.classified.is_empty()
    assert result.selected.is_empty()
    assert result.decisions == ()
    assert result.enrichment_issues == (issue,)
    assert result.classified.schema["selection_status"] == pl.String
    assert result.classified.schema["selection_reason_codes"] == pl.List(pl.String)


def test_baseline_fixture_selects_only_accounting_candidates() -> None:
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
    result = select_accounting(enrich_accounting(normalized))

    assert result.is_valid
    assert result.selected["entry_number"].to_list() == [
        "L001",
        "L002",
        "L003",
        "L004",
        "L011",
        "L012",
    ]
    excluded = result.classified.filter(pl.col("selection_status") == "excluded")
    assert excluded.select("entry_number", "selection_reason_codes").rows() == [
        ("L005", ["excluded_category"]),
        ("L006", ["excluded_category"]),
        ("L007", ["credit_entry"]),
        ("L008", ["non_positive_amount"]),
        ("L009", ["non_analytical_account"]),
        ("L010", ["non_result_account"]),
    ]
