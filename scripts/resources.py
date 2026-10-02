"""freelab machine probe, local allowance store and placement (spec §1 G3b, §3, §4).

Probes this machine's RAM/CPU/GPU, stores the user's day/night compute allowance in
`$FREELAB_HOME/local.json` (default `~/.freelab`), and decides where a job with a given need should run.
Cloud first: when a cloud backend is connected with free credit left (`--cloud-available`), the answer is
cloud, unless the user asked for this machine (`--prefer local`). Otherwise: now (fits the day allowance),
tonight (fits the night allowance), cloud (a connected free tier can take it), or ask (nothing fits, no cloud
connected)."""
from __future__ import annotations
import argparse, json, math, os, platform, subprocess, sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

DEFAULT_GPU = {"kind": "none", "name": None, "mem_gb": 0.0, "unified": False}


def home() -> Path:
    return Path(os.environ.get("FREELAB_HOME", "~/.freelab")).expanduser()


# --- parsers (pure, testable without touching the real machine) -----------------------------


def parse_macos(sysctl_mem: str, sysctl_ncpu: str, brand: str, displays_json: str) -> dict:
    ram_gb = round(int(sysctl_mem.strip()) / 2**30, 1)
    cpu_threads = int(sysctl_ncpu.strip())
    brand = brand.strip()
    gpu = dict(DEFAULT_GPU)
    if brand.startswith("Apple"):
        name = brand
        try:
            displays = json.loads(displays_json)
            model = displays["SPDisplaysDataType"][0].get("sppci_model")
            if model:
                name = model
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError):
            pass
        gpu = {"kind": "apple", "name": name, "mem_gb": ram_gb, "unified": True}
    return {"os": "macos", "cpu": brand, "cpu_threads": cpu_threads, "ram_gb": ram_gb, "gpu": gpu}


def _parse_nvidia_smi(text: str | None) -> dict:
    if text:
        line = next((l for l in text.strip().splitlines() if l.strip()), "")  # the first card only
        if line:
            name, _, mem = line.rpartition(",")
            try:
                return {"kind": "cuda", "name": name.strip(), "mem_gb": round(float(mem.strip()) / 1024, 1),
                         "unified": False}
            except ValueError:
                pass
    return dict(DEFAULT_GPU)


def parse_linux(meminfo: str, ncpu: int, nvidia_smi: str | None) -> dict:
    kb = 0
    for line in meminfo.splitlines():
        if line.startswith("MemTotal:"):
            kb = int(line.split()[1])
            break
    ram_gb = round(kb / (1024**2), 1)
    return {"os": "linux", "cpu": f"{ncpu}-thread CPU", "cpu_threads": ncpu, "ram_gb": ram_gb,
            "gpu": _parse_nvidia_smi(nvidia_smi)}


# --- probing the real machine ---------------------------------------------------------------


