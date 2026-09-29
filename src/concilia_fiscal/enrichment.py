from dataclasses import dataclass
from enum import StrEnum
from typing import cast

import polars as pl

from concilia_fiscal.normalization import NormalizedData


class EnrichmentErrorCode(StrEnum):
    ACCOUNT_NOT_FOUND = "account_not_found"
    DUPLICATE_ACCOUNT_CODE = "duplicate_account_code"


@dataclass(frozen=True, slots=True)
class EnrichmentIssue:
    code: EnrichmentErrorCode
    account_code: str
    accounting_source_rows: tuple[int, ...]
    account_source_rows: tuple[int, ...]
    message: str


@dataclass(frozen=True, slots=True)
class EnrichmentResult:
    accounting: pl.DataFrame
    is_valid: bool
    issues: tuple[EnrichmentIssue, ...]


type AccountAttributes = tuple[int, str, str, str]


def enrich_accounting(data: NormalizedData) -> EnrichmentResult:
    accounts_by_code: dict[str, list[AccountAttributes]] = {}
    for row in data.accounts.select(
        "account_code",
        "source_row",
        "account_nature",
        "account_description",
        "account_type",
    ).iter_rows():
        account_code = cast(str, row[0])
        accounts_by_code.setdefault(account_code, []).append(
            (
                cast(int, row[1]),
                cast(str, row[2]),
                cast(str, row[3]),
                cast(str, row[4]),
            )
        )

    accounting_rows_by_code: dict[str, list[int]] = {}
    for account_code, source_row in data.accounting.select(
        "account_code", "source_row"
    ).iter_rows():
        accounting_rows_by_code.setdefault(cast(str, account_code), []).append(
            cast(int, source_row)
        )

    duplicate_codes = sorted(
        account_code for account_code, records in accounts_by_code.items() if len(records) > 1
    )
    missing_codes = sorted(set(accounting_rows_by_code) - set(accounts_by_code))

    issues = [
        EnrichmentIssue(
            code=EnrichmentErrorCode.DUPLICATE_ACCOUNT_CODE,
            account_code=account_code,
            accounting_source_rows=tuple(sorted(accounting_rows_by_code.get(account_code, []))),
            account_source_rows=tuple(
                sorted(record[0] for record in accounts_by_code[account_code])
            ),
            message=(
                f'O código de conta "{account_code}" aparece mais de uma vez no plano de contas.'
            ),
        )
        for account_code in duplicate_codes
    ]
    issues.extend(
        EnrichmentIssue(
            code=EnrichmentErrorCode.ACCOUNT_NOT_FOUND,
            account_code=account_code,
            accounting_source_rows=tuple(sorted(accounting_rows_by_code[account_code])),
            account_source_rows=(),
            message=f'O código de conta "{account_code}" não foi encontrado no plano de contas.',
        )
        for account_code in missing_codes
    )

    account_source_rows: list[int | None] = []
    account_natures: list[str | None] = []
    account_descriptions: list[str | None] = []
    account_types: list[str | None] = []
    for account_code in data.accounting["account_code"]:
        records = accounts_by_code.get(cast(str, account_code), [])
        if len(records) != 1:
            account_source_rows.append(None)
            account_natures.append(None)
            account_descriptions.append(None)
            account_types.append(None)
            continue

        source_row, nature, description, account_type = records[0]
        account_source_rows.append(source_row)
        account_natures.append(nature)
        account_descriptions.append(description)
        account_types.append(account_type)

    enriched = data.accounting.with_columns(
        pl.Series("account_nature", account_natures, dtype=pl.String),
        pl.Series("account_description", account_descriptions, dtype=pl.String),
        pl.Series("account_type", account_types, dtype=pl.String),
        pl.Series("account_source_row", account_source_rows, dtype=pl.Int64),
    )
    return EnrichmentResult(
        accounting=enriched,
        is_valid=not issues,
        issues=tuple(issues),
    )
