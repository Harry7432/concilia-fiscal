from io import BytesIO
from pathlib import Path

from concilia_fiscal import read_workbook

FIXTURES = Path(__file__).parent / "fixtures"


def test_reads_workbook_from_uploaded_bytes() -> None:
    uploaded_file = BytesIO((FIXTURES / "fiscal_teste.xlsx").read_bytes())
    uploaded_file.seek(10)

    data = read_workbook(uploaded_file, "Fiscal")

    assert uploaded_file.tell() == 10
    assert data.shape == (11, 5)
    assert data.columns == [
        "Alíquota PIS",
        "Número Documento",
        "Vlr Documento",
        "Fornecedor",
        "Data Fiscal",
    ]
