"""freelab poll: watch one run, keep lab/status.json and lab/status.html current, and exit when the run ends.

    python3 scripts/poll.py BACKEND RUN_ID [--lab lab] [--expected-minutes M] [--every SECONDS] [--once]
                            [--link URL] [--max-hours H] [--run-dir DIR] [--kernel OWNER/SLUG]
                            [--teamspace ORG/TEAMSPACE] [--job NAME] [--goal TEXT]

BACKEND is modal, kaggle, lightning or local. Meant for Bash run_in_background, from the project root. Without
lab/status.json (onboarding's connection check, before any charter) it starts a minimal one: goal text --goal
(default "connection check"), metric accuracy, no target; the plan skill later sets the real goal. Each tick:
1. fetch the run's small files (status.txt, metrics.jsonl, summary.json) into lab/runs/ID/ with the backend's own
   CLI, through scripts/withenv (which loads ./.env for that command only). A failed or empty download keeps the
   last good copy: each file lands in a temporary folder and replaces the old one only when it is not empty (and,
   for metrics.jsonl, not smaller). On Kaggle, while the kernel runs, it keeps `kaggle kernels logs -f` streaming
   into lab/runs/ID/live.log (restarted up to 3 times) and reads the step and the validation checks from it;
2. update that run in lab/status.json (state, step, total, metric = the latest validation value of the goal's
   metric, detail, eta, link, expected_minutes) and the page's `refresh_seconds`, add an event for each new
   validation check and each change of state, and render lab/status.html (both written atomically, under a lock);
3. print one line per new validation check (validation only: never a test score, so a research loop cannot see
   one), then sleep for the cadence.
When the run is done, failed or stopped it prints `final: <state> step=<s>/<t> val=<v>` and exits 0 (done),
3 (stopped) or 1 (failed, or an error: giving up after --max-hours, or after 10 checks in a row that could not
update status.json). A run the provider says ended but whose result files could not be fetched after 5 checks is
failed ("ended, but the results could not be fetched: fetch them by hand"), exit 1.
--once checks once and prints `now: <state> ...` (exit 0); it records nothing for a run nobody knows yet (not in
status.json, no files, the provider does not know it: a typo'd id, or a run launched seconds ago) and exits 1.
A local run paused between nights (`local_run.py --when night --nights N`: status `stopped (deadline)` while its
launcher still waits for the next night window) shows as waiting, and the poll keeps watching; --max-hours then
counts from the latest resume. `status_page.py forget --lab LAB RUN_ID` removes a run's entry.

Cadence (--every overrides): 30 s in the first 5 minutes after the run started; then by the expected length
(--expected-minutes, else the run's expected_minutes in status.json): under 30 min every 30 s, up to 3 h every
90 s, up to 12 h every 5 min, longer every 15 min; unknown, every 60 s.

Backend commands (from skills/compute/references/<backend>.md), each run as `scripts/withenv CMD...`:
- modal:     modal volume get --force freelab-runs ID/<file> <tmp dir>       (status.txt is the state)
- kaggle:    kaggle kernels status OWNER/freelab-ID                         (queued/running/complete/error/cancelled)
             kaggle kernels logs -f OWNER/freelab-ID >> lab/runs/ID/live.log (background, while running)
             kaggle kernels output OWNER/freelab-ID -p <tmp dir> --file-pattern '^(metrics\\.jsonl|status\\.txt|...)$'
             (once the kernel has ended). OWNER/SLUG comes from --kernel, else the `id` in
             lab/backends/kaggle-ID/kernel-metadata.json. The default link is https://www.kaggle.com/code/OWNER/SLUG.
- lightning: lightning job inspect NAME --teamspace TEAMSPACE               (JSON; the state, to verify live)
             lightning cp lit://TEAMSPACE/jobs/NAME/freelab-runs/ID/<file> <tmp file>
             TEAMSPACE comes from --teamspace, else `lightning_teamspace` in ${FREELAB_HOME:-~/.freelab}/onboarded;
             NAME is --job, else the run id.
- local:     nothing to fetch: the files are already in lab/runs/ID/ (or --run-dir).
FREELAB_WITHENV overrides the path of scripts/withenv (tests). Standard library only."""
from __future__ import annotations
import argparse, json, os, re, shutil, signal, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlib  # noqa: E402
import status_page as sp  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent
BACKENDS = ("modal", "kaggle", "lightning", "local")
SMALL_FILES = ("status.txt", "metrics.jsonl", "summary.json")
EXIT = {"done": 0, "stopped": 3, "failed": 1}
EARLY_SECONDS = 5 * 60
CMD_TIMEOUT = 120
STREAM_RESTARTS = 3     # Kaggle: the live log stream is started once and restarted up to this many times
FETCH_TRIES = 5         # ticks to wait for the final files after the provider says the run ended
ETA_WINDOW = 20         # the ETA's rate comes from at most this many of the latest training rows
ETA_GAP_SECONDS = 60    # a gap between training rows longer than this (and 5x the usual one) is a pause: a resume
DEFAULT_GOAL = "connection check"
FAIL_NOTE_AFTER = 3     # consecutive ticks with every command failing before a note on stderr
MAX_TICK_ERRORS = 10    # consecutive ticks that could not update status.json before the poll gives up (exit 1)
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")  # as scripts/backends/local_run.py
KAGGLE_PATTERN = r"^(metrics\.jsonl|status\.txt|summary\.json|config\.json|.*\.log)$"
LOG_TAIL_BYTES = 512 * 1024

