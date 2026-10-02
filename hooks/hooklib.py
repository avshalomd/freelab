"""Shared helpers for freelab's Python hooks (guard.py, post.py, stop.py). Standard library only."""
from __future__ import annotations
import json, os, sys
from pathlib import Path


def read_input() -> dict:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


LAB_FILES = ("charter.md", "ledger.jsonl", ".launches")  # names only freelab writes in lab/


def _freelab_status(path: Path) -> bool:
    """lab/status.json in freelab's own shape (status_page.validate: version 1, a goal object with a metric)."""
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    return isinstance(doc, dict) and doc.get("version") == 1 and isinstance(doc.get("goal"), dict) \
        and "metric" in doc["goal"]


def uses_freelab(cwd) -> bool:
    """A project that uses freelab: cwd/lab/ (freelab's experiment area) holds one of the files only freelab writes
    there (LAB_FILES) or a status.json in freelab's shape, or cwd/.env has a line starting `# freelab:`
    (scripts/env.sh writes it during onboarding, before lab/ exists). A `lab/` folder alone, or one with generic
    names such as plan.md, is not enough: other projects have those. The .env check reads only for that marker and
    never shows anything. Even here, the hooks act only on freelab's own commands and files."""
    try:
        root = Path(cwd)
        if any((root / "lab" / name).is_file() for name in LAB_FILES) or _freelab_status(root / "lab" / "status.json"):
            return True
        env = root / ".env"
        if env.is_file():
            with env.open(errors="replace") as f:
                return any(line.startswith("# freelab:") for line in f)
    except OSError:
        return False
    return False


def hook_cwd(data: dict) -> str:
    cwd = data.get("cwd")
    return cwd if isinstance(cwd, str) and cwd else os.getcwd()
