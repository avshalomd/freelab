"""freelab cleanup: the inventory, the light clean and scoped removal of a lab's local files, as
skills/cleanup/SKILL.md describes (its §1 run classes, its §2 scope guard, its §6 record in lab/cleanup.jsonl).
Run it from the project root. Local files only: cloud copies are listed and deleted with each backend's CLI.

    python3 scripts/cleanup.py inventory [--lab lab] [--exp EXP]...   JSON: runs, light items, deep items
    python3 scripts/cleanup.py light [--lab lab] [--exp EXP]...       remove the light items, one line each
    python3 scripts/cleanup.py remove PATH... [--lab lab] [--exp EXP]... [--include-run ID]...

Every removal: the path is literal (no glob), inside the scope guard, listed by a fresh inventory taken just before
it, and recorded in lab/cleanup.jsonl ({"t", "where": "local", "path", "bytes"}) before it is deleted. Items of a
running or resumable run are refused unless --include-run names that run. The loop's worktree (lab/worktrees/loop)
is a deep item: git removes the folder and the branch lab/<tag> stays; refused while a run is running or when it has
uncommitted changes."""
from __future__ import annotations
import argparse, json, os, re, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runlib import complete_checkpoints, has_checkpoint, launcher_alive  # noqa: E402

ACTIVE_STATES = ("queued", "starting", "running")
RESULT_STATUSES = ("keep", "discard", "crash")
STAGED = ("ckpt", "metrics.jsonl", "init")
LOOP_WORKTREE = "loop"


# --- reading the lab ----------------------------------------------------------------------------------------------


def _json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _used(st: os.stat_result) -> int:
    """Bytes on disk: st_blocks × 512 where the platform has it (not on Windows), else the file size."""
    blocks = getattr(st, "st_blocks", None)
    return blocks * 512 if blocks is not None else st.st_size


