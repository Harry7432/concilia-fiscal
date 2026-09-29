from dataclasses import dataclass
from enum import StrEnum

from concilia_fiscal.models import FileKind


class ValueKind(StrEnum):
    TEXT = "text"
    DATE = "date"
    DECIMAL = "decimal"


@dataclass(frozen=True, slots=True)
class ColumnContract:
    name: str
    value_kind: ValueKind


@dataclass(frozen=True, slots=True)
class WorkbookContract:
    file_kind: FileKind
    sheet_name: str
    columns: tuple[ColumnContract, ...]


CONTRACTS = {
    FileKind.ACCOUNTING: WorkbookContract(
        file_kind=FileKind.ACCOUNTING,
        sheet_name="Contabil",
        columns=(
            ColumnContract("Código", ValueKind.TEXT),
            ColumnContract("Histórico", ValueKind.TEXT),
            ColumnContract("D/C", ValueKind.TEXT),
            ColumnContract("Vlr Saldo Final", ValueKind.DECIMAL),
            ColumnContract("CNPJ", ValueKind.TEXT),
            ColumnContract("Data", ValueKind.DATE),
            ColumnContract("Número Lançamento", ValueKind.TEXT),
        ),
    ),
    FileKind.FISCAL: WorkbookContract(
        file_kind=FileKind.FISCAL,
        sheet_name="Fiscal",
        columns=(
            ColumnContract("Alíquota PIS", ValueKind.DECIMAL),
            ColumnContract("Número Documento", ValueKind.TEXT),
            ColumnContract("Vlr Documento", ValueKind.DECIMAL),
            ColumnContract("Fornecedor", ValueKind.TEXT),
            ColumnContract("Data Fiscal", ValueKind.DATE),
        ),
    ),
    FileKind.ACCOUNTS: WorkbookContract(
        file_kind=FileKind.ACCOUNTS,
        sheet_name="Plano_Contas",
        columns=(
            ColumnContract("Conta", ValueKind.TEXT),
            ColumnContract("Natureza Conta", ValueKind.TEXT),
            ColumnContract("Descrição Conta Societária", ValueKind.TEXT),
            ColumnContract("Tipo Conta", ValueKind.TEXT),
        ),
    ),
}
