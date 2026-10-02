import os, shutil, stat, subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
ENV_SH = ROOT / "scripts" / "env.sh"
WITHENV = ROOT / "scripts" / "withenv"
MARKER = "# freelab: paste each value after the =, no quotes, no spaces"
SECRET = "sk-very-secret-value-123"


def run(cwd, *args, shell=None):
    cmd = [str(ENV_SH), *args] if shell is None else [shell, "-c", " ".join([str(ENV_SH), *args])]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=20)


def test_both_scripts_are_executable():
    assert os.access(ENV_SH, os.X_OK) and os.access(WITHENV, os.X_OK)


def test_add_creates_env_with_marker_and_placeholders(tmp_path):
    r = run(tmp_path, "add", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")
    assert r.returncode == 0 and r.stdout == "added MODAL_TOKEN_ID\nadded MODAL_TOKEN_SECRET\n"
    env = tmp_path / ".env"
    assert env.read_text() == f"{MARKER}\nMODAL_TOKEN_ID=\nMODAL_TOKEN_SECRET=\n"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_add_is_idempotent_and_never_touches_existing_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"OTHER=1\nKAGGLE_API_TOKEN={SECRET}")   # no trailing newline
    env.chmod(0o644)
    r = run(tmp_path, "add", "KAGGLE_API_TOKEN", "LIGHTNING_API_KEY")
    assert r.returncode == 0 and r.stdout == "added LIGHTNING_API_KEY\n" and SECRET not in r.stdout + r.stderr
    assert env.read_text() == f"OTHER=1\nKAGGLE_API_TOKEN={SECRET}\n{MARKER}\nLIGHTNING_API_KEY=\n"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    before = env.read_text()
    r = run(tmp_path, "add", "KAGGLE_API_TOKEN", "LIGHTNING_API_KEY")
    assert r.returncode == 0 and r.stdout == "" and env.read_text() == before
    run(tmp_path, "add", "LIGHTNING_USER_ID")
    assert env.read_text().count(MARKER) == 1   # the comment is written once


def test_check_present_missing_empty(tmp_path):
    (tmp_path / ".env").write_text(f"A={SECRET}\nB=\nC=   \nexport D='{SECRET}'\nE= # comment\n")
    r = run(tmp_path, "check", "A", "B", "C", "D", "E", "F")
    assert r.returncode == 1
    assert r.stdout == "A: present\nB: missing\nC: missing\nD: present\nE: missing\nF: missing\n"
    assert SECRET not in r.stdout + r.stderr
    r = run(tmp_path, "check", "A", "D")
    assert r.returncode == 0 and r.stdout == "A: present\nD: present\n"


def test_check_without_env_file(tmp_path):
    r = run(tmp_path, "check", "A")
    assert r.returncode == 1 and r.stdout == "A: missing\n"
    assert not (tmp_path / ".env").exists()


@pytest.mark.parametrize("args", [[], ["add"], ["check"], ["show", "A"], ["add", "1BAD"], ["add", "A-B"]])
def test_bad_usage_exits_2(tmp_path, args):
    r = run(tmp_path, *args)
    assert r.returncode == 2 and r.stdout == ""


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")
def test_works_when_invoked_from_zsh(tmp_path):
    (tmp_path / ".env").write_text(f"A={SECRET}\n")
    r = run(tmp_path, "check", "A", "B", shell="zsh")
    assert r.returncode == 1 and r.stdout == "A: present\nB: missing\n"
    r = run(tmp_path, "add", "B", shell="zsh")
    assert r.stdout == "added B\n"
    # also when zsh runs the file itself
    r = subprocess.run(["zsh", str(ENV_SH), "check", "A", "B"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 1 and r.stdout == "A: present\nB: missing\n"


def test_withenv_loads_env_without_printing(tmp_path):
    (tmp_path / ".env").write_text(f"echo noisy\nMY_KEY={SECRET}\n")
    r = subprocess.run([str(WITHENV), "sh", "-c", 'test "$MY_KEY" = "$1" && echo loaded', "_", SECRET],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "loaded\n" and "noisy" not in r.stdout


def test_withenv_without_env_and_exit_code(tmp_path):
    r = subprocess.run([str(WITHENV), "sh", "-c", "exit 7"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 7
    r = subprocess.run([str(WITHENV)], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 2 and "usage" in r.stderr
