import json, os, sys, types
from datetime import datetime, timedelta
import pytest, local_run as lr, resources

APPLE = {"gpu": {"kind": "apple", "unified": True}, "ram_gb": 24}

def test_build_env_apple():
    env = lr.build_env({"ram_gb": 8, "gpu_mem_gb": 6, "cpu_threads": 4}, APPLE, {})
    assert env["FREELAB_THREADS"] == "4" and env["OMP_NUM_THREADS"] == "4"
    assert env["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] == "0.33"  # 6 / (0.75 * 24)


def test_build_env_mps_ratio_targets_the_grant_and_caps_at_one():
    # torch scales the ratio by the recommended working set (~0.75 x RAM), so an 8 GB grant on a 48 GB Mac allows
    # about 8 GB, not 8/48 of the working set (5.9 GiB, which OOMed the quick start's evaluation)
    env = lr.build_env({"ram_gb": 16, "gpu_mem_gb": 8, "cpu_threads": 4}, {**APPLE, "ram_gb": 48}, {})
    assert env["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] == "0.22"
    env = lr.build_env({"ram_gb": 24, "gpu_mem_gb": 24, "cpu_threads": 4}, APPLE, {})
    assert env["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] == env["PYTORCH_MPS_LOW_WATERMARK_RATIO"] == "1.0"


def test_build_env_apple_gpu_share_never_above_the_ram_allowance():
    # unified memory: a GPU allowance above the RAM allowance is capped at the RAM allowance (4 / (0.75 * 24))
    env = lr.build_env({"ram_gb": 4, "gpu_mem_gb": 12, "cpu_threads": 4}, APPLE, {})
    assert env["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] == "0.22" and env["FREELAB_GPU_MEM_GB"] == "12"

def test_deadline_minutes():
    assert lr.deadline_minutes(datetime(2026, 9, 29, 7, 0), datetime(2026, 9, 29, 7, 30)) == 20
    assert lr.deadline_minutes(datetime(2026, 9, 29, 7, 29), datetime(2026, 9, 29, 7, 30)) == 0

def test_lock_is_exclusive(tmp_path):
    with lr.Lock(tmp_path / "gpu.lock"):
        with pytest.raises(BlockingIOError):
            with lr.Lock(tmp_path / "gpu.lock"): pass

def test_missing_allowance_exit_2(tmp_path, monkeypatch, capsys):
    (tmp_path / "exp").mkdir(); (tmp_path / "exp" / "train.py").write_text("")
    monkeypatch.setattr(sys, "argv", ["local_run.py", str(tmp_path / "exp"), "--run-id", "r1", "--lab", str(tmp_path / "lab")])
    with pytest.raises(SystemExit) as e: lr.main()
    assert e.value.code == 2 and "no local allowance yet" in capsys.readouterr().err

def test_dry_run_command(tmp_path, monkeypatch, capsys):
    resources.save_allowance({"probe": {"gpu": {"kind": "none", "unified": False}, "ram_gb": 16},
        "day": {"ram_gb": 4, "gpu_mem_gb": 0, "cpu_threads": 2}, "night": {"ram_gb": 12, "gpu_mem_gb": 0, "cpu_threads": 8},
        "night_window": {"start": "00:05", "end": "07:30"}, "idle_check": False})
    (tmp_path / "exp").mkdir(); (tmp_path / "exp" / "train.py").write_text("")
    monkeypatch.setattr(sys, "argv", ["local_run.py", str(tmp_path / "exp"), "--run-id", "r1", "--lab",
                                      str(tmp_path / "lab"), "--dry-run", "--", "--smoke"])
    with pytest.raises(SystemExit) as e: lr.main()
    out = json.loads(capsys.readouterr().out)
    assert e.value.code == 0 and "--smoke" in out["cmd"] and out["env"]["FREELAB_THREADS"] == "2"


# --- controller rulings and the rest of the launcher ------------------------------------------

ALLOWANCE = {"probe": {"gpu": {"kind": "none", "unified": False}, "ram_gb": 16},
             "day": {"ram_gb": 4, "gpu_mem_gb": 0, "cpu_threads": 2},
             "night": {"ram_gb": 12, "gpu_mem_gb": 0, "cpu_threads": 8},
             "night_window": {"start": "00:05", "end": "07:30"}, "idle_check": False}


def setup_exp(tmp_path, train=""):
    resources.save_allowance(ALLOWANCE)
    (tmp_path / "exp").mkdir()
    (tmp_path / "exp" / "train.py").write_text(train)
    return tmp_path / "exp", tmp_path / "lab"


def run_main(monkeypatch, exp, lab, *flags, extra=()):
    argv = ["local_run.py", str(exp), "--run-id", "r1", "--lab", str(lab), *flags]
    if extra:
        argv += ["--", *extra]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as e:
        lr.main()
    return e.value.code


def test_build_env_sets_mps_low_watermark_not_above_high():
    # torch refuses to initialise MPS when the low watermark (default 1.4) exceeds the high one
    env = lr.build_env({"ram_gb": 8, "gpu_mem_gb": 6, "cpu_threads": 4}, APPLE, {})
    assert float(env["PYTORCH_MPS_LOW_WATERMARK_RATIO"]) <= float(env["PYTORCH_MPS_HIGH_WATERMARK_RATIO"])
    assert env["FREELAB_MAX_RAM_GB"] == "8" and env["FREELAB_GPU_MEM_GB"] == "6"
    assert "FREELAB_MACHINE_RAM_GB" not in env and env["MKL_NUM_THREADS"] == "4"


CUDA = {"gpu": {"kind": "cuda", "unified": False}, "ram_gb": 32}


def test_build_env_mps_ratio_floor_and_no_mps_vars_off_apple():
    env = lr.build_env({"ram_gb": 8, "gpu_mem_gb": 1, "cpu_threads": 4}, APPLE, {})
    assert env["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] == "0.1"
    env = lr.build_env({"ram_gb": 8, "gpu_mem_gb": 6, "cpu_threads": 4}, CUDA, {"CUDA_VISIBLE_DEVICES": "0"})
    assert "PYTORCH_MPS_HIGH_WATERMARK_RATIO" not in env and env["CUDA_VISIBLE_DEVICES"] == "0"


def test_build_env_gpu_allowance_zero_means_no_gpu():
    # CUDA: hide the GPU so the experiment picks the CPU instead of crashing out of memory
    env = lr.build_env({"ram_gb": 8, "gpu_mem_gb": 0, "cpu_threads": 4}, CUDA, {"CUDA_VISIBLE_DEVICES": "0,1"})
    assert env["CUDA_VISIBLE_DEVICES"] == "" and env["FREELAB_GPU_MEM_GB"] == "0"
    # Apple: no MPS watermark variables at all (the experiment reads FREELAB_GPU_MEM_GB == "0")
    env = lr.build_env({"ram_gb": 8, "gpu_mem_gb": 0, "cpu_threads": 4}, APPLE, {})
    assert env["FREELAB_GPU_MEM_GB"] == "0" and "CUDA_VISIBLE_DEVICES" not in env
    assert not any(k.startswith("PYTORCH_MPS_") for k in env)


def test_dry_run_env_shows_hidden_cuda_gpu(tmp_path, monkeypatch, capsys):
    exp, lab = setup_exp(tmp_path)
    resources.save_allowance(dict(ALLOWANCE, probe=CUDA))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    assert run_main(monkeypatch, exp, lab, "--dry-run") == 0
    assert json.loads(capsys.readouterr().out)["env"]["CUDA_VISIBLE_DEVICES"] == ""


def test_build_env_keeps_base_and_prepends_scripts_to_pythonpath():
    env = lr.build_env({"ram_gb": 8, "gpu_mem_gb": 0, "cpu_threads": 4}, APPLE,
                       {"PATH": "/bin", "PYTHONPATH": "/elsewhere", "OMP_NUM_THREADS": "64"})
    assert env["PATH"] == "/bin" and env["OMP_NUM_THREADS"] == "4"
    assert env["PYTHONPATH"].split(os.pathsep) == [str(lr.SCRIPTS), "/elsewhere"]


def test_dry_run_env_holds_only_freelab_variables(tmp_path, monkeypatch, capsys):
    exp, lab = setup_exp(tmp_path)
    monkeypatch.setenv("SOME_SECRET_TOKEN", "do-not-print")
    monkeypatch.setenv("PYTHONPATH", "/inherited/path")
    assert run_main(monkeypatch, exp, lab, "--dry-run") == 0
    text = capsys.readouterr().out
    out = json.loads(text)
    assert "do-not-print" not in text and "/inherited/path" not in text
    assert set(out["env"]) <= {"FREELAB_MAX_RAM_GB", "FREELAB_GPU_MEM_GB", "FREELAB_THREADS",
                               "OMP_NUM_THREADS", "MKL_NUM_THREADS", "PYTHONPATH",
                               "PYTORCH_MPS_HIGH_WATERMARK_RATIO", "PYTORCH_MPS_LOW_WATERMARK_RATIO",
                               "CUDA_VISIBLE_DEVICES"}
    assert out["when"] == "now" and out["max_minutes"] is None and out["window"] is None
    assert "--max-minutes" not in out["cmd"] and "--resume" not in out["cmd"]
    # a dry run never creates the run directory and never takes the lock
    assert not lab.exists() and not (resources.home() / "local-run.lock").exists()


def test_night_dry_run_has_window_and_positive_max_minutes(tmp_path, monkeypatch, capsys):
    exp, lab = setup_exp(tmp_path)
    monkeypatch.setattr(lr, "_now", lambda: datetime(2026, 9, 28, 14, 0))
    assert run_main(monkeypatch, exp, lab, "--when", "night", "--dry-run") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["window"] == ["2026-09-29T00:05", "2026-09-29T07:30"]
    assert out["max_minutes"] == 435 and out["env"]["FREELAB_THREADS"] == "8"
    cmd = out["cmd"]
    assert cmd[cmd.index("--max-minutes") + 1] == "435"


def test_dry_run_adds_resume_only_for_a_complete_checkpoint(tmp_path, monkeypatch, capsys):
    exp, lab = setup_exp(tmp_path)
    torn = lab / "runs" / "r1" / "ckpt" / "step-00000002"
    torn.mkdir(parents=True)
    run_main(monkeypatch, exp, lab, "--dry-run")
    assert "--resume" not in json.loads(capsys.readouterr().out)["cmd"]
    (lab / "runs" / "r1" / "ckpt" / "step-00000001").mkdir()
    (lab / "runs" / "r1" / "ckpt" / "step-00000001" / "COMPLETE").write_text("")
    run_main(monkeypatch, exp, lab, "--dry-run")
    assert "--resume" in json.loads(capsys.readouterr().out)["cmd"]


def test_raise_below_allowance_exit_2(tmp_path, monkeypatch, capsys):
    exp, lab = setup_exp(tmp_path)
    assert run_main(monkeypatch, exp, lab, "--raise-ram", "2", "--dry-run") == 2
    assert "--raise-ram" in capsys.readouterr().err


def test_lock_held_exit_2(tmp_path, monkeypatch, capsys):
    exp, lab = setup_exp(tmp_path, "raise SystemExit(0)\n")
    lock = resources.home() / "local-run.lock"
    with lr.Lock(lock, "other-run"):
        assert run_main(monkeypatch, exp, lab) == 2
    err = capsys.readouterr().err
    assert str(lock) in err and "another local run is active" in err and "other-run" in err


FAKE_TRAIN = """import json, os, sys
import runlib  # proves local_run put scripts/ on PYTHONPATH
print("fake train", json.dumps(sys.argv[1:]), os.environ["FREELAB_THREADS"], os.getcwd())
print("to stderr", file=sys.stderr)
raise SystemExit(int(os.environ.get("FAKE_EXIT", "0")))
"""


def test_launch_now_runs_train_and_writes_config_and_log(tmp_path, monkeypatch, capsys):
    exp, lab = setup_exp(tmp_path, FAKE_TRAIN)
    code = run_main(monkeypatch, exp, lab, "--raise-ram", "6", "--raise-threads", "2", extra=["--smoke"])
    assert code == 0
    run_dir = lab / "runs" / "r1"
    log = (run_dir / "log.txt").read_text()
    assert "fake train" in log and "--smoke" in log and "to stderr" in log and str(exp.resolve()) in log
    assert f'["--out", "{run_dir.resolve()}", "--smoke"]' in log and " 2 " in log
    cfg = json.loads((run_dir / "config.json").read_text())
    assert cfg["run_id"] == "r1" and cfg["when"] == "now" and "--smoke" in cfg["cmd"] and cfg["started"]
    assert datetime.fromisoformat(cfg["started"]).tzinfo is not None
    assert cfg["allowance"] == {"ram_gb": 6, "gpu_mem_gb": 0, "cpu_threads": 2}
    assert cfg["raised"] == {"ram_gb": 6}


def test_launch_passes_through_child_exit_code(tmp_path, monkeypatch):
    exp, lab = setup_exp(tmp_path, FAKE_TRAIN)
    monkeypatch.setenv("FAKE_EXIT", "3")
    assert run_main(monkeypatch, exp, lab) == 3
    cfg = json.loads((lab / "runs" / "r1" / "config.json").read_text())
    assert cfg["raised"] is None


def test_night_inside_window_starts_now_with_minutes_left(tmp_path, monkeypatch):
    exp, lab = setup_exp(tmp_path, FAKE_TRAIN)
    monkeypatch.setattr(lr, "_now", lambda: datetime(2026, 9, 29, 6, 0))
    assert run_main(monkeypatch, exp, lab, "--when", "night") == 0
    log = (lab / "runs" / "r1" / "log.txt").read_text()
    assert '"--max-minutes", "80"' in log and " 8 " in log


def test_night_with_too_little_window_left_does_not_start(tmp_path, monkeypatch, capsys):
    exp, lab = setup_exp(tmp_path, FAKE_TRAIN)
    monkeypatch.setattr(lr, "_now", lambda: datetime(2026, 9, 29, 7, 25))
    assert run_main(monkeypatch, exp, lab, "--when", "night") == 3
    assert "not starting" in capsys.readouterr().out
    assert not (lab / "runs" / "r1" / "log.txt").exists()


def fake_clock(monkeypatch, start):
    clock = [start]
    monkeypatch.setattr(lr, "_now", lambda: clock[0])
    monkeypatch.setattr(lr, "time", types.SimpleNamespace(sleep=lambda s: clock.__setitem__(0, clock[0] + timedelta(seconds=s))))
    return clock


NIGHT_TRAIN = """import sys, pathlib
out = pathlib.Path(sys.argv[sys.argv.index("--out") + 1])
print("argv", " ".join(sys.argv[1:]))
if "--resume" in sys.argv:
    raise SystemExit(0)
(out / "ckpt" / "step-00000001").mkdir(parents=True)
(out / "ckpt" / "step-00000001" / "COMPLETE").write_text("")
(out / "status.txt").write_text("stopped (deadline)\\n")
raise SystemExit(3)
"""


def test_nights_relaunch_next_window_with_resume(tmp_path, monkeypatch, capsys):
    exp, lab = setup_exp(tmp_path, NIGHT_TRAIN)
    clock = fake_clock(monkeypatch, datetime(2026, 9, 29, 6, 0))
    assert run_main(monkeypatch, exp, lab, "--when", "night", "--nights", "2") == 0
    launches = [l for l in (lab / "runs" / "r1" / "log.txt").read_text().splitlines() if l.startswith("argv")]
    assert len(launches) == 2
    assert "--max-minutes 80" in launches[0] and "--resume" not in launches[0]
    assert "--resume --max-minutes 435" in launches[1]
    assert clock[0] == datetime(2026, 9, 30, 0, 5)
    assert "night 1 of 2 is over" in capsys.readouterr().out


def test_nights_stops_after_the_last_night(tmp_path, monkeypatch):
    exp, lab = setup_exp(tmp_path, NIGHT_TRAIN)
    fake_clock(monkeypatch, datetime(2026, 9, 29, 6, 0))
    assert run_main(monkeypatch, exp, lab, "--when", "night") == 3


def test_idle_check_window_closes_before_idle_exit_3(tmp_path, monkeypatch, capsys):
    exp, lab = setup_exp(tmp_path, FAKE_TRAIN)
    resources.save_allowance(dict(ALLOWANCE, idle_check=True))
    fake_clock(monkeypatch, datetime(2026, 9, 29, 6, 0))
    monkeypatch.setattr(lr.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(lr, "idle_seconds", lambda: 30.0)
    assert run_main(monkeypatch, exp, lab, "--when", "night") == 3
    assert "before the machine was idle; nothing ran" in capsys.readouterr().out
    assert not (lab / "runs" / "r1").exists()


def test_nights_needs_when_night(tmp_path, monkeypatch):
    exp, lab = setup_exp(tmp_path)
    assert run_main(monkeypatch, exp, lab, "--nights", "2", "--dry-run") == 2


def dry_cmd(monkeypatch, capsys, exp, lab, *flags, extra=()):
    assert run_main(monkeypatch, exp, lab, "--dry-run", *flags, extra=extra) == 0
    out = json.loads(capsys.readouterr().out)
    return out, out["cmd"]


def test_window_deadline_wins_over_a_longer_max_minutes_in_experiment_args(tmp_path, monkeypatch, capsys):
    exp, lab = setup_exp(tmp_path)
    monkeypatch.setattr(lr, "_now", lambda: datetime(2026, 9, 29, 6, 0))
    for extra in (["--max-minutes", "99999", "--smoke"], ["--max-minutes=99999", "--smoke"], ["--max-minutes", "0"]):
        out, cmd = dry_cmd(monkeypatch, capsys, exp, lab, "--when", "night", extra=extra)
        assert cmd.count("--max-minutes") == 1 and not any(a.startswith("--max-minutes=") for a in cmd)
        assert cmd[cmd.index("--max-minutes") + 1] == "80" and out["max_minutes"] == 80


def test_shorter_max_minutes_in_experiment_args_is_kept_at_night(tmp_path, monkeypatch, capsys):
    exp, lab = setup_exp(tmp_path)
    monkeypatch.setattr(lr, "_now", lambda: datetime(2026, 9, 29, 6, 0))
    out, cmd = dry_cmd(monkeypatch, capsys, exp, lab, "--when", "night", extra=["--max-minutes", "5", "--smoke"])
    assert cmd.count("--max-minutes") == 1 and cmd[cmd.index("--max-minutes") + 1] == "5"
    assert out["max_minutes"] == 5 and "--smoke" in cmd


def test_max_minutes_in_experiment_args_untouched_when_now(tmp_path, monkeypatch, capsys):
    exp, lab = setup_exp(tmp_path)
    out, cmd = dry_cmd(monkeypatch, capsys, exp, lab, extra=["--max-minutes=99999"])
    assert out["max_minutes"] is None and cmd[-1] == "--max-minutes=99999" and "--max-minutes" not in cmd


def test_night_launch_caps_experiment_max_minutes_at_the_window(tmp_path, monkeypatch):
    exp, lab = setup_exp(tmp_path, FAKE_TRAIN)
    monkeypatch.setattr(lr, "_now", lambda: datetime(2026, 9, 29, 6, 0))
    assert run_main(monkeypatch, exp, lab, "--when", "night", extra=["--max-minutes", "99999"]) == 0
    log = (lab / "runs" / "r1" / "log.txt").read_text()
    assert '"--max-minutes", "80"' in log and "99999" not in log
    cfg = json.loads((lab / "runs" / "r1" / "config.json").read_text())
    assert cfg["started"].startswith("2026-09-29T06:00:00")


# --- night_runs and the configurable idle wait (0.3.0) -----------------------------------------


@pytest.mark.parametrize("flags", [(), ("--dry-run",)])
def test_night_refused_when_the_allowance_has_no_night_runs(tmp_path, monkeypatch, capsys, flags):
    exp, lab = setup_exp(tmp_path, FAKE_TRAIN)
    resources.save_allowance(dict(ALLOWANCE, night_runs=False))
    monkeypatch.setattr(lr, "_now", lambda: datetime(2026, 9, 29, 6, 0))
    assert run_main(monkeypatch, exp, lab, "--when", "night", *flags) == 2
    err = capsys.readouterr().err
    assert "night runs are turned off" in err and "--when now" in err
    assert not (lab / "runs" / "r1").exists()


def test_now_still_runs_when_night_runs_are_off(tmp_path, monkeypatch):
    exp, lab = setup_exp(tmp_path, FAKE_TRAIN)
    resources.save_allowance(dict(ALLOWANCE, night_runs=False))
    assert run_main(monkeypatch, exp, lab) == 0


def idle_run(monkeypatch, tmp_path, allowance, idle, start=datetime(2026, 9, 29, 6, 0)):
    exp, lab = setup_exp(tmp_path, FAKE_TRAIN)
    resources.save_allowance(allowance)
    fake_clock(monkeypatch, start)
    monkeypatch.setattr(lr.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(lr, "idle_seconds", lambda: idle)
    return run_main(monkeypatch, exp, lab, "--when", "night")


def test_idle_minutes_from_the_allowance_set_the_wait(tmp_path, monkeypatch, capsys):
    # 20 minutes idle: enough for a 15-minute wait (the default), not for 30
    assert idle_run(monkeypatch, tmp_path, dict(ALLOWANCE, idle_check=True, idle_minutes=30), 20 * 60.0) == 3
    out = capsys.readouterr().out
    assert "idle for 30 minutes" in out and "before the machine was idle" in out


def test_idle_minutes_shorter_than_the_default(tmp_path, monkeypatch, capsys):
    assert idle_run(monkeypatch, tmp_path, dict(ALLOWANCE, idle_check=True, idle_minutes=5), 6 * 60.0) == 0
    assert "idle for 5 minutes" in capsys.readouterr().out


@pytest.mark.parametrize("extra", [{}, {"idle_minutes": None}])
def test_idle_check_without_minutes_waits_15(tmp_path, monkeypatch, capsys, extra):
    assert idle_run(monkeypatch, tmp_path, dict(ALLOWANCE, idle_check=True, **extra), 14 * 60.0) == 3
    assert "idle for 15 minutes" in capsys.readouterr().out


# --- 0.4.1: one launcher per run id, a bare --max-minutes, no night window -------------------------

def test_a_second_launcher_for_the_same_run_is_refused(tmp_path, monkeypatch, capsys):
    import runlib
    exp, lab = setup_exp(tmp_path, FAKE_TRAIN)
    run_dir = lab / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / runlib.LAUNCHER_MARKER).write_text(str(os.getpid()))   # a live launcher (this test's process)
    assert run_main(monkeypatch, exp, lab) == 2
    assert "already has a launcher" in capsys.readouterr().err and not (run_dir / "log.txt").exists()
    (run_dir / runlib.LAUNCHER_MARKER).write_text("999999999")        # a launcher that is gone: a stale marker
    assert run_main(monkeypatch, exp, lab) == 0
    assert not (run_dir / runlib.LAUNCHER_MARKER).exists()            # removed when the launcher ends


def test_the_launcher_marker_is_held_while_waiting_between_nights(tmp_path, monkeypatch):
    import runlib
    exp, lab = setup_exp(tmp_path, NIGHT_TRAIN)
    clock = fake_clock(monkeypatch, datetime(2026, 9, 29, 6, 0))
    run_dir = lab / "runs" / "r1"
    seen = []
    real_sleep = lr.time.sleep

    def sleep(s):
        seen.append(runlib.launcher_alive(run_dir))
        real_sleep(s)
    monkeypatch.setattr(lr, "time", types.SimpleNamespace(sleep=sleep))
    assert run_main(monkeypatch, exp, lab, "--when", "night", "--nights", "2") == 0
    assert seen and all(seen) and clock[0] == datetime(2026, 9, 30, 0, 5)
    assert not (run_dir / runlib.LAUNCHER_MARKER).exists()


@pytest.mark.parametrize("flags", [[], ["--when", "night"]])
def test_a_bare_max_minutes_in_the_experiment_args_is_refused(tmp_path, monkeypatch, capsys, flags):
    exp, lab = setup_exp(tmp_path, FAKE_TRAIN)
    monkeypatch.setattr(lr, "_now", lambda: datetime(2026, 9, 29, 6, 0))
    assert run_main(monkeypatch, exp, lab, *flags, extra=["--smoke", "--max-minutes"]) == 2
    assert "has no value" in capsys.readouterr().err and not (lab / "runs" / "r1").exists()


def test_night_without_a_night_window_exit_2(tmp_path, monkeypatch, capsys):
    exp, lab = setup_exp(tmp_path, FAKE_TRAIN)
    resources.save_allowance({k: v for k, v in ALLOWANCE.items() if k != "night_window"})
    assert run_main(monkeypatch, exp, lab, "--when", "night") == 2
    assert "no night window" in capsys.readouterr().err