PROGRESS_RE = re.compile(r"step (\d+)/(\d+) \(\d+%\), loss ([-+0-9.eE]+|nan|inf), ([0-9.]+) min")
EVAL_RE = re.compile(r"eval (val|test) ([A-Za-z_][\w.\-]*) (-?[0-9.]+(?:[eE]-?\d+)?) at step (\d+)")


# --- small helpers ---

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _parse_time(text) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


_atomic_write = runlib.atomic_write


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def cadence(expected_minutes=None, started: datetime | None = None, now: datetime | None = None,
            every: float | None = None) -> int:
    """Seconds between ticks: `every` when given; 30 in the first 5 minutes after `started`; then by the expected
    run length: < 30 min 30 s, <= 180 min 90 s, <= 720 min 300 s, longer 900 s; unknown 60 s."""
    if every:
        return max(1, int(round(every)))
    now = now or _now()
    if started is not None and 0 <= (now - started).total_seconds() < EARLY_SECONDS:
        return 30
    if not sp._finite_number(expected_minutes) or expected_minutes <= 0:
        return 60
    if expected_minutes < 30:
        return 30
    if expected_minutes <= 180:
        return 90
    if expected_minutes <= 720:
        return 300
    return 900


def _eta_words(minutes: float) -> str:
    if minutes < 1.5:
        return "1 min"
    if minutes < 60:
        return f"{round(minutes)} min"
    h, m = divmod(int(round(minutes)), 60)
    return f"{h} h {m} min" if m else f"{h} h"


def _fmt(value: float, percent: bool) -> str:
    """A score for an event: 0.758 -> '75.8%' for a percentage metric, else up to 3 decimals."""
    return f"{value * 100:.1f}%" if percent else sp._fmt_num(value)


def _status_line(path: Path) -> str:
    """The first meaningful line of status.txt ("" when missing); a CLI's own "✓ ..." line is skipped."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return next((l.strip() for l in lines if l.strip() and not l.lstrip().startswith("✓")), "")


def state_from_status(line: str, previous: str | None = None) -> str:
    """runlib's status.txt line as a run state: none yet -> starting (queued stays queued); done; stopped (...);
    failed: ...; anything else -> running."""
    low = line.strip().lower()
    if not low:
        return "queued" if previous == "queued" else "starting"
    if low.startswith("done"):
        return "done"
    if low.startswith("stopped"):
        return "stopped"
    if low.startswith("failed"):
        return "failed"
    return "running"


def kaggle_state(text: str) -> str | None:
    """`kaggle kernels status` output as queued, running, complete, error or cancelled (None if unreadable).
    It reads `... has status "running"` (or "KernelWorkerStatus.RUNNING"); to verify live on kaggle 2.x."""
    m = re.search(r'status\s+"?([A-Za-z_.]+)"?', text or "")
    word = m.group(1).rsplit(".", 1)[-1].lower() if m else ""
    for key, state in (("cancel", "cancelled"), ("error", "error"), ("fail", "error"), ("complete", "complete"),
                       ("running", "running"), ("queued", "queued"), ("new", "queued"), ("pending", "queued")):
        if key in word:
            return state
    return None


def lightning_state(text: str) -> str | None:
    """`lightning job inspect` JSON as queued, running, complete, error or cancelled (None if unreadable). The key
    and the values are to verify live: it looks for a "status", "state" or "phase" string anywhere in the JSON."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    found: list[str] = []

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and k.lower() in ("status", "state", "phase"):
                    found.append(v)
                else:
                    walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(data)
    for value in found:
        low = value.lower()
        for key, state in (("cancel", "cancelled"), ("stop", "cancelled"), ("fail", "error"), ("error", "error"),
                           ("complet", "complete"), ("succe", "complete"), ("finish", "complete"),
                           ("done", "complete"), ("running", "running"), ("pending", "queued"),
                           ("queue", "queued"), ("start", "queued"), ("provision", "queued")):
            if key in low:
                return state
    return None


