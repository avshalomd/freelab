"""Table-driven tests for hooks/guard.py (PreToolUse), hooks/post.py (PostToolUse) and hooks/stop.py (Stop), run as
subprocesses with JSON stdin."""
import json, os, re, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "hooks" / "guard.py"
STOP = ROOT / "hooks" / "stop.py"
POST = ROOT / "hooks" / "post.py"

CHARTER = "# Charter\n\n- **Target:** test accuracy >= 0.80\n- **Budget:** USD 0 beyond free credit, 1 hour\n"


def hook(script, payload, home):
    env = {**os.environ, "HOME": str(home)}
    r = subprocess.run([sys.executable, str(script)], input=json.dumps(payload), capture_output=True, text=True,
                       env=env, timeout=20)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def decision(out):
    return out["hookSpecificOutput"]["permissionDecision"] if out else None


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture
def lab_proj(tmp_path):
    p = tmp_path / "proj"
    (p / "lab").mkdir(parents=True)
    (p / "lab" / "ledger.jsonl").write_text("")   # a freelab file: lab/ alone (or lab/plan.md) does not count
    return p


def bash(cwd, command):
    return {"hook_event_name": "PreToolUse", "cwd": str(cwd), "tool_name": "Bash",
            "tool_input": {"command": command, "description": "x"}}


def tool(cwd, name, **ti):
    return {"hook_event_name": "PreToolUse", "cwd": str(cwd), "tool_name": name, "tool_input": ti}


def post(cwd, command, response=None):
    """A PostToolUse input for a Bash call (Claude Code sends it only after the call succeeded)."""
    return {"hook_event_name": "PostToolUse", "cwd": str(cwd), "tool_name": "Bash",
            "tool_input": {"command": command, "description": "x"},
            "tool_response": {"stdout": "", "stderr": "", "interrupted": False, "isImage": False}
            if response is None else response, "tool_use_id": "toolu_1"}


LEGACY = "set -a; [ -f .env ] && . ./.env 2>/dev/null; set +a; "

