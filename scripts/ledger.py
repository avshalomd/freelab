"""freelab spend ledger: append-only JSONL of estimate/actual spend entries, one line per
entry, `lab/ledger.jsonl`. `total()` sums the actuals where a run has any, and the estimates
otherwise, per run."""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runlib import read_metrics  # noqa: E402  (any JSONL file: skips blank and torn lines)

KINDS = ("estimate", "actual")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path(lab) -> Path:
    return Path(lab) / "ledger.jsonl"


def add(lab, backend: str, run: str, usd: float, kind: str, note: str = "") -> dict:
    """Append one spend entry and return it."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS!r}, got {kind!r}")
    rec = {"t": _now(), "backend": backend, "run": run, "usd": usd, "kind": kind, "note": note}
    p = _path(lab)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def read_entries(lab) -> list[dict]:
    """Read ledger.jsonl, skipping blank and torn (incomplete) lines."""
    return read_metrics(_path(lab))


def total(lab) -> float:
    """Sum spend across all runs: per run, the actuals if any exist, else the estimates.

    "Any exist" means at least one actual-kind entry was recorded for that run, not that the
    actuals sum to something nonzero -- a $0.00 actual (common on a free tier) must still win
    over an earlier nonzero estimate, rather than being treated as "no actual yet"."""
    by_run: dict[str, dict] = {}
    for rec in read_entries(lab):
        run = rec.get("run")
        kind = rec.get("kind")
        usd = rec.get("usd", 0.0)
        if kind not in KINDS:
            continue
        sums = by_run.setdefault(run, {"estimate": 0.0, "actual": 0.0, "has_actual": False})
        sums[kind] += usd
        if kind == "actual":
            sums["has_actual"] = True
    grand = 0.0
    for sums in by_run.values():
        grand += sums["actual"] if sums["has_actual"] else sums["estimate"]
    return grand


def _cli_add(args) -> int:
    add(args.lab, args.backend, args.run, args.usd, args.kind, args.note)
    return 0


def _cli_total(args) -> int:
    print(f"{total(args.lab):.4f}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="ledger.py")
    sub = p.add_subparsers(dest="command", required=True)

    add_p = sub.add_parser("add", help="append a spend entry")
    add_p.add_argument("--lab", required=True, type=Path)
    add_p.add_argument("--backend", required=True)
    add_p.add_argument("--run", required=True)
    add_p.add_argument("--usd", required=True, type=float)
    add_p.add_argument("--kind", required=True, choices=KINDS)
    add_p.add_argument("--note", default="")
    add_p.set_defaults(func=_cli_add)

    total_p = sub.add_parser("total", help="print the ledger's total spend")
    total_p.add_argument("--lab", required=True, type=Path)
    total_p.set_defaults(func=_cli_total)

    args = p.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
