#!/usr/bin/env python3
"""freelab local launcher: run an experiment on this machine within the user's allowance (skills/compute/references/
local.md; the allowance comes from skills/onboard step 3). `--when now` starts at once under the day allowance.
`--when night` waits for the night window (and for the allowance's idle_minutes, 15 by default, if idle_check is
set), runs under the night allowance with --max-minutes ending before the window closes, and resumes on the next
night, up to --nights; it refuses when the allowance has night_runs false or no night window. One local run at a
time holds FREELAB_HOME/local-run.lock. The lock is taken at launch (after any wait), so a sleeping night run never
blocks a daytime one. One launcher per run id: it holds lab/runs/ID/.launcher (its pid) from start to end, also
while it waits between nights, and a second launch of the same id is refused while that pid is alive
(scripts/poll.py reads it too: a run stopped at a night window's end while its launcher waits shows as waiting, not
stopped). A --max-minutes among the experiment args must have a number and is capped at the window's. A GPU
allowance of 0 hides a CUDA GPU (CUDA_VISIBLE_DEVICES="") and sets no MPS limits; otherwise the MPS watermark is
min(gpu_mem_gb, ram_gb) / (0.75 * machine RAM), capped at 1.0: torch applies the ratio to Metal's recommended
working set, about 75 % of RAM, so the cap lands near that many GB. MPS memory is not in the process RSS, so on
Apple Silicon the watermark, not runlib's RSS guard, caps the GPU share. Exit codes: the child's (0 done, 1 failed,
3 stopped and resumable); 2 for bad input, no allowance, a held lock or another live launcher of the same run; 3
when the night window closes before anything started. Standard library only."""
from __future__ import annotations
import argparse, json, os, platform, re, shutil, signal, subprocess, sys, time
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import resources, runlib  # noqa: E402

IDLE_MINUTES = 15    # the default: the machine counts as idle after this many minutes without keyboard or mouse input
POLL_SECONDS = 60
WORKING_SET = 0.75   # Metal's recommended working set as a share of RAM, which torch's MPS watermark ratio scales
RAISES = (("raise_ram", "ram_gb", "GB of RAM"), ("raise_gpu", "gpu_mem_gb", "GB of GPU memory"),
          ("raise_threads", "cpu_threads", "CPU threads"))


class _Usage(Exception):
    """Bad input or not set up: exit 2 with this message."""


def _now() -> datetime:
    return datetime.now()


def build_env(allowance_part: dict, probe: dict, base_env: dict) -> dict:
    """base_env plus the variables freelab sets for a run under `allowance_part` (day or night, after raises)."""
    env = dict(base_env)
    threads = str(int(allowance_part.get("cpu_threads", 1)))
    env.update({"FREELAB_MAX_RAM_GB": f"{float(allowance_part.get('ram_gb', 0)):g}",
                "FREELAB_GPU_MEM_GB": f"{float(allowance_part.get('gpu_mem_gb', 0)):g}",
                "FREELAB_THREADS": threads, "OMP_NUM_THREADS": threads, "MKL_NUM_THREADS": threads})
    kind, gpu_mem = probe.get("gpu", {}).get("kind"), float(allowance_part.get("gpu_mem_gb", 0))
    if kind == "cuda" and gpu_mem == 0:
        env["CUDA_VISIBLE_DEVICES"] = ""  # an allowance of 0 means "no GPU": hide it rather than cap it at 0 bytes
    elif kind == "apple" and gpu_mem > 0 and probe.get("ram_gb"):
        gpu_mem = min(gpu_mem, float(allowance_part.get("ram_gb", gpu_mem)))  # unified memory: never above the RAM
        ratio = str(min(1.0, max(0.1, round(gpu_mem / (WORKING_SET * probe["ram_gb"]), 2))))
        # torch refuses to start MPS when the low watermark (default 1.4) is above the high one, so set both
        env["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = env["PYTORCH_MPS_LOW_WATERMARK_RATIO"] = ratio
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(SCRIPTS), base_env.get("PYTHONPATH")) if p)
    return env


def deadline_minutes(now: datetime, window_end: datetime, margin: float = 10) -> float:
    """Minutes left in the window, minus the margin, never below 0."""
    return max(0.0, (window_end - now).total_seconds() / 60 - margin)