# (command, expected decision) in a project that uses freelab, before any launch gate matters
BASH_CASES = [
    # reading .env or key files
    ("cat .env", "deny"),
    ("cat ./.env", "deny"),
    ("head -n 3 sub/dir/.env", "deny"),
    ("tail .env", "deny"),
    ("less .env", "deny"),
    ("more .env", "deny"),
    ("bat .env", "deny"),
    ("nl .env", "deny"),
    ("od -c .env", "deny"),
    ("xxd .env", "deny"),
    ("strings .env", "deny"),
    ("cat .env*", "deny"),
    ("cat ~/.modal.toml", "deny"),
    ("cat $HOME/.kaggle/kaggle.json", "deny"),
    ("ls ~/.lightning && cat ~/.lightning/credentials.json", "deny"),
    ("cp .env /tmp/keys", "deny"),
    ("mv .env backup.env", "deny"),
    ("grep MODAL .env", "deny"),
    ("grep -n '^MODAL_TOKEN_ID=' .env", "deny"),
    ("sed -n 1p .env", "deny"),
    ("awk -F= '{print $2}' .env", "deny"),
    ("while read l; do echo $l; done < .env", "deny"),
    ("python3 -c \"print(open('.env').read())\"", "deny"),
    ("bash -c 'cat .env'", "deny"),
    ("diff <(cat .env) other", "deny"),
    ("echo `cat .env`", "deny"),
    ("x=$(cat .env); echo ok", "deny"),
    # printing the environment or a credential
    (LEGACY + "echo $MODAL_TOKEN_SECRET", "deny"),
    ("source .env && echo \"${KAGGLE_API_TOKEN}\"", "deny"),
    ("printf '%s' $LIGHTNING_API_KEY", "deny"),
    ("echo $LIGHTNING_USER_ID", "deny"),
    ("echo $KAGGLE_KEY", "deny"),
    (LEGACY + "printenv", "deny"),
    ("printenv MODAL_TOKEN_ID", "deny"),
    ("env", "deny"),
    ("env | grep KAGGLE", "deny"),
    (LEGACY + "set", "deny"),
    ("export -p", "deny"),
    ("declare -x", "deny"),
    ("modal token info", "deny"),
    (LEGACY + "kaggle config view", "deny"),
    ("gcloud auth print-access-token", "deny"),
    ("scripts/withenv printenv", "deny"),
    ("python3 - <<'EOF'\nimport os\nprint(os.environ['MODAL_TOKEN_ID'])\nEOF", "deny"),
    ("echo x > .env", "deny"),
    # interpreter code that reads the whole environment, or a key, and outputs it
    ("python3 -c 'import os; print(os.environ)'", "deny"),
    ("python -c 'import os; print(dict(os.environ))'", "deny"),
    ("python3 -c 'import os,json; print(json.dumps({**os.environ}))'", "deny"),
    ("python3 -c 'from os import environ; [print(k, v) for k, v in environ.items()]'", "deny"),
    ("python3 -c 'import os; print(os.getenv(\"MODAL_TOKEN_SECRET\"))'", "deny"),
    ("python3 -c 'import os; print(os.environ.get(\"KAGGLE_API_TOKEN\"))'", "deny"),
    ("python3 -c 'import os; os.system(\"env\")'", "deny"),
    ("python3 -c 'import subprocess; print(subprocess.check_output([\"printenv\"]))'", "deny"),
    ("node -e 'console.log(process.env)'", "deny"),
    ("node -e 'console.log(JSON.stringify(process.env))'", "deny"),
    ("node -p 'process.env'", "deny"),
    ("node -e 'console.log(process.env.LIGHTNING_API_KEY)'", "deny"),
    ("perl -e 'print \"$_=$ENV{$_}\\n\" for keys %ENV'", "deny"),
    ("perl -le 'print $ENV{MODAL_TOKEN_ID}'", "deny"),
    ("ruby -e 'p ENV.to_h'", "deny"),
    ("ruby -e 'puts ENV.map { |k, v| k }'", "deny"),
    ("ruby -e 'puts `env`'", "deny"),
    ("awk 'BEGIN { for (k in ENVIRON) print k \"=\" ENVIRON[k] }'", "deny"),
    ("awk 'BEGIN { print ENVIRON[\"KAGGLE_KEY\"] }'", "deny"),
    ("bash -c 'python3 -c \"import os; print(os.environ)\"'", "deny"),
    ("scripts/withenv python3 -c 'import os; print(os.environ)'", "deny"),
    ("python3 - <<'EOF'\nimport os\nfor k, v in os.environ.items():\n    print(k, v)\nEOF", "deny"),
    # allowed
    ("python3 -c 'import os; print(os.environ.get(\"HF_HOME\"))'", None),
    ("python3 -c 'import os; print(os.getenv(\"PATH\"))'", None),
    ("node -e 'console.log(process.env.HOME)'", None),
    ("ruby -e 'puts ENV[\"HOME\"]'", None),
    ("awk '{print $1}' lab/results.tsv", None),
    ("python3 -c \"import json; print(json.load(open('lab/runs/a/summary.json'))['final_val_accuracy'])\"", None),
    ("scripts/withenv python3 train.py --epochs 3 --out lab/runs/a", None),
    ("set -a; . ./.env; set +a; kaggle kernels list --mine", None),
    ("git stash", None),
    ("git stash pop", None),
    ("git log --oneline -5", None),
    ("git diff lab/charter.md", None),
    ("git add lab/charter.md lab/plan.md", None),
    ("git -C lab/worktrees/loop add .gitignore experiments/banking77-laya", None),
    ("git show HEAD:README.md", None),
    ("git log -- .env", None),
    ("lightning job delete --help", None),
    ("kaggle kernels delete -h", None),
    ("scripts/withenv kaggle kernels status me/freelab-a", None),
    ("${CLAUDE_PLUGIN_ROOT}/scripts/env.sh add MODAL_TOKEN_ID MODAL_TOKEN_SECRET", None),
    ("${CLAUDE_PLUGIN_ROOT}/scripts/env.sh check KAGGLE_API_TOKEN", None),
    (LEGACY + "kaggle kernels status me/freelab-a", None),
    (LEGACY + "modal volume ls freelab-runs", None),
    ("grep -q '^MODAL_TOKEN_ID=' .env", None),
    ("grep -qE '^KAGGLE_API_TOKEN=.+' .env && echo set", None),
    ("grep -c '^A=' .env", None),
    ("open -t .env", None),
    ("xdg-open .env", None),
    ("chmod 600 .env", None),
    ("touch .env", None),
    ("echo 'X=' >> .env", None),
    ("echo $KAGGLE_USERNAME", None),
    ("printenv HOME", None),
    ("env FOO=1 python3 train.py", None),
    ("set -euo pipefail", None),
    ("ls -la", None),
    ("cat lab/status.json", None),
    ("grep -n env README.md", None),
    ("git status", None),
    # heredocs: a body fed to cat, a commit message, is text; one fed to an interpreter or a shell is code
    ("cat > lab/notes.md <<'EOF'\nset up Modal\nenv\ncat .env\nEOF", None),
    ("cat >> .env <<'EOF'\nKAGGLE_KEY=\nEOF", None),
    ("cat <<-EOF > lab/notes.md\n\tprintenv\n\tEOF\necho done", None),
    ("bash <<'EOF'\ncat .env\nEOF", "deny"),
    ("cat > lab/notes.md <<'EOF'\nnotes\nEOF\ncat .env", "deny"),          # a command after the body still counts
    # text inside $(...) and backticks within a word, `bash -lc`, and wrappers with options
    ('echo "$(cat .env)"', "deny"),
    ('echo "`cat .env`"', "deny"),
    ('x="$(grep KAGGLE .env)"', "deny"),
    ('bash -lc "cat .env"', "deny"),
    ("sh -ec 'cat .env'", "deny"),
    ("bash -o pipefail -c 'cat .env'", "deny"),
    ("sudo -u me cat .env", "deny"),
    ("nice -n 5 cat .env", "deny"),
    ("timeout 5 cat .env", "deny"),
    ("timeout -s KILL 5 head .env", "deny"),
    ("env -i cat .env", "deny"),
    ("xargs -n 1 cat .env", "deny"),
    ("cat .*", "deny"),
    ("timeout 600 python3 train.py", None),
    ('echo "$(date) done"', None),
    # recursive greps whose pattern matches a key's line in a .env they reach
    ("grep -rn KAGGLE_KEY .", "deny"),
    ("grep -r MODAL_TOKEN .", "deny"),
    ("grep -Rin 'modal_token' .", "deny"),
    ("grep -rn 'KAGGLE\\|MODAL' .", "deny"),
    ("grep -rn = .", "deny"),
    ("rg --hidden KAGGLE_KEY", "deny"),
    ("rg -uu 'MODAL_TOKEN_.*'", "deny"),
    ("grep -rn KAGGLE_KEY --exclude=.env .", None),
    ("grep -rn KAGGLE_KEY --exclude .env .", None),
    ("grep -rn KAGGLE --include='*.py' .", None),
    ("grep -rln KAGGLE_KEY .", None),
    ("grep -rn kaggle skills/", None),          # case-sensitive: cannot match KAGGLE_KEY=
    ("grep -rn 'def main' .", None),
    ("rg KAGGLE_KEY", None),                     # rg skips hidden files such as .env
    ("rg --hidden -g '!.env' KAGGLE_KEY", None),
    ("rg --hidden -t py KAGGLE_KEY", None),
]


@pytest.mark.parametrize("command,expect", BASH_CASES)
def test_guard_bash_in_a_lab_project(lab_proj, home, command, expect):
    (lab_proj / "lab" / "runs" / "exp-02").mkdir(parents=True)   # a freelab run, so its Lightning job is freelab's
    out = hook(GUARD, bash(lab_proj, command), home)
    assert decision(out) == expect, out
    if out:   # a deny reason goes to Claude and names the guard
        assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert out["hookSpecificOutput"]["permissionDecisionReason"].startswith("freelab guard: ")


