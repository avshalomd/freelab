"""freelab status page: lab/status.json -> a self-contained HTML page (stdlib only). No external requests: CSS and the
SVG charts are inline. Every value that comes from the data is escaped with html.escape. Schema is status.json
version 1 (skills/status/SKILL.md): {version, updated, goal, best, runs, budget, decisions, events}. goal.target may
be null while there is no charter yet (scripts/poll.py starts a status.json for onboarding's connection check that
way); `set goal` needs a number. status.json may also hold an optional `stages` key (a plan of named stages with a
state and detail), so a status.json written before stages existed (freelab 0.1.0) still renders. `budget` may hold
an optional `usd_free` (the free credit, in dollars), marked on the cost meter. lab/runs/<id>/metrics.jsonl feeds
the charts and lab/results.tsv, when present, is the research loop's experiment log.

The page, top to bottom: one plain sentence on what is happening now; a bar
from the start (the step-0 value of the split the result comes from) to the target with the best
so far marked; charts (the goal's metric per split with dashed start and target lines, the kept
metric per experiment); training health (the training loss with its moving average, the scores at
each check and a verdict: still improving, levelling off or plateaued); the plan as a timeline;
cost and time left; and the technical details, collapsed. A before/after pair always comes from
one split. It reloads itself while a run is queued, starting or running (every `refresh_seconds`, default 30 s).

The page is built from named blocks (BLOCKS), in the order of the optional `layout` list in status.json, else
DEFAULT_LAYOUT (the page above). Unknown names are skipped; `custom:<name>` inlines lab/blocks/<name>.html (written
by the agent; its <script> tags are stripped). A run may carry `link` (the provider's own page for the run, an
http(s) URL), shown as an "Open on <provider>" link, and `expected_minutes`, which scripts/poll.py uses for its
cadence.

CLI (CLI_HELP below): `status_page.py LAB` renders LAB/status.html; `event --lab LAB "text"` adds one event;
`set --lab LAB KEY JSON` sets one field (best, budget, budget.NAME, stages, decisions, goal, layout, refresh_seconds);
`forget --lab LAB RUN_ID` removes one run's entry (a run that never launched, such as a typo'd id). Each holds
LAB/.status.lock (the lock scripts/poll.py uses), validates, renders the page from the new document, and only then
writes status.json and status.html atomically: an exit 2 writes nothing. Events are newest first; trim_events keeps
EVENTS_CAP of them plus every "research loop ..." event."""
from __future__ import annotations
import argparse, html, json, math, os, re, sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import runlib
from runlib import atomic_write

try:
    import fcntl
except ImportError:  # Windows has no fcntl: the status lock is then a no-op (one poll per lab is the usual case)
    fcntl = None

SCHEMA_KEYS = {"version", "updated", "goal", "best", "runs", "budget", "decisions", "events"}
RUN_STATES = ("queued", "starting", "running", "stopped", "done", "failed")
RUN_KEYS = {"id", "backend", "state", "step", "total", "metric", "eta", "detail", "started"}
RUN_OPTIONAL_KEYS = {"link", "expected_minutes"}  # freelab 0.4.0: the provider's run page, the expected length
BEST_KEYS = {"value", "run", "at"}

OPTIONAL_KEYS = {"stages", "layout", "refresh_seconds"}  # optional so a status.json written by freelab 0.1.0 still renders
REFRESH_DEFAULT = 30
REFRESH_RANGE = (5, 86400)
STAGE_KEYS = {"name", "state", "detail"}
STAGE_STATES = ("planned", "running", "done", "skipped")
RESULT_COLUMNS = ("id", "commit", "backend", "gpu", "minutes", "metric", "status", "change")
RESULT_STATUSES = ("keep", "discard", "crash")
RESULTS_CAP = 50

EVENTS_CAP = 50
KEEP_EVENT = re.compile(r"^\s*research loop\b", re.I)  # never trimmed: research §3 counts the loop's hours from it


def trim_events(events: list) -> None:
    """Cut `events` (newest first) to EVENTS_CAP in place, dropping the oldest ones, but never an event whose text
    starts with "research loop": the loop's start (and end) stay however long the loop runs."""
    if len(events) <= EVENTS_CAP:
        return
    kept = []
    keep = [isinstance(e, dict) and bool(KEEP_EVENT.match(str(e.get("text", "")))) for e in events]
    room = max(0, EVENTS_CAP - sum(keep))
    for e, k in zip(events, keep):
        if k:
            kept.append(e)
        elif room > 0:
            kept.append(e)
            room -= 1
    events[:] = kept


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _check_keys(obj: dict, allowed: set, label: str, optional: set = frozenset()) -> None:
    keys = set(obj.keys())
    for key in sorted(allowed - keys):
        raise ValueError(f"{label} missing key: {key!r}")
    for key in sorted(keys - allowed - optional):
        raise ValueError(f"{label} has unknown key: {key!r}")


_LINK_RE = re.compile(r"^https?://[^\s\"'<>`]+$")


def valid_link(url) -> bool:
    """True for an http(s) URL with a host and no spaces, quotes or angle brackets (a provider's run page)."""
    if not isinstance(url, str) or not _LINK_RE.match(url):
        return False
    return bool(urlparse(url).netloc)


def validate(doc: dict) -> None:
    """Raise ValueError naming the key for a missing/unknown top-level key, a version other
    than 1, a run missing/with an unknown key, a run state outside RUN_STATES, a malformed
    `best` or `goal` (text, metric, a numeric or null target, direction), or a malformed `stages`
    entry (name, state outside STAGE_STATES, detail). `stages` is optional (OPTIONAL_KEYS),
    so a status.json written before it existed (freelab 0.1.0) still validates."""
    if not isinstance(doc, dict):
        raise ValueError("status.json must be a JSON object")
    keys = set(doc.keys())
    for key in sorted(SCHEMA_KEYS - keys):
        raise ValueError(f"missing required top-level key: {key!r}")
    for key in sorted(keys - SCHEMA_KEYS - OPTIONAL_KEYS):
        raise ValueError(f"unknown top-level key: {key!r}")
    if doc["version"] != 1:
        raise ValueError(f"version must be 1, got {doc['version']!r}")

    goal = doc["goal"]
    if not isinstance(goal, dict):
        raise ValueError("goal must be an object")
    for key in ("text", "metric"):
        if not isinstance(goal.get(key), str) or not goal[key].strip():
            raise ValueError(f"goal.{key} must be non-empty text, got {goal.get(key)!r}")
    if "target" not in goal or (goal["target"] is not None and not _finite_number(goal["target"])):
        raise ValueError(f"goal.target must be a number (or null before the charter), got {goal.get('target')!r}")
    direction = goal.get("direction")
    if direction not in ("max", "min"):
        raise ValueError(f"goal.direction must be 'max' or 'min', got {direction!r}")

    best = doc["best"]
    if best is not None:
        if not isinstance(best, dict):
            raise ValueError("best must be null or an object")
        _check_keys(best, BEST_KEYS, "best")

    runs = doc["runs"]
    if not isinstance(runs, list):
        raise ValueError("runs must be a list")
    for run in runs:
        if not isinstance(run, dict):
            raise ValueError("each run must be an object")
        _check_keys(run, RUN_KEYS, "run", RUN_OPTIONAL_KEYS)
        if run["state"] not in RUN_STATES:
            raise ValueError(f"run {run.get('id')!r} has invalid state: {run['state']!r}")
        if "link" in run and run["link"] is not None and not valid_link(run["link"]):
            raise ValueError(f"run {run.get('id')!r} link must be an http(s) URL, got {run['link']!r}")
        if "expected_minutes" in run and run["expected_minutes"] is not None and not (
                _finite_number(run["expected_minutes"]) and run["expected_minutes"] > 0):
            raise ValueError(f"run {run.get('id')!r} expected_minutes must be a positive number, "
                             f"got {run['expected_minutes']!r}")

    if not isinstance(doc["budget"], dict):
        raise ValueError("budget must be an object")
    if not isinstance(doc["decisions"], list):
        raise ValueError("decisions must be a list")
    if not isinstance(doc["events"], list):
        raise ValueError("events must be a list")

    if "stages" in doc:
        if not isinstance(doc["stages"], list):
            raise ValueError("stages must be a list")
        for stage in doc["stages"]:
            if not isinstance(stage, dict):
                raise ValueError("each stage must be an object")
            _check_keys(stage, STAGE_KEYS, "stage")
            if not isinstance(stage["name"], str) or not stage["name"].strip():
                raise ValueError(f"stage name must be non-empty text, got {stage['name']!r}")
            if stage["state"] not in STAGE_STATES:
                raise ValueError(f"stage {stage['name']!r} has invalid state: {stage['state']!r}")

    if "layout" in doc:
        layout = doc["layout"]
        if not isinstance(layout, list) or not all(isinstance(x, str) for x in layout):
            raise ValueError(f"layout must be a list of block names, got {layout!r}")
    if "refresh_seconds" in doc:
        sec = doc["refresh_seconds"]
        if not _finite_number(sec) or not REFRESH_RANGE[0] <= sec <= REFRESH_RANGE[1]:
            raise ValueError(f"refresh_seconds must be a number from {REFRESH_RANGE[0]} to {REFRESH_RANGE[1]}, "
                             f"got {sec!r}")


def new_status(goal: dict, budget: dict) -> dict:
    """A valid empty status.json document, for the skills to start from."""
    return {
        "version": 1,
        "updated": _now(),
        "goal": dict(goal),
        "stages": [],
        "best": None,
        "runs": [],
        "budget": dict(budget),
        "decisions": [],
        "events": [],
    }