class Lock:
    """An exclusive, non-blocking lock on `path` holding `note` (the run id); a second holder gets BlockingIOError."""

    def __init__(self, path, note: str = ""):
        self.path, self.note = Path(path), note

    def __enter__(self) -> "Lock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            self.f.close()
            raise BlockingIOError(f"{self.path} is held by another process") from e
        self.f.seek(0)
        self.f.truncate()
        self.f.write(self.note)
        self.f.flush()
        return self

    def __exit__(self, *exc) -> None:
        self.f.close()  # closing the file releases the lock


def idle_seconds() -> float | None:
    """Seconds since the last keyboard/mouse input on macOS (HIDIdleTime), or None if it cannot be read."""
    try:
        out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, encoding="utf-8", errors="replace",
                             timeout=10).stdout
        return int(next(l for l in out.splitlines() if "HIDIdleTime" in l).split()[-1]) / 1e9
    except (OSError, subprocess.SubprocessError, StopIteration, ValueError):
        return None


def _wait_idle(until: datetime, minutes: int = IDLE_MINUTES) -> bool:
    """Wait for `minutes` idle minutes; False if `until` passes first. Skipped (True) where it cannot be measured."""
    if platform.system() != "Darwin":
        print("idle check skipped: it is only available on macOS", flush=True)
        return True
    print(f"waiting for the machine to be idle for {minutes} minutes", flush=True)
    while _now() < until:
        idle = idle_seconds()
        if idle is None:
            print("idle check skipped: could not read the idle time", flush=True)
            return True
        if idle >= minutes * 60:
            return True
        time.sleep(POLL_SECONDS)
    return False


def _sleep_until(t: datetime) -> None:
    # short sleeps against the wall clock, so a laptop that slept through part of the wait still starts on time
    while (left := (t - _now()).total_seconds()) > 0:
        time.sleep(min(left, POLL_SECONDS))


def _cap_minutes(max_minutes: int | None, extra: list[str]) -> tuple[float | None, list[str]]:
    """With a window deadline, fold a --max-minutes from the experiment args into it (the smaller wins, 0 = none);
    without one, leave the experiment args untouched. Either way a --max-minutes without a number is refused."""
    rest, user, i = [], None, 0
    while i < len(extra):
        if extra[i] == "--max-minutes":
            if i + 1 >= len(extra):
                raise _Usage("--max-minutes at the end of the experiment args has no value")
            user, i = extra[i + 1], i + 2
        elif extra[i].startswith("--max-minutes="):
            user, i = extra[i].split("=", 1)[1], i + 1
        else:
            rest, i = rest + [extra[i]], i + 1
    try:
        user_minutes = float(user) if user is not None else 0.0
    except ValueError:
        raise _Usage(f"--max-minutes {user!r} in the experiment args is not a number") from None
    if max_minutes is None:
        return None, extra
    return (min(user_minutes, max_minutes) if user_minutes > 0 else max_minutes), rest


def build_cmd(exp: Path, run_dir: Path, max_minutes: float | None, extra: list[str]) -> list[str]:
    cmd = [sys.executable, str(exp / "train.py"), "--out", str(run_dir)]
    if runlib.has_checkpoint(run_dir / "ckpt"):
        cmd.append("--resume")
    if max_minutes is not None:
        cmd += ["--max-minutes", f"{max_minutes:g}"]
    cmd += extra
    if platform.system() == "Darwin" and shutil.which("caffeinate"):
        cmd = ["caffeinate", "-i", *cmd]  # keeps the Mac awake; it forwards signals and the exit code
    return cmd


