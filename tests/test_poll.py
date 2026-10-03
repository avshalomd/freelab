import json, re, shutil, subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import poll
import status_page as sp

GOAL = {"text": "Route bank messages", "metric": "accuracy", "target": 0.8, "direction": "max"}
BUDGET = {"usd_limit": 30, "usd_spent": 0.0, "free_credit_note": "Modal free credit"}
TEST_VALUE = 0.9123  # a test score: must never reach stdout


def rows(*val_steps, train_to=0, total=290, test=False):
    out = [{"t": f"2026-10-02T10:{s // 60:02d}:{s % 60:02d}+00:00", "step": s, "total": total, "split": "train",
            "name": "loss", "value": 2.0 - s / 300} for s in range(1, train_to + 1)]
    for i, s in enumerate(val_steps):
        out.append({"t": "2026-10-02T10:00:00+00:00", "step": s, "total": total, "split": "val",
                    "name": "accuracy", "value": round(0.535 + 0.1 * i, 3)})
        out.append({"t": "2026-10-02T10:00:00+00:00", "step": s, "total": total, "split": "val", "name": "ece",
                    "value": 0.1})
    if test:
        out.append({"t": "2026-10-02T10:00:00+00:00", "step": 0, "total": total, "split": "test",
                    "name": "accuracy", "value": TEST_VALUE})
    return "".join(json.dumps(r) + "\n" for r in out)