def _float(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def read_results(path) -> list[dict]:
    """The rows of a research loop's results.tsv (RESULT_COLUMNS, tab-separated, a header line first) in file
    order. A row with the wrong number of fields, an unknown status, a non-numeric minutes, or a keep or discard
    row without a finite metric is skipped; a crash may leave the metric empty (None). A missing or unreadable
    file reads as no rows."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    rows = []
    for line in lines:
        fields = [f.strip() for f in line.split("\t")]
        if len(fields) != len(RESULT_COLUMNS) or fields[0] == "id":
            continue
        row = dict(zip(RESULT_COLUMNS, fields))
        minutes, metric = _float(row["minutes"]), _float(row["metric"])
        if row["status"] not in RESULT_STATUSES or minutes is None or (metric is None and row["status"] != "crash"):
            continue
        rows.append({**row, "minutes": minutes, "metric": metric})
    return rows


def _round3(value: float) -> float:
    """`value` rounded to at most 3 decimals (0.5776 -> 0.578); an integral float stays as it is."""
    if value == int(value):
        return value
    return round(value, 3)


def _disp(value) -> str:
    """Escaped display string; a dash for None/empty (metric, eta, step may be missing). A
    finite float is rounded to at most 3 decimals (e.g. 0.5776983094928478 -> 0.578); an int
    (a step count) is shown as-is."""
    if value is None or value == "":
        return "—"
    if isinstance(value, float) and math.isfinite(value):
        value = _round3(value)
    return html.escape(str(value))


def _esc(text) -> str:
    return html.escape(str(text))


def _finite_number(x) -> bool:
    """True for a real, finite int/float -- excludes bool, str, None, NaN and +/-inf."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _pct(numerator, denominator) -> float:
    """The ratio as a percentage in [0, 100]; 0 for a non-finite input or a zero denominator (never NaN -> 100)."""
    if not _finite_number(numerator) or not _finite_number(denominator) or denominator == 0:
        return 0.0
    return max(0.0, min(100.0, (numerator / denominator) * 100.0))


def _goal_pct(value, target, direction) -> float | None:
    """Progress toward the target in [0, 100], or None for a non-finite input; for "min", a value <= 0 is met."""
    if not _finite_number(value) or not _finite_number(target):
        return None
    if direction == "min":
        if value <= 0:
            return 100.0
        return _pct(target, value)
    return _pct(value, target)


_DIRECTION_SYMBOL = {"max": "≥", "min": "≤"}  # >=, <=
ACTIVE_STATES = ("queued", "starting", "running")
MAX_POINTS = 300  # a longer series is averaged down to this many points, to keep the page small


# --- numbers in plain words ---

def _unsign_zero(text: str) -> str:
    return text[1:] if text.startswith("-") and float(text.rstrip("%")) == 0 else text


def _fmt_num(value: float) -> str:
    """`value` with at most 3 decimals, and at least 2 below 10 (0.3 -> "0.30", 2.3 -> "2.30", 12.5 -> "12.5")."""
    min_decimals = 2 if abs(value) < 10 else 0
    head, _, decimals = f"{round(value, 3):.3f}".partition(".")
    while len(decimals) > min_decimals and decimals.endswith("0"):
        decimals = decimals[:-1]
    return _unsign_zero(f"{head}.{decimals}" if decimals else head)


def _fmt_values(values: list, percent: bool) -> list[str]:
    """Format values together: a percentage without decimals, or with one (two) when two different values would
    otherwise read the same (0.795 and 0.80 -> "79.5%", "80.0%"); a plain number as in _fmt_num."""
    if not percent:
        return [_fmt_num(v) for v in values]
    for decimals in (0, 1, 2):
        texts = [f"{v * 100:.{decimals}f}" for v in values]
        if all(texts[i] != texts[j] or values[i] == values[j] for i in range(len(values)) for j in range(i)):
            break
    return [_unsign_zero(t) + "%" for t in texts]


def _fmt_value(value: float, percent: bool) -> str:
    return _fmt_values([value], percent)[0]


_RATE_WORDS = ("acc", "error", "rate", "f1", "precision", "recall", "auc", "iou", "match")


def _percent_metric(name, direction, values) -> bool:
    """True when the metric reads best as a percentage: every value is in [0, 1] and the metric is a score to raise
    (direction max) or its name says it is a rate (accuracy, error rate, F1, ...). A loss never is."""
    low = str(name).lower()
    if "loss" in low or "perplex" in low:
        return False
    vals = [v for v in values if _finite_number(v)]
    if not vals or any(v < 0 or v > 1 for v in vals):
        return False
    return direction == "max" or any(word in low for word in _RATE_WORDS)


def _metric_label(name) -> str:
    """'accuracy' -> 'Accuracy', 'val_loss' -> 'Val loss'."""
    text = str(name).replace("_", " ").strip()
    return text[:1].upper() + text[1:]


_BACKEND_LABELS = {"lightning": "Lightning AI", "modal": "Modal", "kaggle": "Kaggle", "local": "this computer"}


def _where(backend) -> str:
    """A run's `backend` in plain words: 'lightning T4' -> 'Lightning AI (T4)', 'local' -> 'this computer'."""
    text = str(backend or "").strip()
    if not text:
        return ""
    parts = re.split(r"[\s:/]+", text, maxsplit=1)
    name = _BACKEND_LABELS.get(parts[0].lower(), parts[0])
    rest = parts[1].strip() if len(parts) > 1 else ""
    return f"{name} ({rest})" if rest else name


def _eta_text(eta) -> str | None:
    """'4 min', '~4 min' or 'about 4 min' -> '4 min'; None when there is no ETA."""
    text = re.sub(r"^(~|≈|about|approx\.?|approximately)\s*", "", str(eta or "").strip(), flags=re.I).strip()
    return text if text and text not in ("—", "-", "None") else None


def _step_pct(run: dict, trained: bool = True) -> int | None:
    """How far through its steps the run is, or None when unknown: no step or total, or step 0 before the run has
    logged any training point (a run that has not started training is not "0% done")."""
    step, total = run.get("step"), run.get("total")
    if not _finite_number(step) or not _finite_number(total) or total <= 0 or (step == 0 and not trained):
        return None
    return int(round(_pct(step, total)))


def _clock(text) -> str | None:
    """An ISO time as '10:05 UTC'; None when it is not one."""
    try:
        when = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc)
    return f"{when:%H:%M} UTC"


def _met(value, target, direction) -> bool:
    return value <= target if direction == "min" else value >= target


def _better(a, b, direction) -> bool:
    return a < b if direction == "min" else a > b


def _fmt_time(text) -> str:
    """An ISO time as '1 Oct 10:05 UTC'; anything else as it is (escaped)."""
    try:
        when = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return _disp(text)
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc)
    return f"{when.day} {when:%b %H:%M} UTC"


# --- the data behind the page ---

def _focus_run(runs: list) -> dict | None:
    """The run the page is about: the last active run, else the last run, else None."""
    runs = [r for r in runs if isinstance(r, dict)]
    active = [r for r in runs if r.get("state") in ACTIVE_STATES]
    return (active or runs or [None])[-1]


def _run_rows(lab: Path, run_id) -> list[dict]:
    if run_id is None:
        return []
    return [r for r in runlib.read_metrics(lab / "runs" / str(run_id) / "metrics.jsonl") if isinstance(r, dict)]


def _metric_series(rows: list, name) -> dict[str, list[tuple]]:
    """{split: [(step, value), ...]} for one metric, sorted by step; rows with a non-finite step or value are
    dropped (bad data must not reach the chart math)."""
    out: dict[str, list[tuple]] = {}
    for r in rows:
        if not isinstance(r, dict) or r.get("name") != name:
            continue
        step, value = r.get("step"), r.get("value")
        if _finite_number(step) and _finite_number(value):
            out.setdefault(str(r.get("split") or "result"), []).append((step, value))
    for points in out.values():
        points.sort(key=lambda p: p[0])
    return out


def _headline_split(series: dict) -> str | None:
    """The split the sentence reads while a run is going: validation when the run logs it, else test, else train."""
    for key in ("val", "test", "train"):
        if series.get(key):
            return key
    return next((key for key, points in series.items() if points), None)


def _close(a, b) -> bool:
    """Equal up to rounding to 3 decimals (a `best` copied from metrics.jsonl may be rounded)."""
    return math.isclose(a, b, rel_tol=5e-4, abs_tol=5e-4)


def _split_of(series: dict, value) -> str | None:
    """The split a reported value comes from: the first split whose last point is that value (test, then validation,
    then training, then the rest), else the first that holds it anywhere; None when no point matches."""
    order = [k for k in ("test", "val", "train") if series.get(k)] + [
        k for k in series if k not in ("test", "val", "train") and series[k]]
    for k in order:
        if _close(series[k][-1][1], value):
            return k
    return next((k for k in order if any(_close(v, value) for _, v in series[k])), None)


def _best_split(doc: dict, series: dict, focus: dict | None, best) -> str | None:
    """The split of the focus run that `best` comes from; None when best belongs to another run or matches no point."""
    run = doc["best"].get("run") if isinstance(doc.get("best"), dict) else None
    if focus is None or (run not in (None, "") and str(run) != str(focus.get("id"))):
        return None
    return _split_of(series, best)


def _start_of(series: dict, split, final) -> tuple | None:
    """(step, value) where `split` started (its step-0 or earliest point) when that comes before the point holding
    `final`; None when the split has no earlier point, so there is no "went from" to claim."""
    points = (series.get(split) or []) if split else []
    if not points or final is None:
        return None
    at = max((i for i, (_, v) in enumerate(points) if _close(v, final)), default=len(points) - 1)
    return points[0] if at > 0 else None


def _result(doc: dict, series: dict, focus: dict | None) -> tuple:
    """(value, split): what the page reports for the focus run and the split it comes from (None when unknown).
    It is `best` once the run is done, else the latest point of the headline split, else the run's own metric,
    else `best`."""
    head = _headline_split(series)
    if head:
        latest, split = series[head][-1][1], head
    elif focus is not None and _finite_number(focus.get("metric")):
        latest, split = focus["metric"], None
    else:
        latest, split = None, None
    best = _best_value(doc)
    if best is not None and ((focus or {}).get("state") == "done" or latest is None):
        return best, _best_split(doc, series, focus, best)
    return latest, split


def _best_value(doc: dict):
    best = doc.get("best")
    if isinstance(best, dict) and _finite_number(best.get("value")):
        return best["value"]
    return None


def _downsample(points: list, cap: int = MAX_POINTS) -> list[tuple]:
    """At most `cap` points: each bucket of consecutive points becomes one, at its last step, with their mean."""
    if len(points) <= cap:
        return list(points)
    size = math.ceil(len(points) / cap)
    out = []
    for i in range(0, len(points), size):
        chunk = points[i:i + size]
        out.append((chunk[-1][0], sum(v for _, v in chunk) / len(chunk)))
    return out


def _ma_window(n: int) -> int:
    """The moving-average window for `n` points: about 5% of them, at least 5."""
    return max(5, math.ceil(n * 0.05))


def _moving_average(points: list, window: int) -> list[tuple]:
    """A trailing moving average: each point becomes the mean of itself and up to `window - 1` points before it, so
    the last point says where the loss is now."""
    out, total = [], 0.0
    for i, (x, y) in enumerate(points):
        total += y
        if i >= window:
            total -= points[i - window][1]
        out.append((x, total / min(i + 1, window)))
    return out


# --- 1. Now: one plain sentence ---

def _lead(run: dict, trained: bool = True) -> str:
    where = _where(run.get("backend"))
    on = f" on {where}" if where else ""
    state = run.get("state")
    pct = _step_pct(run, trained)
    if state == "running":
        eta, started = _eta_text(run.get("eta")), _clock(run.get("started"))
        done = [f"{pct}% done"] if pct is not None else [f"started {started}"] if started else []
        parts = done + ([f"about {eta} left"] if eta else [])
        return f"Training{on}" + (": " + ", ".join(parts) if parts else "") + "."
    if state == "starting":
        return f"Starting{on}."
    if state == "queued":
        return f"Waiting to start{on}."
    if state == "done":
        return f"Finished{on}."
    if state == "stopped":
        return f"The last run stopped{on}" + (f" at {pct}% done" if pct is not None else "") + "."
    reason = re.sub(r"^\s*failed\s*:?\s*", "", str(run.get("detail") or ""), flags=re.I).strip().rstrip(".")
    return f"The last run failed{on}" + (f": {reason}" if reason else "") + "."


