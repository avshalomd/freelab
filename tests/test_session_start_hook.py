import json, os, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "session-start.sh"


def run(env_home):
    env = {**os.environ, "FREELAB_HOME": str(env_home)}
    return subprocess.run([str(HOOK)], capture_output=True, text=True, env=env, timeout=10)


def test_hooks_json_runs_the_script_at_session_start():
    cfg = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    cmd = cfg["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh" in cmd
    assert os.access(HOOK, os.X_OK)


def test_not_onboarded_points_at_the_onboard_skill(tmp_path):
    home = tmp_path / "free lab"  # a space in the path
    r = run(home)
    assert r.returncode == 0 and len(r.stdout.strip().splitlines()) == 1
    line = r.stdout.strip()
    assert "freelab onboard skill" in line and "offer once" in line and "AskUserQuestion" in line
    assert "Not now" in line and "set up freelab" in line
    assert "/goal" not in line and "snooze" not in line


def test_the_offer_comes_once_per_machine(tmp_path):
    """After the hook has printed its line once, it writes `nudged` and is quiet in every later session."""
    home = tmp_path / "free lab"
    assert "freelab onboard skill" in run(home).stdout
    assert (home / "nudged").is_file()
    for _ in range(2):
        r = run(home)
        assert r.returncode == 0 and r.stdout == ""


def test_nudged_is_silent(tmp_path):
    (tmp_path / "nudged").write_text("2026-10-01\n")
    r = run(tmp_path)
    assert r.returncode == 0 and r.stdout == ""


def test_onboarded_is_silent(tmp_path):
    (tmp_path / "onboarded").write_text('{"date": "2026-09-28", "services": []}\n')
    r = run(tmp_path)
    assert r.returncode == 0 and r.stdout == ""
    assert not (tmp_path / "nudged").exists()


def test_default_home_is_used_when_freelab_home_is_unset(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "FREELAB_HOME"}
    env["HOME"] = str(tmp_path)
    r = subprocess.run([str(HOOK)], capture_output=True, text=True, env=env, timeout=10)
    assert r.returncode == 0 and "freelab onboard skill" in r.stdout
    assert (tmp_path / ".freelab" / "nudged").is_file()
    r = subprocess.run([str(HOOK)], capture_output=True, text=True, env=env, timeout=10)
    assert r.returncode == 0 and r.stdout == ""


def test_unwritable_home_still_offers(tmp_path):
    """If the marker cannot be written, the offer still comes (and exit 0)."""
    blocker = tmp_path / "file"
    blocker.write_text("")
    r = run(blocker / "sub")   # a path under a regular file: mkdir fails
    assert r.returncode == 0 and "freelab onboard skill" in r.stdout


def test_hooks_json_registers_guard_and_stop():
    """The PreToolUse guard and the Stop hook (test_hooks.py checks the PostToolUse entry)."""
    cfg = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    pre = cfg["PreToolUse"][0]
    assert pre["matcher"] == "*"
    assert pre["hooks"][0]["command"] == 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/guard.py"'
    assert cfg["Stop"][0]["hooks"][0]["command"] == 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/stop.py"'
