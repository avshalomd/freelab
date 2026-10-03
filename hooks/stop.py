#!/usr/bin/env python3
"""freelab Stop hook: a finished freelab run needs a report. Only in a project that uses freelab
(hooklib.uses_freelab), and only about freelab's own runs (lab/status.json); anywhere else it exits 0 with no
output.

Blocks the stop once per run (the id goes to lab/.stop-reminded) when lab/status.json lists a run as `done` that
no report covers yet. A run counts as reported when its id appears in any lab/report*.md (report.md and the kept
report-run1.md, report-run2.md, ... of earlier rounds), or when the newest of those files was written after the
run finished (the earliest write time of its lab/runs/ID/summary.json, status.txt or metrics.jsonl). It never
blocks:
- when `stop_hook_active` is true (Claude is already continuing because of a stop hook);
- while lab/status.json lists a run as queued, starting or running: the session is waiting for it, not done;
- while a research loop is active (the newest "research loop ..." event is "research loop started" (events are
  newest first), lab/results.tsv present, and no lab/report*.md newer than it): the loop reports at its end;
- while a freelab poll (poll.py) runs in the background, if the Stop input carries a `background_tasks` list
  (used only when Claude Code sends one; without it, the run states in lab/status.json decide);
- for connection-check runs (ids starting `smoke-`).
Any error allows the stop."""
from __future__ import annotations
import json, re, sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ inside the installed plugin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hooklib import hook_cwd, uses_freelab, read_input  # noqa: E402

REASON = ("freelab: a run finished ({runs}): write the report with the report skill, then offer the next steps. "
          "This reminder comes once per run.")
ACTIVE = ("queued", "starting", "running")  # status_page.RUN_STATES of a run not finished yet
LOOP_START = re.compile(r"research loop started", re.I)
LOOP_END = re.compile(r"research loop (?:ended|stopped|finished|done)", re.I)


def _mtime(p: Path) -> float | None:
    try:
        return p.stat().st_mtime
    except OSError:
        return None


def reports(lab: Path) -> list[Path]:
    """lab/report.md and the kept reports of earlier rounds (report-run1.md, ...)."""
    try:
        return sorted(p for p in lab.glob("report*.md") if p.is_file())
    except OSError:
        return []


def newest_report_t(lab: Path) -> float | None:
    times = [t for t in (_mtime(p) for p in reports(lab)) if t is not None]
    return max(times) if times else None


def loop_active(lab: Path, doc: dict) -> bool:
    results = lab / "results.tsv"
    results_t = _mtime(results)
    if results_t is None:
        return False
    # events are newest first (status_page.add_event and poll.py insert at 0): the first loop event decides
    for e in doc.get("events") or []:
        text = str(e.get("text", "")) if isinstance(e, dict) else ""
        if LOOP_END.search(text):
            return False
        if LOOP_START.search(text):
            report_t = newest_report_t(lab)
            return report_t is None or report_t <= results_t
    return False


def poll_running(data: dict) -> bool:
    for task in data.get("background_tasks") or []:
        if isinstance(task, dict) and "poll.py" in str(task.get("command", "")) \
                and str(task.get("status", "running")).lower() in ("running", "pending", "in_progress"):
            return True
    return False


def finished_at(lab: Path, run: dict, status_t: float) -> float:
    """The earliest sign the run had finished: the oldest of its summary.json, status.txt and metrics.jsonl, so a
    later re-download of one of them, or a new event in status.json, does not make an already reported run look
    new. Without those files, the run folder's time, else status.json's."""
    folder = lab / "runs" / str(run.get("id"))
    times = [t for t in (_mtime(folder / n) for n in ("summary.json", "status.txt", "metrics.jsonl")) if t is not None]
    return min(times) if times else (_mtime(folder) or status_t)


def reported_ids(lab: Path, ids) -> set:
    """The ids (of `ids`) named in any lab/report*.md, as a whole word."""
    texts = []
    for p in reports(lab):
        try:
            texts.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    text = "\n".join(texts)
    return {rid for rid in ids if re.search(r"(?<![\w-])" + re.escape(rid) + r"(?![\w-])", text)}


def evaluate(data: dict):
    if data.get("stop_hook_active"):
        return None
    cwd = hook_cwd(data)
    if not uses_freelab(cwd):
        return None
    lab = Path(cwd) / "lab"
    status = lab / "status.json"
    status_t = _mtime(status)
    if status_t is None:
        return None
    doc = json.loads(status.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(doc, dict) or poll_running(data) or loop_active(lab, doc):
        return None
    runs = [r for r in doc.get("runs") or [] if isinstance(r, dict)]
    if any(r.get("state") in ACTIVE for r in runs):
        return None
    reminded_file = lab / ".stop-reminded"
    reminded = set(reminded_file.read_text(encoding="utf-8", errors="replace").split()) if reminded_file.is_file() else set()
    report_t = newest_report_t(lab)
    candidates = []
    for run in runs:
        if run.get("state") != "done":
            continue
        rid = str(run.get("id") or "")
        if not rid or rid.startswith("smoke-") or rid in reminded or any(rid == r for r, _ in candidates):
            continue
        candidates.append((rid, run))
    named = reported_ids(lab, [rid for rid, _ in candidates]) if candidates else set()
    pending = [rid for rid, run in candidates
               if rid not in named and (report_t is None or report_t < finished_at(lab, run, status_t))]
    if not pending:
        return None
    with reminded_file.open("a", encoding="utf-8") as f:
        f.write("".join(rid + "\n" for rid in pending))
    return {"decision": "block", "reason": REASON.format(runs=", ".join(pending))}


def main() -> int:
    try:
        out = evaluate(read_input())
        if out:
            print(json.dumps(out))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