def now_sentence(doc: dict, series: dict, trained: bool | None = None) -> str:
    """The page's top sentence, in plain words (not escaped). `series` is {split: [(step, value), ...]} of the
    goal's metric for the run the page is about (_focus_run). The result is `best` once the run is done, else the
    latest point on the validation split when it logs one, else test, else train. The start is the first point
    (step 0) of the same split the result comes from; with no earlier point on that split there is no "went from".
    `trained` says whether the run has logged any training point (None: guessed from `series`); before that, step 0
    is not shown as "0% done". For example: "Training on Lightning AI (T4): 60% done, about 4 min left. Accuracy
    went from 54% to 76%; the target is 80%." """
    goal = doc["goal"]
    metric, target, direction = goal["metric"], goal["target"], goal["direction"]
    series = series or {}
    best = _best_value(doc)
    values = [v for points in series.values() for _, v in points] + [target] + ([best] if best is not None else [])
    percent = _percent_metric(metric, direction, values)
    or_lower = " or lower" if direction == "min" else ""
    words = str(metric).replace("_", " ")
    has_target = _finite_number(target)
    target_text = f" Target: {words} {_fmt_value(target, percent)}{or_lower}." if has_target else ""
    runs = [r for r in doc.get("runs") or [] if isinstance(r, dict)]
    focus = _focus_run(runs)
    if focus is None:
        return "Nothing has run yet." + target_text

    state = focus.get("state")
    lead = _lead(focus, bool(series.get("train")) if trained is None else trained)
    others = sum(r.get("state") in ACTIVE_STATES for r in runs) - (state in ACTIVE_STATES)
    if others > 0:
        lead += f" {others} more run{' is' if others == 1 else 's are'} active."
    final, split = _result(doc, series, focus)
    if final is None:
        return f"{lead} No results yet.{target_text}"
    first = start_point = _start_of(series, split, final)
    if first is None and split and series[split][0][0] == 0 and _close(series[split][0][1], final):
        first = series[split][0]  # the only point so far is the start itself

    show_best = state in ACTIVE_STATES and best is not None and _better(best, final, direction)
    s, f, t, b = _fmt_values([final if first is None else first[1], final, target if has_target else final,
                              best if show_best else final], percent)
    name = _metric_label(metric)
    if start_point is not None:
        clause = f"{name} went from {s} to {f}"
    elif first is not None:
        clause = f"{name} is {s} at the start"
    else:
        clause = f"{name} is {f}" + (" so far" if state in ACTIVE_STATES else "")
    if not has_target:
        tail = "."
    elif state == "done":
        reached = "reached" if _met(final, target, direction) else "not reached"
        tail = f"; the target of {t}{or_lower} is {reached}."
    else:
        tail = f"; the target is {t}{or_lower}."
    return f"{lead} {clause}{tail}" + (f" The best so far is {b}." if show_best else "")


# --- 2. Progress to the target ---

def _bar_position(baseline, value, target, direction) -> float | None:
    """Where `value` sits on a bar from the start (baseline, left) to the target (right), in [0, 100]; without a
    start, the share of the target (as before). None when there is no value."""
    if not _finite_number(value) or not _finite_number(target):
        return None
    if _met(value, target, direction):
        return 100.0
    if _finite_number(baseline) and not _met(baseline, target, direction):
        return max(0.0, min(100.0, (value - baseline) / (target - baseline) * 100.0))
    return _goal_pct(value, target, direction)


def _render_target_bar(baseline, value, target, direction, percent: bool = False, label: str = "Best so far") -> str:
    """The progress bar: the start on the left, the target on the right, `value` marked (works for "min")."""
    pos = _bar_position(baseline, value, target, direction)
    has_start = _finite_number(baseline) and not _met(baseline, target, direction)
    b, v, t = _fmt_values([baseline if has_start else target, value if pos is not None else target, target], percent)
    or_lower = " or lower" if direction == "min" else ""
    if has_start:
        left = f"Start {b}"
    elif direction == "max" and pos is not None:  # with no result yet, a bare "0%" would read as "0% done"
        left = _fmt_value(0, percent)
    else:
        left = ""
    if pos is None:
        fill, flag, caption = 0.0, "", "No result yet."
    else:
        fill = pos
        align = "al-l" if pos < 18 else "al-r" if pos > 82 else "al-c"
        flag = (f'<div class="bar-flag {align}" style="left:{pos:.1f}%"><span>{_esc(label)}</span> <b>{v}</b></div>')
        if pos >= 100.0:
            caption = "Target reached."
        elif has_start and _better(baseline, value, direction):
            caption = "Worse than at the start, so far."
        elif has_start:
            caption = f"{pos:.0f}% of the way from the start to the target."
        else:
            caption = f"{pos:.0f}% of the way to the target."
    mark = f'<span class="bar-mark" style="left:{fill:.1f}%"></span>' if pos is not None else ""
    return (
        f'<div class="bar-wrap">{flag}'
        f'<div class="bar bar-large"><div class="bar-fill" style="width:{fill:.1f}%"></div>{mark}</div>'
        f'<div class="bar-ends"><span>{left}</span><span>Target {t}{or_lower}</span></div></div>'
        f'<p class="progress-label">{caption}</p>'
    )


# --- 3. Charts (inline SVG) ---

CHART_W, CHART_H = 400, 236
CHART_LEFT, CHART_RIGHT, CHART_TOP, CHART_BOTTOM = 54, 14, 16, 44
_SPLIT_LEGEND = {"val": "Validation (checked during training)", "test": "Test (scored at the start and the end)",
                 "train": "Training examples"}
_SPLIT_WORDS = {"val": "validation", "test": "test", "train": "training"}


def _ticks(lo: float, hi: float, count: int = 4, bounds: tuple | None = None, min_step: float = 0.0):
    """About `count` round tick values covering [lo, hi] and their step."""
    if hi < lo:
        lo, hi = hi, lo
    if hi - lo < 1e-12:
        pad = abs(hi) * 0.1 or 1.0
        lo, hi = lo - pad, hi + pad
        if bounds:
            lo, hi = max(lo, bounds[0]), min(hi, bounds[1])
    raw = (hi - lo) / count
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw * (1 - 1e-9))
    step = max(step, min_step)
    start = math.floor(lo / step + 1e-9) * step
    n = max(1, math.ceil((hi - start) / step - 1e-9))
    return [start + i * step for i in range(n + 1)], step


def _tick_label(value: float, step: float, percent: bool) -> str:
    scale = 100 if percent else 1
    s = step * scale
    decimals = 0
    while decimals < 4 and abs(round(s, decimals) - s) > 1e-9:
        decimals += 1
    return _unsign_zero(f"{value * scale:.{decimals}f}") + ("%" if percent else "")


def _svg_chart(series: list[dict], refs: list[dict], *, percent: bool, y_title: str, x_title: str, aria: str,
               x_domain: tuple | None = None, x_ticks: list | None = None) -> str:
    """A line chart with labelled axes. `series`: [{key, points, line, dots}] drawn in order; `refs`: dashed
    horizontal lines [{key, value, text, where}] with `where` "left-above", "right-above" or "right-below"."""
    W, H, L, R, T, B = CHART_W, CHART_H, CHART_LEFT, CHART_RIGHT, CHART_TOP, CHART_BOTTOM
    xs = [x for s in series for x, _ in s["points"]]
    ys = [y for s in series for _, y in s["points"]] + [r["value"] for r in refs]
    if x_domain is None:
        x_ticks, _ = _ticks(min(xs + [0]), max(xs), 4, min_step=1)
        x_domain = (x_ticks[0], x_ticks[-1])
    y_ticks, y_step = _ticks(min(ys), max(ys), 4, (0.0, 1.0) if percent else None)
    x_lo, x_hi = x_domain
    y_lo, y_hi = y_ticks[0], y_ticks[-1]

    def sx(x):
        return L + (x - x_lo) / ((x_hi - x_lo) or 1) * (W - L - R)

    def sy(y):
        return (H - B) - (y - y_lo) / ((y_hi - y_lo) or 1) * (H - B - T)

    x_step = (x_ticks[1] - x_ticks[0]) if len(x_ticks) > 1 else 1
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="{_esc(aria)}">']
    for t in y_ticks:
        y = sy(t)
        out.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}"></line>')
        out.append(f'<text class="tick-y" x="{L - 8}" y="{y + 4:.1f}" text-anchor="end">'
                   f'{_tick_label(t, y_step, percent)}</text>')
    out.append(f'<line class="axis" x1="{L}" x2="{W - R}" y1="{H - B}" y2="{H - B}"></line>')
    for t in x_ticks:
        out.append(f'<text class="tick-x" x="{sx(t):.1f}" y="{H - B + 17}" text-anchor="middle">'
                   f'{_tick_label(t, x_step, False)}</text>')
    out.append(f'<text class="axis-title" x="{(L + W - R) / 2:.1f}" y="{H - 6}" text-anchor="middle">'
               f'{_esc(x_title)}</text>')
    out.append(f'<text class="axis-title" transform="translate(13 {(T + H - B) / 2:.1f}) rotate(-90)" '
               f'text-anchor="middle">{_esc(y_title)}</text>')
    for r in refs:
        y = sy(r["value"])
        out.append(f'<line class="ref ref-{r["key"]}" x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}" '
                   'stroke-dasharray="5 4"></line>')
        x, anchor = (L + 6, "start") if r["where"].startswith("left") else (W - R - 6, "end")
        ty = y - 5 if r["where"].endswith("above") else y + 13
        out.append(f'<text class="ref-label ref-label-{r["key"]}" x="{x}" y="{ty:.1f}" text-anchor="{anchor}">'
                   f'{_esc(r["text"])}</text>')
    for s in series:
        points, key = s["points"], _esc(s["key"])
        if len(points) > 1 and s.get("line", True):
            coords = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in points)
            out.append(f'<polyline data-series="{key}" points="{coords}" class="line line-{key}"></polyline>')
        if s.get("dots") or len(points) == 1:
            out.extend(f'<circle class="dot dot-{key}" cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="3.5"></circle>'
                       for x, y in points)
    out.append("</svg>")
    return "".join(out)


def _legend(items: list[tuple]) -> str:
    """items: (key, text, kind) with kind "line", "dot", "hollow" or "dash"."""
    lis = "".join(f'<li><span class="sw sw-{kind} sw-{_esc(key)}" aria-hidden="true"></span>{_esc(text)}</li>'
                  for key, text, kind in items)
    return f'<ul class="legend">{lis}</ul>'


def _figure(name: str, title: str, note: str, svg: str, legend: str) -> str:
    return (f'<figure class="chart-card" data-chart="{name}"><figcaption><h3>{_esc(title)}</h3>'
            f'<p class="muted">{_esc(note)}</p></figcaption>{svg}{legend}</figure>')