@pytest.fixture
def proj(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    lab = root / "lab"
    lab.mkdir(parents=True)
    doc = sp.new_status(GOAL, BUDGET)
    doc["runs"] = [{"id": "r1", "backend": "modal L4", "state": "starting", "step": None, "total": None,
                    "metric": None, "eta": None, "detail": "launched",
                    "started": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")}]
    (lab / "status.json").write_text(json.dumps(doc))
    withenv = tmp_path / "withenv"
    withenv.write_text("#!/bin/sh\nexit 0\n")
    withenv.chmod(0o755)
    monkeypatch.setenv("FREELAB_WITHENV", str(withenv))
    monkeypatch.chdir(root)
    monkeypatch.setattr(poll, "_sleep", lambda s: None)
    return root


class FakeCloud:
    """Stands in for the backend CLIs: files of the 'remote' run live in self.remote; steps run on each sleep."""

    def __init__(self, tmp_path, monkeypatch):
        self.remote = tmp_path / "remote"
        self.remote.mkdir()
        self.calls = []
        self.kaggle_status = "running"
        self.lightning_status = "Running"
        self.empty = set()   # names that download as an empty file
        self.modal_apps = []  # what `modal app list --json` returns
        self.steps = []
        monkeypatch.setattr(poll, "_run", self.run)
        monkeypatch.setattr(poll, "_sleep", self.sleep)

    def put(self, name, text):
        (self.remote / name).write_text(text)

    def sleep(self, seconds):
        if self.steps:
            self.steps.pop(0)()

    def _copy(self, name, dest: Path):
        src = self.remote / name
        if name in self.empty:
            dest.write_text("")
            return 0
        if not src.exists():
            return 1
        shutil.copy(src, dest)
        return 0

    def run(self, cmd, cwd, timeout=120):
        self.calls.append(cmd)
        rc, out = 1, ""
        if cmd[:4] == ["modal", "volume", "get", "--force"]:
            name = cmd[5].split("/", 1)[1]
            rc = self._copy(name, Path(cmd[6]) / name)
        elif cmd[:4] == ["modal", "app", "list", "--json"]:
            rc, out = 0, json.dumps(self.modal_apps)
        elif cmd[:3] == ["kaggle", "kernels", "status"]:
            rc, out = 0, f'{cmd[3]} has status "KernelWorkerStatus.{self.kaggle_status.upper()}"'
        elif cmd[:3] == ["kaggle", "kernels", "output"]:
            dest = Path(cmd[cmd.index("-p") + 1])
            for name in ("status.txt", "metrics.jsonl", "summary.json"):
                self._copy(name, dest / name)
            rc = 0
        elif cmd[:3] == ["lightning", "job", "inspect"]:
            rc, out = 0, json.dumps({"name": cmd[3], "status": self.lightning_status, "total_cost": 0.1})
        elif cmd[:2] == ["lightning", "cp"]:
            name = cmd[2].rsplit("/", 1)[1]
            rc = self._copy(name, Path(cmd[3]))
        return subprocess.CompletedProcess(cmd, rc, out, "")


@pytest.fixture
def cloud(tmp_path, monkeypatch, proj):
    return FakeCloud(tmp_path, monkeypatch)


def status(root):
    return json.loads((root / "lab" / "status.json").read_text())


def run_of(root, rid="r1"):
    return next(r for r in status(root)["runs"] if r["id"] == rid)


# --- cadence ---

@pytest.mark.parametrize("expected, seconds", [(None, 60), (10, 30), (29, 30), (30, 90), (180, 90), (181, 300),
                                               (720, 300), (721, 900), (3000, 900)])
def test_cadence_follows_the_expected_length(expected, seconds):
    now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    assert poll.cadence(expected, now - timedelta(minutes=10), now) == seconds


def test_cadence_is_30_s_in_the_first_5_minutes_and_every_overrides():
    now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    assert poll.cadence(600, now - timedelta(minutes=2), now) == 30
    assert poll.cadence(600, now - timedelta(minutes=6), now) == 300
    assert poll.cadence(600, now - timedelta(minutes=2), now, every=45) == 45


# --- one tick ---

def test_once_updates_status_json_and_the_page(cloud, proj, capsys):
    cloud.put("status.txt", "epoch 1/3, step 120/290, loss 1.234\n")
    cloud.put("metrics.jsonl", rows(0, 97, train_to=120, test=True))
    code = poll.main(["modal", "r1", "--once", "--expected-minutes", "15",
                      "--link", "https://modal.com/apps/me/main/ap-123"])
    assert code == 0
    run = run_of(proj)
    assert run["state"] == "running" and run["step"] == 120 and run["total"] == 290
    assert run["metric"] == 0.635 and run["detail"] == "epoch 1/3, step 120/290, loss 1.234"
    assert run["link"] == "https://modal.com/apps/me/main/ap-123" and run["expected_minutes"] == 15
    assert run["eta"]  # from the pace of the training rows
    doc = status(proj)
    assert doc["refresh_seconds"] == 30
    texts = [e["text"] for e in doc["events"]]
    assert any("validation accuracy 63.5% at step 97 of 290 (start 53.5%)" in t for t in texts)
    assert any("at the start: 53.5%" in t for t in texts)
    html = (proj / "lab" / "status.html").read_text()
    assert "Live · reloads every 30 s" in html and "Open on Modal" in html
    assert '<meta http-equiv="refresh" content="30">' in html
    out = capsys.readouterr().out
    assert "r1: val accuracy 0.535 at step 0 (start)" in out
    assert "r1: val accuracy 0.635 at step 97/290 (start 0.535)" in out
    assert "now: running step=120/290 val=0.635" in out
    assert not re.search(r"\btest\b", out) and str(TEST_VALUE) not in out
    # the commands went to the backend's CLI (through withenv, see test_commands_go_through_withenv)
    assert ["modal", "volume", "get", "--force", "freelab-runs", "r1/status.txt"] == cloud.calls[0][:6]


def test_a_second_check_adds_no_repeat_events_or_lines(cloud, proj, capsys):
    cloud.put("status.txt", "epoch 1/3\n")
    cloud.put("metrics.jsonl", rows(0, 97, train_to=100))
    poll.main(["modal", "r1", "--once"])
    n = len(status(proj)["events"])
    capsys.readouterr()
    poll.main(["modal", "r1", "--once"])
    assert len(status(proj)["events"]) == n
    assert "val accuracy" not in capsys.readouterr().out


def test_an_empty_or_failed_download_keeps_the_last_metrics(cloud, proj):
    run_dir = proj / "lab" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    good = rows(0, 97, train_to=100)
    (run_dir / "metrics.jsonl").write_text(good)
    cloud.put("status.txt", "epoch 1/3\n")
    cloud.empty.add("metrics.jsonl")
    poll.main(["modal", "r1", "--once"])
    assert (run_dir / "metrics.jsonl").read_text() == good
    cloud.empty.clear()
    cloud.put("metrics.jsonl", rows(0, train_to=10))  # smaller than the copy we have: a stale view
    poll.main(["modal", "r1", "--once"])
    assert (run_dir / "metrics.jsonl").read_text() == good
    (cloud.remote / "metrics.jsonl").unlink()  # the command fails
    poll.main(["modal", "r1", "--once"])
    assert (run_dir / "metrics.jsonl").read_text() == good
    assert run_of(proj)["metric"] == 0.635


@pytest.mark.parametrize("final, code", [("done", 0), ("stopped (deadline)", 3), ("failed: CUDA out of memory", 1)])
def test_loops_until_the_run_ends_with_its_exit_code(cloud, proj, capsys, final, code):
    cloud.put("status.txt", "epoch 1/3\n")
    cloud.put("metrics.jsonl", rows(0, train_to=50, test=True))
    cloud.steps = [lambda: cloud.put("metrics.jsonl", rows(0, 97, train_to=100, test=True)),
                   lambda: (cloud.put("status.txt", final + "\n"),
                            cloud.put("metrics.jsonl", rows(0, 97, 194, train_to=200, test=True)))]
    assert poll.main(["modal", "r1", "--every", "1"]) == code
    out = capsys.readouterr().out.splitlines()
    state = final.split()[0].rstrip(":")
    assert out[-1] == f"final: {state} step=200/290 val=0.735"
    assert [l for l in out if "val accuracy" in l][-1] == "r1: val accuracy 0.735 at step 194/290 (start 0.535)"
    assert not any("test" in l or str(TEST_VALUE) in l for l in out)
    run = run_of(proj)
    assert run["state"] == state and run["eta"] is None
    html = (proj / "lab" / "status.html").read_text()
    assert "http-equiv" not in html  # the page stops reloading once nothing is active
    texts = " ".join(e["text"] for e in status(proj)["events"])
    if state == "failed":
        assert "r1 failed on Modal (L4): CUDA out of memory." in texts
    elif state == "stopped":
        assert "r1 stopped on Modal (L4) (deadline)." in texts
    else:
        assert "r1 finished on Modal (L4): validation accuracy 73.5%." in texts


def test_commands_go_through_withenv(proj, tmp_path, monkeypatch):
    log = tmp_path / "calls.log"
    stand_in = tmp_path / "withenv-log"
    stand_in.write_text(f'#!/bin/sh\necho "$PWD|$*" >> "{log}"\nexit 1\n')
    stand_in.chmod(0o755)
    monkeypatch.setenv("FREELAB_WITHENV", str(stand_in))
    assert poll.main(["modal", "r1", "--once"]) == 0
    calls = log.read_text().splitlines()
    assert len(calls) == 3
    assert all(c.startswith(f"{proj.resolve()}|modal volume get --force freelab-runs r1/") for c in calls)


def test_default_withenv_is_the_plugins_script(monkeypatch):
    monkeypatch.delenv("FREELAB_WITHENV", raising=False)
    assert poll._withenv() == str(Path(poll.__file__).resolve().parent / "withenv")


def test_bad_link_missing_status_and_max_hours(cloud, proj, capsys):
    assert poll.main(["modal", "r1", "--once", "--link", "javascript:alert(1)"]) == 1
    cloud.put("status.txt", "epoch 1/3\n")
    assert poll.main(["modal", "r1", "--max-hours", "0"]) == 1
    assert "stopped watching" in capsys.readouterr().out
    (proj / "lab" / "status.json").unlink()   # no status.json (onboarding's connection check): the poll starts one
    assert poll.main(["modal", "r1", "--once"]) == 0
    assert status(proj)["goal"] == {"text": "connection check", "metric": "accuracy", "target": None,
                                    "direction": "max"}
    assert run_of(proj)["state"] == "running" and (proj / "lab" / "status.html").is_file()


def test_tick_errors_honour_every_max_hours_and_give_up(cloud, proj, capsys, monkeypatch):
    """A status.json the poll cannot update (here a JSON list) must not loop forever: each error sleeps the
    --every cadence, --max-hours still ends the watch, and MAX_TICK_ERRORS errors in a row give up."""
    (proj / "lab" / "status.json").write_text("[]")
    slept = []
    monkeypatch.setattr(poll, "_sleep", slept.append)
    assert poll.main(["modal", "r1", "--every", "7"]) == 1
    assert slept == [7] * (poll.MAX_TICK_ERRORS - 1)
    captured = capsys.readouterr()
    assert captured.out.splitlines()[-1].startswith(f"poll: gave up after {poll.MAX_TICK_ERRORS} checks in a row")
    assert "status.json must be a JSON object" in captured.err
    slept.clear()
    assert poll.main(["modal", "r1", "--every", "7", "--max-hours", "0"]) == 1
    assert slept == [] and "stopped watching after 0 h" in capsys.readouterr().out
    (proj / "lab" / "status.json").write_text('{"runs": "x", "goal": {}}')   # a dict with the wrong shapes
    assert poll.main(["modal", "r1", "--once"]) == 1


def test_a_tick_error_then_recovery_resets_the_count(cloud, proj, monkeypatch):
    good = (proj / "lab" / "status.json").read_text()
    (proj / "lab" / "status.json").write_text("[]")
    cloud.put("status.txt", "done\n")
    cloud.steps = [lambda: (proj / "lab" / "status.json").write_text(good)]
    assert poll.main(["modal", "r1", "--every", "1"]) == 0
    assert run_of(proj)["state"] == "done"


@pytest.mark.parametrize("argv", [
    ["modal", "r1", "--expected-minutes", "0"],
    ["modal", "r1", "--expected-minutes", "-5"],
    ["modal", "r1", "--every", "0"],
    ["modal", "../escape"],
    ["modal", "-r1"],
    ["modal", "r 1"],
])
def test_bad_arguments_are_refused_before_anything_is_written(cloud, proj, argv):
    before = (proj / "lab" / "status.json").read_text()
    with pytest.raises(SystemExit) as e:
        poll.main(argv + ["--once"])
    assert e.value.code == 2
    assert (proj / "lab" / "status.json").read_text() == before


def test_the_end_of_run_counters_restart_when_the_provider_runs_again(cloud, proj, monkeypatch):
    kaggle_lab(proj)
    monkeypatch.setattr(poll, "_popen_stream", lambda cmd, cwd, log: 4242)
    monkeypatch.setattr(poll, "_stream_alive", lambda pid: False)
    run_dir = proj / "lab" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / ".poll.json").write_text(json.dumps({"provider": "complete", "fetch_tries": 3,
                                                    "stream_starts": 1 + poll.STREAM_RESTARTS}))
    cloud.kaggle_status = "running"   # relaunched under the same id
    assert poll.main(["kaggle", "r1", "--once"]) == 0
    memo = json.loads((run_dir / ".poll.json").read_text())
    assert "fetch_tries" not in memo and "stream_starts" not in memo and memo["provider"] == "running"
    assert poll.main(["kaggle", "r1", "--once"]) == 0
    assert json.loads((run_dir / ".poll.json").read_text())["stream_starts"] == 1   # the stream starts again


def test_a_run_missing_from_status_json_is_added(cloud, proj):
    cloud.put("status.txt", "epoch 1/3\n")
    poll.main(["modal", "r2", "--once"])
    run = run_of(proj, "r2")
    assert run["state"] == "running" and run["backend"] == "modal"
    sp.validate(status(proj))


# --- Kaggle, Lightning, local ---

def kaggle_lab(proj):
    d = proj / "lab" / "backends" / "kaggle-r1"
    d.mkdir(parents=True)
    (d / "kernel-metadata.json").write_text(json.dumps({"id": "alice/freelab-r1"}))


def test_kaggle_reads_the_live_log_and_restarts_the_stream(cloud, proj, monkeypatch, capsys):
    kaggle_lab(proj)
    starts = []
    monkeypatch.setattr(poll, "_popen_stream", lambda cmd, cwd, log: starts.append(cmd) or 4242)
    monkeypatch.setattr(poll, "_stream_alive", lambda pid: False)  # the stream keeps exiting
    run_dir = proj / "lab" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "live.log").write_text(
        f"eval test accuracy {TEST_VALUE} at step 0\neval val accuracy 0.535 at step 0\n"
        "step 1/290 (0%), loss 4.10, 0.1 min\nstep 50/290 (17%), loss 1.23, 2.0 min\n")
    for _ in range(6):
        assert poll.main(["kaggle", "r1", "--once"]) == 0
    assert len(starts) == 1 + poll.STREAM_RESTARTS
    assert starts[0] == ["kaggle", "kernels", "logs", "-f", "alice/freelab-r1"]
    run = run_of(proj)
    assert run["state"] == "running" and (run["step"], run["total"]) == (50, 290)
    assert run["metric"] == 0.535 and run["detail"] == "step 50/290 (17%), loss 1.23, 2.0 min"
    assert run["link"] == "https://www.kaggle.com/code/alice/freelab-r1" and run["eta"] == "10 min"
    out = capsys.readouterr().out
    assert "r1: val accuracy 0.535 at step 0 (start)" in out and str(TEST_VALUE) not in out

    # the kernel completes: the small files are fetched and the poll ends
    cloud.kaggle_status = "complete"
    cloud.put("status.txt", "done\n")
    cloud.put("metrics.jsonl", rows(0, 145, 290, train_to=290, test=True))
    cloud.put("summary.json", json.dumps({"final_accuracy": TEST_VALUE}))
    assert poll.main(["kaggle", "r1", "--once"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[-1] == "final: done step=290/290 val=0.735" and str(TEST_VALUE) not in out
    assert any(c[:3] == ["kaggle", "kernels", "output"] and "--file-pattern" in c for c in cloud.calls)
    assert (run_dir / "summary.json").exists() and (run_dir / "live.log").exists()
    assert not (run_dir / ".poll-tmp").exists()


def test_kaggle_queued_then_starting(cloud, proj, monkeypatch):
    kaggle_lab(proj)
    monkeypatch.setattr(poll, "_popen_stream", lambda cmd, cwd, log: 1)
    monkeypatch.setattr(poll, "_stream_alive", lambda pid: True)
    cloud.kaggle_status = "queued"
    poll.main(["kaggle", "r1", "--once"])
    assert run_of(proj)["state"] == "queued" and "Waiting for a free machine" in run_of(proj)["detail"]
    cloud.kaggle_status = "running"
    poll.main(["kaggle", "r1", "--once"])
    assert run_of(proj)["state"] == "starting" and run_of(proj)["step"] is None


def test_kaggle_complete_but_files_missing_waits_then_gives_up(cloud, proj, monkeypatch, capsys):
    kaggle_lab(proj)
    cloud.kaggle_status = "complete"
    for _ in range(poll.FETCH_TRIES - 1):
        assert poll.main(["kaggle", "r1", "--once"]) == 0
        assert "fetching the results" in run_of(proj)["detail"]
    assert poll.main(["kaggle", "r1", "--once"]) == 1
    detail = run_of(proj)["detail"]
    assert run_of(proj)["state"] == "failed" and "results could not be fetched: fetch them by hand" in detail
    assert "final: failed" in capsys.readouterr().out


def test_kaggle_needs_a_kernel_ref(cloud, proj):
    assert poll.main(["kaggle", "r1", "--once"]) == 1
    assert poll.main(["kaggle", "r1", "--once", "--kernel", "bob/freelab-r1"]) == 0


def test_lightning_copies_metrics_live(cloud, proj, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "onboarded").write_text(json.dumps({"lightning_teamspace": "org/ts"}))
    cloud.put("status.txt", "epoch 2/3\n")
    cloud.put("metrics.jsonl", rows(0, 97, train_to=150))
    assert poll.main(["lightning", "r1", "--once"]) == 0
    run = run_of(proj)
    assert run["state"] == "running" and run["step"] == 150 and run["metric"] == 0.635
    assert ["lightning", "job", "inspect", "r1", "--teamspace", "org/ts"] in cloud.calls
    assert any(c[:3] == ["lightning", "cp", "lit://org/ts/jobs/r1/freelab-runs/r1/metrics.jsonl"]
               for c in cloud.calls)
    cloud.lightning_status = "Completed"
    cloud.put("status.txt", "done\n")
    assert poll.main(["lightning", "r1", "--once"]) == 0
    assert run_of(proj)["state"] == "done"


def test_lightning_running_before_any_status_line_is_running(cloud, proj, tmp_path, monkeypatch):
    """A non-Kaggle provider that says the job runs is enough before the run writes its first status line."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "onboarded").write_text(json.dumps({"lightning_teamspace": "org/ts"}))
    monkeypatch.setenv("FREELAB_HOME", str(home))
    assert poll.main(["lightning", "r1", "--once"]) == 0
    assert run_of(proj)["state"] == "running"
    assert any("r1 started training on" in e["text"] for e in status(proj)["events"])
    cloud.lightning_status = "Pending"   # queued with no status line stays queued/starting
    doc = status(proj)
    doc["runs"][0]["state"] = "starting"
    (proj / "lab" / "status.json").write_text(json.dumps(doc))
    assert poll.main(["lightning", "r1", "--once"]) == 0
    assert run_of(proj)["state"] in ("queued", "starting")


def test_poll_events_keep_the_research_loop_start(cloud, proj):
    doc = status(proj)
    doc["events"] = [{"t": "2026-10-02T10:00:00+00:00", "text": f"exp-{i} discarded"} for i in range(49)] + [
        {"t": "2026-10-02T09:00:00+00:00", "text": "research loop started"}]
    (proj / "lab" / "status.json").write_text(json.dumps(doc))
    cloud.put("status.txt", "epoch 1/3\n")
    cloud.put("metrics.jsonl", rows(0, 97, train_to=150))
    assert poll.main(["modal", "r1", "--once"]) == 0
    events = status(proj)["events"]
    assert len(events) == sp.EVENTS_CAP and events[-1]["text"] == "research loop started"


def test_local_reads_the_run_directory(proj, monkeypatch, capsys):
    monkeypatch.setattr(poll, "_run", lambda *a, **k: pytest.fail("local runs need no command"))
    run_dir = proj / "lab" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "status.txt").write_text("stopped (allowance)\n")
    (run_dir / "metrics.jsonl").write_text(rows(0, 97, train_to=100, test=True))
    assert poll.main(["local", "r1", "--once"]) == 3
    out = capsys.readouterr().out
    assert out.splitlines()[-1] == "final: stopped step=100/290 val=0.635" and str(TEST_VALUE) not in out


def test_live_log_parsing_ignores_test_lines(tmp_path):
    log = tmp_path / "live.log"
    log.write_text("noise\neval val accuracy 0.700 at step 0\nstep 25/100 (25%), loss 0.50, 1.0 min\n"
                   "eval test accuracy 0.990 at step 100\neval val accuracy 0.800 at step 100\n")
    progress, evals = poll.read_live_log(log)
    assert progress == {"step": 25, "total": 100, "minutes": 1.0, "text": "step 25/100 (25%), loss 0.50, 1.0 min"}
    assert [(e["step"], e["value"]) for e in evals] == [(0, 0.7), (100, 0.8)]


@pytest.mark.parametrize("text, state", [('a/b has status "running"', "running"),
                                         ('a/b has status "KernelWorkerStatus.COMPLETE"', "complete"),
                                         ('a/error-analysis has status "queued"', "queued"),
                                         ('a/b has status "cancelAcknowledged"', "cancelled"),
                                         ('a/b has status "error"', "error"), ("garbage", None)])
def test_kaggle_status_parsing(text, state):
    assert poll.kaggle_state(text) == state


# --- a Modal container that dies without writing status.txt ---

def test_modal_app_stopped_without_status_ends_as_failed(cloud, proj):
    link = "https://modal.com/apps/ws/main/ap-Dead123"
    cloud.put("metrics.jsonl", rows(0, 145))
    cloud.modal_apps = [{"app_id": "ap-Dead123", "state": "stopped"}]
    rc = poll.main(["modal", "r1", "--link", link, "--every", "1", "--max-hours", "1"])
    assert rc == 1
    assert run_of(proj)["state"] == "failed"


def test_modal_app_stopped_with_done_status_is_done(cloud, proj):
    cloud.put("metrics.jsonl", rows(0, 145, 290))
    cloud.put("status.txt", "done\n")
    cloud.modal_apps = [{"app_id": "ap-Ok123", "state": "stopped"}]
    rc = poll.main(["modal", "r1", "--link", "https://modal.com/apps/ws/main/ap-Ok123", "--every", "1"])
    assert rc == 0
    assert run_of(proj)["state"] == "done"
    assert not any(c[:3] == ["modal", "app", "list"] for c in cloud.calls)


def test_modal_running_app_keeps_polling(cloud, proj):
    cloud.put("metrics.jsonl", rows(0))
    cloud.modal_apps = [{"app_id": "ap-Live1", "state": "ephemeral (detached)"}]
    rc = poll.main(["modal", "r1", "--link", "https://modal.com/apps/ws/main/ap-Live1", "--once"])
    assert rc == 0
    assert run_of(proj)["state"] in ("starting", "running")


# --- the run contract, end to end ---

def test_a_run_folder_written_by_runlib_reads_back_in_poll_and_the_page(proj, capsys):
    """Write a run folder with runlib.Run the way examples/banking77-laya/train.py does (status lines, val and test
    rows through run.log, train loss, run.finish(summary)), then poll it as a local run: the field names agree."""
    import argparse
    import runlib
    out = proj / "lab" / "runs" / "r1"
    args = argparse.Namespace(out=str(out), resume=False, max_minutes=0.0, smoke=False)
    total = 4
    with runlib.Run(args) as run:
        run.status("zero-shot evaluation")
        run.log(0, total, "test", "accuracy", TEST_VALUE)
        run.log(0, total, "val", "accuracy", 0.5)
        for step in range(1, total + 1):
            run.log(step, total, "train", "loss", 2.0 / step)
            run.status(f"epoch 1/1, step {step}/{total}, loss {2.0 / step:.3f}")
        run.log(total, total, "val", "accuracy", 0.75)
        run.log(total, total, "test", "accuracy", TEST_VALUE)
        run.finish({"final_accuracy": TEST_VALUE, "zero_shot_accuracy": 0.4})
    assert runlib.exit_code(run) == 0
    assert poll.main(["local", "r1", "--once"]) == 0
    stdout = capsys.readouterr().out
    assert stdout.splitlines()[-1] == "final: done step=4/4 val=0.75" and str(TEST_VALUE) not in stdout
    r = run_of(proj)
    assert (r["state"], r["step"], r["total"], r["metric"]) == ("done", 4, 4, 0.75)
    sp.validate(status(proj))
    html = (proj / "lab" / "status.html").read_text()
    assert "75%" in html and not re.search(r"\bnan\b", html, re.I)


# --- 0.4.1 ---------------------------------------------------------------------------------------

def _train_rows(start: datetime, steps, every_s=6.0, step0=1):
    return [{"t": (start + timedelta(seconds=i * every_s)).isoformat(), "step": step0 + i, "total": 1000,
             "split": "train", "name": "loss", "value": 1.0} for i in range(steps)]


def test_eta_rate_ignores_the_gap_before_a_resume():
    t0 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    before = _train_rows(t0, 30)                                       # 1 step every 6 s
    after = _train_rows(t0 + timedelta(hours=20), 10, step0=31)        # resumed 20 h later, same pace
    step, total, rate = poll._progress_rows(before + after)
    assert step == 40 and total == 1000 and rate == pytest.approx(1 / 6)
    _, _, steady = poll._progress_rows(_train_rows(t0, 40))
    assert steady == pytest.approx(1 / 6)
    _, _, just_resumed = poll._progress_rows(before + after[:1])       # one row since the resume: no rate yet
    assert just_resumed is None


def test_no_status_json_starts_one_with_the_given_goal(tmp_path, monkeypatch):
    lab = tmp_path / "proj" / "lab"
    run_dir = lab / "runs" / "smoke"
    run_dir.mkdir(parents=True)
    (run_dir / "status.txt").write_text("done\n")
    (run_dir / "metrics.jsonl").write_text(rows(0, 50, train_to=50, total=50))
    assert poll.main(["local", "smoke", "--lab", str(lab), "--once", "--goal", "Check Modal works"]) == 0
    doc = json.loads((lab / "status.json").read_text())
    assert doc["goal"]["text"] == "Check Modal works" and doc["goal"]["target"] is None
    assert doc["runs"][0]["state"] == "done" and (lab / "status.html").is_file()
    sp.set_key(lab, "goal", GOAL)   # the plan skill sets the real goal later
    assert json.loads((lab / "status.json").read_text())["goal"] == GOAL


def test_once_records_nothing_for_an_unknown_run(cloud, proj, capsys):
    before = status(proj)
    assert poll.main(["modal", "typo", "--once"]) == 1
    assert "not known" in capsys.readouterr().err
    assert status(proj) == before and not (proj / "lab" / "runs" / "typo").exists()
    assert poll.main(["local", "typo", "--once"]) == 1 and not (proj / "lab" / "runs" / "typo").exists()
    cloud.put("status.txt", "epoch 1/3\n")                    # the run's files exist: it is recorded
    assert poll.main(["modal", "typo", "--once"]) == 0 and run_of(proj, "typo")["state"] == "running"


def test_once_records_a_run_the_provider_knows(cloud, proj):
    d = proj / "lab" / "backends" / "kaggle-new"
    d.mkdir(parents=True)
    (d / "kernel-metadata.json").write_text(json.dumps({"id": "alice/freelab-new"}))
    cloud.kaggle_status = "queued"
    assert poll.main(["kaggle", "new", "--once"]) == 0 and run_of(proj, "new")["state"] == "queued"


def test_kaggle_ref_follows_the_lab_option(cloud, tmp_path, monkeypatch):
    lab = tmp_path / "elsewhere" / "mylab"
    d = lab / "backends" / "kaggle-r9"
    d.mkdir(parents=True)
    (d / "kernel-metadata.json").write_text(json.dumps({"id": "alice/freelab-r9"}))
    assert poll.kaggle_ref(lab, "r9") == "alice/freelab-r9"
    assert poll.main(["kaggle", "r9", "--lab", str(lab), "--once"]) == 0
    assert any(c[:4] == ["kaggle", "kernels", "status", "alice/freelab-r9"] for c in cloud.calls)


def test_a_local_run_between_nights_is_waiting_and_watched(proj, monkeypatch, capsys):
    import os, runlib
    monkeypatch.setattr(poll, "_run", lambda *a, **k: pytest.fail("local runs need no command"))
    run_dir = proj / "lab" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "status.txt").write_text("stopped (deadline)\n")
    (run_dir / "metrics.jsonl").write_text(rows(0, 97, train_to=100))
    (run_dir / runlib.LAUNCHER_MARKER).write_text(str(os.getpid()))   # the launcher sleeps until the next night
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        if len(slept) == 2:   # the launcher ends: night 2 was the last
            (run_dir / runlib.LAUNCHER_MARKER).unlink()
    monkeypatch.setattr(poll, "_sleep", sleep)
    assert poll.main(["local", "r1", "--max-hours", "0.0001"]) == 3
    assert len(slept) == 2 and min(slept) >= 300
    out = capsys.readouterr().out
    assert out.splitlines()[-1].startswith("final: stopped") and "stopped watching" not in out
    (run_dir / runlib.LAUNCHER_MARKER).write_text(str(os.getpid()))
    assert poll.main(["local", "r1", "--once"]) == 0
    assert run_of(proj)["state"] == "queued" and "next night" in run_of(proj)["detail"]
