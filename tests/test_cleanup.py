import json, os, subprocess, sys
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cleanup.py"


def write(p: Path, text: str = "x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def ckpt(run: Path, step: int, complete: bool = True) -> Path:
    d = run / "ckpt" / f"step-{step:08d}"
    write(d / "model.bin", "w" * 5000)
    if complete:
        write(d / "COMPLETE", "")
    return d


def make_run(lab: Path, rid: str, status: str, summary: bool = False, steps=(1,)) -> Path:
    run = lab / "runs" / rid
    write(run / "metrics.jsonl", '{"step": 0}\n')
    write(run / "status.txt", status + "\n")
    if summary:
        write(run / "summary.json", "{}")
    for s in steps:
        ckpt(run, s)
    return run


@pytest.fixture
def proj(tmp_path, monkeypatch):
    """A temp project: finished best run, finished discarded run with leftovers, a stopped (resumable) run, an
    ended run, staged copies, a __pycache__, and the files that are always kept."""
    monkeypatch.chdir(tmp_path)
    lab = tmp_path / "lab"
    best = make_run(lab, "exp-01", "done", summary=True, steps=(5,))
    old = make_run(lab, "exp-02", "done", summary=True, steps=(5,))
    (old / "ckpt" / ".tmp-abc").mkdir()
    ckpt(old, 6, complete=False)                       # a torn write
    make_run(lab, "exp-03", "stopped (deadline)", steps=(2,))
    make_run(lab, "exp-04", "failed: boom", steps=())
    write(lab / "runs" / "exp-04" / "ckpt" / "step-00000001" / "partial.bin")  # torn, so not resumable
    write(lab / "status.json", json.dumps({"goal": {"direction": "max"}, "best": {"run": "exp-01", "value": 0.8},
                                           "runs": [{"id": r, "state": "done"} for r in ("exp-01", "exp-02")]}))
    for keep in ("charter.md", "report.md", "ledger.jsonl", "status.html"):
        write(lab / keep)
    write(lab / "__pycache__" / "a.pyc")
    write(lab / "backends" / "modal_app.py")
    write(lab / "backends" / "kaggle-data-bk" / "metrics.jsonl", '{"step": 0}\n')
    write(lab / "backends" / "lightning-bk" / "train.py")
    return tmp_path


def cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def inv():
    r = cli("inventory")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def paths(items, **match):
    return {i["path"] for i in items if all(i.get(k) == v for k, v in match.items())}


def test_inventory_classifies_runs_and_lists_items(proj):
    doc = inv()
    classes = {r["id"]: r["class"] for r in doc["runs"]}
    assert classes == {"exp-01": "finished", "exp-02": "finished", "exp-03": "resumable", "exp-04": "ended"}
    assert [r["id"] for r in doc["runs"] if r["best"]] == ["exp-01"]
    # a resumable run blocks the staged copies and its checkpoints are kept; partial writes are light items
    assert paths(doc["light"]) == {"lab/runs/exp-02/ckpt/.tmp-abc", "lab/runs/exp-02/ckpt/step-00000006",
                                   "lab/__pycache__"}
    assert "lab/runs/exp-01/ckpt/step-00000005" in paths(doc["deep"], recommendation="Keep")
    assert "lab/runs/exp-03/ckpt" in paths(doc["deep"], recommendation="Keep")
    assert {"lab/runs/exp-02/ckpt", "lab/runs/exp-04/ckpt"} <= paths(doc["deep"], recommendation="Remove")
    assert "lab/backends/kaggle-data-bk/metrics.jsonl" in paths(doc["deep"], recommendation="Keep")
    assert all(i["bytes"] >= 0 for i in doc["light"] + doc["deep"])
    assert not any("modal_app.py" in p or p.endswith("charter.md") for p in paths(doc["light"] + doc["deep"]))


def test_light_removes_only_leftover_process_files_and_logs_first(proj):
    r = cli("light")
    assert r.returncode == 0, r.stderr
    lab = proj / "lab"
    assert not (lab / "runs" / "exp-02" / "ckpt" / ".tmp-abc").exists()
    assert not (lab / "runs" / "exp-02" / "ckpt" / "step-00000006").exists()
    assert not (lab / "__pycache__").exists()
    # untouched: complete checkpoints, metrics, summaries, kept files, staged copies (exp-03 is resumable)
    assert (lab / "runs" / "exp-02" / "ckpt" / "step-00000005" / "COMPLETE").exists()
    assert (lab / "runs" / "exp-03" / "ckpt" / "step-00000002").exists()
    assert (lab / "runs" / "exp-02" / "metrics.jsonl").exists() and (lab / "charter.md").exists()
    assert (lab / "backends" / "kaggle-data-bk" / "metrics.jsonl").exists()
    log = [json.loads(l) for l in (lab / "cleanup.jsonl").read_text().splitlines()]
    assert {l["path"] for l in log} == {"lab/runs/exp-02/ckpt/.tmp-abc", "lab/runs/exp-02/ckpt/step-00000006",
                                        "lab/__pycache__"}
    assert all(set(l) == {"t", "where", "path", "bytes"} and l["where"] == "local" for l in log)
    assert "light clean: removed 3 items" in r.stdout
    assert cli("light").stdout.strip() == "light clean: nothing to remove"


def test_light_removes_staged_copies_once_no_run_is_unfinished(proj):
    lab = proj / "lab"
    write(lab / "runs" / "exp-03" / "summary.json", "{}")       # exp-03 finished after all
    import shutil; shutil.rmtree(lab / "runs" / "exp-04" / "ckpt" / "step-00000001")
    write(lab / "runs" / "exp-04" / "status.txt", "failed: boom\n")
    r = cli("light")
    assert r.returncode == 0
    assert not (lab / "backends" / "kaggle-data-bk" / "metrics.jsonl").exists()   # original is in lab/runs
    assert not (lab / "backends" / "lightning-bk").exists()
    assert (lab / "backends" / "modal_app.py").exists()


def test_running_run_keeps_pycache(proj):
    lab = proj / "lab"
    doc = json.loads((lab / "status.json").read_text())
    doc["runs"].append({"id": "exp-05", "state": "running"})
    (lab / "status.json").write_text(json.dumps(doc))
    cli("light")
    assert (lab / "__pycache__").exists()
    assert cli("remove", "lab/__pycache__").returncode == 1


@pytest.mark.parametrize("path,why", [
    ("lab/runs/*/ckpt", "literal"),
    ("lab/runs", "scope"),
    ("lab/runs/exp-02", "scope"),
    ("lab/charter.md", "scope"),
    ("lab/backends/modal_app.py", "scope"),
    ("../elsewhere/ckpt", "relative"),
    ("/tmp/x/lab/runs/exp-02/ckpt", "relative"),
    ("src/model.py", "outside"),
    ("lab/runs/exp-09/ckpt", "not listed"),
    ("lab/runs/exp-03/ckpt", "resumable"),
])
def test_remove_refuses(proj, path, why):
    r = cli("remove", path)
    assert r.returncode == 1 and why in r.stderr
    assert not (proj / "lab" / "cleanup.jsonl").exists()


def test_remove_logs_then_deletes_listed_checkpoints(proj):
    r = cli("remove", "lab/runs/exp-02/ckpt", "lab/runs/exp-04/ckpt")
    assert r.returncode == 0, r.stderr
    lab = proj / "lab"
    assert not (lab / "runs" / "exp-02" / "ckpt").exists() and not (lab / "runs" / "exp-04" / "ckpt").exists()
    assert (lab / "runs" / "exp-02" / "summary.json").exists() and (lab / "runs" / "exp-02" / "metrics.jsonl").exists()
    log = [json.loads(l) for l in (lab / "cleanup.jsonl").read_text().splitlines()]
    assert [l["path"] for l in log] == ["lab/runs/exp-02/ckpt", "lab/runs/exp-04/ckpt"]
    assert log[0]["bytes"] > 0


def test_remove_rechecks_existence(proj):
    assert cli("remove", "lab/runs/exp-02/ckpt").returncode == 0
    r = cli("remove", "lab/runs/exp-02/ckpt")
    assert r.returncode == 1
    lines = (proj / "lab" / "cleanup.jsonl").read_text().splitlines()
    assert len(lines) == 1   # nothing logged for the second, already gone


def test_remove_a_resumable_run_only_when_named(proj):
    r = cli("remove", "lab/runs/exp-03/ckpt", "--include-run", "exp-03")
    assert r.returncode == 0, r.stderr
    assert not (proj / "lab" / "runs" / "exp-03" / "ckpt").exists()


def test_best_checkpoint_is_removable_only_when_picked_by_path(proj):
    r = cli("remove", "lab/runs/exp-01/ckpt/step-00000005")
    assert r.returncode == 0, r.stderr
    assert (proj / "lab" / "runs" / "exp-01" / "summary.json").exists()


def test_results_tsv_marks_finished_and_worktrees(proj):
    lab = proj / "lab"
    write(lab / "results.tsv", "id\tcommit\tbackend\tgpu\tminutes\tmetric\tstatus\tchange\n"
                               "exp-03\tabc\tmodal\tT4\t20\t0.7\tdiscard\ttry x\n")
    (lab / "worktrees" / "exp-03").mkdir(parents=True)   # not a git worktree: git status fails, so not light
    (lab / "worktrees" / "exp-07").mkdir(parents=True)
    doc = inv()
    assert {r["id"]: r["class"] for r in doc["runs"]}["exp-03"] == "finished"
    assert "lab/worktrees/exp-07" in paths(doc["deep"], recommendation="Keep")
    assert cli("remove", "lab/worktrees/exp-07").returncode == 1


def test_light_removes_a_clean_research_worktree_with_git(proj):
    git = lambda *a: subprocess.run(["git", *a], cwd=proj, capture_output=True, text=True, check=True)
    git("init", "-q")
    write(proj / ".gitignore", "lab/\n")
    write(proj / "train.py", "print(1)\n")
    git("add", ".gitignore", "train.py")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    git("worktree", "add", "-q", "--detach", "lab/worktrees/exp-03")
    write(proj / "lab" / "results.tsv", "id\tcommit\tbackend\tgpu\tminutes\tmetric\tstatus\tchange\n"
                                        "exp-03\tabc\tmodal\tT4\t20\t0.7\tdiscard\ttry x\n")
    assert "lab/worktrees/exp-03" in paths(inv()["light"], kind="worktree")
    r = cli("light")
    assert r.returncode == 0 and "removed lab/worktrees/exp-03" in r.stdout
    assert not (proj / "lab" / "worktrees" / "exp-03").exists()
    assert "exp-03" not in git("worktree", "list").stdout


def test_light_removes_poll_tmp_but_not_poll_json_lock_or_a_running_runs_folder(proj):
    lab = proj / "lab"
    doc = json.loads((lab / "status.json").read_text())
    doc["runs"].append({"id": "exp-05", "state": "running"})
    (lab / "status.json").write_text(json.dumps(doc))
    write(lab / "runs" / "exp-05" / "status.txt", "running\n")
    for rid in ("exp-02", "exp-03", "exp-05"):
        write(lab / "runs" / rid / ".poll-tmp" / "metrics.jsonl", "{}\n")
        write(lab / "runs" / rid / ".poll.json", "{}")
    write(lab / ".status.lock", "")
    r = cli("light")
    assert r.returncode == 0, r.stderr
    assert not (lab / "runs" / "exp-02" / ".poll-tmp").exists()      # finished
    assert not (lab / "runs" / "exp-03" / ".poll-tmp").exists()      # resumable: no poll is running for it
    assert (lab / "runs" / "exp-05" / ".poll-tmp").exists()          # a poll may be fetching into it
    assert all((lab / "runs" / rid / ".poll.json").exists() for rid in ("exp-02", "exp-03", "exp-05"))
    assert (lab / ".status.lock").exists()
    log = [json.loads(l)["path"] for l in (lab / "cleanup.jsonl").read_text().splitlines()]
    assert "lab/runs/exp-02/.poll-tmp" in log and "lab/runs/exp-03/.poll-tmp" in log
    assert "lab/runs/exp-05/.poll-tmp" not in log


@pytest.fixture
def loop_proj(proj):
    """The temp project as a git repo with the research loop's worktree lab/worktrees/loop on branch lab/demo."""
    git = lambda *a, cwd=proj: subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True)
    git("init", "-q")
    write(proj / ".gitignore", "lab/\n")
    write(proj / "train.py", "print(1)\n")
    git("add", ".gitignore", "train.py")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    git("worktree", "add", "-q", "lab/worktrees/loop", "-b", "lab/demo")
    return git