def _metric_figure(rows: list, goal: dict, total=None, start_split: str | None = None) -> str:
    """The goal's metric over the training steps: each split its own series, with dashed start and target lines.
    The start line is where `start_split` (the split the reported result comes from; the headline split when None
    or not logged) started, and is left out when that split has no step-0 or earlier point. A run that does not log
    the goal's metric charts its first other metric (not the loss), with no lines."""
    names = [r.get("name") for r in rows if r.get("name") is not None]
    metric = goal["metric"] if goal["metric"] in names else next((n for n in names if n != "loss"), None)
    if metric is None:
        return ""
    series = _metric_series(rows, metric)
    if not series:
        return ""
    is_goal = metric == goal["metric"]
    direction = goal["direction"] if is_goal else None
    target = goal.get("target") if is_goal and _finite_number(goal.get("target")) else None
    values = [v for points in series.values() for _, v in points] + ([target] if target is not None else [])
    percent = _percent_metric(metric, direction, values)
    order = [k for k in ("train", "test", "val") if k in series] + [k for k in series if k not in _SPLIT_LEGEND]
    drawn = []
    for key in order:
        points = _downsample(series[key])
        drawn.append({"key": key if key in _SPLIT_LEGEND else "other", "points": points, "line": True,
                      "dots": len(points) <= 40})
    legend = [(k, _SPLIT_LEGEND.get(k, _metric_label(k)), "line") for k in ("val", "test", "train") if k in series]
    legend += [("other", _metric_label(k), "line") for k in series if k not in _SPLIT_LEGEND]
    refs = []
    if is_goal:
        split = start_split if series.get(start_split) else _headline_split(series)
        points = series[split]
        start = points[0][1] if len(points) > 1 or points[0][0] == 0 else None
        s = _fmt_value(start, percent) if start is not None else ""
        if start is not None and target is not None:
            s, t = _fmt_values([start, target], percent)
        elif target is not None:
            t = _fmt_value(target, percent)
        if start is not None:
            word = f"{_SPLIT_WORDS.get(split, split)} " if len(series) > 1 else ""
            refs.append({"key": "baseline", "value": start, "text": f"{word}start {s}",
                         "where": "right-below" if direction == "min" else "right-above"})
            legend.append(("baseline", f"Start{' on ' + word.strip() if word else ''} ({s})", "dash"))
        if target is not None:
            refs.append({"key": "target", "value": target, "text": f"target {t}", "where": "left-above"})
            legend.append(("target", f"Target ({t})", "dash"))
    x_max = max(x for points in series.values() for x, _ in points)
    if _finite_number(total) and total > x_max:
        x_max = total
    x_ticks, _ = _ticks(0, x_max, 4, min_step=1)
    label = _metric_label(metric)
    svg = _svg_chart(drawn, refs, percent=percent, y_title=label, x_title="Training step",
                     aria=f"{label} over training steps", x_domain=(0, x_ticks[-1]), x_ticks=x_ticks)
    better = {"max": "Higher is better. ", "min": "Lower is better. "}.get(direction, "")
    note = better + ("The dashed lines show where it started and the target." if len(refs) > 1 else
                     "The dashed line shows the target." if target is not None and refs else
                     "The dashed line shows where it started." if refs else "Each line is one set of examples.")
    return _figure("metric", f"{label} during training", note, svg, _legend(legend))


def _loss_figure(rows: list, total=None) -> str:
    """The training loss: each logged step thin and faint, and from HEALTH_MIN_POINTS points its moving average
    (a window of about 5% of the points, at least 5) as the main line."""
    points = _metric_series(rows, "loss").get("train") or []
    if not points:
        return ""
    raw = _downsample(points)
    drawn = [{"key": "loss", "points": raw, "line": True, "dots": len(raw) == 1}]
    legend = [("loss", "Loss at each step", "line")]
    if len(points) >= HEALTH_MIN_POINTS:
        drawn.append({"key": "trend", "points": _downsample(_moving_average(points, _ma_window(len(points)))),
                      "line": True})
        legend.append(("trend", "Moving average (the trend)", "line"))
    x_max = max(raw[-1][0], total if _finite_number(total) else 0)
    x_ticks, _ = _ticks(0, x_max, 4, min_step=1)
    svg = _svg_chart(drawn, [], percent=False, y_title="Loss", x_title="Training step",
                     aria="Training loss over steps", x_domain=(0, x_ticks[-1]), x_ticks=x_ticks)
    return _figure("loss", "Training loss",
                   "How wrong the model still is on its training examples. Lower is better; it should go down.",
                   svg, _legend(legend))


def _results_figure(rows: list, goal: dict) -> str:
    """A research loop's experiments: each scored one a dot (kept filled, discarded hollow), the kept ones joined,
    with the dashed target."""
    scored = [(i + 1, r) for i, r in enumerate(rows) if r["metric"] is not None]
    if not scored:
        return ""
    keep = [(i, r["metric"]) for i, r in scored if r["status"] == "keep"]
    discard = [(i, r["metric"]) for i, r in scored if r["status"] != "keep"]
    target = goal.get("target") if _finite_number(goal.get("target")) else None
    percent = _percent_metric(goal["metric"], goal["direction"], [m for _, m in keep + discard] + [target])
    t = _fmt_value(target, percent) if target is not None else ""
    n = len(rows)
    x_ticks = list(range(1, n + 1)) if n <= 10 else [x for x in _ticks(1, n, 5, min_step=1)[0] if 1 <= x <= n]
    drawn = [{"key": "kept", "points": keep, "line": True, "dots": False},
             {"key": "discard", "points": discard, "line": False, "dots": True},
             {"key": "keep", "points": keep, "line": False, "dots": True}]
    refs = [{"key": "target", "value": target, "text": f"target {t}", "where": "left-above"}] if target is not None \
        else []
    label = _metric_label(goal["metric"])
    svg = _svg_chart(drawn, refs, percent=percent, y_title=label, x_title="Experiment",
                     aria=f"{label} per experiment", x_domain=(0.5, n + 0.5), x_ticks=x_ticks)
    legend = _legend([("keep", "Kept (it improved the result)", "dot"), ("discard", "Discarded", "hollow")]
                     + ([("target", f"Target ({t})", "dash")] if target is not None else []))
    crashed = len(rows) - len(scored)
    note = f"Each dot is one experiment's {label.lower()}. The line joins the kept ones." + (
        f" {crashed} crashed and {'has' if crashed == 1 else 'have'} no dot." if crashed else "")
    return _figure("experiments", "Experiments", note, svg, legend)


# --- 3b. Training health ---

HEALTH_MIN_POINTS = 10  # fewer training-loss points than this: too early to judge
_HEALTH_VERDICTS = {"improving": "Still improving", "levelling": "Levelling off", "plateau": "Plateaued"}
_HEALTH_HINTS = {
    "improving": "More training would likely help: a longer run should score higher.",
    "levelling": "More training may add a little; a change (learning rate, model or data) will likely matter more.",
    "plateau": "More of the same won't help; try a change (learning rate, a bigger model or more data).",
    "worse": "More of the same won't help: the model may be starting to memorise its training examples. Try a "
             "change (fewer steps, more data or more regularisation).",
}


def _step_text(step) -> str:
    return str(int(step)) if float(step).is_integer() else _fmt_num(step)


def _trend_split(evals: dict) -> str | None:
    """The split whose last two checks show the trend: validation (or another held-out split) with 2+ points; test
    only with 3+, since a test scored just at the start and the end says nothing about the last stretch."""
    order = [k for k in ("val",) if k in evals] + [k for k in evals if k not in ("val", "test")] + ["test"]
    return next((k for k in order if len(evals.get(k) or []) >= (3 if k == "test" else 2)), None)


def training_health(rows: list, metric: str = "accuracy", direction: str = "max") -> dict | None:
    """Whether more training would help, from a run's metrics.jsonl rows: {"state", "verdict", "reason", "hint"}
    with state "improving", "levelling" or "plateau" and verdict "Still improving", "Levelling off" or "Plateaued".
    The held-out `metric` between the last two checks decides (up by more than 1 point, or 1% for a metric that is
    not a percentage: still improving; more than 0.2: small gains; about flat: levelling off if the training loss's
    moving average over the last ~20% of steps is still falling by more than 1%, else plateaued; down by more than
    1 point: plateaued, as it may be memorising). The loss alone decides only when no split has two checks yet
    (falling by more than 5%: still improving; by more than 1%: small gains). None with fewer than HEALTH_MIN_POINTS finite training-loss
    points or no held-out check of `metric`; non-finite and malformed rows are skipped."""
    rows = [r for r in rows or [] if isinstance(r, dict)]
    loss = _metric_series(rows, "loss").get("train") or []
    evals = {k: p for k, p in _metric_series(rows, metric).items() if k != "train" and p}
    if len(loss) < HEALTH_MIN_POINTS or not evals:
        return None

    smooth = _moving_average(loss, _ma_window(len(loss)))
    cut = loss[-1][0] - 0.2 * (loss[-1][0] - loss[0][0])
    tail = [p for p in smooth if p[0] >= cut]
    tail = tail if len(tail) >= 2 else smooth[-2:]
    a, b = tail[0][1], tail[-1][1]
    drop = (a - b) / abs(a) if a else 0.0
    loss_level = "big" if drop > 0.05 else "small" if drop > 0.01 else "flat"
    la, lb = next(pair for d in (2, 3, 4) for pair in [(f"{a:.{d}f}", f"{b:.{d}f}")] if pair[0] != pair[1] or d == 4)
    loss_clause = {
        "big": f"the training loss was still falling ({la} → {lb}) over the last 20% of steps",
        "small": f"the training loss fell only {drop * 100:.0f}% ({la} → {lb}) over the last 20% of steps",
        "flat": f"the training loss {'went up' if drop < -0.01 else 'stayed about flat'} ({la} → {lb}) over the "
                "last 20% of steps",
    }[loss_level]

    eval_level, eval_clause = None, ""
    split = _trend_split(evals)
    if split:
        (s1, v1), (s2, v2) = evals[split][-2:]
        percent = _percent_metric(metric, direction, [v for p in evals.values() for _, v in p])
        gain = (v1 - v2 if direction == "min" else v2 - v1) / (1.0 if percent else max(abs(v1), 1e-12))
        eval_level = "big" if gain > 0.01 else "small" if gain > 0.002 else "worse" if gain < -0.01 else "flat"
        e1, e2 = (f"{v * 100:.1f}%" for v in (v1, v2)) if percent else _fmt_values([v1, v2], False)
        what = f"{_SPLIT_WORDS.get(split, split)} {str(metric).replace('_', ' ')}"
        moved = "rose" if v2 > v1 else "fell"
        steps = f"(steps {_step_text(s1)} and {_step_text(s2)})"
        eval_clause = {
            "big": f"{what} {moved} from {e1} to {e2} between the last two checks {steps}",
            "small": f"{what} {moved} only a little, from {e1} to {e2}, between the last two checks {steps}",
            "flat": f"{what} hardly moved between the last two checks ({e1} → {e2})",
            "worse": f"{what} got worse, from {e1} to {e2}, between the last two checks {steps}",
        }[eval_level]

    # The held-out check decides when there is one (the loss alone can keep falling while the model memorises);
    # the loss only breaks a flat held-out check (still falling: levelling, not plateau) or stands in for a missing one.
    if eval_level is None:
        state = {"big": "improving", "small": "levelling"}.get(loss_level, "plateau")
    elif eval_level == "big":
        state = "improving"
    elif eval_level == "small":
        state = "levelling"
    elif eval_level == "flat" and loss_level != "flat":
        state = "levelling"
    else:
        state = "plateau"
    agree = (eval_level in ("big", "small")) == (loss_level in ("big", "small"))
    reason = (", and " if agree else ", while ").join(c for c in (eval_clause, loss_clause) if c)
    if state == "levelling":
        reason = "the gains are small: " + reason
    return {"state": state, "verdict": _HEALTH_VERDICTS[state], "reason": reason,
            "hint": _HEALTH_HINTS["worse" if eval_level == "worse" else state]}


