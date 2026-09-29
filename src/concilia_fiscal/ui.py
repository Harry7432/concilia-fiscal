from dataclasses import asdict

import streamlit as st

from concilia_fiscal.models import FileKind, ValidationResult
from concilia_fiscal.validation import validate_file

MAX_UPLOAD_SIZE_MB = 10


def _render_result(label: str, result: ValidationResult) -> None:
    st.subheader(label)
    if result.is_valid:
        st.success("Planilha válida.")
    else:
        st.error("A planilha contém erros de validação.")

    status, rows, errors = st.columns(3)
    status.metric("Status", "Válida" if result.is_valid else "Inválida")
    rows.metric("Linhas", result.row_count)
    errors.metric("Erros", len(result.errors))

    st.write("**Colunas reconhecidas:**", ", ".join(result.recognized_columns) or "Nenhuma")
    st.write("**Colunas extras:**", ", ".join(result.extra_columns) or "Nenhuma")

    if result.errors:
        st.write("**Erros encontrados**")
        st.dataframe([asdict(error) for error in result.errors], width="stretch", hide_index=True)

    if result.data is not None:
        st.write("**Prévia dos dados**")
        st.dataframe(result.data.head(5), width="stretch", hide_index=True)


def render_app() -> None:
    st.set_page_config(page_title="Concilia Fiscal", layout="wide")
    st.title("Concilia Fiscal")
    st.caption("Importe e valide as planilhas antes de iniciar a conciliação.")

    accounting_file = st.file_uploader(
        "Planilha contábil", type=["xlsx"], max_upload_size=MAX_UPLOAD_SIZE_MB
    )
    fiscal_file = st.file_uploader(
        "Planilha fiscal", type=["xlsx"], max_upload_size=MAX_UPLOAD_SIZE_MB
    )
    accounts_file = st.file_uploader(
        "Plano de contas", type=["xlsx"], max_upload_size=MAX_UPLOAD_SIZE_MB
    )

    files_ready = all((accounting_file, fiscal_file, accounts_file))
    submitted = st.button("Validar planilhas", disabled=not files_ready, type="primary")

    if not submitted:
        return

    assert accounting_file is not None
    assert fiscal_file is not None
    assert accounts_file is not None

    results = (
        (
            "Planilha contábil",
            validate_file(
                accounting_file,
                file_name=accounting_file.name,
                file_kind=FileKind.ACCOUNTING,
            ),
        ),
        (
            "Planilha fiscal",
            validate_file(
                fiscal_file,
                file_name=fiscal_file.name,
                file_kind=FileKind.FISCAL,
            ),
        ),
        (
            "Plano de contas",
            validate_file(
                accounts_file,
                file_name=accounts_file.name,
                file_kind=FileKind.ACCOUNTS,
            ),
        ),
    )

    for label, result in results:
        _render_result(label, result)