@pytest.mark.parametrize("command,what", [
    ("modal volume rm -r freelab-runs exp-02/ckpt", "`exp-02/ckpt` in the Volume `freelab-runs` on Modal"),
    ("kaggle kernels delete -y me/freelab-exp-02", "the kernel `me/freelab-exp-02` on Kaggle"),
    ("kaggle datasets delete -y me/freelab-banking", "the dataset `me/freelab-banking` on Kaggle"),
    ("lightning job delete exp-02 --teamspace me/ts", "the job `exp-02` on Lightning AI"),
])
def test_delete_ask_names_what_and_where(lab_proj, home, command, what):
    (lab_proj / "lab" / "runs" / "exp-02").mkdir(parents=True)
    reason = hook(GUARD, bash(lab_proj, command), home)["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason == f"This permanently deletes {what}; there is no trash. Approve only if you want it deleted."


@pytest.mark.parametrize("command,expect", [
    # freelab's storage: asked or denied
    (LEGACY + "modal volume rm -r freelab-runs exp-02/ckpt", "ask"),
    ("scripts/withenv modal volume rm -r freelab-runs exp-02/ckpt", "ask"),
    (LEGACY + "kaggle kernels delete -y me/freelab-exp-02", "ask"),
    (LEGACY + "kaggle datasets delete -y me/freelab-banking", "ask"),
    (LEGACY + "lightning job delete exp-02 --teamspace me/ts", "ask"),
    (LEGACY + "modal volume delete freelab-runs", "deny"),
    ("modal volume delete freelab-runs --yes", "deny"),
    ("modal volume rm freelab-runs exp-02/status.txt", "ask"),
    ("lightning rm lit://me/ts/studios/freelab/freelab-runs/exp-09/ckpt", "ask"),
    ("lightning rm lit://me/ts/studios/freelab/freelab-init/exp-09/step-1", "ask"),
    ("lightning studio delete --name freelab --teamspace me/ts", "ask"),
    ("lightning job delete exp-02-r2 --teamspace me/ts", "ask"),          # a relaunch of a freelab run
    ("lightning job delete --name exp-02 --teamspace me/ts", "ask"),
    ("kaggle kernels delete -y me/freelab-exp-02-r1", "ask"),
    # the user's own storage: no output
    ("modal volume rm -r my-data old/", None),
    ("modal volume delete my-data", None),
    ("modal volume delete", None),
    ("kaggle kernels delete -y me/my-notebook", None),
    ("kaggle datasets delete -y me/house-prices", None),
    ("lightning job delete my-batch-job --teamspace me/ts", None),
    ("lightning studio delete --name my-studio --teamspace me/ts", None),
    ("lightning rm lit://me/ts/studios/my-studio/data/old.csv", None),
])
def test_cloud_deletes_cover_only_freelab_storage(lab_proj, home, command, expect):
    (lab_proj / "lab" / "runs" / "exp-02").mkdir(parents=True)
    out = hook(GUARD, bash(lab_proj, command), home)
    assert decision(out) == expect
    if expect == "ask":   # an ask reason is shown to the user, in plain words
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert reason.startswith("This permanently deletes ") and not re.search(r"\bguard\b", reason)


def commit(message):
    """A commit the way Claude Code writes one: the message in a heredoc inside $(...)."""
    return f"git add hooks/guard.py && git commit -m \"$(cat <<'EOF'\n{message}\nEOF\n)\""


@pytest.mark.parametrize("message", [
    "fix: never upload .env, it is already ignored",
    "docs: do not print KAGGLE_KEY or MODAL_TOKEN_SECRET; read open(.env) never",
    "test: modal run lab/backends/modal_app.py --run-id exp-01 needs a charter",
    "chore: kaggle kernels delete -y me/freelab-exp-02 asks first\nmodal volume delete freelab-runs is denied",
    "note: cat .env and printenv are blocked; python3 -c 'print(os.environ)' too",
])
def test_git_commit_messages_are_silent(lab_proj, home, message):
    """No rules on git commands: a commit message is text, whatever it mentions."""
    (lab_proj / "lab" / "runs" / "exp-02").mkdir(parents=True)
    assert hook(GUARD, bash(lab_proj, commit(message)), home) is None
    assert hook(POST, post(lab_proj, commit(message)), home) is None
    assert not (lab_proj / "lab" / ".launches").exists()


@pytest.mark.parametrize("body", [
    "kaggle kernels delete -y me/freelab-r1",
    "modal volume rm -r freelab-runs exp-02/ckpt",
    "modal run lab/backends/modal_app.py --run-id r2",
    "python3 scripts/backends/local_run.py exp --run-id r2",
])
def test_heredoc_bodies_that_write_a_file_are_not_commands(lab_proj, home, body):
    command = f"cat > lab/notes.md <<'EOF'\n## Next\n{body}\nEOF"
    assert hook(GUARD, bash(lab_proj, command), home) is None          # no ask, no launch gate
    assert hook(POST, post(lab_proj, command), home) is None
    assert not (lab_proj / "lab" / ".launches").exists()               # writing a note is not a launch


def powershell(cwd, command):
    return {"hook_event_name": "PreToolUse", "cwd": str(cwd), "tool_name": "PowerShell",
            "tool_input": {"command": command, "description": "x"}}


@pytest.mark.parametrize("command,expect", [
    ("Get-Content .env", "deny"),
    ("gc .env", "deny"),
    ("GET-CONTENT -Raw .\\.env", "deny"),
    ("type .env", "deny"),
    ("Select-String KAGGLE .env", "deny"),
    ("Copy-Item .env C:\\tmp\\keys", "deny"),
    ("Get-Content $HOME\\.kaggle\\kaggle.json", "deny"),
    ("Get-ChildItem env:", "deny"),
    ("gci env:*", "deny"),
    ("Get-Item env:KAGGLE_KEY", "deny"),
    ("echo $env:KAGGLE_KEY", "deny"),
    ("Write-Output \"${env:MODAL_TOKEN_SECRET}\"", "deny"),
    ("[Environment]::GetEnvironmentVariables()", "deny"),
    ("[Environment]::GetEnvironmentVariable('LIGHTNING_API_KEY')", "deny"),
    ("Set-Content .env 'X='", "deny"),
    ("cat .env", "deny"),
    ("Add-Content .env 'KAGGLE_KEY='", None),
    ("echo $env:HOME", None),
    ("Get-ChildItem env:PATH", None),
    ("Get-Content lab\\plan.md", None),
    ("Get-Content .env.example", None),
    ("Add-Type -Path x.dll", None),
])
def test_guard_powershell(lab_proj, home, command, expect):
    out = hook(GUARD, powershell(lab_proj, command), home)
    assert decision(out) == expect, out


@pytest.mark.parametrize("command", [
    "modal run app.py",
    "modal run --detach src/train_app.py::main --gpu A10G",
    "kaggle kernels push -p mykernel",
    "kaggle kernels push",
    "lightning job run --name nightly-eval --teamspace me/ts --studio my-studio --machine T4 "
    "--command \"python eval.py\"",
    "python3 scripts/local_run.py --epochs 3",
    "python3 train.py --epochs 3",
])
def test_the_users_own_launches_are_silent(lab_proj, home, command):
    """A project that uses freelab is still the user's project: their own launches get no gate and no record,
    even with no charter and no estimate."""
    (lab_proj / "mykernel").mkdir()
    (lab_proj / "mykernel" / "kernel-metadata.json").write_text(json.dumps({"id": "me/my-kernel", "title": "x"}))
    r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(bash(lab_proj, command)), capture_output=True,
                       text=True, env={**os.environ, "HOME": str(home)})
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert hook(POST, post(lab_proj, command), home) is None
    assert not (lab_proj / "lab" / ".launches").exists()