def _eval_table(rows: list, goal: dict) -> str:
    """The held-out scores at each check: one row per evaluation step, one column per split and metric (the goal's
    metric, then the others the run logs, such as ECE; not the loss). The latest 20 checks."""
    names = list(dict.fromkeys(r.get("name") for r in rows if isinstance(r.get("name"), str)))
    names = sorted((n for n in names if n != "loss"), key=lambda n: n != goal["metric"])[:3]
    columns = []
    for name in names:
        series = {k: p for k, p in _metric_series(rows, name).items() if k != "train" and p}
        direction = goal["direction"] if name == goal["metric"] else None
        percent = _percent_metric(name, direction, [v for p in series.values() for _, v in p])
        for split in [k for k in ("val", "test") if k in series] + [k for k in series if k not in ("val", "test")]:
            columns.append((name, split, dict(series[split]), percent))
    if not columns:
        return ""
    groups = [(name, sum(c[0] == name for c in columns)) for name in dict.fromkeys(c[0] for c in columns)]
    top = "".join(f'<th colspan="{n}">{_esc(name.upper() if len(name) <= 3 else _metric_label(name))}</th>'
                  for name, n in groups)
    sub = "".join(f"<th>{_esc({'val': 'Validation', 'test': 'Test'}.get(split, _metric_label(split)))}</th>"
                  for _, split, _, _ in columns)
    steps = sorted({s for _, _, values, _ in columns for s in values})[-20:]
    body = "".join("<tr><td>" + _step_text(s) + (" (start)" if s == 0 else "") + "</td>" + "".join(
        "<td>" + ("—" if s not in values else f"{values[s] * 100:.1f}%" if percent else _fmt_num(values[s]))
        + "</td>" for _, _, values, percent in columns) + "</tr>" for s in steps)
    return (f'<div class="table-wrap"><table class="evals"><thead><tr><th rowspan="2">Step</th>{top}</tr>'
            f"<tr>{sub}</tr></thead><tbody>{body}</tbody></table></div>")


def _render_health(health: dict | None, rows: list, goal: dict, loss_figure: str) -> str:
    """The Training health card: the verdict with its reason and what it means, the loss chart and the scores at each
    check. Nothing when there is too little data to judge (health is None)."""
    if health is None:
        return ""
    table = _eval_table(rows, goal)
    names = {r.get("name") for r in rows}
    better = [f"{'lower' if goal['direction'] == 'min' else 'higher'} {str(goal['metric']).replace('_', ' ')}"]
    better += ["lower ECE"] if "ece" in names and goal["metric"] != "ece" else []
    note = f"Measured on examples the model does not train on; {' and '.join(better)} is better."
    evals = (f'<div class="evals"><h3>Scores at each check</h3><p class="muted">{_esc(note)}</p>{table}</div>'
             if table else "")
    return (f'<section class="card health" data-state="{health["state"]}"><h2>Training health</h2>'
            f'<p class="verdict"><strong>{_esc(health["verdict"])}:</strong> {_esc(health["reason"])}.</p>'
            f'<p class="muted hint">{_esc(health["hint"])}</p>'
            f'<div class="health-grid">{loss_figure}{evals}</div></section>')


def _render_chart(lab: Path, run_id, goal: dict, total=None) -> str:
    """The metric chart of one run (a <figure>), or "" when it has no numbers yet."""
    return _metric_figure(_run_rows(Path(lab), run_id), goal, total)


def _render_charts(figures: list[str]) -> str:
    figures = [f for f in figures if f]
    if not figures:
        return ('<section class="card charts-empty"><p class="muted">The charts appear here once a run reports its '
                "first numbers.</p></section>")
    return f'<section class="charts{" single" if len(figures) == 1 else ""}">{"".join(figures)}</section>'


# --- 4. Plan, 5. Cost and time ---

_STAGE_WORDS = {"planned": "Planned", "running": "Running now", "done": "Done", "skipped": "Skipped"}


def _render_stages(stages: list) -> str:
    if not stages:
        return ""
    items = []
    for s in stages:
        state = s["state"]
        detail = f'<span class="stage-detail">{_esc(s["detail"])}</span>' if str(s.get("detail") or "").strip() else ""
        items.append(f'<li class="stage stage-{_esc(state)}"><span class="stage-dot" aria-hidden="true"></span>'
                     f'<span class="stage-name">{_esc(s["name"])}</span>'
                     f'<span class="stage-state">{_STAGE_WORDS.get(state, _esc(state))}</span>{detail}</li>')
    done = sum(s["state"] == "done" for s in stages)
    return (f'<section class="card plan"><div class="card-head"><h2>Plan</h2>'
            f'<span class="muted">{done} of {len(stages)} stages done</span></div>'
            f'<ol class="timeline">{"".join(items)}</ol></section>')


def _money(value) -> str:
    if not _finite_number(value):
        return "—"
    return f"${value:,.0f}" if value == int(value) and abs(value) >= 10 else f"${value:,.2f}"


def _render_cost(budget: dict) -> str:
    """Spent against the limit, with where the free credit ends marked when `usd_free` (optional) is set."""
    limit, spent, free = budget.get("usd_limit"), budget.get("usd_spent"), budget.get("usd_free")
    note = str(budget.get("free_credit_note") or "").strip()
    if _finite_number(limit) and limit > 0:
        pct, of = _pct(spent, limit), f"spent of {_money(limit)}"
    else:
        pct, of = (100.0 if _finite_number(spent) and spent > 0 else 0.0), "spent; the limit is $0"
    mark, lines = "", []
    if _finite_number(free) and _finite_number(limit) and 0 < free < limit:
        mark = f'<span class="meter-free" style="left:{_pct(free, limit):.1f}%" title="free credit ends"></span>'
        lines.append(f"The tick marks where the {_money(free)} of free credit ends.")
    if _finite_number(free) and _finite_number(spent):
        lines.append("All of it is covered by free credit so far." if spent <= free else
                     f"{_money(spent - free)} is beyond the free credit.")
    warn = " warn" if pct >= 80 else ""
    extra = "".join(f'<p class="muted small">{line}</p>' for line in lines)
    note_p = f'<p class="muted small">{_esc(note)}</p>' if note else ""
    return (f'<section class="card cost"><h2>Cost</h2>'
            f'<p class="big">{_money(spent)} <span class="muted">{of}</span></p>'
            f'<div class="bar meter{warn}"><div class="bar-fill" style="width:{pct:.1f}%"></div>{mark}</div>'
            f"{extra}{note_p}</section>")


def _render_time(focus: dict | None, trained: bool = True) -> str:
    """Time left for the focus run, with a bar of its steps; before the run has logged a training point, step 0 is
    unknown progress, so it shows when the run started instead of "step 0" and an empty bar."""
    if focus is None:
        big, small, bar = "Not started", "The time left shows here once a run starts.", ""
    else:
        state, rid = focus.get("state"), _esc(focus.get("id", ""))
        step, total = focus.get("step"), focus.get("total")
        steps = (f"step {int(step) if float(step).is_integer() else _disp(step)} of "
                 f"{int(total) if float(total).is_integer() else _disp(total)}"
                 if _finite_number(step) and _finite_number(total) else "")
        if _step_pct(focus, trained) is None:
            started = _clock(focus.get("started"))
            steps = f"started {started}" if started else ""
        eta = _eta_text(focus.get("eta"))
        if state == "running":
            big = f"about {_esc(eta)}" if eta else "working on it"
            small = f"left for run {rid}" + (f" · {steps}" if steps else "")
        elif state in ("starting", "queued"):
            big = "starting" if state == "starting" else "waiting"
            small = f"run {rid} " + ("is getting a machine ready" if state == "starting" else "waits for a free slot")
        else:
            big = {"done": "Done", "stopped": "Stopped", "failed": "Failed"}.get(state, _esc(state))
            small = f"run {rid}" + (f" · {steps}" if steps else "")
        pct = _step_pct(focus, trained)
        bar = (f'<div class="bar meter"><div class="bar-fill" style="width:{pct:.1f}%"></div></div>'
               if pct is not None else "")
    return (f'<section class="card time"><h2>Time left</h2><p class="big">{big}</p>{bar}'
            f'<p class="muted small">{small}</p></section>')


# --- 6. Details (collapsed) ---

_RUN_STATE_WORDS = {"queued": "Waiting", "starting": "Starting", "running": "Running", "stopped": "Stopped",
                    "done": "Done", "failed": "Failed"}
_EXPLAIN = {
    "accuracy": "the share of examples the model gets right; higher is better.",
    "ece": "ECE (calibration error): how far the model's confidence is from its real accuracy; lower is better.",
    "loss": "how wrong the model still is on its training examples; lower is better. It should go down as it "
            "learns.",
    "f1": "balances how many of the model's answers are right and how many right answers it finds; higher is better.",
    "perplexity": "how surprised the model is by the text; lower is better.",
}


def _explain(name) -> str:
    low = str(name).lower()
    if low in _EXPLAIN:
        return _EXPLAIN[low]
    tokens = re.split(r"[\s_\-.]+", low)
    return next((text for key, text in _EXPLAIN.items() if key in tokens), "")


def _table(head: list[str], rows: list[list[str]], cls: str = "") -> str:
    th = "".join(f"<th>{h}</th>" for h in head)
    body = "".join("<tr" + (f' class="{r[0]}"' if r[0] else "") + ">" + "".join(f"<td>{c}</td>" for c in r[1:])
                   + "</tr>" for r in rows)
    return f'<div class="table-wrap"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def _provider(backend) -> str:
    """The provider's name for a link: 'modal L4' -> 'Modal', 'lightning T4' -> 'Lightning AI'; "" for local."""
    first = re.split(r"[\s:/]+", str(backend or "").strip(), maxsplit=1)[0]
    return "" if first.lower() == "local" else _BACKEND_LABELS.get(first.lower(), first)


def _run_link(run: dict | None, cls: str = "run-link") -> str:
    """'Open on Modal' for a run with a valid `link` (opens in a new tab, rel=noopener); "" otherwise."""
    if not isinstance(run, dict) or not valid_link(run.get("link")):
        return ""
    name = _provider(run.get("backend"))
    text = f"Open on {name}" if name else "Open the run's page"
    return (f'<a class="{cls}" href="{html.escape(run["link"], quote=True)}" target="_blank" rel="noopener">'
            f'{_esc(text)}<span aria-hidden="true"> ↗</span></a>')