def _run(cmd: list[str]) -> str | None:
    """Run a probe command with a 10s timeout; None on any failure (missing tool, timeout,
    non-zero exit) so probe() never raises."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def _probe_windows() -> dict:
    ram_gb = 0.0
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
        ram_gb = round(stat.ullTotalPhys / 2**30, 1)
    except Exception:
        ram_gb = 0.0
    ncpu = os.cpu_count() or 0
    nvidia = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    return {"os": "windows", "cpu": platform.processor() or "unknown", "cpu_threads": ncpu, "ram_gb": ram_gb,
            "gpu": _parse_nvidia_smi(nvidia)}


def probe() -> dict:
    system = platform.system()
    if system == "Darwin":
        mem = _run(["sysctl", "-n", "hw.memsize"]) or "0"
        ncpu = _run(["sysctl", "-n", "hw.ncpu"]) or "0"
        brand = _run(["sysctl", "-n", "machdep.cpu.brand_string"]) or ""
        displays = _run(["system_profiler", "SPDisplaysDataType", "-json"]) or "{}"
        return parse_macos(mem, ncpu, brand, displays)
    if system == "Linux":
        try:
            meminfo = Path("/proc/meminfo").read_text()
        except OSError:
            meminfo = ""
        nvidia = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        return parse_linux(meminfo, os.cpu_count() or 0, nvidia)
    if system == "Windows":
        return _probe_windows()
    return {"os": system.lower() or "unknown", "cpu": "unknown", "cpu_threads": os.cpu_count() or 0,
            "ram_gb": 0.0, "gpu": dict(DEFAULT_GPU)}


# --- local allowance store --------------------------------------------------------------------


def load_allowance() -> dict:
    p = home() / "local.json"
    if not p.exists():
        raise FileNotFoundError("no local allowance yet: set it in the onboard skill, step 3 (resources.py set ...)")
    try:
        doc = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"corrupt allowance file at {p}: {e}") from e
    if not isinstance(doc, dict):
        raise ValueError(f"corrupt allowance file at {p}: expected a JSON object")
    return doc


def save_allowance(doc: dict) -> Path:
    doc = dict(doc)
    doc["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    h = home()
    h.mkdir(parents=True, exist_ok=True)
    p = h / "local.json"
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2))
    os.replace(tmp, p)
    return p


# --- the night window and placement -----------------------------------------------------------


def _parse_hhmm(s: str) -> time:
    try:
        return datetime.strptime(s, "%H:%M").time()
    except ValueError:
        raise ValueError(f"invalid time {s!r}, expected HH:MM") from None


def window(now: datetime, start: str, end: str) -> tuple[datetime, datetime, bool]:
    """The current or next occurrence of the [start, end) window, naive local time. Handles a
    window that crosses midnight (end <= start means "ends the next day")."""
    start_t, end_t = _parse_hhmm(start), _parse_hhmm(end)
    if start_t == end_t:
        raise ValueError(f"window start and end must differ, got {start!r} and {end!r}")

    def win_for(day):
        s = datetime.combine(day, start_t)
        e = datetime.combine(day + timedelta(days=1) if end_t <= start_t else day, end_t)
        return s, e

    today = now.date()
    candidates = [win_for(today + timedelta(days=d)) for d in (-1, 0, 1)]
    for s, e in candidates:
        if s <= now < e:
            return s, e, True
    s, e = min((s, e) for s, e in candidates if s > now)  # tomorrow's window always starts after now
    return s, e, False


def _fits(need: dict, budget: dict, unified: bool) -> bool:
    if unified:
        if need.get("ram_gb", 0) + need.get("gpu_mem_gb", 0) > budget.get("ram_gb", 0):
            return False
    else:
        if need.get("ram_gb", 0) > budget.get("ram_gb", 0):
            return False
        if need.get("gpu_mem_gb", 0) > budget.get("gpu_mem_gb", 0):
            return False
    if "cpu_threads" in need and need["cpu_threads"] > budget.get("cpu_threads", 0):
        return False
    return True


def _describe(need: dict, day: dict, night: dict, unified: bool) -> str:
    if unified:
        total = need.get("ram_gb", 0) + need.get("gpu_mem_gb", 0)
        needs = f"needs {total:g} GB (RAM + GPU, unified memory)"
        budgets = f"day allowance {day.get('ram_gb', 0):g} GB, night allowance {night.get('ram_gb', 0):g} GB"
    else:
        needs = f"needs {need.get('ram_gb', 0):g} GB RAM and {need.get('gpu_mem_gb', 0):g} GB GPU memory"
        budgets = (f"day allowance {day.get('ram_gb', 0):g} GB RAM / {day.get('gpu_mem_gb', 0):g} GB GPU, "
                   f"night allowance {night.get('ram_gb', 0):g} GB RAM / {night.get('gpu_mem_gb', 0):g} GB GPU")
    if "cpu_threads" in need:
        needs += f" and {need['cpu_threads']:g} CPU threads"
    return f"{needs}; {budgets}"


def place(need: dict, allowance: dict, now: datetime, cloud_available: bool,
          prefer: str = "cloud") -> dict:
    """Where a job runs. Cloud first: with a connected cloud backend (`cloud_available`) and prefer="cloud" (the
    default) it is "cloud". With prefer="local", or no cloud: "now" (fits the day allowance), "tonight" (fits the
    night allowance), "cloud" (does not fit here, a cloud backend is connected) or "ask"."""
    if prefer not in ("cloud", "local"):
        raise ValueError(f"prefer must be 'cloud' or 'local', got {prefer!r}")
    unified = bool(allowance.get("probe", {}).get("gpu", {}).get("unified"))
    day, night = allowance.get("day", {}), allowance.get("night", {})
    why = _describe(need, day, night, unified)
    if cloud_available and prefer == "cloud":
        return {"place": "cloud", "why": "a cloud backend with free credit is connected (cloud first); " + why,
                "nights": 0}
    if _fits(need, day, unified):
        placement = "now"
    elif _fits(need, night, unified):
        placement = "tonight"
    elif cloud_available:
        placement = "cloud"
    else:
        placement = "ask"
    nights = 0
    if placement == "tonight":
        nw = allowance.get("night_window", {})
        s, e, _ = window(now, nw.get("start", "00:00"), nw.get("end", "00:00"))
        window_hours = (e - s).total_seconds() / 3600
        nights = max(1, math.ceil(need.get("hours", 0) / window_hours)) if window_hours > 0 else 1
    return {"place": placement, "why": why, "nights": nights}


# --- machine presets ----------------------------------------------------------------------------

PRESET_TEXT = {
    ("day", "low"): "you will not notice it",
    ("day", "medium"): "busy, but the computer stays usable",
    ("day", "high"): "the computer gets noticeably slower",
    ("night", "none"): "no night runs",
    ("night", "partial"): "most of the machine at night",
    ("night", "full"): "everything except a reserve for the system",
}
DAY_SHARE = {"low": 0.25, "medium": 0.5, "high": 0.75}
NIGHT_PARTIAL_SHARE = 0.6
DEFAULT_IDLE_MINUTES = 15


def presets(probe: dict) -> dict:
    """Day and night allowances computed from a probe. The reserve left for the system is max(4 GB, 15 % of RAM)
    of RAM and one CPU thread. GPU memory is the RAM figure on a unified-memory machine (reserve taken the same
    way), the card's memory on a CUDA machine, and 0 with no GPU. Every value has a floor (1 GB, 1 thread) and a
    day value never goes above the night `full` one; `partial` never goes above `full`. A night preset is not
    raised to a day preset here: `set` does that for the day the user picked."""
    ram, threads = float(probe.get("ram_gb") or 0), int(probe.get("cpu_threads") or 0)
    gpu = probe.get("gpu") or {}
    unified = bool(gpu.get("unified"))
    has_gpu = gpu.get("kind") not in (None, "none")
    gpu_mem = ram if unified else (float(gpu.get("mem_gb") or 0) if has_gpu else 0.0)
    reserve = max(4.0, 0.15 * ram)
    ram_cap = max(1.0, ram - reserve)
    gpu_cap = max(1.0, gpu_mem - reserve) if unified else gpu_mem
    thread_cap = max(1, threads - 1)

    def part(share: float | None, ram_max: float, gpu_max: float, thread_max: int) -> dict:
        def scaled(total: float, top: float) -> float:
            return top if share is None else min(top, total * share)
        gpu_part = 0.0 if gpu_max <= 0 else max(1.0, scaled(gpu_mem, gpu_max)) if unified else scaled(gpu_mem, gpu_max)
        return {"ram_gb": round(max(1.0, scaled(ram, ram_max)), 1), "gpu_mem_gb": round(gpu_part, 1),
                "cpu_threads": max(1, min(thread_max, int(threads * share + 1e-9) if share is not None else thread_max))}

    return {"day": {name: part(share, ram_cap, gpu_cap, thread_cap) for name, share in DAY_SHARE.items()},
            "night": {"none": None, "partial": part(NIGHT_PARTIAL_SHARE, ram_cap, gpu_cap, thread_cap),
                      "full": part(None, ram_cap, gpu_cap, thread_cap)}}


# --- CLI ----------------------------------------------------------------------------------------


def _cli_probe(args) -> int:
    print(json.dumps(probe(), indent=2))
    return 0


def _cli_show(args) -> int:
    print(json.dumps(load_allowance(), indent=2))
    return 0


def _cli_presets(args) -> int:
    out = {"day": {}, "night": {}}
    table = presets(probe())  # probe once: on macOS it runs system_profiler
    for (period, name), text in PRESET_TEXT.items():
        values = table[period][name] or {}
        out[period][name] = {**values, "description": text}
    print(json.dumps(out, indent=2))
    return 0


def _period(args, period: str, chosen: dict) -> dict:
    """The `period` ("day" or "night") allowance: the preset's values (empty with no preset) with any explicit
    --{period}-ram/-gpu/-threads on top. main() has already checked that nothing is left unset."""
    given = {"ram_gb": getattr(args, f"{period}_ram"), "gpu_mem_gb": getattr(args, f"{period}_gpu"),
             "cpu_threads": getattr(args, f"{period}_threads")}
    return {**chosen, **{k: v for k, v in given.items() if v is not None}}


def _cli_set(args) -> int:
    start_t, end_t = _parse_hhmm(args.start), _parse_hhmm(args.end)
    if start_t == end_t:
        raise ValueError(f"night window start and end must differ, got {args.start!r}")
    if args.idle_minutes is not None and args.idle_minutes < 1:
        raise ValueError("--idle-minutes must be at least 1")
    machine = probe()
    table = presets(machine)
    day = _period(args, "day", table["day"].get(args.day_preset, {}))
    night_none = args.night_preset == "none"
    if night_none:
        night, night_runs = dict(day), False
    else:
        base = table["night"].get(args.night_preset, {})
        base = {k: max(v, day[k]) for k, v in base.items()}   # a night preset never goes below the chosen day
        night, night_runs = _period(args, "night", base), True
    doc = {"probe": machine, "day": day, "night": night, "night_runs": night_runs,
           "night_window": {"start": args.start, "end": args.end},
           "idle_check": bool(args.idle_check or args.idle_minutes), "idle_minutes": args.idle_minutes}
    if args.day_preset:
        doc["day_preset"] = args.day_preset
    if args.night_preset:
        doc["night_preset"] = args.night_preset
    if night["ram_gb"] < day["ram_gb"] or night["gpu_mem_gb"] < day["gpu_mem_gb"] or night["cpu_threads"] < day["cpu_threads"]:
        raise ValueError(
            "night allowance must be at least the day allowance "
            f"(day: {day['ram_gb']:g} GB RAM / {day['gpu_mem_gb']:g} GB GPU / {day['cpu_threads']:g} threads, "
            f"night: {night['ram_gb']:g} GB RAM / {night['gpu_mem_gb']:g} GB GPU / {night['cpu_threads']:g} threads)"
        )
    print(f"wrote {save_allowance(doc)}")
    return 0


def _cli_check(args) -> int:
    allowance = load_allowance()
    need = {"ram_gb": args.ram, "gpu_mem_gb": args.gpu_mem, "hours": args.hours}
    print(json.dumps(place(need, allowance, datetime.now(), bool(args.cloud_available), args.prefer), indent=2))
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="resources.py")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("probe", help="probe this machine's RAM/CPU/GPU").set_defaults(func=_cli_probe)
    sub.add_parser("show", help="print the local allowance").set_defaults(func=_cli_show)
    sub.add_parser("presets", help="print the day and night presets computed for this machine"
                   ).set_defaults(func=_cli_presets)

    set_p = sub.add_parser("set", help="set the local day/night allowance")
    set_p.add_argument("--day-preset", choices=["low", "medium", "high"])
    set_p.add_argument("--night-preset", choices=["none", "partial", "full"])
    for period in ("day", "night"):
        set_p.add_argument(f"--{period}-ram", type=float, help="GB of RAM (overrides the preset's value)")
        set_p.add_argument(f"--{period}-gpu", type=float, help="GB of GPU memory (overrides the preset's value)")
        set_p.add_argument(f"--{period}-threads", type=int, help="CPU threads (overrides the preset's value)")
    set_p.add_argument("--start", required=True, help="night window start, HH:MM")
    set_p.add_argument("--end", required=True, help="night window end, HH:MM")
    set_p.add_argument("--idle-check", action="store_true", help=f"wait for {DEFAULT_IDLE_MINUTES} idle minutes")
    set_p.add_argument("--idle-minutes", type=int, help="idle minutes to wait for at night (implies --idle-check)")
    set_p.set_defaults(func=_cli_set)

    check_p = sub.add_parser("check", help="place a job: cloud first when --cloud-available, else now / tonight / "
                             "cloud / ask from its need vs. the allowance")
    check_p.add_argument("--ram", required=True, type=float)
    check_p.add_argument("--gpu-mem", required=True, type=float)
    check_p.add_argument("--hours", required=True, type=float)
    check_p.add_argument("--cloud-available", action="store_true",
                         help="a cloud backend is connected and has free credit left")
    check_p.add_argument("--prefer", choices=["cloud", "local"], default="cloud",
                         help="cloud (default): cloud whenever --cloud-available; local: this machine when the job "
                              "fits (the user asked for it, or a long job would burn the free quota)")
    check_p.set_defaults(func=_cli_check)

    args = p.parse_args()
    if args.command == "set":
        for period, preset in (("day", args.day_preset), ("night", args.night_preset)):
            numbers = [f"--{period}-{k}" for k in ("ram", "gpu", "threads")]
            given = [n for n in numbers if getattr(args, n[2:].replace("-", "_")) is not None]
            if preset is None and len(given) < 3:
                p.error(f"for the {period}, give --{period}-preset or all of {', '.join(numbers)}")
            if preset == "none" and given:
                p.error(f"--night-preset none means no night runs; it cannot be combined with {given[0]}")
    try:
        code = args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
