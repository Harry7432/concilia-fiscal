from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_application_loads_with_validation_disabled() -> None:
    app = AppTest.from_file(Path(__file__).parents[1] / "streamlit_app.py").run()

    assert not app.exception
    assert app.title[0].value == "Concilia Fiscal"
    assert app.button[0].label == "Validar planilhas"
    assert app.button[0].disabled