def _render_runs(runs: list) -> str:
    if not runs:
        return '<section class="runs"><h3>Runs</h3><p class="muted">No runs yet.</p></section>'
    runs = [r for r in runs if isinstance(r, dict)]
    links = any(valid_link(r.get("link")) for r in runs)  # the column shows only when a run has a provider page
    rows = [["", _esc(r.get("id", "")), _esc(_where(r.get("backend")) or "—"),
             _RUN_STATE_WORDS.get(r.get("state"), _esc(r.get("state"))),
             f"step {_disp(r.get('step'))} / {_disp(r.get('total'))}", _disp(r.get("metric")), _disp(r.get("eta")),
             _disp(r.get("detail")), _fmt_time(r.get("started")) if r.get("started") else "—"]
            + ([_run_link(r) or "—"] if links else [])
            for r in runs]
    head = ["Run", "Where", "State", "Progress", "Result", "Time left", "Latest message", "Started"]
    head += ["Provider page"] if links else []
    return f'<section class="runs"><h3>Runs</h3>{_table(head, rows)}</section>'


def _render_results(rows: list, goal: dict) -> str:
    if not rows:
        return ""
    kept = sum(r["status"] == "keep" for r in rows)
    cells = ("id", "metric", "status", "backend", "gpu", "minutes", "commit", "change")
    words = {"id": "Experiment", "metric": _esc(goal["metric"]), "status": "Decision", "backend": "Where",
             "gpu": "GPU", "minutes": "Minutes", "commit": "Commit", "change": "What changed"}
    body = [[f"res-{_esc(r['status'])}"] + [_disp(r[c]) for c in cells] for r in rows[::-1][:RESULTS_CAP]]
    more = (f'<p class="muted">{len(rows) - RESULTS_CAP} older experiments in results.tsv</p>'
            if len(rows) > RESULTS_CAP else "")
    return (f'<section class="results"><h3>Experiments</h3><p class="muted">{len(rows)} experiments, {kept} kept '
            "(newest first; keep = it improved the result and stays)</p>"
            f"{_table([words[c] for c in cells], body)}{more}</section>")


def _render_decisions(decisions: list) -> str:
    if not decisions:
        body = '<p class="muted">No decisions waiting.</p>'
    else:
        items = [f"<li><strong>{_disp(d.get('title'))}</strong><p>{_disp(d.get('text'))}</p>"
                 f"<p class=\"rec\">Recommendation: {_disp(d.get('rec'))}</p></li>"
                 for d in decisions if isinstance(d, dict)]
        body = f"<ul class=\"list\">{''.join(items)}</ul>"
    return f'<section class="decisions"><h3>Decisions for you</h3>{body}</section>'


def _render_events(events: list) -> str:
    shown = [e for e in events[:EVENTS_CAP] if isinstance(e, dict)]
    if not shown:
        body = '<p class="muted">No events yet.</p>'
    else:
        items = [f'<li><span class="event-t">{_fmt_time(e.get("t")) if e.get("t") else "—"}</span> '
                 f'{_disp(e.get("text"))}</li>' for e in shown]
        body = f"<ul class=\"list\">{''.join(items)}</ul>"
    return f'<section class="events"><h3>What happened</h3>{body}</section>'


def _render_measurements(rows: list, goal: dict) -> str:
    """Every metric of the run, start and latest per split, each with a one-line explanation."""
    names = list(dict.fromkeys(r.get("name") for r in rows if isinstance(r.get("name"), str)))
    names.sort(key=lambda n: (n != goal["metric"], n == "loss"))
    body = []
    for name in names:
        for split, points in _metric_series(rows, name).items():
            body.append(["", _esc(name), _esc(_SPLIT_WORDS.get(split, split)), _fmt_num(points[0][1]),
                         _fmt_num(points[-1][1]), html.escape(_explain(name), quote=False) or "—"])
    if not body:
        return ""
    head = ["Measurement", "Examples", "Start", "Latest", "What it means"]
    return f'<section class="secondary"><h3>All measurements (latest run)</h3>{_table(head, body)}</section>'


def _render_glossary(goal: dict, rows: list) -> str:
    sym = _DIRECTION_SYMBOL[goal["direction"]]
    goal_text = (f"{_esc(goal['metric'])} {sym} {_fmt_num(goal['target'])}, as the charter states it."
                 if _finite_number(goal.get("target")) else f"{_esc(goal['metric'])}; no target set yet.")
    terms = [("Goal", goal_text),
             ("Step", "one small update of the model from a batch of training examples."),
             ("Validation", "examples kept out of training and checked during it, to see progress honestly."),
             ("Test", "a separate set of examples, scored at the start and once at the end."),
             ("Start", "the score before any training (step 0), the baseline to beat."),
             ("Loss", _EXPLAIN["loss"]),
             ("Plateau", "when the scores stop getting better as training goes on: more of the same training won't "
                         "help, a change (learning rate, model or data) might.")]
    if any(_explain(r.get("name")) == _EXPLAIN["ece"] for r in rows):
        terms.append(("ECE", _EXPLAIN["ece"].split(": ", 1)[1]))
    items = "".join(f"<li><strong>{term}</strong>: {html.escape(text, quote=False) if term != 'Goal' else text}</li>"
                    for term, text in terms)
    return f'<section class="glossary"><h3>What the words mean</h3><ul class="list">{items}</ul></section>'


def _render_details(doc: dict, rows: list, results: list) -> str:
    goal = doc["goal"]
    return ('<details class="details"><summary><span>Details</span> <span class="muted">runs, experiments, '
            "decisions, events and every measurement</span></summary>"
            + _render_runs(doc["runs"]) + _render_results(results, goal) + _render_decisions(doc["decisions"])
            + _render_events(doc["events"]) + _render_measurements(rows, goal) + _render_glossary(goal, rows)
            + "</details>")


def refresh_label(seconds) -> str:
    """How often the page reloads, in plain words: 30 -> '30 s', 90 -> '90 s', 300 -> '5 min', 150 -> '3 min'."""
    sec = int(round(seconds))
    if sec < 120 and sec % 60:
        return f"{sec} s"
    return f"{max(1, round(sec / 60))} min"


def _refresh(doc: dict) -> int:
    sec = doc.get("refresh_seconds")
    return int(round(sec)) if _finite_number(sec) else REFRESH_DEFAULT


def _render_top(doc: dict, sentence: str, percent: bool, focus: dict | None) -> str:
    goal = doc["goal"]
    runs = [r for r in doc["runs"] if isinstance(r, dict)]
    if any(r.get("state") in ACTIVE_STATES for r in runs):
        pill = ('<span class="pill pill-live"><span class="pulse"></span>Live · reloads every '
                f'{refresh_label(_refresh(doc))}</span>')
    elif focus is None:
        pill = '<span class="pill">Not started</span>'
    elif focus.get("state") == "done":
        pill = '<span class="pill pill-done">Finished</span>'
    else:
        pill = '<span class="pill pill-bad">Needs a look</span>'
    n = len(doc["decisions"])
    notice = (f'<p class="notice">{n} decision{" is" if n == 1 else "s are"} waiting for you: see Details '
              "below.</p>" if n else "")
    sym = _DIRECTION_SYMBOL[goal["direction"]]
    target = (f"{_esc(goal['metric'])} {sym} {_fmt_value(goal['target'], percent)}"
              if _finite_number(goal.get("target")) else "none set yet")
    link = _run_link(focus, "run-link btn")
    actions = f'<p class="top-actions">{link}</p>' if link else ""
    return (f'<header class="top"><div class="eyebrow">{pill}<h1>{_esc(goal["text"])}</h1></div>'
            f'<p class="now">{_esc(sentence)}</p><p class="goal-meta">Target: {target}</p>{actions}{notice}</header>')