def read_live_log(path: Path) -> tuple[dict | None, list[dict]]:
    """The newest progress line ({step, total, minutes, text}) and every validation check ([{step, name, value}])
    in a Kaggle live log. Test lines are ignored."""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - LOG_TAIL_BYTES))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None, []
    progress, evals = None, []
    for line in text.splitlines():
        m = PROGRESS_RE.search(line)
        if m:
            progress = {"step": int(m.group(1)), "total": int(m.group(2)), "minutes": float(m.group(4)),
                        "text": m.group(0)}
        m = EVAL_RE.search(line)
        if m and m.group(1) == "val":
            try:
                evals.append({"step": int(m.group(4)), "name": m.group(2), "value": float(m.group(3)),
                              "total": progress["total"] if progress else None})
            except ValueError:
                pass
    return progress, evals


# --- running backend commands ---

def _withenv() -> str:
    return os.environ.get("FREELAB_WITHENV") or str(PLUGIN / "scripts" / "withenv")


def _run(cmd: list[str], cwd: Path, timeout: int = CMD_TIMEOUT) -> subprocess.CompletedProcess | None:
    """Run a backend command through withenv from the project root; None when it could not run or timed out.
    Its output is captured, never printed."""
    try:
        return subprocess.run([_withenv(), *cmd], cwd=cwd, capture_output=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def _popen_stream(cmd: list[str], cwd: Path, log: Path) -> int | None:
    """Start `cmd` through withenv in the background, appending to `log`, in its own session (it outlives a
    --once poll); its pid, or None."""
    try:
        with log.open("ab") as out:
            proc = subprocess.Popen([_withenv(), *cmd], cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
        return proc.pid
    except OSError:
        return None


def _stream_alive(pid) -> bool:
    """Whether pid is still our `kaggle kernels logs` stream (not a reused pid)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    try:
        out = subprocess.run(["ps", "-o", "stat=,command=", "-p", str(pid)], capture_output=True, encoding="utf-8",
                             errors="replace", timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return True
    return bool(out) and not out.startswith("Z") and "logs" in out


def _stop_stream(pid) -> None:
    if _stream_alive(pid):
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass


class Backend:
    """Fetches one run's small files into its run directory. `fetch()` returns what the provider says about the
    run (queued, running, complete, error, cancelled) or None when the files alone say it."""
    name = ""

    def __init__(self, run_id: str, run_dir: Path, root: Path, args, memo: dict):
        self.run_id, self.run_dir, self.root, self.args, self.memo = run_id, run_dir, root, args, memo
        self.ok = 0        # commands that worked this tick
        self.tried = 0
        self.last_error = ""
        self.progress: dict | None = None   # a live log's newest progress line
        self.log_evals: list[dict] = []     # a live log's validation checks
        self.known = False                  # the provider knows this run (its status or app answered)

    def default_link(self) -> str | None:
        return None

    def fetch(self) -> str | None:
        return None

    def close(self) -> None:
        pass

    # helpers
    def cmd(self, cmd: list[str], timeout: int = CMD_TIMEOUT) -> subprocess.CompletedProcess | None:
        self.tried += 1
        res = _run(cmd, self.root, timeout)
        if res is not None and res.returncode == 0:
            self.ok += 1
        elif res is not None:
            self.last_error = ((res.stderr or res.stdout or "").strip().splitlines() or [""])[-1][:200]
        else:
            self.last_error = "the command could not run or timed out"
        return res

    def tmp_dir(self) -> Path:
        d = self.run_dir / ".poll-tmp"
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def take(self, src: Path, name: str) -> bool:
        """Move a downloaded file into the run directory when it is not empty (metrics.jsonl: not smaller either);
        otherwise keep the last good copy."""
        dest = self.run_dir / name
        try:
            size = src.stat().st_size
        except OSError:
            return False
        if size == 0 or (name == "metrics.jsonl" and dest.exists() and size < dest.stat().st_size):
            return False
        os.replace(src, dest)
        return True

    def cleanup_tmp(self) -> None:
        shutil.rmtree(self.run_dir / ".poll-tmp", ignore_errors=True)


class Modal(Backend):
    name = "modal"

    def fetch(self) -> str | None:
        tmp = self.tmp_dir()
        for name in SMALL_FILES:  # status first: the metrics fetched after a "done" are complete
            res = self.cmd(["modal", "volume", "get", "--force", "freelab-runs", f"{self.run_id}/{name}", str(tmp)])
            if res is not None and res.returncode == 0:
                self.take(tmp / name, name)
        self.cleanup_tmp()
        return self._app_state()

    def _app_state(self) -> str | None:
        """When the run's files do not say it ended, ask Modal whether its app has stopped: a container that died
        without writing status.txt would otherwise read as running until --max-hours. The app id comes from the
        --link (https://modal.com/apps/WORKSPACE/ENV/ap-...). "error" sends the run through the usual
        fetch-retries, so a late status.txt still decides; None when unknown or still running."""
        if state_from_status(_status_line(self.run_dir / "status.txt")) in EXIT:
            return None
        m = re.search(r"\b(ap-[A-Za-z0-9]+)", self.args.link or self.memo.get("link") or "")
        if not m:
            return None
        res = self.cmd(["modal", "app", "list", "--json"])
        try:
            apps = json.loads(res.stdout) if res is not None and res.returncode == 0 else []
        except ValueError:
            return None
        app = next((a for a in apps if isinstance(a, dict) and a.get("app_id") == m.group(1)), None)
        self.known = self.known or app is not None
        return "error" if app and str(app.get("state", "")).lower() == "stopped" else None


def kaggle_ref(lab: Path, run_id: str) -> str | None:
    """OWNER/SLUG from LAB/backends/kaggle-ID/kernel-metadata.json (written at launch), or None."""
    meta = _read_json(Path(lab) / "backends" / f"kaggle-{run_id}" / "kernel-metadata.json", {})
    ref = meta.get("id") if isinstance(meta, dict) else None
    return ref if isinstance(ref, str) and re.fullmatch(r"[\w.-]+/[\w.-]+", ref) else None


class Kaggle(Backend):
    name = "kaggle"

    def __init__(self, *a):
        super().__init__(*a)
        self.ref = self.args.kernel or kaggle_ref(Path(self.args.lab).resolve(), self.run_id)

    def default_link(self) -> str | None:
        return f"https://www.kaggle.com/code/{self.ref}" if self.ref else None

    def fetch(self) -> str | None:
        res = self.cmd(["kaggle", "kernels", "status", self.ref])
        state = kaggle_state(res.stdout) if res is not None and res.returncode == 0 else None
        self.known = self.known or state is not None
        if state == "running":
            self._ensure_stream()
        if state in ("complete", "error", "cancelled"):
            self._stop()
            tmp = self.tmp_dir()
            res = self.cmd(["kaggle", "kernels", "output", self.ref, "-p", str(tmp), "--file-pattern",
                            KAGGLE_PATTERN], timeout=600)
            if res is not None and res.returncode == 0:
                for f in sorted(tmp.rglob("*")):
                    if f.is_file() and f.name != "live.log" and not f.name.startswith("."):
                        self.take(f, f.name)
            self.cleanup_tmp()
        self.progress, self.log_evals = read_live_log(self.run_dir / "live.log")
        return state

    def _ensure_stream(self) -> None:
        """Keep `kaggle kernels logs -f` writing lab/runs/ID/live.log while the kernel runs: start it, and
        restart it when it has exited, up to STREAM_RESTARTS times (its exit is not the end of the run).
        `kernels logs -f` is to verify live (kaggle 2.x source and --help, not yet tried on a run)."""
        if _stream_alive(self.memo.get("stream_pid")):
            return
        starts = int(self.memo.get("stream_starts") or 0)
        if starts > STREAM_RESTARTS:
            return
        pid = _popen_stream(["kaggle", "kernels", "logs", "-f", self.ref], self.root, self.run_dir / "live.log")
        self.memo["stream_pid"], self.memo["stream_starts"] = pid, starts + 1

    def _stop(self) -> None:
        _stop_stream(self.memo.get("stream_pid"))
        self.memo["stream_pid"] = None

    def close(self) -> None:
        self._stop()


class Lightning(Backend):
    name = "lightning"

    def __init__(self, *a):
        super().__init__(*a)
        self.teamspace = self.args.teamspace or self._teamspace_from_marker()
        self.job = self.args.job or self.run_id

    @staticmethod
    def _teamspace_from_marker() -> str | None:
        home = Path(os.environ.get("FREELAB_HOME") or Path.home() / ".freelab")
        marker = _read_json(home / "onboarded", {})
        ts = marker.get("lightning_teamspace") if isinstance(marker, dict) else None
        return ts if isinstance(ts, str) and ts.strip() else None

    def fetch(self) -> str | None:
        res = self.cmd(["lightning", "job", "inspect", self.job, "--teamspace", self.teamspace])
        state = lightning_state(res.stdout) if res is not None and res.returncode == 0 else None
        self.known = self.known or state is not None
        tmp = self.tmp_dir()
        for name in SMALL_FILES:  # status first, as on Modal
            src = f"lit://{self.teamspace}/jobs/{self.job}/freelab-runs/{self.run_id}/{name}"
            res = self.cmd(["lightning", "cp", src, str(tmp / name)])
            if res is not None and res.returncode == 0:
                self.take(tmp / name, name)
        self.cleanup_tmp()
        return state


class Local(Backend):
    name = "local"


BACKEND_CLASSES = {"modal": Modal, "kaggle": Kaggle, "lightning": Lightning, "local": Local}


# --- one tick ---

def _latest_val(rows: list, metric: str) -> list[dict]:
    """The validation rows of `metric` with a finite step and value, by step (one per step: the last logged)."""
    by_step: dict = {}
    for r in rows:
        if (isinstance(r, dict) and r.get("split") == "val" and r.get("name") == metric
                and sp._finite_number(r.get("step")) and sp._finite_number(r.get("value"))):
            by_step[r["step"]] = r
    return [by_step[s] for s in sorted(by_step)]


def _progress_rows(rows: list) -> tuple:
    """(step, total, rate in steps per second or None) from the train and val rows. The rate comes from the latest
    ETA_WINDOW training rows, after the longest gap among them when that gap is a pause (a resume)."""
    pts = [r for r in rows if isinstance(r, dict) and r.get("split") in ("train", "val")
           and sp._finite_number(r.get("step"))]
    if not pts:
        return None, None, None
    last = max(pts, key=lambda r: r["step"])
    total = last.get("total") if sp._finite_number(last.get("total")) else None
    train = [(r["step"], _parse_time(r.get("t"))) for r in rows if isinstance(r, dict) and r.get("split") == "train"
             and sp._finite_number(r.get("step"))]
    train = [(s, t) for s, t in train if t is not None][-ETA_WINDOW:]
    # a resume after a pause (another session, the next night) leaves one long gap: the rate counts only after it
    gaps = [(train[i + 1][1] - train[i][1]).total_seconds() for i in range(len(train) - 1)]
    if len(gaps) >= 2:
        i = max(range(len(gaps)), key=gaps.__getitem__)
        usual = sorted(g for j, g in enumerate(gaps) if j != i)[(len(gaps) - 1) // 2]
        if gaps[i] > ETA_GAP_SECONDS and gaps[i] > 5 * max(usual, 0.0):
            train = train[i + 1:]
    rate = None
    if len(train) >= 2:
        (s0, t0), (s1, t1) = train[0], train[-1]
        if s1 > s0 and t1 > t0:
            rate = (s1 - s0) / (t1 - t0).total_seconds()
    return last["step"], total, rate


class Poller:
    def __init__(self, args):
        self.args = args
        self.lab = Path(args.lab).resolve()
        self.root = self.lab.parent
        self.run_id = args.run_id
        self.run_dir = Path(args.run_dir).resolve() if args.run_dir else self.lab / "runs" / self.run_id
        self.new_dir = not self.run_dir.exists()  # a --once check removes it again for a run nobody knows
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.memo_path = self.run_dir / ".poll.json"
        self.memo = _read_json(self.memo_path, {})
        if not isinstance(self.memo, dict):
            self.memo = {}
        self.backend = BACKEND_CLASSES[args.backend](self.run_id, self.run_dir, self.root, args, self.memo)
        self.t0 = _now()
        self.fail_streak = 0
        self.render_warned = False
        self.cadence = cadence(every=args.every) if args.every else 30  # until a tick works out the real one
        self.paused = False   # a local run waiting for its next night window

    # the provider's name and where the run is, in plain words
    def _where(self, run: dict) -> str:
        return sp._where(run.get("backend")) or sp._where(self.args.backend)

    def tick(self) -> tuple[str, dict, list[str]]:
        """Fetch, update status.json, render. Returns (state, run, stdout lines)."""
        b = self.backend
        b.ok = b.tried = 0
        provider = b.fetch()
        if provider in ("queued", "running"):  # running (again, after a relaunch): the end-of-run counters restart
            if self.memo.get("provider") in ("complete", "error", "cancelled"):
                self.memo.pop("stream_starts", None)
            self.memo.pop("fetch_tries", None)
        if provider is not None:
            self.memo["provider"] = provider
        if b.tried and not b.ok:
            self.fail_streak += 1
            if self.fail_streak == FAIL_NOTE_AFTER:
                print(f"poll: no answer from {b.name} for {FAIL_NOTE_AFTER} checks; keeping the last numbers "
                      f"(last error: {b.last_error})", file=sys.stderr, flush=True)
        else:
            self.fail_streak = 0

        status_line = _status_line(self.run_dir / "status.txt")
        rows = runlib.read_metrics(self.run_dir / "metrics.jsonl")
        lines: list[str] = []
        with sp.status_lock(self.lab):
            doc = json.loads((self.lab / "status.json").read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("status.json must be a JSON object")
            if self.args.once and not self._known(doc, status_line, rows):
                self.forget_dir()
                raise UnknownRun(f"run {self.run_id} is not known on {sp._where(self.args.backend)}: it is not in "
                                 f"{self.lab.name}/status.json, has no files, and the provider does not know it. "
                                 "Nothing was recorded. Check the run id (a run launched seconds ago can take a "
                                 "minute to appear).")
            run = self._run_entry(doc)
            state = self._update(doc, run, provider, status_line, rows, lines)
            sp.validate(doc)  # never write a status.json the status skill's `set` and `event` would then refuse
            _atomic_write(self.lab / "status.json", json.dumps(doc, indent=2) + "\n")
            try:
                sp.write_page(self.lab)
                self.render_warned = False
            except (ValueError, OSError) as e:
                if not self.render_warned:
                    print(f"poll: could not render the page: {e}", file=sys.stderr, flush=True)
                    self.render_warned = True
        _atomic_write(self.memo_path, json.dumps(self.memo))
        return state, run, lines

    def _known(self, doc: dict, status_line: str, rows: list) -> bool:
        """Whether anyone knows this run: an entry in status.json, its files, or the provider."""
        listed = any(isinstance(r, dict) and str(r.get("id")) == self.run_id for r in doc.get("runs") or [])
        return listed or bool(status_line or rows) or self.backend.known or not self.new_dir

    def forget_dir(self) -> None:
        """Remove the run directory this poll made, when it holds nothing but the poll's own files."""
        if self.new_dir and all(p.name in (".poll-tmp", ".poll.json") for p in self.run_dir.iterdir()):
            shutil.rmtree(self.run_dir, ignore_errors=True)

    def _run_entry(self, doc: dict) -> dict:
        runs = doc.setdefault("runs", [])
        run = next((r for r in runs if isinstance(r, dict) and str(r.get("id")) == self.run_id), None)
        if run is None:
            run = {"id": self.run_id, "backend": self.args.backend, "state": "starting", "step": None,
                   "total": None, "metric": None, "eta": None, "detail": "", "started": _iso(self.t0)}
            runs.append(run)
            self._event(doc, f"Started watching run {self.run_id} on {self._where(run)}.")
        return run

    def _event(self, doc: dict, text: str) -> None:
        events = doc.setdefault("events", [])
        events.insert(0, {"t": _iso(_now()), "text": text})
        sp.trim_events(events)

    def _update(self, doc: dict, run: dict, provider: str | None, status_line: str, rows: list,
                lines: list[str]) -> str:
        goal = doc["goal"]
        metric = goal["metric"]
        b = self.backend
        prev = run.get("state")
        where = self._where(run)

        # the state
        if provider is None:
            state = state_from_status(status_line, prev)
            if b.name == "kaggle":  # status unreadable this tick: keep what we knew
                state = prev if prev in sp.RUN_STATES else "starting"
        elif provider == "queued":
            state = "queued" if not status_line else state_from_status(status_line, prev)
        elif provider == "running":
            if b.name == "kaggle":
                state = "running" if (b.progress or b.log_evals or rows) else "starting"
            else:  # the provider says it runs: before the first status line, that is enough
                state = state_from_status(status_line, prev) if status_line.strip() else "running"
        else:  # the provider says it ended: the files say how, once fetched
            state = state_from_status(status_line, prev)
            if state not in EXIT:
                tries = int(self.memo.get("fetch_tries") or 0) + 1
                self.memo["fetch_tries"] = tries
                if tries < FETCH_TRIES:
                    state = "running"
                    status_line = f"Finished on {where}; fetching the results"
                else:  # no result files: nothing says how it went, so it counts as failed (exit 1)
                    state = "failed"
                    status_line = (f"Ended on {where} ({provider}), but the results could not be fetched: "
                                   "fetch them by hand")

        # a local run between nights: stopped at the window's end while its launcher waits for the next one
        self.paused = (b.name == "local" and state == "stopped" and status_line.strip().lower() == "stopped (deadline)"
                       and runlib.launcher_alive(self.run_dir))
        if self.paused:
            state = "queued"
            status_line = "Paused until the next night window; the launcher resumes it then"

        # step, total, eta
        step, total, rate = _progress_rows(rows)
        if step is None and b.progress:
            step, total = b.progress["step"], b.progress["total"]
            if b.progress["minutes"] > 0:
                rate = step / (b.progress["minutes"] * 60)
        if step is not None:
            run["step"], run["total"] = step, total if total is not None else run.get("total")
        eta = None
        if state == "running" and rate and sp._finite_number(run.get("step")) and sp._finite_number(run.get("total")):
            left = run["total"] - run["step"]
            if left > 0:
                eta = _eta_words(left / rate / 60)
        run["eta"] = eta

        if state != prev and state == "running" and prev in (None, "queued", "starting"):
            self._event(doc, f"{self.run_id} started training on {where}.")

        # the validation checks: metric, events, stdout lines
        vals = [{"step": r["step"], "value": r["value"], "total": r.get("total")} for r in _latest_val(rows, metric)]
        if not vals:
            vals = [e for e in b.log_evals if e["name"] == metric]
        if vals:
            run["metric"] = vals[-1]["value"]
        seen = set(self.memo.get("seen") or [])
        start = vals[0] if vals and vals[0]["step"] == 0 else None
        percent = sp._percent_metric(metric, goal["direction"], [v["value"] for v in vals] + [goal["target"]])
        words = str(metric).replace("_", " ")
        for v in vals:
            if v["step"] in seen:
                continue
            seen.add(v["step"])
            tot = v.get("total") or run.get("total")
            at = f"step {sp._step_text(v['step'])}" + (f" of {sp._step_text(tot)}" if sp._finite_number(tot) else "")
            if v is start:
                self._event(doc, f"{self.run_id}: validation {words} at the start: {_fmt(v['value'], percent)}.")
                lines.append(f"{self.run_id}: val {metric} {v['value']:.4g} at step 0 (start)")
            else:
                since = f" (start {_fmt(start['value'], percent)})" if start else ""
                self._event(doc, f"{self.run_id}: validation {words} {_fmt(v['value'], percent)} at {at}{since}.")
                lines.append(f"{self.run_id}: val {metric} {v['value']:.4g} at step {sp._step_text(v['step'])}"
                             + (f"/{sp._step_text(tot)}" if sp._finite_number(tot) else "")
                             + (f" (start {start['value']:.4g})" if start else ""))
        self.memo["seen"] = sorted(seen)

        # detail
        if b.name == "kaggle" and provider == "running" and b.progress:
            detail = b.progress["text"]
        elif status_line:
            detail = status_line
        elif state == "queued":
            detail = f"Waiting for a free machine on {where}"
        elif state == "starting":
            detail = f"Getting a machine ready on {where}"
        else:
            detail = run.get("detail") or ""
        run["detail"] = detail

        # link, expected length
        link = self.args.link or run.get("link") or b.default_link()
        if link and sp.valid_link(link):
            run["link"] = link
            self.memo["link"] = link  # the Modal app check reads it on the next ticks
        if self.args.expected_minutes:
            em = self.args.expected_minutes
            run["expected_minutes"] = int(em) if float(em).is_integer() else em

        # a change of state
        if state != prev:
            if state == "done":
                last = f": validation {words} {_fmt(vals[-1]['value'], percent)}" if vals else ""
                self._event(doc, f"{self.run_id} finished on {where}{last}.")
            elif state == "stopped":
                why = re.sub(r"^stopped\s*", "", status_line, flags=re.I).strip(" ()")
                self._event(doc, f"{self.run_id} stopped on {where}" + (f" ({why})" if why else "") + ".")
            elif state == "failed":
                why = re.sub(r"^failed\s*:?\s*", "", status_line, flags=re.I).strip()
                self._event(doc, f"{self.run_id} failed on {where}" + (f": {why}" if why else "") + ".")
        run["state"] = state

        # the page's reload matches the cadence
        started = _parse_time(run.get("started")) or self.t0
        expected = self.args.expected_minutes or run.get("expected_minutes")
        self.cadence = cadence(expected, started, _now(), self.args.every)
        if self.paused and not self.args.every:
            self.cadence = max(self.cadence, 300)
        doc["refresh_seconds"] = min(max(self.cadence, sp.REFRESH_RANGE[0]), sp.REFRESH_RANGE[1])
        doc["updated"] = _iso(_now())
        return state


class UnknownRun(Exception):
    """A --once check of a run nobody knows: nothing is recorded."""


def _val_text(run: dict) -> str:
    v = run.get("metric")
    return f"{v:.4g}" if sp._finite_number(v) else "none"


def _steps_text(run: dict) -> str:
    s, t = run.get("step"), run.get("total")
    fmt = lambda x: sp._step_text(x) if sp._finite_number(x) else "?"  # noqa: E731
    return f"{fmt(s)}/{fmt(t)}"


def _positive(text: str) -> float:
    value = float(text)
    if not value > 0 or value == float("inf"):
        raise argparse.ArgumentTypeError(f"must be a positive number, got {text!r}")
    return value


def _run_id(text: str) -> str:
    if not RUN_ID_RE.fullmatch(text):
        raise argparse.ArgumentTypeError("may hold only letters, digits, '.', '_' and '-'")
    return text


EPILOG = """exit codes: 0 done (or a --once check), 3 stopped, 1 failed or an error. An ended run whose results
could not be fetched is failed (exit 1). --once records nothing for a run nobody knows yet (exit 1). A local run
paused between nights (local_run.py --nights N) shows as waiting and the poll keeps watching. Without LAB/status.json
the poll starts a minimal one (--goal). `status_page.py forget --lab LAB RUN_ID` removes a run's entry."""


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="poll.py", description="Watch one freelab run and keep the status page current.",
                                epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("backend", choices=BACKENDS)
    p.add_argument("run_id", type=_run_id)
    p.add_argument("--lab", default="lab", help="the lab directory (default: lab)")
    p.add_argument("--expected-minutes", type=_positive, help="how long the run should take (sets the cadence)")
    p.add_argument("--every", type=_positive, help="seconds between checks (overrides the cadence)")
    p.add_argument("--once", action="store_true", help="one check, then exit")
    p.add_argument("--link", help="the provider's page for the run (an http(s) URL)")
    p.add_argument("--max-hours", type=float, help="stop watching after this many hours (exit 1)")
    p.add_argument("--run-dir", help="where the run's files are (default: LAB/runs/RUN_ID)")
    p.add_argument("--kernel", help="kaggle: OWNER/SLUG (default: from lab/backends/kaggle-ID/kernel-metadata.json)")
    p.add_argument("--teamspace", help="lightning: ORG/TEAMSPACE (default: from the onboarded marker)")
    p.add_argument("--job", help="lightning: the job name (default: the run id)")
    p.add_argument("--goal", default=DEFAULT_GOAL,
                   help=f"without LAB/status.json: the goal text of the minimal one the poll starts "
                        f"(default {DEFAULT_GOAL!r})")
    return p.parse_args(argv)


def start_status(lab: Path, goal: str) -> None:
    """Write a minimal valid LAB/status.json (no charter yet: metric accuracy, no target) unless one exists."""
    lab.mkdir(parents=True, exist_ok=True)
    with sp.status_lock(lab):
        path = lab / "status.json"
        if not path.exists():
            doc = sp.new_status({"text": " ".join(goal.split()) or DEFAULT_GOAL, "metric": "accuracy",
                                 "target": None, "direction": "max"}, {})
            sp.validate(doc)
            _atomic_write(path, json.dumps(doc, indent=2) + "\n")


def main(argv=None) -> int:
    args = parse_args(argv)
    lab = Path(args.lab)
    if args.link and not sp.valid_link(args.link):
        print(f"poll: --link must be an http(s) URL, got {args.link!r}", file=sys.stderr)
        return 1
    if args.backend != "local" and not os.access(_withenv(), os.X_OK):
        print(f"poll: {_withenv()} is missing or not executable", file=sys.stderr)
        return 1
    if args.backend == "kaggle" and not (args.kernel or kaggle_ref(lab.resolve(), args.run_id)):
        print(f"poll: kaggle needs --kernel OWNER/SLUG (no {lab}/backends/kaggle-ID/kernel-metadata.json found)",
              file=sys.stderr)
        return 1
    if args.backend == "lightning" and not (args.teamspace or Lightning._teamspace_from_marker()):
        print("poll: lightning needs --teamspace ORG/TEAMSPACE (no lightning_teamspace in the onboarded marker)",
              file=sys.stderr)
        return 1
    if not (lab / "status.json").is_file():
        try:
            start_status(lab, args.goal)
        except (OSError, ValueError) as e:
            print(f"poll: could not start {lab / 'status.json'}: {e}", file=sys.stderr)
            return 1

    poller = Poller(args)
    run: dict = {}
    errors = 0
    try:
        while True:
            try:
                state, run, lines = poller.tick()
                errors = 0
            except UnknownRun as e:
                print(f"poll: {e}", file=sys.stderr, flush=True)
                return 1
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
                errors += 1
                print(f"poll: could not update {lab / 'status.json'}: {e}", file=sys.stderr, flush=True)
                if args.once:
                    return 1
                if errors >= MAX_TICK_ERRORS:
                    print(f"poll: gave up after {errors} checks in a row could not update {lab / 'status.json'} "
                          f"(last error: {e}); run {args.run_id} may still be going", flush=True)
                    return 1
                state, lines = None, []
            for line in lines:
                print(line, flush=True)
            if state in EXIT:
                print(f"final: {state} step={_steps_text(run)} val={_val_text(run)}", flush=True)
                return EXIT[state]
            if args.once:
                print(f"now: {state} step={_steps_text(run)} val={_val_text(run)}", flush=True)
                return 0
            if poller.paused:  # waiting for the next night: --max-hours counts from the latest resume
                poller.t0 = _now()
            max_hours = args.max_hours
            if max_hours is None:
                expected = args.expected_minutes or run.get("expected_minutes")
                max_hours = max(6.0, 3 * expected / 60) if sp._finite_number(expected) else 24.0
            if (_now() - poller.t0).total_seconds() > max_hours * 3600:
                print(f"poll: stopped watching after {max_hours:g} h; run {args.run_id} is still "
                      f"{state or 'unknown'} (step={_steps_text(run)} val={_val_text(run)})", flush=True)
                return 1
            _sleep(poller.cadence)
    finally:
        if not args.once:  # a --once check leaves a Kaggle live log stream running for the next check
            poller.backend.close()


if __name__ == "__main__":
    raise SystemExit(main())