@pytest.mark.parametrize("command,backend", [
    ("modal run --detach /abs/proj/lab/backends/modal_app.py::main --run-id exp-01 --minutes 20", "modal"),
    ("cd lab/backends && FREELAB_EXP=/p/exp FREELAB_RUNLIB=/r modal run modal_app.py::main --run-id exp-01", "modal"),
    ("kaggle kernels push -p ./lab/backends/kaggle-exp-01/ -t 1800", "kaggle"),
    ("kaggle kernels push -p staged", "kaggle"),        # its kernel-metadata.json names a freelab- kernel
    ("lightning job run --name exp-01 --studio=freelab --command \"python -u train.py\"", "lightning"),
    ("lightning job run --name exp-01 --studio other --command \"python -u train.py --out ~/freelab-runs/x\"",
     "lightning"),
    ("python3 /Users/me/.claude/plugins/freelab/scripts/backends/local_run.py exp --run-id exp-01", "local"),
])
def test_freelab_launches_are_recognised(lab_proj, home, command, backend):
    (lab_proj / "staged").mkdir()
    (lab_proj / "staged" / "kernel-metadata.json").write_text(json.dumps({"id": "me/freelab-exp-01"}))
    out = hook(GUARD, bash(lab_proj, command), home)   # no charter: the gate blocks it
    assert decision(out) == "deny"
    assert out["hookSpecificOutput"]["permissionDecisionReason"].startswith(f"freelab guard: {backend} launch blocked")


def test_deny_messages_say_what_to_do_instead(lab_proj, home):
    reason = hook(GUARD, bash(lab_proj, "cat .env"), home)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "scripts/env.sh check NAME" in reason and "open -t .env" in reason
    reason = hook(GUARD, tool(lab_proj, "Edit", file_path=str(lab_proj / ".env"), old_string="a", new_string="b"),
                  home)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "scripts/env.sh add NAME" in reason


@pytest.mark.parametrize("name,ti,expect", [
    ("Read", {"file_path": "{p}/.env"}, "deny"),
    ("Read", {"file_path": ".env"}, "deny"),
    ("Read", {"file_path": "{p}/sub/.env"}, "deny"),
    ("Read", {"file_path": "{h}/.modal.toml"}, "deny"),
    ("Read", {"file_path": "~/.kaggle/kaggle.json"}, "deny"),
    ("Read", {"file_path": "{h}/.lightning/credentials.json"}, "deny"),
    ("Read", {"file_path": "{p}/.env.example"}, None),
    ("Read", {"file_path": "{p}/lab/charter.md"}, None),
    ("Edit", {"file_path": "{p}/.env", "old_string": "A=", "new_string": "A=1"}, "deny"),
    ("Write", {"file_path": "{p}/.env", "content": "A=\n"}, "deny"),
    ("Write", {"file_path": "{h}/.kaggle/kaggle.json", "content": "{}"}, "deny"),
    ("Write", {"file_path": "{p}/lab/plan.md", "content": "x"}, None),
    ("Grep", {"pattern": "TOKEN", "path": "{p}/.env"}, "deny"),
    ("Grep", {"pattern": "x", "path": "{h}/.kaggle"}, "deny"),
    ("Grep", {"pattern": "TOKEN", "glob": ".env*"}, "deny"),
    ("Grep", {"pattern": "MODAL_TOKEN_ID", "output_mode": "content"}, "deny"),
    ("Grep", {"pattern": "MODAL_TOKEN_ID", "output_mode": "content", "glob": "*.md"}, None),
    ("Grep", {"pattern": "MODAL_TOKEN_ID", "output_mode": "content", "type": "py"}, None),
    ("Grep", {"pattern": "MODAL_TOKEN_ID", "output_mode": "content", "path": "{p}/lab/ledger.jsonl"}, None),
    ("Grep", {"pattern": "MODAL_TOKEN_ID", "output_mode": "content", "path": "{p}"}, "deny"),   # a folder: .env inside
    ("Grep", {"pattern": "MODAL_TOKEN_ID", "output_mode": "content", "path": "{p}/lab"}, "deny"),
    ("Grep", {"pattern": "MODAL_TOKEN_ID", "output_mode": "content", "path": "{p}/missing.md"}, "deny"),
    ("Grep", {"pattern": "MODAL_TOKEN_ID", "output_mode": "content", "path": "{p}/.env"}, "deny"),
    ("Grep", {"pattern": "MODAL_TOKEN_ID", "output_mode": "content", "glob": "*"}, "deny"),
    ("Grep", {"pattern": "KAGGLE", "output_mode": "content"}, "deny"),
    ("Grep", {"pattern": "MODAL_TOKEN_.*", "output_mode": "content"}, "deny"),
    ("Grep", {"pattern": "kaggle", "output_mode": "content", "-i": True}, "deny"),
    ("Grep", {"pattern": "KAGGLE", "output_mode": "content", "glob": "**/*"}, "deny"),
    ("Grep", {"pattern": "kaggle", "output_mode": "content"}, None),          # case-sensitive: no key line
    ("Grep", {"pattern": "def main", "output_mode": "content", "glob": "*"}, None),
    ("Grep", {"pattern": "def main", "output_mode": "content", "glob": "**/*"}, None),
    ("Grep", {"pattern": "TODO", "glob": "*"}, None),
    ("Grep", {"pattern": "MODAL_TOKEN_ID", "output_mode": "files_with_matches", "path": "{p}"}, None),
    ("Grep", {"pattern": "def main", "path": "{p}"}, None),
    ("Glob", {"pattern": "*", "path": "{h}/.kaggle"}, "deny"),
    ("Glob", {"pattern": "**/*.py"}, None),
    ("Glob", {"pattern": ".env*"}, None),   # names only, no values
])
def test_guard_file_tools(lab_proj, home, name, ti, expect):
    ti = {k: v.replace("{p}", str(lab_proj)).replace("{h}", str(home)) if isinstance(v, str) else v
          for k, v in ti.items()}
    assert decision(hook(GUARD, tool(lab_proj, name, **ti), home)) == expect