def test_loop_worktree_is_a_deep_item_removed_with_git_keeping_the_branch(loop_proj):
    git = loop_proj
    doc = inv()
    assert "lab/worktrees/loop" not in paths(doc["light"])
    item = next(i for i in doc["deep"] if i["path"] == "lab/worktrees/loop")
    assert item["kind"] == "worktree" and item["recommendation"].startswith("Remove") and "blocked" not in item
    r = cli("remove", "lab/worktrees/loop")
    assert r.returncode == 0 and "removed lab/worktrees/loop" in r.stdout, r.stderr
    assert not (Path("lab") / "worktrees" / "loop").exists()
    assert "lab/worktrees/loop" not in git("worktree", "list").stdout.replace(str(Path.cwd()), "")
    assert "lab/demo" in git("branch", "--list", "lab/demo").stdout          # the branch stays
    log = [json.loads(l) for l in (Path("lab") / "cleanup.jsonl").read_text().splitlines()]
    assert log[-1]["path"] == "lab/worktrees/loop" and log[-1]["where"] == "local"


def test_loop_worktree_refused_with_uncommitted_changes(loop_proj):
    write(Path("lab/worktrees/loop/new.py"), "x = 1\n")
    item = next(i for i in inv()["deep"] if i["path"] == "lab/worktrees/loop")
    assert "uncommitted" in item["blocked"]
    r = cli("remove", "lab/worktrees/loop")
    assert r.returncode == 1 and "uncommitted" in r.stderr
    assert (Path("lab") / "worktrees" / "loop" / "new.py").exists()
    assert not (Path("lab") / "cleanup.jsonl").exists()


