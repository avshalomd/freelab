"""freelab run on Kaggle (copied from freelab's scripts/backends/templates/kaggle_run.py; see
skills/compute/references/kaggle.md). Fill in ARGS below: train.py's arguments, where --max-minutes is the run's
budget in minutes (the smoke default shown here: replace it for a real run)."""
import shutil, subprocess, sys
from pathlib import Path

ARGS = ["--max-minutes", "20", "--smoke"]  # FILL IN: train.py's arguments for this run
src = next(Path("/kaggle/input").rglob("train.py")).parent  # the attached private Dataset
exp, out = Path("/tmp/freelab-exp"), Path("/kaggle/working")
shutil.copytree(src, exp, ignore=shutil.ignore_patterns("ckpt"))
if (src / "ckpt").is_dir():  # a checkpoint uploaded for a resume or a move
    shutil.copytree(src / "ckpt", out / "ckpt", dirs_exist_ok=True)
    if (src / "metrics.jsonl").is_file():  # the run's history so far, so metrics continue
        shutil.copy(src / "metrics.jsonl", out / "metrics.jsonl")
    ARGS.append("--resume")
if subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"], cwd=exp).returncode:
    sys.exit(1)
code = subprocess.run([sys.executable, "-u", "train.py", "--out", str(out), *ARGS], cwd=exp).returncode
sys.exit(code if code >= 0 else 1)