# --- which projects use freelab -------------------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["cat .env", "modal volume delete x", "modal run app.py::main --run-id a",
                                     "echo $MODAL_TOKEN_SECRET", "env"])
def test_guard_is_silent_outside_a_lab_project(tmp_path, home, command):
    plain = tmp_path / "other"
    plain.mkdir()
    (plain / ".env").write_text("SOMETHING=1\n")   # a .env without freelab's comment
    r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(bash(plain, command)), capture_output=True,
                       text=True, env={**os.environ, "HOME": str(home)})
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert hook(GUARD, tool(plain, "Read", file_path=str(plain / ".env")), home) is None


FREELAB_STATUS = {"version": 1, "updated": "2026-10-02T10:00:00+00:00",
                  "goal": {"text": "beat 0.8", "metric": "accuracy", "target": 0.8, "direction": "max"},
                  "best": None, "runs": [], "budget": {}, "decisions": [], "events": []}


def test_a_lab_folder_alone_is_not_a_lab_project(tmp_path, home):
    other = tmp_path / "other"
    (other / "lab" / "notebooks").mkdir(parents=True)   # some other project's lab/ folder
    (other / "lab" / "plan.md").write_text("# Plan\n")           # generic names
    (other / "lab" / "handoff.md").write_text("# Handoff\n")
    (other / "lab" / "status.json").write_text(json.dumps({"runs": [], "status": "ok"}))   # not freelab's shape
    for payload in (bash(other, "modal run app.py"), bash(other, "cat .env"), bash(other, "modal volume rm x y")):
        r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload), capture_output=True, text=True,
                           env={**os.environ, "HOME": str(home)})
        assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    (other / "lab" / "status.json").write_text(json.dumps(FREELAB_STATUS))
    assert decision(hook(GUARD, bash(other, "cat .env"), home)) == "deny"   # freelab's status.json makes it one


@pytest.mark.parametrize("name", ["charter.md", "ledger.jsonl", ".launches"])
def test_each_freelab_file_marks_a_lab_project(tmp_path, home, name):
    p = tmp_path / "p"
    (p / "lab").mkdir(parents=True)
    (p / "lab" / name).write_text("")
    assert decision(hook(GUARD, bash(p, "cat .env"), home)) == "deny"


def test_onboarding_project_without_lab_is_guarded(tmp_path, home):
    onb = tmp_path / "onb"
    onb.mkdir()
    (onb / ".env").write_text("# freelab: paste each value after the =, no quotes, no spaces\nMODAL_TOKEN_ID=\n")
    assert decision(hook(GUARD, bash(onb, "cat .env"), home)) == "deny"
    assert decision(hook(GUARD, tool(onb, "Read", file_path=str(onb / ".env")), home)) == "deny"
    assert hook(GUARD, bash(onb, "scripts/env.sh check MODAL_TOKEN_ID"), home) is None
    # the connection-check smoke runs before any charter exists
    smoke = (LEGACY + "FREELAB_EXP=x modal run --detach lab/backends/modal_app.py::main --run-id smoke-modal-20261002 "
             "--gpu L4 --minutes 20 --args=--smoke")
    assert hook(GUARD, bash(onb, smoke), home) is None


def test_charter_alone_marks_a_lab_project(tmp_path, home):
    p = tmp_path / "c"
    (p / "lab").mkdir(parents=True)
    (p / "lab" / "charter.md").write_text(CHARTER)
    assert decision(hook(GUARD, bash(p, "cat .env"), home)) == "deny"


@pytest.mark.parametrize("stdin", ["", "not json", "[]", '{"tool_name": "Bash"}',
                                   '{"tool_name": "Bash", "tool_input": "x", "cwd": "/nonexistent"}'])
def test_guard_never_crashes(stdin, home):
    r = subprocess.run([sys.executable, str(GUARD)], input=stdin, capture_output=True, text=True,
                       env={**os.environ, "HOME": str(home)})
    assert r.returncode == 0 and r.stdout == ""


# --- the launch gate ----------------------------------------------------------------------------------------------

MODAL = (LEGACY + "FREELAB_EXP=\"$PWD/exp\" modal run --detach lab/backends/modal_app.py::main --run-id exp-01 "
         "--gpu L4 --minutes 20 --args=\"--epochs 3\"")
KAGGLE = LEGACY + "kaggle kernels push -p lab/backends/kaggle-exp-01 -t 1800 --accelerator NvidiaTeslaT4"
LIGHTNING = (LEGACY + "lightning job run --name exp-01 --teamspace me/ts --studio freelab --machine T4 "
             "--command \"cd ~/freelab/exp && python -u train.py --out ~/freelab-runs/exp-01 --max-minutes 20\"")
LOCAL = ("uv run --with-requirements exp/requirements.txt python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backends/local_run.py "
         "exp --run-id exp-01 --when now -- --max-minutes 20")