class _Child:
    """Runs the experiment, forwarding SIGTERM/SIGINT to it so it checkpoints and exits 3. A signal that
    arrives while nothing is running (waiting for the window) ends the launcher with 3: nothing was lost."""

    def __enter__(self) -> "_Child":
        self.proc, self.signalled = None, False
        self._old = {s: signal.signal(s, self._on) for s in (signal.SIGTERM, signal.SIGINT)}
        return self

    def _on(self, sig, _frame) -> None:
        self.signalled = True
        if self.proc is None:
            print("stopped while waiting; nothing was running", flush=True)
            raise SystemExit(3)
        self.proc.send_signal(sig)

    def run(self, cmd: list[str], cwd: Path, env: dict, log_path: Path) -> int:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"--- freelab local_run {_now().isoformat(timespec='seconds')}: {' '.join(cmd)}\n")
            log.flush()
            self.proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                code = self.proc.wait()
            finally:
                self.proc = None
        return code if code >= 0 else 1  # killed by a signal it did not handle: failed

    def __exit__(self, *exc) -> None:
        for s, h in self._old.items():
            signal.signal(s, h)


def _allowance_part(allowance: dict, a) -> tuple[dict, dict | None]:
    which = "night" if a.when == "night" else "day"
    part, raised = dict(allowance[which]), {}
    for flag, key, unit in RAISES:
        value, current = getattr(a, flag), allowance[which].get(key, 0)
        if value is None:
            continue
        if value < current:
            raise _Usage(f"--{flag.replace('_', '-')} {value:g} is below the {which} allowance of {current:g} {unit}; "
                         "the --raise-* flags only raise it (change the allowance itself with resources.py set)")
        if value > current:
            part[key] = raised[key] = value
    return part, raised or None


def _deadline_hit(run_dir: Path) -> bool:
    try:
        return (run_dir / "status.txt").read_text(encoding="utf-8", errors="replace").strip() == "stopped (deadline)"
    except OSError:
        return False


def _launch(a, extra: list[str]) -> int:
    exp = Path(a.exp_dir).resolve()
    if not (exp / "train.py").is_file():
        raise _Usage(f"no train.py in {exp}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", a.run_id):
        raise _Usage("--run-id may hold only letters, digits, '.', '_' and '-'")
    if a.nights < 1 or (a.nights > 1 and a.when != "night"):
        raise _Usage("--nights must be at least 1, and more than 1 only with --when night")
    try:
        allowance = resources.load_allowance()
        if a.when == "night" and allowance.get("night_runs") is False:
            raise _Usage("night runs are turned off in the allowance, so nothing runs at night. Use --when now, or "
                         "turn night runs on with resources.py set --night-preset partial or full.")
        part, raised = _allowance_part(allowance, a)
        nw = resources.night_window(allowance) if a.when == "night" else None
        if a.when == "night" and nw is None:
            raise _Usage("the allowance has no night window: set one with resources.py set --start HH:MM --end HH:MM")
    except (FileNotFoundError, ValueError, KeyError) as e:
        raise _Usage(str(e) if not isinstance(e, KeyError) else f"the allowance file has no {e} entry") from None
    probe = allowance.get("probe", {})
    run_dir = Path(a.lab).resolve() / "runs" / a.run_id
    if a.dry_run:
        win = resources.window(_now(), *nw) if nw else None
        max_minutes = int(deadline_minutes(_now() if win[2] else win[0], win[1])) if win else None
        window = [win[0].isoformat(timespec="minutes"), win[1].isoformat(timespec="minutes")] if win else None
        minutes, rest = _cap_minutes(max_minutes, extra)
        print(json.dumps({"cmd": build_cmd(exp, run_dir, minutes, rest), "env": build_env(part, probe, {}),
                          "max_minutes": minutes, "when": a.when, "window": window}, indent=2))
        return 0
    _cap_minutes(None, extra)  # a bad --max-minutes fails now, not after waiting for the night
    with _Launcher(run_dir, a.run_id):
        return _run_nights(a, exp, run_dir, extra, allowance, part, raised, probe, nw)


class _Launcher:
    """Hold lab/runs/ID/.launcher (this process's pid) while this launcher lives; refuse when another live
    launcher holds it for the same run id."""

    def __init__(self, run_dir: Path, run_id: str):
        self.path, self.run_id = run_dir / runlib.LAUNCHER_MARKER, run_id

    def __enter__(self) -> "_Launcher":
        if runlib.launcher_alive(self.path.parent):
            pid = self.path.read_text(encoding="utf-8").strip()
            raise _Usage(f"run {self.run_id} already has a launcher (pid {pid}), waiting for its night window or "
                         "running: wait for it, or stop it first")
        self.made_dir = not self.path.parent.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        runlib.atomic_write(self.path, f"{os.getpid()}\n")
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self.path.read_text(encoding="utf-8").split()[0] == str(os.getpid()):
                self.path.unlink()
            if self.made_dir and not any(self.path.parent.iterdir()):
                self.path.parent.rmdir()  # nothing ran (the night window closed first): leave no empty run folder
        except (OSError, IndexError):
            pass


