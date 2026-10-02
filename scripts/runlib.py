"""freelab run contract: any experiment script that uses this runs on every freelab backend.
Contract: --out/--resume/--max-minutes/--smoke; metrics.jsonl + status.txt; atomic checkpoints under ckpt/ (the
newest KEEP while the run goes, so a stopped or failed run can resume; only the newest once it finishes);
SIGTERM/SIGINT/deadline -> checkpoint-and-stop with exit code 3; exit codes 0 done, 1 failed, 2 bad input, 3 stopped.
Local runs (launched by backends/local_run.py) also get the allowance guard: FREELAB_* variables cap threads and
CUDA memory, and a process RSS over FREELAB_MAX_RAM_GB, or swap growing by over 1 GB, stops the run ("allowance").
Standard library only; torch is used only if the experiment has already imported it."""
from __future__ import annotations
import argparse, json, os, re, shutil, signal, subprocess, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


def add_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--out", required=True, help="run directory (metrics, status, checkpoints)")
    p.add_argument("--resume", action="store_true", help="continue from the newest complete checkpoint")
    p.add_argument("--max-minutes", type=float, default=0.0, help="stop (resumably) before this many minutes; 0 = none")
    p.add_argument("--smoke", action="store_true", help="tiny run that proves the backend works")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def complete_checkpoints(ckpt_dir) -> list[Path]:
    """Complete checkpoints (step dirs holding a COMPLETE marker) under ckpt_dir, oldest first."""
    d = Path(ckpt_dir)
    if not d.is_dir():
        return []
    return sorted((p for p in d.iterdir() if p.is_dir() and p.name.startswith("step-") and (p / "COMPLETE").exists()),
                  key=lambda p: p.name)


def has_checkpoint(ckpt_dir) -> bool:
    """Whether --resume has something to resume: a complete step-* checkpoint, or a complete .old-step-* one
    (an interrupted same-step overwrite that Run.latest_checkpoint() restores)."""
    return bool(complete_checkpoints(ckpt_dir)) or any(Path(ckpt_dir).glob(".old-step-*/COMPLETE"))


# --- the allowance guard (local runs only) ----------------------------------------------------

CHECK_EVERY = 60.0  # seconds between memory/swap checks
SWAP_GROWTH_GB = 1.0


def apply_allowance() -> None:
    """Apply the thread and GPU-memory limits local_run.py passes in FREELAB_* variables (a no-op elsewhere).
    Never imports torch, and never lets a limit that cannot be applied crash the run."""
    threads = os.environ.get("FREELAB_THREADS")
    if threads:
        os.environ.setdefault("OMP_NUM_THREADS", threads)
        os.environ.setdefault("MKL_NUM_THREADS", threads)
    torch = sys.modules.get("torch")
    if torch is None:
        return
    if threads:
        try:
            torch.set_num_threads(int(threads))
        except Exception:
            pass
    gpu = os.environ.get("FREELAB_GPU_MEM_GB")
    if gpu:
        try:
            # 0 means "no GPU": local_run hides CUDA devices instead, and a 0-byte cap would only crash the run
            if float(gpu) > 0 and torch.cuda.is_available():
                total = torch.cuda.get_device_properties(0).total_memory / 2**30
                torch.cuda.set_per_process_memory_fraction(min(1.0, float(gpu) / total))
        except Exception:
            pass


def rss_gb() -> float | None:
    """This process's resident memory in GB, or None if it cannot be read."""
    try:
        status = Path("/proc/self/status")
        if status.exists():
            for line in status.read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 2**20
        elif sys.platform == "darwin":
            out = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True,
                                 timeout=10).stdout
            return int(out.strip()) / 2**20
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def parse_swapusage(text: str) -> float | None:
    """GB of swap in use from macOS `sysctl -n vm.swapusage` ("total = 2048.00M  used = 1022.25M  ...")."""
    m = re.search(r"used\s*=\s*([\d.]+)([KMGT])", text)
    if not m:
        return None
    return float(m.group(1)) * {"K": 2**-20, "M": 2**-10, "G": 1.0, "T": 1024.0}[m.group(2)]