def ready(lab_proj, estimate_offset_s=-60):
    lab = lab_proj / "lab"
    (lab / "charter.md").write_text(CHARTER)
    add_estimate(lab, estimate_offset_s)


def add_estimate(lab, offset_s):
    t = (datetime.now(timezone.utc) + timedelta(seconds=offset_s)).isoformat(timespec="seconds")
    with (lab / "ledger.jsonl").open("a") as f:
        f.write(json.dumps({"t": t, "backend": "modal", "run": "exp-01", "usd": 0.2, "kind": "estimate",
                            "note": ""}) + "\n")


@pytest.mark.parametrize("command", [MODAL, KAGGLE, LIGHTNING, LOCAL])
def test_launch_passes_when_ready_and_needs_a_new_estimate_next_time(lab_proj, home, command):
    ready(lab_proj)
    assert hook(GUARD, bash(lab_proj, command), home) is None
    assert not (lab_proj / "lab" / ".launches").exists()     # the guard records nothing: the call may not run
    assert hook(GUARD, bash(lab_proj, command), home) is None   # declined or failed: the estimate still counts
    assert hook(POST, post(lab_proj, command), home) is None    # it ran: PostToolUse records it, silently
    launches = (lab_proj / "lab" / ".launches").read_text().splitlines()
    assert len(launches) == 1
    out = hook(GUARD, bash(lab_proj, command), home)
    assert decision(out) == "deny"
    assert "no cost estimate in lab/ledger.jsonl since the last launch" in \
        out["hookSpecificOutput"]["permissionDecisionReason"]
    add_estimate(lab_proj / "lab", 5)
    assert hook(GUARD, bash(lab_proj, command), home) is None


@pytest.mark.parametrize("response,recorded", [
    ({"stdout": "", "stderr": "", "interrupted": False, "isImage": False}, True),
    ({"stdout": "", "stderr": "", "interrupted": True, "isImage": False}, True),     # cannot tell: record
    ({"backgroundTaskId": "b1"}, True),                                              # a background launch
    ("launched", True),
    (None, True),
    ({"stdout": "", "stderr": "boom", "is_error": True}, False),
    ({"stdout": "", "stderr": "boom", "exit_code": 1}, False),
    ({"stdout": "", "stderr": "", "exitCode": 2}, False),
    ({"stdout": "", "stderr": "", "exit_code": 0}, True),
])
def test_post_records_a_launch_unless_it_failed(lab_proj, home, response, recorded):
    ready(lab_proj)
    payload = post(lab_proj, MODAL)
    payload["tool_response"] = response
    assert hook(POST, payload, home) is None
    assert (lab_proj / "lab" / ".launches").exists() == recorded


@pytest.mark.parametrize("command", [
    "modal run --detach lab/backends/modal_app.py::main --run-id smoke-modal-1 --minutes 20 --args=--smoke",
    "modal run --help",
    "lightning job run --help",
    "kaggle kernels status me/x",
    "ls -la",
])
def test_post_ignores_other_commands(lab_proj, home, command):
    assert hook(POST, post(lab_proj, command), home) is None
    assert not (lab_proj / "lab" / ".launches").exists()


def test_post_is_silent_outside_a_lab_project_and_on_bad_input(tmp_path, home):
    other = tmp_path / "other"
    (other / "lab").mkdir(parents=True)
    r = subprocess.run([sys.executable, str(POST)], input=json.dumps(post(other, MODAL)), capture_output=True,
                       text=True, env={**os.environ, "HOME": str(home)})
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert not (other / "lab" / ".launches").exists()
    for stdin in ("", "garbage", "[]", '{"tool_name": "Bash", "tool_input": "x"}'):
        r = subprocess.run([sys.executable, str(POST)], input=stdin, capture_output=True, text=True,
                           env={**os.environ, "HOME": str(home)})
        assert r.returncode == 0 and r.stdout == ""


def test_post_hook_is_registered_for_bash():
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    entry = hooks["PostToolUse"][0]
    assert "Bash" in entry["matcher"].split("|")
    assert entry["hooks"][0]["command"] == 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/post.py"'


@pytest.mark.parametrize("charter,missing", [
    (None, "no lab/charter.md: run the plan skill"),
    ("- **Budget:** USD 0, 1 hour\n", "no Target with a number in lab/charter.md: run the plan skill"),
    ("- **Target:** better accuracy\n- **Budget:** USD 0\n", "no Target with a number"),
    ("- **Target:** accuracy >= 0.8\n", "no Budget in lab/charter.md: run the plan skill"),
])
def test_launch_denied_names_the_missing_piece(lab_proj, home, charter, missing):
    if charter is not None:
        (lab_proj / "lab" / "charter.md").write_text(charter)
    add_estimate(lab_proj / "lab", -60)
    out = hook(GUARD, bash(lab_proj, MODAL), home)
    assert decision(out) == "deny" and missing in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert not (lab_proj / "lab" / ".launches").exists()


def test_launch_without_estimate_is_denied(lab_proj, home):
    (lab_proj / "lab" / "charter.md").write_text(CHARTER)
    out = hook(GUARD, bash(lab_proj, KAGGLE), home)
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert decision(out) == "deny" and "ledger.py add --lab lab --kind estimate" in reason


@pytest.mark.parametrize("command", [
    MODAL.replace(" --minutes 20", ""),
    LOCAL.replace(" -- --max-minutes 20", ""),
    LIGHTNING.replace(" --max-minutes 20", ""),
])
def test_modal_lightning_and_local_need_a_minutes_cap(lab_proj, home, command):
    ready(lab_proj)
    out = hook(GUARD, bash(lab_proj, command), home)
    assert decision(out) == "deny" and "no minutes cap" in out["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("command", [
    "modal run --detach lab/backends/modal_app.py::main --run-id a --gpu L4 --minutes 20 --args=--smoke",
    "modal run app.py::main --run-id a --minutes 20 --args=\"--epochs 1 --smoke\"",
    "kaggle kernels push -p lab/backends/kaggle-smoke-kaggle-20261002 -t 1800",
    "lightning job run --name smoke-lightning-20261002 --command \"python -u train.py --max-minutes 20 --smoke\"",
    "python3 scripts/backends/local_run.py exp --run-id smoke-local --when now -- --smoke",
    "python3 scripts/backends/local_run.py exp --run-id exp-01 --dry-run -- --epochs 1",
    "modal run --help",
    "modal app list",
    "kaggle kernels status me/x",
    "lightning job inspect exp-01 --teamspace me/ts",
    "lightning job run --help",
    "lightning job delete --help",
])
def test_smoke_help_and_other_commands_are_not_gated(lab_proj, home, command):
    assert hook(GUARD, bash(lab_proj, command), home) is None
    assert not (lab_proj / "lab" / ".launches").exists()


