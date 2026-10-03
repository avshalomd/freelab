#!/usr/bin/env python3
"""freelab PostToolUse hook (Bash, PowerShell): records one of freelab's own gated launches in lab/.launches once it has run.
Only in a project that uses freelab (hooklib.uses_freelab on the hook's cwd), and only for the launches
guard.gated_launch recognises as freelab's (the user's own `modal run app.py` and the like are not recorded);
anywhere else it exits 0 with no output, and it never prints anything.

Claude Code runs PostToolUse only after a tool call succeeded (a Bash command that exits non-zero goes to
PostToolUseFailure, and a call the guard denied or the user declined runs neither), so a denied, declined or failed
launch does not use up its cost estimate. The Bash `tool_response` holds stdout, stderr and `interrupted`, with no
exit code; if a response does carry an error flag or a non-zero exit code, the launch is not recorded. When success
cannot be told (a background command, an interrupted one), the launch is recorded: the gate then asks for a new
estimate, the safe side. Which commands count is guard.gated_launch (smoke runs and `--help` do not; a heredoc
body that only writes a file is text, not a launch, while one fed to a shell, `bash <<EOF`, is commands).
Any error: no record, exit 0."""
from __future__ import annotations
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ inside the installed plugin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hooklib import hook_cwd, uses_freelab, read_input  # noqa: E402
from guard import all_segments, gated_launch, record_launch  # noqa: E402

EXIT_KEYS = ("exit_code", "exitCode", "returncode", "returnCode", "code")


def failed(response) -> bool:
    """True only when the tool response says the command failed."""
    if not isinstance(response, dict):
        return False
    if response.get("is_error") is True:
        return True
    for key in EXIT_KEYS:
        value = response.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value != 0:
            return True
    return False


def evaluate(data: dict) -> str | None:
    """The backend recorded, or None."""
    if data.get("hook_event_name", "PostToolUse") != "PostToolUse":
        return None
    if data.get("tool_name") not in ("Bash", "PowerShell"):
        return None
    cwd = hook_cwd(data)
    if not uses_freelab(cwd):
        return None
    ti = data.get("tool_input")
    command = ti.get("command") if isinstance(ti, dict) else None
    if not isinstance(command, str) or not command.strip():
        return None
    launch = gated_launch(all_segments(command), cwd)
    if launch is None or failed(data.get("tool_response")):
        return None
    record_launch(Path(cwd) / "lab", launch[0])
    return launch[0]


def main() -> int:
    try:
        evaluate(read_input())
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