_CSS = """
*, *::before, *::after { box-sizing: border-box; }
:root {
  color-scheme: light dark;
  --bg: #f6f7f9; --card: #ffffff; --fg: #15171c; --muted: #646b78; --line: #e3e6eb; --grid: #eef0f3;
  --accent: #3657d6; --accent-soft: #e6ebfb; --ink: #2b2f38; --faint: #b9bfca;
  --good: #188a4f; --warn: #c25a12; --bad: #c8322b;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0f1115; --card: #171a20; --fg: #e8eaee; --muted: #9aa2af; --line: #272b33; --grid: #1f232a;
    --accent: #7d9bff; --accent-soft: #1f2840; --ink: #d6d9df; --faint: #4b525e;
    --good: #4cc98a; --warn: #f0954a; --bad: #f2756d;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #0f1115; --card: #171a20; --fg: #e8eaee; --muted: #9aa2af; --line: #272b33; --grid: #1f232a;
  --accent: #7d9bff; --accent-soft: #1f2840; --ink: #d6d9df; --faint: #4b525e;
  --good: #4cc98a; --warn: #f0954a; --bad: #f2756d;
}
html { background: var(--bg); -webkit-text-size-adjust: 100%; }
body { background: var(--bg); color: var(--fg); margin: 0; line-height: 1.5; overflow-wrap: anywhere;
  font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }
.container { max-width: 920px; margin: 0 auto; padding: 28px 16px 40px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
h1 { font-size: 0.95rem; font-weight: 500; color: var(--muted); margin: 0; }
h2 { font-size: 0.8rem; font-weight: 600; margin: 0 0 12px; color: var(--muted); text-transform: uppercase;
  letter-spacing: 0.06em; }
h3 { font-size: 1rem; margin: 0 0 2px; }
p { margin: 0; }
.muted { color: var(--muted); }
.small { font-size: 0.85rem; margin-top: 8px; }
.card, .chart-card { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 20px; }
.card-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.card-head h2 { margin-bottom: 12px; }
.top { padding: 8px 0 4px; }
.eyebrow { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.now { font-size: clamp(1.3rem, 1.05rem + 1.3vw, 1.9rem); font-weight: 600; line-height: 1.3;
  letter-spacing: -0.01em; max-width: 34em; }
.goal-meta { color: var(--muted); margin-top: 10px; }
.notice { margin-top: 12px; padding: 10px 14px; border-radius: 10px; background: var(--accent-soft);
  color: var(--fg); display: inline-block; }
.pill { display: inline-flex; align-items: center; gap: 6px; font-size: 0.78rem; font-weight: 600;
  padding: 3px 10px; border-radius: 999px; border: 1px solid var(--line); color: var(--muted); background: var(--card); }
.pill-live { color: var(--accent); border-color: var(--accent); }
.pill-done { color: var(--good); border-color: var(--good); }
.pill-bad { color: var(--bad); border-color: var(--bad); }
.pulse { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); animation: pulse 2s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: 0.3; } }
@media (prefers-reduced-motion: reduce) { .pulse { animation: none; } }
.bar { position: relative; background: var(--grid); border-radius: 999px; height: 10px; }
.bar-fill { background: var(--accent); height: 100%; border-radius: 999px; }
.bar-large { height: 14px; }
.bar-wrap { padding-top: 34px; }
.bar-mark { position: absolute; top: 50%; width: 20px; height: 20px; margin: -10px 0 0 -10px; border-radius: 50%;
  background: var(--card); border: 4px solid var(--accent); }
.bar-flag { position: relative; height: 0; white-space: nowrap; font-size: 0.9rem; }
.bar-flag > * { position: relative; top: -30px; }
.bar-flag.al-c { transform: translateX(-50%); display: inline-block; }
.bar-flag.al-l { margin-left: -10px; display: inline-block; }
.bar-flag.al-r { transform: translateX(-100%); display: inline-block; margin-left: 10px; }
.bar-flag span { color: var(--muted); }
.bar-ends { display: flex; justify-content: space-between; gap: 12px; margin-top: 10px; font-size: 0.88rem;
  color: var(--muted); }
.progress-label { margin-top: 12px; }
.charts { display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 380px), 1fr)); }
.chart-card { margin: 0; padding: 18px 18px 14px; }
.chart-card figcaption p { font-size: 0.88rem; }
.chart { display: block; width: 100%; height: auto; margin-top: 10px; overflow: visible; }
.chart text { font-family: inherit; font-size: 11px; fill: var(--muted); }
.chart .axis-title { font-size: 11px; fill: var(--fg); }
.chart .grid { stroke: var(--grid); stroke-width: 1; }
.chart .axis { stroke: var(--line); stroke-width: 1; }
.chart .line { fill: none; stroke-width: 2.2; stroke-linejoin: round; stroke-linecap: round; }
.ref { stroke-width: 1.5; }
.ref-target { stroke: var(--good); }
.ref-baseline { stroke: var(--faint); }
.chart .ref-label-target { fill: var(--good); font-weight: 600; }
.chart .ref-label-baseline { fill: var(--muted); }
.line-val, .line-kept, .line-trend { stroke: var(--accent); }
.line-test { stroke: var(--ink); stroke-width: 1.6; }
.line-train, .line-other { stroke: var(--faint); stroke-width: 1.4; }
.line-loss { stroke: var(--faint); stroke-width: 1.1; opacity: 0.75; }
.line-trend { stroke-width: 2.6; }
.line-kept { stroke-width: 1.6; opacity: 0.6; }
.dot-val, .dot-keep, .dot-trend { fill: var(--accent); }
.dot-test { fill: var(--ink); }
.dot-train, .dot-other, .dot-loss { fill: var(--faint); }
.dot-discard { fill: var(--card); stroke: var(--faint); stroke-width: 1.6; }
.legend { list-style: none; padding: 0; margin: 10px 0 0; display: flex; flex-wrap: wrap; gap: 6px 16px;
  font-size: 0.82rem; color: var(--muted); }
.legend li { display: inline-flex; align-items: center; gap: 6px; }
.sw { display: inline-block; flex: none; }
.sw-line { width: 16px; height: 3px; border-radius: 2px; }
.sw-dot, .sw-hollow { width: 9px; height: 9px; border-radius: 50%; }
.sw-hollow { border: 1.6px solid var(--faint); }
.sw-dash { width: 16px; border-top: 2px dashed; height: 0; }
.sw-val, .sw-trend, .sw-keep { background: var(--accent); }
.sw-test { background: var(--ink); }
.sw-train, .sw-other, .sw-loss { background: var(--faint); }
.sw-target { border-color: var(--good); }
.sw-baseline { border-color: var(--faint); }
.charts-empty { text-align: center; padding: 28px 20px; }
.verdict { font-size: 1.1rem; line-height: 1.4; }
.verdict strong { color: var(--accent); }
.health[data-state="levelling"] .verdict strong { color: var(--warn); }
.health[data-state="plateau"] .verdict strong { color: var(--muted); }
.hint { margin-top: 6px; }
.health-grid { display: grid; gap: 20px 28px; margin-top: 16px;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); }
.health .chart-card { border: none; padding: 0; border-radius: 0; background: none; }
.evals h3 { margin-bottom: 2px; }
.evals > p { font-size: 0.88rem; }
table.evals td { font-variant-numeric: tabular-nums; white-space: nowrap; }
table.evals th { vertical-align: bottom; }
table.evals thead tr:first-child th[colspan] { color: var(--fg); }
.charts.single { grid-template-columns: minmax(0, 1fr); }
.charts.single .chart { max-height: 300px; }
.timeline { list-style: none; margin: 0; padding: 0; display: grid; gap: 0; }
.stage { position: relative; display: grid; grid-template-columns: 22px 1fr auto; column-gap: 12px;
  padding: 0 0 18px; align-items: start; }
.stage:last-child { padding-bottom: 0; }
.stage::before { content: ""; position: absolute; left: 10px; top: 22px; bottom: 0; width: 2px; background: var(--line); }
.stage:last-child::before { display: none; }
.stage-dot { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--faint); background: var(--card);
  display: grid; place-items: center; font-size: 12px; font-weight: 700; color: var(--card); }
.stage-name { font-weight: 600; }
.stage-state { font-size: 0.8rem; color: var(--muted); white-space: nowrap; }
.stage-detail { grid-column: 2 / 4; color: var(--muted); font-size: 0.88rem; }
.stage-done .stage-dot { background: var(--good); border-color: var(--good); }
.stage-done .stage-dot::after { content: "✓"; }
.stage-running .stage-dot { border-color: var(--accent); box-shadow: inset 0 0 0 4px var(--card);
  background: var(--accent); }
.stage-running .stage-state { color: var(--accent); font-weight: 600; }
.stage-skipped .stage-name { color: var(--muted); text-decoration: line-through; }
.pair { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); }
.big { font-size: 1.6rem; font-weight: 650; letter-spacing: -0.01em; margin-bottom: 10px; }
.big .muted { font-size: 0.95rem; font-weight: 400; letter-spacing: 0; }
.meter { height: 10px; }
.meter.warn .bar-fill { background: var(--warn); }
.meter-free { position: absolute; top: -4px; bottom: -4px; width: 2px; margin-left: -1px; background: var(--good); }
.details { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 0 20px; }
.details > summary { cursor: pointer; padding: 16px 0; font-weight: 600; list-style-position: outside; }
.details > summary .muted { font-weight: 400; }
.details[open] > summary { border-bottom: 1px solid var(--line); margin-bottom: 4px; }
.details section { padding: 16px 0; border-bottom: 1px solid var(--line); }
.details section:last-child { border-bottom: none; }
.details h3 { margin-bottom: 8px; }
.table-wrap { overflow-x: auto; margin-top: 8px; }
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th, td { text-align: left; padding: 6px 10px 6px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; white-space: nowrap; }
td { overflow-wrap: normal; }
.results tr.res-keep td { color: var(--good); font-weight: 600; }
.results tr.res-crash td { color: var(--bad); }
.list { list-style: none; margin: 0; padding: 0; }
.list li { padding: 8px 0; border-bottom: 1px solid var(--line); }
.list li:last-child { border-bottom: none; }
.rec { color: var(--muted); font-size: 0.85rem; }
.event-t { color: var(--muted); font-size: 0.8rem; margin-right: 6px; white-space: nowrap; }
.top-actions { margin-top: 14px; }
.btn { display: inline-flex; align-items: center; gap: 2px; padding: 7px 14px; border-radius: 999px;
  border: 1px solid var(--accent); color: var(--accent); background: var(--card); font-weight: 600;
  font-size: 0.9rem; text-decoration: none; }
.btn:hover { background: var(--accent-soft); }
.btn:focus-visible, .run-link:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
a.run-link:not(.btn) { color: var(--accent); white-space: nowrap; }
.block h3 { margin-bottom: 8px; }
.custom { overflow-x: auto; }
.custom img, .custom svg, .custom video { max-width: 100%; height: auto; }
footer { color: var(--muted); font-size: 0.8rem; text-align: center; }
@media (max-width: 520px) {
  .card, .chart-card { padding: 16px; border-radius: 12px; }
  .details { padding: 0 16px; }
  .container { padding-top: 20px; }
}
"""


class Page:
    """What the blocks share, worked out once per render from lab/status.json and the focus run's metrics."""

    def __init__(self, lab, doc: dict):
        self.lab, self.doc = Path(lab), doc
        self.goal = goal = doc["goal"]
        self.focus = focus = _focus_run(doc["runs"])
        self.rows = rows = _run_rows(self.lab, focus.get("id") if focus else None)
        self.series = series = _metric_series(rows, goal["metric"])
        self.results = read_results(self.lab / "results.tsv")
        best = _best_value(doc)
        values = [v for points in series.values() for _, v in points] + [goal.get("target")] + [best] * (best is not None)
        self.percent = _percent_metric(goal["metric"], goal["direction"], values)
        self.trained = any(r.get("split") == "train" for r in rows)
        self.sentence = now_sentence(doc, series, self.trained)
        if best is not None:  # the bar marks the best so far; its start is on the split that best comes from
            self.value, self.label, self.split = best, "Best so far", _best_split(doc, series, focus, best)
        else:
            (self.value, self.split), self.label = _result(doc, series, focus), "Latest"
        self.start = _start_of(series, self.split, self.value)
        self.total = focus.get("total") if focus else None
        self.health = training_health(rows, goal["metric"], goal["direction"])
        self.loss = "" if goal["metric"] == "loss" else _loss_figure(rows, self.total)
        self.active = any(isinstance(r, dict) and r.get("state") in ACTIVE_STATES for r in doc["runs"])
        self.refresh = _refresh(doc)


# --- the blocks: each takes the Page and returns its HTML ("" to leave it out) ---

def _block_headline(p: Page) -> str:
    return _render_top(p.doc, p.sentence, p.percent, p.focus)


def _block_progress(p: Page) -> str:
    if not _finite_number(p.goal.get("target")):
        return ""  # no target yet (onboarding's connection check): nothing to show progress toward
    return ('<section class="card progress"><h2>Progress to the target</h2>'
            + _render_target_bar(p.start[1] if p.start else None, p.value, p.goal["target"], p.goal["direction"],
                                 p.percent, p.label) + "</section>")


def _block_charts(p: Page) -> str:
    return _render_charts([_metric_figure(p.rows, p.goal, p.total, p.split), "" if p.health else p.loss,
                           _results_figure(p.results, p.goal)])


def _block_health(p: Page) -> str:
    return _render_health(p.health, p.rows, p.goal, p.loss)


def _block_plan(p: Page) -> str:
    return _render_stages(p.doc.get("stages", []))


def _block_cost(p: Page) -> str:
    return _render_cost(p.doc["budget"])


def _block_time(p: Page) -> str:
    return _render_time(p.focus, p.trained)


def _block_cost_time(p: Page) -> str:
    return f'<div class="pair">{_block_cost(p)}{_block_time(p)}</div>'


def _block_details(p: Page) -> str:
    return _render_details(p.doc, p.rows, p.results)