def _run_nights(a, exp: Path, run_dir: Path, extra: list[str], allowance: dict, part: dict, raised, probe: dict,
                nw) -> int:
    """Run now, or on up to --nights night windows (resuming each night after the first)."""
    env, lock = build_env(part, probe, dict(os.environ)), resources.home() / "local-run.lock"
    not_before, code, max_minutes = _now(), 1, None
    with _Child() as child:
        for night in range(1, a.nights + 1):
            if a.when == "night":
                start, end, _ = resources.window(max(_now(), not_before), *nw)
                if start > _now():
                    print(f"waiting for the night window: {start:%Y-%m-%d %H:%M} to {end:%H:%M}", flush=True)
                    _sleep_until(start)
                if allowance.get("idle_check") and not _wait_idle(end, allowance.get("idle_minutes") or IDLE_MINUTES):
                    print(f"the night window closed at {end:%H:%M} before the machine was idle; nothing ran. "
                          "Launch again to try the next night.", flush=True)
                    return 3
                max_minutes = int(deadline_minutes(_now(), end))
                if max_minutes == 0:
                    print(f"under 10 minutes left before the night window closes at {end:%H:%M}; not starting. "
                          "Launch again for the next night.", flush=True)
                    return 3
                not_before = end
            cmd = build_cmd(exp, run_dir, *_cap_minutes(max_minutes, extra))
            try:
                with Lock(lock, a.run_id):
                    run_dir.mkdir(parents=True, exist_ok=True)
                    if night == 1:
                        config = {"run_id": a.run_id, "when": a.when, "allowance": part, "raised": raised, "cmd": cmd,
                                  "started": _now().astimezone().isoformat(timespec="seconds")}
                        runlib.atomic_write(run_dir / "config.json", json.dumps(config, indent=2) + "\n")
                    code = child.run(cmd, exp, env, run_dir / "log.txt")
            except BlockingIOError:
                other = lock.read_text(encoding="utf-8", errors="replace").strip() if lock.exists() else ""
                raise _Usage(f"another local run is active{f' (run {other})' if other else ''}: the lock {lock} "
                             "is held. Wait for it to finish, or stop it first.") from None
            if not (code == 3 and night < a.nights and not child.signalled and _deadline_hit(run_dir)):
                return code
            print(f"night {night} of {a.nights} is over; resuming on the next night", flush=True)
    return code


def main() -> None:
    argv = sys.argv[1:]
    own, extra = (argv[:argv.index("--")], argv[argv.index("--") + 1:]) if "--" in argv else (argv, [])
    p = argparse.ArgumentParser(prog="local_run.py", description="run an experiment locally within the allowance")
    p.add_argument("exp_dir", help="experiment directory holding train.py")
    p.add_argument("--run-id", required=True)
    p.add_argument("--when", choices=["now", "night"], default="now")
    p.add_argument("--lab", default="lab", help="lab directory; the run goes to LAB/runs/ID")
    p.add_argument("--raise-ram", type=float, help="this run's RAM limit in GB (at least the allowance)")
    p.add_argument("--raise-gpu", type=float, help="this run's GPU memory limit in GB (at least the allowance)")
    p.add_argument("--raise-threads", type=int, help="this run's CPU thread limit (at least the allowance)")
    p.add_argument("--nights", type=int, default=1,
                   help="with --when night: resume on up to this many nights. Between nights this launcher sleeps "
                        "and keeps lab/runs/ID/.launcher; the poll shows the run as waiting and keeps watching")
    p.add_argument("--dry-run", action="store_true", help="print the command and freelab's variables, run nothing")
    args = p.parse_args(own)
    try:
        code = _launch(args, extra)
    except _Usage as e:
        print(str(e), file=sys.stderr)
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
