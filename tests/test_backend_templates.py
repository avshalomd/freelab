"""The backend templates the compute references copy into lab/backends/ must stay valid Python."""
import py_compile
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parent.parent / "scripts" / "backends" / "templates"


@pytest.mark.parametrize("name", ["modal_app.py", "kaggle_run.py"])
def test_template_compiles(name, tmp_path):
    py_compile.compile(str(TEMPLATES / name), cfile=str(tmp_path / "out.pyc"), doraise=True)


def test_kaggle_template_marks_its_placeholder():
    text = (TEMPLATES / "kaggle_run.py").read_text(encoding="utf-8")
    assert 'ARGS = ["--max-minutes", "20", "--smoke"]  # FILL IN' in text


def test_modal_template_reads_paths_from_env():
    text = (TEMPLATES / "modal_app.py").read_text(encoding="utf-8")
    assert 'os.environ.get("FREELAB_EXP", "")' in text and 'os.environ.get("FREELAB_RUNLIB", "")' in text