def _card(inner: str) -> str:
    """A details section shown on its own (a layout that lifts it out of Details) gets a card around it."""
    return f'<div class="card block">{inner}</div>' if inner else ""


BLOCKS = {
    "headline": _block_headline,        # the pill, the goal, the Now sentence, the target and the provider link
    "progress": _block_progress,        # the bar from the start to the target
    "charts": _block_charts,            # the metric over the steps, the loss (until health shows), experiments
    "health": _block_health,            # the Training health card
    "plan": _block_plan,                # the stages as a timeline
    "cost_time": _block_cost_time,      # cost and time left side by side
    "cost": _block_cost,
    "time": _block_time,
    "details": _block_details,          # the collapsed details: the six blocks below
    "runs": lambda p: _card(_render_runs(p.doc["runs"])),
    "results": lambda p: _card(_render_results(p.results, p.goal)),
    "decisions": lambda p: _card(_render_decisions(p.doc["decisions"])),
    "events": lambda p: _card(_render_events(p.doc["events"])),
    "measurements": lambda p: _card(_render_measurements(p.rows, p.goal)),
    "glossary": lambda p: _card(_render_glossary(p.goal, p.rows)),
}
DEFAULT_LAYOUT = ("headline", "progress", "charts", "health", "plan", "cost_time", "details")
_CUSTOM_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SCRIPT = re.compile(r"<(script|iframe|object)\b.*?(?:</\1\s*>|$)|<embed\b[^>]*>", re.I | re.S)
_TAG = re.compile(r"<[a-zA-Z][^>]*>")
_ON_ATTR = re.compile(r"""\s+on[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""", re.I)
_JS_URL = re.compile(r"""(\b(?:href|src|action|formaction|xlink:href)\s*=\s*["']?)\s*javascript:""", re.I)


def strip_scripts(text: str) -> str:
    """`text` without <script>, <iframe>, <object> and <embed> elements (an unclosed one is cut to the end), on*=
    event handlers and javascript: links. A basic filter for the agent's own blocks, not a full HTML sanitizer."""
    text = _SCRIPT.sub("", text)
    text = _TAG.sub(lambda m: _JS_URL.sub(r"\1#", _ON_ATTR.sub("", m.group(0))), text)
    return text


def _custom_block(lab: Path, name: str) -> str:
    """lab/blocks/<name>.html inlined in a card, its <script> tags stripped; "" for a bad name or a missing file."""
    if not _CUSTOM_NAME.match(name):
        return ""
    try:
        text = (lab / "blocks" / f"{name}.html").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    text = strip_scripts(text).strip()
    return f'<section class="card custom" data-block="{_esc(name)}">{text}</section>' if text else ""


def render_blocks(page: Page, layout) -> str:
    out = []
    for name in layout:
        if name.startswith("custom:"):
            out.append(_custom_block(page.lab, name[len("custom:"):]))
        elif name in BLOCKS:
            out.append(BLOCKS[name](page))
    return "".join(out)


def render(lab, doc: dict | None = None) -> str:
    """Render lab/status.json into a self-contained HTML status page: the blocks of its `layout` (DEFAULT_LAYOUT:
    the Now sentence, the progress bar, the charts, training health, the plan, cost and time, and the collapsed
    details), then the footer. It reloads itself every `refresh_seconds` (default 30) while a run is active. `doc`
    renders that document instead of reading lab/status.json (so a change is rendered before it is written)."""
    lab = Path(lab)
    if doc is None:
        doc = json.loads((lab / "status.json").read_text(encoding="utf-8"))
    validate(doc)
    page = Page(lab, doc)
    body = render_blocks(page, doc.get("layout") or DEFAULT_LAYOUT) + (
        f'<footer>Updated {_fmt_time(doc.get("updated"))} · freelab</footer>')
    head_html = "".join([
        "<!doctype html>\n",
        "<!-- freelab status_page -->\n",
        '<html lang="en">\n',
        "<head>\n",
        '<meta charset="utf-8">\n',
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n',
        f'<meta http-equiv="refresh" content="{page.refresh}">\n' if page.active else "",
        f"<title>{_esc(page.goal.get('text') or 'freelab status')}</title>\n",
        "<style>\n",
        _CSS,
        "\n</style>\n",
        "</head>\n",
        "<body>\n",
        '<main class="container">\n',
    ])
    return head_html + body + "\n</main>\n</body>\n</html>\n"


def write_page(lab, doc: dict | None = None) -> Path:
    """Render (from `doc`, else lab/status.json) and write lab/status.html atomically."""
    out = Path(lab) / "status.html"
    atomic_write(out, render(lab, doc))
    return out


@contextmanager
def status_lock(lab):
    """Hold LAB/.status.lock (exclusive) around a read-modify-write of status.json; scripts/poll.py takes it too."""
    with (Path(lab) / ".status.lock").open("a", encoding="utf-8") as lock:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _locked_update(lab, change) -> Path:
    """Read lab/status.json under lab/.status.lock (the lock scripts/poll.py takes around its own read-modify-write),
    apply `change(doc)`, set `updated`, validate and render the page from the new document, then write status.json
    and status.html atomically. Nothing is written when `change`, the validation or the rendering raises."""
    lab = Path(lab)
    with status_lock(lab):
        path = lab / "status.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("status.json must be a JSON object")
        change(doc)
        doc["updated"] = _now()
        page = render(lab, doc)  # validates
        atomic_write(path, json.dumps(doc, indent=2) + "\n")
        out = lab / "status.html"
        atomic_write(out, page)
        return out


def add_event(lab, text: str) -> Path:
    """Put one event at the top of lab/status.json (newest first; trim_events keeps the list short), under the
    lock, atomically, then re-render the page."""
    text = " ".join(str(text).split())
    if not text:
        raise ValueError("the event text is empty")

    def change(doc: dict) -> None:
        if not isinstance(doc.get("events"), list):
            raise ValueError("events must be a list")
        doc["events"].insert(0, {"t": _now(), "text": text})
        trim_events(doc["events"])
    return _locked_update(lab, change)


SET_KEYS = ("best", "budget", "stages", "decisions", "goal", "layout", "refresh_seconds")


def set_key(lab, key: str, value) -> Path:
    """Set one top-level field of lab/status.json (SET_KEYS), or one `budget.NAME` field, to `value` (already
    parsed from JSON), under the lock, validated before it is written, then re-render the page. The fields the
    poll owns (runs, events, updated, version) are not settable: events go through add_event."""
    parts = key.split(".")
    if parts[0] not in SET_KEYS or len(parts) > 2 or (len(parts) == 2 and parts[0] != "budget") \
            or (len(parts) == 2 and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", parts[1])):
        raise ValueError(f"cannot set {key!r}: use one of {', '.join(SET_KEYS)} or budget.NAME")
    if len(parts) == 2 and parts[1].startswith("usd_") and value is not None and not (
            _finite_number(value) and value >= 0):
        raise ValueError(f"{key} must be a number of dollars (0 or more) or null, got {value!r}")

    if key == "goal" and not (isinstance(value, dict) and _finite_number(value.get("target"))):
        raise ValueError("goal.target must be a number: the charter's numeric target")

    def change(doc: dict) -> None:
        if len(parts) == 1:
            doc[key] = value
        else:
            budget = doc.get("budget")
            if not isinstance(budget, dict):
                raise ValueError("budget must be an object")
            budget[parts[1]] = value
    return _locked_update(lab, change)


def forget_run(lab, run_id: str) -> Path:
    """Remove run `run_id`'s entry from lab/status.json (a run that never launched, such as a typo'd id, so it stops
    showing as starting and blocking the cleanup), under the lock, then re-render the page. Its files, if any, stay."""
    def change(doc: dict) -> None:
        runs = doc.get("runs")
        if not isinstance(runs, list):
            raise ValueError("runs must be a list")
        kept = [r for r in runs if not (isinstance(r, dict) and str(r.get("id")) == run_id)]
        if len(kept) == len(runs):
            raise ValueError(f"no run {run_id!r} in status.json")
        doc["runs"] = kept
    return _locked_update(lab, change)


CLI_HELP = """usage:
  status_page.py LAB                        render LAB/status.html from LAB/status.json
  status_page.py event --lab LAB "text"     add one event (newest first)
  status_page.py set --lab LAB KEY JSON     set one field: best, budget, budget.NAME, stages, decisions, goal,
                                            layout or refresh_seconds (the value is JSON: 0.42, null, '"text"')
  status_page.py forget --lab LAB RUN_ID    remove one run's entry (a run that never launched)

Each takes LAB/.status.lock, validates, renders, then writes status.json and status.html atomically.
Exit 0 on success; exit 2 (with the reason on stderr) writes nothing."""


def main(argv=None) -> None:
    """The CLI: see CLI_HELP."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "forget":
        parser = argparse.ArgumentParser(prog="status_page.py forget", epilog=CLI_HELP,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("--lab", type=Path, default=Path("lab"), help="lab directory (default lab)")
        parser.add_argument("run_id", help="the run whose entry to remove")
        args = parser.parse_args(argv[1:])
        try:
            forget_run(args.lab, args.run_id)
        except (ValueError, OSError) as e:
            print(f"status_page: could not forget {args.run_id}: {e}", file=sys.stderr)
            raise SystemExit(2)
        return
    if argv and argv[0] == "set":
        parser = argparse.ArgumentParser(prog="status_page.py set", epilog=CLI_HELP,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("--lab", type=Path, default=Path("lab"), help="lab directory (default lab)")
        parser.add_argument("key", help=f"one of {', '.join(SET_KEYS)}, or budget.NAME (e.g. budget.usd_spent)")
        parser.add_argument("value", help="the new value, as JSON (e.g. 0.42, null, '{\"value\": 0.86, ...}')")
        args = parser.parse_args(argv[1:])
        try:
            value = json.loads(args.value)
        except ValueError as e:
            print(f"status_page: the value is not JSON ({e}); quote text as JSON, e.g. '\"text\"'", file=sys.stderr)
            raise SystemExit(2)
        try:
            set_key(args.lab, args.key, value)
        except (ValueError, OSError) as e:
            print(f"status_page: could not set {args.key}: {e}", file=sys.stderr)
            raise SystemExit(2)
        return
    if argv and argv[0] == "event":
        parser = argparse.ArgumentParser(prog="status_page.py event", epilog=CLI_HELP,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("--lab", type=Path, default=Path("lab"), help="lab directory (default lab)")
        parser.add_argument("text", help="the event, in plain words")
        args = parser.parse_args(argv[1:])
        try:
            add_event(args.lab, args.text)
        except (ValueError, OSError) as e:
            print(f"status_page: could not add the event: {e}", file=sys.stderr)
            raise SystemExit(2)
        return
    parser = argparse.ArgumentParser(prog="status_page.py", epilog=CLI_HELP,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("lab", type=Path, help="lab directory containing status.json")
    args = parser.parse_args(argv)
    try:
        with status_lock(args.lab):
            write_page(args.lab)
    except (ValueError, OSError) as e:
        print(f"status_page: invalid status.json: {e}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