def size_bytes(p: Path) -> int:
    """Disk usage the way `du -sk` × 1024 counts it (on Windows, the sum of the file sizes)."""
    used = 0
    try:
        if p.is_symlink() or not p.is_dir():
            return -(-_used(p.lstat()) // 1024) * 1024
        for root, dirs, files in os.walk(p):
            for name in dirs + files:
                try:
                    used += _used(os.lstat(os.path.join(root, name)))
                except OSError:
                    pass
        used += _used(p.lstat())
    except OSError:
        return 0
    return -(-used // 1024) * 1024


def human(n: int) -> str:
    for unit, k in (("GB", 2**30), ("MB", 2**20), ("KB", 2**10)):
        if n >= k:
            return f"{n / k:.1f} {unit}"
    return f"{n} B"


def results_rows(lab: Path) -> list[dict]:
    p = lab / "results.tsv"
    if not p.is_file():
        return []
    lines = [l for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    if not lines:
        return []
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in lines[1:]]


def run_class(lab: Path, rid: str, states: dict, finished_ids: set) -> str:
    """§1: finished, running, resumable or ended. When in doubt, a run counts as running (not finished). A folder
    with no status.txt, no metrics.jsonl and no status.json entry (a run that never launched) has ended."""
    run = lab / "runs" / rid
    if states.get(rid) in ACTIVE_STATES or launcher_alive(run):
        return "running"
    if rid in finished_ids or (run / "summary.json").is_file():
        return "finished"
    try:
        st = (run / "status.txt").read_text(encoding="utf-8", errors="replace").strip().splitlines()[0].strip()
    except (OSError, IndexError):
        never_ran = not (run / "status.txt").exists() and not (run / "metrics.jsonl").exists() and rid not in states
        return "ended" if never_ran else "running"
    if st.startswith("stopped"):
        return "resumable"
    if st.startswith("failed"):
        return "resumable" if has_checkpoint(run / "ckpt") else "ended"
    return "running"


class Lab:
    def __init__(self, lab: str, exps=()):
        self.lab = Path(lab)
        self.exps = [Path(e) for e in exps]
        doc = _json(self.lab / "status.json")
        self.doc = doc if isinstance(doc, dict) else {}
        runs = [r for r in self.doc.get("runs") or [] if isinstance(r, dict)]
        self.states = {str(r.get("id")): r.get("state") for r in runs}
        self.rows = results_rows(self.lab)
        finished = {r.get("id") for r in self.rows if r.get("status") in RESULT_STATUSES}
        runs_dir = self.lab / "runs"
        ids = sorted(p.name for p in runs_dir.iterdir() if p.is_dir()) if runs_dir.is_dir() else []
        self.classes = {rid: run_class(self.lab, rid, self.states, finished) for rid in ids}
        self.result_ids = finished
        self.best = self._best_ids()

    def _best_ids(self) -> set:
        best = set()
        b = self.doc.get("best")
        if isinstance(b, dict) and b.get("run"):
            best.add(str(b["run"]))
        kept = []
        for r in self.rows:
            if r.get("status") == "keep":
                try:
                    kept.append((float(r.get("metric", "")), r.get("id")))
                except ValueError:
                    pass
        if kept:
            goal = self.doc.get("goal") if isinstance(self.doc.get("goal"), dict) else {}
            pick = min if goal.get("direction") == "min" else max
            best.add(pick(kept)[1])
        return best

    @property
    def any_running(self) -> bool:
        return any(c == "running" for c in self.classes.values()) or \
            any(s in ACTIVE_STATES for s in self.states.values())

    @property
    def any_unfinished(self) -> bool:
        return self.any_running or any(c == "resumable" for c in self.classes.values())


def _item(path: Path, why: str, rec: str | None = None, run: str | None = None, kind: str = "rm",
          blocked: str | None = None) -> dict:
    d = {"path": path.as_posix(), "bytes": size_bytes(path), "why": why, "kind": kind}
    if blocked:
        d["blocked"] = blocked  # `remove` refuses it for now
    if rec:
        d["recommendation"] = rec
    if run:
        d["run"] = run
    return d


def _pycache(roots) -> list[Path]:
    out = []
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, dirs, _ in os.walk(root):
            if ".venv" in Path(dirpath).parts:
                dirs[:] = []
                continue
            if "__pycache__" in dirs:
                out.append(Path(dirpath) / "__pycache__")
                dirs.remove("__pycache__")
            dirs[:] = [d for d in dirs if d != ".venv"]
    return sorted(set(out))


def _originals_present(lab: Lab, staged: Path) -> bool:
    """A staged copy can go only while the originals are still in lab/runs/ID/."""
    runs = lab.lab / "runs"
    if staged.name == "metrics.jsonl":
        try:
            data = staged.read_bytes()
        except OSError:
            return False
        return any(m.is_file() and m.read_bytes().startswith(data) for m in runs.glob("*/metrics.jsonl"))
    names = [p.name for p in staged.iterdir()] if staged.is_dir() else []
    for name in names:
        if not any((c / name / "COMPLETE").exists() or (c / name).is_file() for c in runs.glob("*/ckpt")):
            return False
    return True


def inventory(lab: Lab) -> dict:
    light, deep = [], []
    # __pycache__ (only when no run is running)
    for p in _pycache([lab.lab, *lab.exps]):
        if lab.any_running:
            deep.append(_item(p, "Python cache; skipped while a run is running", "Keep for now",
                              blocked="a run is running"))
        else:
            light.append(_item(p, "Python cache, rebuilt on the next run"))
    # a poll's download folder, left behind when it was killed mid-fetch (never one a running run's poll may be using;
    # .poll.json and .status.lock are never listed)
    for p in sorted((lab.lab / "runs").glob("*/.poll-tmp")) if (lab.lab / "runs").is_dir() else []:
        if p.is_dir() and lab.classes.get(p.parent.name) != "running":
            light.append(_item(p, "leftover download folder of a poll, made again at the next fetch"))
    # staged upload copies under lab/backends/
    backends = lab.lab / "backends"
    staged = []
    if backends.is_dir():
        for d in sorted(backends.glob("kaggle-data-*")):
            staged += [d / s for s in STAGED if (d / s).exists()]
        staged += [d for d in sorted(backends.glob("lightning-*")) if d.is_dir()]
    for p in staged:
        if lab.any_unfinished:
            deep.append(_item(p, "staged upload copy; kept while a run is running or resumable", "Keep",
                              blocked="a run is running or resumable"))
        elif p.name in ("ckpt", "init", "metrics.jsonl") and not _originals_present(lab, p):
            deep.append(_item(p, "staged upload copy whose original is no longer in lab/runs/", "Keep"))
        else:
            light.append(_item(p, "staged upload copy, staged again at the next launch"))
    # runs
    runs_out = []
    for rid, cls in lab.classes.items():
        is_best = rid in lab.best
        runs_out.append({"id": rid, "class": cls, "best": is_best})
        ckpt = lab.lab / "runs" / rid / "ckpt"
        if not ckpt.is_dir():
            continue
        if cls in ("running", "resumable"):
            if any(ckpt.iterdir()):
                deep.append(_item(ckpt, f"checkpoints of {rid} ({cls}): needed to " +
                                  ("finish it" if cls == "running" else "resume it"), "Keep", run=rid))
            continue
        partial = [p for p in sorted(ckpt.iterdir()) if cls == "finished" and p.is_dir() and (
            p.name.startswith(".tmp-") or (p.name.startswith("step-") and not (p / "COMPLETE").exists()))]
        for p in partial:
            light.append(_item(p, f"unfinished checkpoint write of {rid}; --resume never uses it", run=rid))
        rest = [p for p in sorted(ckpt.iterdir()) if p not in partial]
        if not rest:
            continue
        if is_best:
            complete = complete_checkpoints(ckpt)
            final = complete[-1] if complete else None
            for p in rest:
                if p == final:
                    deep.append(_item(p, f"final checkpoint of the best run ({rid}): the trained model; deleting it "
                                      "loses the result (the numbers stay)", "Keep", run=rid))
                else:
                    deep.append(_item(p, f"older checkpoint of the best run ({rid})", "Remove", run=rid))
        else:
            what = "discarded or superseded" if cls == "finished" else "ended, not resumable"
            deep.append(_item(ckpt, f"checkpoints of {rid} ({what}): frees disk; {rid} can no longer be resumed "
                              "or continued, and its model is gone (the numbers stay)", "Remove", run=rid))
    # research worktrees
    wt = lab.lab / "worktrees"
    if wt.is_dir():
        for p in sorted(x for x in wt.iterdir() if x.is_dir()):
            if p.name == LOOP_WORKTREE:
                # the research loop's own worktree (skills/research): removing it keeps the branch lab/<tag>
                why = "the research loop's worktree: frees disk; the best version stays on its branch lab/<tag>"
                if lab.any_running:
                    deep.append(_item(p, "the research loop's worktree, kept while a run is running (it may be "
                                      "running from it)", "Keep", kind="worktree", blocked="a run is running"))
                elif _git_dirty(p):
                    deep.append(_item(p, "the research loop's worktree with uncommitted changes (or git cannot read "
                                      "it): commit or drop them first", "Keep", kind="worktree",
                                      blocked="it has uncommitted changes"))
                else:
                    deep.append(_item(p, why, "Remove (after the demo)", kind="worktree"))
            elif p.name in lab.result_ids and not _git_dirty(p):
                light.append(_item(p, f"research worktree of {p.name} (its row is in results.tsv)", kind="worktree"))
            elif p.name in lab.result_ids:
                deep.append(_item(p, f"research worktree of {p.name} with uncommitted changes (git would refuse)",
                                  "Remove", kind="worktree"))
            else:
                deep.append(_item(p, f"research worktree of {p.name}: no row in results.tsv yet", "Keep",
                                  kind="worktree", blocked="its experiment has no row in results.tsv yet"))
    hf = os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface")
    return {"lab": lab.lab.as_posix(), "runs": runs_out, "light": light, "deep": deep,
            "light_bytes": sum(i["bytes"] for i in light),
            "shared_caches": [{"path": hf, "recommendation": "Not offered",
                               "why": "shared with other projects; measure with du -sh"}],
            "cloud": "not listed here: use each connected backend's Clean up commands (compute references); "
                     "freelab's guard asks before every cloud delete"}


def _git_dirty(p: Path) -> bool:
    try:
        r = subprocess.run(["git", "-C", str(p), "status", "--porcelain"], capture_output=True, encoding="utf-8",
                           errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return True
    return r.returncode != 0 or bool(r.stdout.strip())


# --- the scope guard and removal ----------------------------------------------------------------------------------

SCOPE = [re.compile(p) for p in (
    r"^runs/[^/]+/ckpt$", r"^runs/[^/]+/ckpt/(?:step-[^/]+|\.tmp-[^/]+|\.old-step-[^/]+)$",
    r"^backends/kaggle-data-[^/]+/(?:ckpt|metrics\.jsonl|init)$", r"^backends/lightning-[^/]+$",
    r"^worktrees/[^/]+$", r"^runs/[^/]+/\.poll-tmp$")]


def scope_error(lab: Lab, path: str) -> str | None:
    """None when `path` passes the §2 scope guard, else why not."""
    if not path or not path.strip():
        return "empty path"
    if any(c in path for c in "*?[]{}~$"):
        return "not a literal path (no globs, variables or ~)"
    if ".." in Path(path).parts:
        return "give the path without '..', inside the lab"
    p = Path(os.path.normpath(path))
    if p.name == "__pycache__":
        return None
    try:  # the lab and the path may each be relative (to the project root) or absolute
        rel = Path(os.path.abspath(p)).relative_to(Path(os.path.abspath(lab.lab))).as_posix()
    except ValueError:
        return f"outside {lab.lab.as_posix()}/"
    if not any(rx.match(rel) for rx in SCOPE):
        return ("outside the scope guard (only lab/runs/<id>/ckpt and the folders in it, staged copies under "
                "lab/backends/, lab/worktrees/<id>, a poll's lab/runs/<id>/.poll-tmp, and listed __pycache__ folders)")
    return None


def _listed(inv: dict, path: str):
    """The inventory item that is `path` or contains it (relative and absolute spellings match)."""
    norm = Path(os.path.abspath(path))
    for item in inv["light"] + inv["deep"]:
        ip = Path(os.path.abspath(item["path"]))
        if norm == ip or ip in norm.parents:
            return item
    return None


def _log(lab: Lab, path: str, nbytes: int, note: str | None = None) -> None:
    rec = {"t": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "where": "local", "path": path,
           "bytes": nbytes}
    if note:
        rec["note"] = note
    lab.lab.mkdir(parents=True, exist_ok=True)
    with (lab.lab / "cleanup.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def _delete(lab: Lab, path: str, kind: str) -> str | None:
    """Log, then delete. Returns an error text when it could not be removed."""
    p = Path(path)
    if not (p.exists() or p.is_symlink()):
        return "no longer there"
    nbytes = size_bytes(p)
    _log(lab, path, nbytes)
    if kind == "worktree":
        r = subprocess.run(["git", "worktree", "remove", path], capture_output=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            msg = (r.stderr.strip().splitlines() or ["git refused"])[0]
            _log(lab, path, 0, note=f"not removed: {msg}")
            return f"git refused: {msg}"
        subprocess.run(["git", "worktree", "prune"], capture_output=True, encoding="utf-8", errors="replace")
        return None
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    else:
        p.unlink()
    return None


def light_clean(lab_dir: str, exps) -> int:
    lab = Lab(lab_dir, exps)
    removed, freed = 0, 0
    for item in inventory(lab)["light"]:  # one fresh inventory, taken just before the removals
        err = _delete(lab, item["path"], item["kind"])
        if err:
            print(f"kept {item['path']}: {err}")
            continue
        removed += 1
        freed += item["bytes"]
        print(f"removed {item['path']} ({human(item['bytes'])})")
    if removed:
        print(f"light clean: removed {removed} item{'s' if removed != 1 else ''}, {human(freed)} freed; metrics, "
              "results and checkpoints are untouched")
    else:
        print("light clean: nothing to remove")
    return 0


def remove(lab_dir: str, exps, paths, include_runs) -> int:
    bad = 0
    for path in paths:
        lab = Lab(lab_dir, exps)
        err = scope_error(lab, path)
        inv = inventory(lab)  # a fresh inventory: re-checks §1 right before this removal
        item = None if err else _listed(inv, path)
        if not err and item is None:
            err = "not listed by the inventory (run `cleanup.py inventory`)"
        if not err:
            run = item.get("run")
            cls = lab.classes.get(run) if run else None
            if cls in ("running", "resumable") and run not in include_runs:
                err = f"{run} is {cls}; its files are kept unless the user names it (--include-run {run})"
            elif item.get("blocked"):
                err = f"kept for now: {item['blocked']}"
        if not err:
            norm = Path(os.path.normpath(path)).as_posix()
            kind = item["kind"] if norm == item["path"] else "rm"
            nbytes = size_bytes(Path(norm))
            err = _delete(lab, norm, kind)
            if not err:
                print(f"removed {norm} ({human(nbytes)})")
                continue
        bad += 1
        print(f"refused {path}: {err}", file=sys.stderr)
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cleanup.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--lab", default="lab", help="lab directory (default lab)")
    common.add_argument("--exp", action="append", default=[],
                        help="experiment directory whose __pycache__ the sweep includes (repeatable)")
    sub.add_parser("inventory", parents=[common], help="print the inventory as JSON (deletes nothing)")
    sub.add_parser("light", parents=[common], help="the light clean: leftover process files only")
    rm = sub.add_parser("remove", parents=[common], help="remove listed items within the scope guard")
    rm.add_argument("paths", nargs="+", metavar="PATH")
    rm.add_argument("--include-run", action="append", default=[], metavar="ID",
                    help="allow removing files of this running or resumable run (the user named it)")
    args = ap.parse_args(argv)
    if args.command == "inventory":
        print(json.dumps(inventory(Lab(args.lab, args.exp)), indent=2))
        return 0
    if args.command == "light":
        return light_clean(args.lab, args.exp)
    return remove(args.lab, args.exp, args.paths, set(args.include_run))


if __name__ == "__main__":
    sys.exit(main())