@pytest.mark.parametrize("command", [
    "modal run lab/backends/modal_app.py --run-id r2 && ls -h lab/runs",
    "modal run lab/backends/modal_app.py --run-id r2 | tee lab/runs/smoke-modal.log",
    "echo --smoke; modal run lab/backends/modal_app.py --run-id r2",
    "modal run lab/backends/modal_app.py --run-id r2 --minutes 20; modal run --help",
])
def test_smoke_and_help_count_only_in_the_launch_segment(lab_proj, home, command):
    out = hook(GUARD, bash(lab_proj, command), home)   # no charter: the gate blocks it
    assert decision(out) == "deny" and "modal launch blocked" in out["hookSpecificOutput"]["permissionDecisionReason"]
    ready(lab_proj)
    assert hook(POST, post(lab_proj, command), home) is None
    assert len((lab_proj / "lab" / ".launches").read_text().splitlines()) == 1   # post records it too


def test_minutes_cap_counts_only_in_the_launch_segment(lab_proj, home):
    ready(lab_proj)
    out = hook(GUARD, bash(lab_proj, "modal run lab/backends/modal_app.py --run-id r2 && echo --minutes 20"), home)
    assert decision(out) == "deny" and "no minutes cap" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_local_night_run_counts_as_capped(lab_proj, home):
    ready(lab_proj)
    cmd = "python3 scripts/backends/local_run.py exp --run-id exp-01 --when night --nights 2 -- --epochs 3"
    assert hook(GUARD, bash(lab_proj, cmd), home) is None


# --- the Stop hook ------------------------------------------------------------------------------------------------


def stop_input(cwd, active=False, tasks=None):
    d = {"hook_event_name": "Stop", "cwd": str(cwd), "stop_hook_active": active, "last_assistant_message": "done"}
    if tasks is not None:
        d["background_tasks"] = tasks
    return d


def status(lab, runs, events=()):
    (lab / "status.json").write_text(json.dumps({"runs": runs, "events": list(events)}))


def done_run(lab, rid, state="done"):
    (lab / "runs" / rid).mkdir(parents=True, exist_ok=True)
    (lab / "runs" / rid / "summary.json").write_text("{}")
    return {"id": rid, "state": state}


def age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


def test_stop_blocks_once_per_finished_run_without_report(lab_proj, home):
    lab = lab_proj / "lab"
    status(lab, [done_run(lab, "exp-01")])
    out = hook(STOP, stop_input(lab_proj), home)
    assert out["decision"] == "block" and "report skill" in out["reason"] and "exp-01" in out["reason"]
    assert (lab / ".stop-reminded").read_text().split() == ["exp-01"]
    assert hook(STOP, stop_input(lab_proj), home) is None          # at most once per run
    status(lab, [done_run(lab, "exp-01"), done_run(lab, "exp-02")])
    out = hook(STOP, stop_input(lab_proj), home)
    assert out["decision"] == "block" and "exp-02" in out["reason"] and "exp-01" not in out["reason"]


def test_stop_allows_when_report_is_newer_than_the_run(lab_proj, home):
    lab = lab_proj / "lab"
    status(lab, [done_run(lab, "exp-01")])
    age(lab / "runs" / "exp-01" / "summary.json", 600)
    (lab / "report.md").write_text("# Report\n")
    assert hook(STOP, stop_input(lab_proj), home) is None


def test_stop_blocks_when_report_is_older_than_the_run(lab_proj, home):
    lab = lab_proj / "lab"
    (lab / "report.md").write_text("# Report\n")
    age(lab / "report.md", 600)
    status(lab, [done_run(lab, "exp-02")])
    assert hook(STOP, stop_input(lab_proj), home)["decision"] == "block"


@pytest.mark.parametrize("runs", [
    [{"id": "exp-01", "state": "running"}],
    [{"id": "exp-01", "state": "failed"}],
    [{"id": "smoke-modal-20261002", "state": "done"}],
    [],
])
def test_stop_allows_without_a_finished_real_run(lab_proj, home, runs):
    status(lab_proj / "lab", runs)
    assert hook(STOP, stop_input(lab_proj), home) is None


def test_stop_hook_active_allows(lab_proj, home):
    lab = lab_proj / "lab"
    status(lab, [done_run(lab, "exp-01")])
    assert hook(STOP, stop_input(lab_proj, active=True), home) is None
    assert not (lab / ".stop-reminded").exists()


def test_stop_allows_during_a_research_loop(lab_proj, home):
    lab = lab_proj / "lab"
    (lab / "results.tsv").write_text("id\tcommit\tbackend\tgpu\tminutes\tmetric\tstatus\tchange\n"
                                     "exp-01\tabc\tmodal\tT4\t9\t0.81\tkeep\tbaseline\n")
    # events are newest first, as status_page.py event and the poll write them
    events = [{"t": "2026-10-02T10:20:00+00:00", "text": "exp-01 reached 0.81"},
              {"t": "2026-10-02T10:00:00+00:00", "text": "research loop started"},
              {"t": "2026-10-02T09:00:00+00:00", "text": "research loop ended: target met"}]   # an earlier loop
    status(lab, [done_run(lab, "exp-01")], events)
    assert hook(STOP, stop_input(lab_proj), home) is None
    # the loop ended: the stop is checked again
    status(lab, [done_run(lab, "exp-01")], [{"t": "2026-10-02T11:00:00+00:00",
                                              "text": "research loop ended: target met"}] + events)
    assert hook(STOP, stop_input(lab_proj), home)["decision"] == "block"