def test_loop_worktree_refused_while_a_run_is_running(loop_proj):
    lab = Path("lab")
    doc = json.loads((lab / "status.json").read_text())
    doc["runs"].append({"id": "exp-05", "state": "running"})
    (lab / "status.json").write_text(json.dumps(doc))
    item = next(i for i in inv()["deep"] if i["path"] == "lab/worktrees/loop")
    assert item["blocked"] == "a run is running"
    r = cli("remove", "lab/worktrees/loop")
    assert r.returncode == 1 and "running" in r.stderr
    assert (lab / "worktrees" / "loop").exists()


def test_size_bytes_falls_back_to_the_file_size_without_st_blocks(tmp_path, monkeypatch):
    """Windows has no st_blocks: the size is then the sum of the file sizes, rounded up to whole KiB."""
    sys.path.insert(0, str(SCRIPT.parent))
    import cleanup
    write(tmp_path / "d" / "a.bin", "x" * 3000)
    write(tmp_path / "d" / "sub" / "b.bin", "y" * 100)
    real = os.lstat

    class NoBlocks:
        def __init__(self, st):
            self.st_size, self.st_mode = st.st_size, st.st_mode

    monkeypatch.setattr(cleanup.os, "lstat", lambda p: NoBlocks(real(p)))
    monkeypatch.setattr(cleanup.Path, "lstat", lambda self: NoBlocks(real(self)))
    dirs = real(tmp_path / "d").st_size + real(tmp_path / "d" / "sub").st_size
    assert cleanup.size_bytes(tmp_path / "d") == -(-(3100 + dirs) // 1024) * 1024
    assert cleanup.size_bytes(tmp_path / "d" / "a.bin") == 3072