def swap_used_gb() -> float | None:
    """GB of swap in use on the whole system, or None if it cannot be read."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True, timeout=10).stdout
            return parse_swapusage(out)
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            kb = {l.split(":")[0]: int(l.split()[1]) for l in meminfo.read_text().splitlines()
                  if l.startswith(("SwapTotal:", "SwapFree:"))}
            return (kb["SwapTotal"] - kb["SwapFree"]) / 2**20
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
        pass
    return None


def read_metrics(path) -> list[dict]:
    """Read a metrics.jsonl file, skipping blank and torn (incomplete) lines."""
    out: list[dict] = []
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


class Run:
    """Context manager implementing the freelab run contract for one experiment run."""

    KEEP = 2

    def __init__(self, args, margin_minutes: float = 2.0):
        self.args = args
        self.out = Path(args.out)
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "ckpt").mkdir(exist_ok=True)
        self.t0 = time.monotonic()
        self.margin = margin_minutes * 60
        self.stop_reason: str | None = None
        self._signalled = False
        self._code: int | None = None
        self._next_check = time.monotonic() + CHECK_EVERY  # next allowance check (tests set 0 to force one)
        self._swap0: float | None = None

    def __enter__(self) -> "Run":
        apply_allowance()
        if os.environ.get("FREELAB_MAX_RAM_GB"):
            self._swap0 = swap_used_gb()
        self._next_check = time.monotonic() + CHECK_EVERY
        self._old = {s: signal.signal(s, self._on_signal) for s in (signal.SIGTERM, signal.SIGINT)}
        self.status("running")
        return self

    def _on_signal(self, *_) -> None:
        self._signalled = True

    def should_stop(self) -> str | None:
        """Return "signal", "deadline", "allowance" (local runs over their memory allowance), or None."""
        if self._signalled:
            self.stop_reason = "signal"
        elif self.args.max_minutes and time.monotonic() - self.t0 >= self.args.max_minutes * 60 - self.margin:
            self.stop_reason = "deadline"
        elif self._over_allowance():
            self.stop_reason = "allowance"
        return self.stop_reason

    def _over_allowance(self) -> bool:
        limit = os.environ.get("FREELAB_MAX_RAM_GB")
        now = time.monotonic()
        if not limit or now < self._next_check:
            return False
        self._next_check = now + CHECK_EVERY
        try:
            limit_gb = float(limit)
        except ValueError:
            return False
        rss = rss_gb()
        if rss is not None and rss > limit_gb:
            print(f"freelab: stopping, this run uses {rss:.1f} GB of memory, over the allowance of {limit_gb:g} GB",
                  file=sys.stderr, flush=True)
            return True
        swap = swap_used_gb()
        if swap is not None and self._swap0 is not None and swap - self._swap0 > SWAP_GROWTH_GB:
            print(f"freelab: stopping, the system's swap grew by {swap - self._swap0:.1f} GB since the run started",
                  file=sys.stderr, flush=True)
            return True
        return False

    def log(self, step: int, total: int, split: str, name: str, value: float) -> None:
        rec = {"t": _now(), "step": step, "total": total, "split": split, "name": name, "value": value}
        with (self.out / "metrics.jsonl").open("a") as f:
            f.write(json.dumps(rec) + "\n")

    def status(self, text: str) -> None:
        _atomic_write(self.out / "status.txt", text + "\n")

    def save(self, write_fn: Callable[[Path], None], step: int) -> Path:
        ckpt_dir = self.out / "ckpt"
        self._heal(ckpt_dir)
        tmpdir = Path(tempfile.mkdtemp(dir=ckpt_dir, prefix=".tmp-"))
        try:
            write_fn(tmpdir)
            (tmpdir / "COMPLETE").write_text("")
        except Exception:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise
        dest = ckpt_dir / f"step-{step:08d}"
        old = ckpt_dir / f".old-step-{step:08d}"
        if dest.exists():
            # Re-saving a step: move the old copy aside with one atomic rename, never delete-then-rename;
            # if the process dies before the next rename, _heal() restores `old`.
            os.replace(dest, old)
        os.replace(tmpdir, dest)
        if old.exists():
            shutil.rmtree(old, ignore_errors=True)
        self._prune(ckpt_dir)
        return dest

    def _heal(self, ckpt_dir: Path) -> None:
        """Finish an interrupted same-step overwrite from save(): if the swap completed
        (dest exists again), drop the leftover backup; if it did not, restore it."""
        for p in list(ckpt_dir.iterdir()):
            if p.is_dir() and p.name.startswith(".old-step-"):
                dest = ckpt_dir / p.name[len(".old-") :]
                if dest.exists():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.replace(p, dest)

    def _prune(self, ckpt_dir: Path) -> None:
        # A stale ".tmp-*" dir left by a previous crash is never the one just written
        # (that one was already renamed away above), so any that remain are safe to drop.
        for p in ckpt_dir.iterdir():
            if p.is_dir() and p.name.startswith(".tmp-"):
                shutil.rmtree(p, ignore_errors=True)
        complete = complete_checkpoints(ckpt_dir)
        if len(complete) > self.KEEP:
            for p in complete[: -self.KEEP]:
                shutil.rmtree(p, ignore_errors=True)
        newest = complete[-1].name if complete else None
        if newest is not None:
            for p in ckpt_dir.iterdir():
                if p.is_dir() and p.name.startswith("step-") and p.name < newest and not (p / "COMPLETE").exists():
                    shutil.rmtree(p, ignore_errors=True)

    def latest_checkpoint(self) -> Path | None:
        ckpt_dir = self.out / "ckpt"
        self._heal(ckpt_dir)
        complete = complete_checkpoints(ckpt_dir)
        return complete[-1] if complete else None

    def finish(self, summary: dict) -> None:
        """Write summary.json and mark the run done. Keeps only the newest complete checkpoint (the final weights)
        unless the run was asked to stop (stop_reason set): then __exit__ marks it stopped and its KEEP checkpoints
        stay for --resume. A failed run never gets here."""
        _atomic_write(self.out / "summary.json", json.dumps(summary))
        if self.stop_reason is None:
            self._keep_newest_only(self.out / "ckpt")
        self.status("done")

    def _keep_newest_only(self, ckpt_dir: Path) -> None:
        """Drop every checkpoint folder except the newest complete one: older complete ones, torn step-* folders,
        and .tmp-*/.old-step-* leftovers. Nothing is removed when there is no complete checkpoint."""
        if not ckpt_dir.is_dir():
            return
        self._heal(ckpt_dir)
        complete = complete_checkpoints(ckpt_dir)
        if not complete:
            return
        for p in ckpt_dir.iterdir():
            if p.is_dir() and p != complete[-1] and p.name.startswith(("step-", ".tmp-", ".old-step-")):
                shutil.rmtree(p, ignore_errors=True)

    def __exit__(self, et, ev, tb) -> bool:
        for s, h in self._old.items():
            signal.signal(s, h)
        if et is not None:
            self.status(f"failed: {(str(ev).splitlines() or [''])[0]}")  # status.txt holds one line
            self._code = 1
            return False
        if self.stop_reason:
            self.status(f"stopped ({self.stop_reason})")
            self._code = 3
        elif self._code is None:
            self._code = 0
        return False


def exit_code(run: Run) -> int:
    return run._code if run._code is not None else 1