def test_loop_start_survives_more_than_50_events(lab_proj, home):
    """status_page.py event trims the list to 50 but keeps "research loop ..." events, so a long loop still reads
    as active to the Stop hook and research §3 can still count its hours from the start."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import status_page
    lab = lab_proj / "lab"
    doc = status_page.new_status({"text": "beat 0.85", "metric": "accuracy", "target": 0.85, "direction": "max"},
                                 {"usd_limit": 0, "usd_spent": 0})
    (lab / "status.json").write_text(json.dumps(doc))
    status_page.add_event(lab, "research loop started")
    for i in range(80):
        status_page.add_event(lab, f"exp-{i:02d} discarded")
    events = json.loads((lab / "status.json").read_text())["events"]
    assert len(events) == 50 and events[-1]["text"] == "research loop started"
    assert events[0]["text"] == "exp-79 discarded"
    (lab / "results.tsv").write_text("id\tstatus\nexp-01\tkeep\n")
    d = json.loads((lab / "status.json").read_text())
    d["runs"] = [done_run(lab, "exp-79")]
    (lab / "status.json").write_text(json.dumps(d))
    assert hook(STOP, stop_input(lab_proj), home) is None


def test_stop_after_a_research_loop_report_allows(lab_proj, home):
    lab = lab_proj / "lab"
    (lab / "results.tsv").write_text("id\tstatus\nexp-01\tkeep\n")
    status(lab, [done_run(lab, "exp-01")], [{"t": "x", "text": "research loop started"}])
    for p in (lab / "results.tsv", lab / "runs" / "exp-01" / "summary.json"):
        age(p, 600)
    (lab / "report.md").write_text("# Report\n")
    assert hook(STOP, stop_input(lab_proj), home) is None


def test_stop_after_train_longer_keeps_quiet_for_the_reported_run(lab_proj, home):
    """Train longer: report.md is kept as report-run1.md (mv keeps its time) and a new charter question follows.
    The first run is reported; re-downloading its summary.json must not bring the reminder back."""
    lab = lab_proj / "lab"
    status(lab, [done_run(lab, "exp-01")])
    age(lab / "runs" / "exp-01" / "summary.json", 900)
    (lab / "report.md").write_text("# Report\n\n| Best run (exp-01) | 0.86 |\n")
    age(lab / "report.md", 600)
    (lab / "report.md").rename(lab / "report-run1.md")
    (lab / "charter.md").rename(lab / "charter-run1.md") if (lab / "charter.md").exists() else None
    assert hook(STOP, stop_input(lab_proj), home) is None
    (lab / "runs" / "exp-01" / "summary.json").write_text("{}")   # fetched again: a new mtime
    assert hook(STOP, stop_input(lab_proj), home) is None
    # the next round finishes: that one is new
    status(lab, [done_run(lab, "exp-01"), done_run(lab, "exp-01-r2")])
    out = hook(STOP, stop_input(lab_proj), home)
    assert out["decision"] == "block" and "exp-01-r2" in out["reason"] and "exp-01," not in out["reason"]


def test_stop_counts_a_newer_kept_report_by_time(lab_proj, home):
    lab = lab_proj / "lab"
    status(lab, [done_run(lab, "exp-01")])
    age(lab / "runs" / "exp-01" / "summary.json", 600)
    (lab / "report-run1.md").write_text("# Report\n(no run id named)\n")
    assert hook(STOP, stop_input(lab_proj), home) is None


def test_stop_allows_while_a_run_is_still_active(lab_proj, home):
    lab = lab_proj / "lab"
    for state in ("queued", "starting", "running"):
        status(lab, [done_run(lab, "exp-01"), {"id": "exp-02", "state": state}])
        assert hook(STOP, stop_input(lab_proj), home) is None
    assert not (lab / ".stop-reminded").exists()
    status(lab, [done_run(lab, "exp-01"), {"id": "exp-02", "state": "failed"}])
    assert hook(STOP, stop_input(lab_proj), home)["decision"] == "block"


def test_stop_times_a_run_by_its_own_files_not_status_json(lab_proj, home):
    """A new event rewrites status.json after the report: the run (finished before the report) stays reported."""
    lab = lab_proj / "lab"
    (lab / "runs" / "exp-01").mkdir(parents=True)
    for name in ("status.txt", "metrics.jsonl"):
        (lab / "runs" / "exp-01" / name).write_text("done\n")
        age(lab / "runs" / "exp-01" / name, 900)
    (lab / "report.md").write_text("# Report\n")
    age(lab / "report.md", 600)
    status(lab, [{"id": "exp-01", "state": "done"}], [{"t": "x", "text": "a new event"}])   # written just now
    assert hook(STOP, stop_input(lab_proj), home) is None
    age(lab / "runs" / "exp-01" / "status.txt", 60)   # one file newer, the oldest still counts
    assert hook(STOP, stop_input(lab_proj), home) is None


def test_stop_allows_while_a_poll_runs_in_the_background(lab_proj, home):
    lab = lab_proj / "lab"
    status(lab, [done_run(lab, "exp-01")])
    tasks = [{"id": "t1", "type": "shell", "status": "running",
              "command": "python3 /x/scripts/poll.py modal exp-02 --expected-minutes 10"}]
    assert hook(STOP, stop_input(lab_proj, tasks=tasks), home) is None
    other = [{"id": "t2", "type": "shell", "status": "running", "command": "npm run dev"}]
    assert hook(STOP, stop_input(lab_proj, tasks=other), home)["decision"] == "block"


def test_stop_is_silent_outside_a_lab_project_and_on_bad_input(tmp_path, home):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert hook(STOP, stop_input(plain), home) is None
    lab = tmp_path / "broken" / "lab"
    lab.mkdir(parents=True)
    (lab / "status.json").write_text("{not json")
    assert hook(STOP, stop_input(lab.parent), home) is None
    r = subprocess.run([sys.executable, str(STOP)], input="garbage", capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == ""


def test_onboarding_project_without_lab_allows_stop(tmp_path, home):
    onb = tmp_path / "onb"
    onb.mkdir()
    (onb / ".env").write_text("# freelab: paste each value after the =, no quotes, no spaces\n")
    assert hook(STOP, stop_input(onb), home) is None
