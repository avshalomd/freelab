import argparse, json, os, signal, sys, time
import pytest
import runlib

def make(tmp_path, *extra):
    p = argparse.ArgumentParser(); runlib.add_args(p)
    return p.parse_args(["--out", str(tmp_path / "run"), *extra])

def test_args_defaults(tmp_path):
    a = make(tmp_path)
    assert a.resume is False and a.smoke is False and a.max_minutes == 0

def test_log_status_finish(tmp_path):
    with runlib.Run(make(tmp_path)) as run:
        run.log(1, 10, "train", "loss", 0.5)
        run.status("step 1/10")
        run.finish({"accuracy": 0.9})
    lines = runlib.read_metrics(run.out / "metrics.jsonl")
    assert lines[0]["name"] == "loss" and lines[0]["value"] == 0.5 and "t" in lines[0]
    assert (run.out / "status.txt").read_text().strip() == "done"
    assert json.loads((run.out / "summary.json").read_text())["accuracy"] == 0.9
    assert runlib.exit_code(run) == 0

def test_read_metrics_skips_torn_line(tmp_path):
    f = tmp_path / "m.jsonl"
    f.write_text('{"step": 1, "value": 1}\n{"step": 2, "val')
    assert [r["step"] for r in runlib.read_metrics(f)] == [1]

def test_checkpoint_atomic_and_latest(tmp_path):
    with runlib.Run(make(tmp_path)) as run:
        run.save(lambda d: (d / "w.txt").write_text("a"), step=1)
        # simulate a torn write: a step dir without COMPLETE
        (run.out / "ckpt" / "step-00000002").mkdir()
        assert run.latest_checkpoint().name == "step-00000001"
        run.save(lambda d: (d / "w.txt").write_text("b"), step=3)
        run.save(lambda d: (d / "w.txt").write_text("c"), step=4)
        kept = sorted(p.name for p in (run.out / "ckpt").iterdir() if (p / "COMPLETE").exists())
        assert kept == ["step-00000003", "step-00000004"]
        assert (run.latest_checkpoint() / "w.txt").read_text() == "c"

def test_save_same_step_overwrite_replaces_atomically(tmp_path):
    with runlib.Run(make(tmp_path)) as run:
        run.save(lambda d: (d / "w.txt").write_text("first"), step=1)
        dest = run.save(lambda d: (d / "w.txt").write_text("second"), step=1)
        assert dest.name == "step-00000001"
        assert (dest / "w.txt").read_text() == "second"
        latest = run.latest_checkpoint()
        assert latest.name == "step-00000001"
        assert (latest / "w.txt").read_text() == "second"
        leftovers = [
            p.name for p in (run.out / "ckpt").iterdir()
            if p.name.startswith(".tmp-") or p.name.startswith(".old-")
        ]
        assert leftovers == []

def test_latest_checkpoint_recovers_interrupted_same_step_overwrite(tmp_path):
    with runlib.Run(make(tmp_path)) as run:
        run.save(lambda d: (d / "w.txt").write_text("first"), step=1)
        ckpt = run.out / "ckpt"
        # Simulate a crash between the two renames save() uses to replace a step that
        # already has a complete checkpoint: the old one was moved aside but the new one
        # never arrived, so step-00000001 itself is briefly missing.
        (ckpt / "step-00000001").rename(ckpt / ".old-step-00000001")
        assert not (ckpt / "step-00000001").exists()
        recovered = run.latest_checkpoint()
        assert recovered is not None and recovered.name == "step-00000001"
        assert (recovered / "w.txt").read_text() == "first"
        assert not (ckpt / ".old-step-00000001").exists()

def test_save_failure_keeps_previous(tmp_path):
    with runlib.Run(make(tmp_path)) as run:
        run.save(lambda d: (d / "w.txt").write_text("ok"), step=1)
        with pytest.raises(RuntimeError):
            run.save(lambda d: (_ for _ in ()).throw(RuntimeError("boom")), step=2)
        assert run.latest_checkpoint().name == "step-00000001"
        run.finish({})

def test_deadline_stops_with_code_3(tmp_path):
    a = make(tmp_path, "--max-minutes", "0.001")
    with runlib.Run(a, margin_minutes=0) as run:
        time.sleep(0.1)
        assert run.should_stop() == "deadline"
    assert runlib.exit_code(run) == 3
    assert "stopped (deadline)" in (run.out / "status.txt").read_text()

def test_sigterm_sets_signal(tmp_path):
    with runlib.Run(make(tmp_path)) as run:
        os.kill(os.getpid(), signal.SIGTERM)
        assert run.should_stop() == "signal"
    assert runlib.exit_code(run) == 3

def test_exception_marks_failed(tmp_path):
    with pytest.raises(ValueError):
        with runlib.Run(make(tmp_path)) as run:
            raise ValueError("bad")
    assert (run.out / "status.txt").read_text().startswith("failed: bad")
    assert runlib.exit_code(run) == 1

def test_allowance_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("FREELAB_MAX_RAM_GB", "0.001")
    with runlib.Run(make(tmp_path)) as run:
        run._next_check = 0
        assert run.should_stop() == "allowance"
    assert runlib.exit_code(run) == 3


# --- the allowance guard: rulings ---------------------------------------------------------------

def test_allowance_not_checked_without_env(tmp_path, monkeypatch):
    monkeypatch.delenv("FREELAB_MAX_RAM_GB", raising=False)
    with runlib.Run(make(tmp_path)) as run:
        run._next_check = 0
        assert run.should_stop() is None
        run.finish({})
    assert runlib.exit_code(run) == 0

def test_allowance_checked_at_most_once_a_minute(tmp_path, monkeypatch):
    monkeypatch.setenv("FREELAB_MAX_RAM_GB", "0.001")
    with runlib.Run(make(tmp_path)) as run:
        assert run.should_stop() is None          # first check is due a minute after start
        run._next_check = 0
        assert run.should_stop() == "allowance"
        assert run._next_check > time.monotonic() + 50
    assert "stopped (allowance)" in (run.out / "status.txt").read_text()

def test_allowance_stop_on_swap_growth(tmp_path, monkeypatch):
    monkeypatch.setenv("FREELAB_MAX_RAM_GB", "1000")
    swap = iter([2.0, 3.5])
    monkeypatch.setattr(runlib, "swap_used_gb", lambda: next(swap))
    with runlib.Run(make(tmp_path)) as run:
        run._next_check = 0
        assert run.should_stop() == "allowance"

def test_allowance_probe_failure_never_stops(tmp_path, monkeypatch):
    monkeypatch.setenv("FREELAB_MAX_RAM_GB", "0.001")
    monkeypatch.setattr(runlib, "rss_gb", lambda: None)
    monkeypatch.setattr(runlib, "swap_used_gb", lambda: None)
    with runlib.Run(make(tmp_path)) as run:
        run._next_check = 0
        assert run.should_stop() is None

def test_parse_swapusage():
    assert runlib.parse_swapusage("total = 2048.00M  used = 1022.25M  free = 1025.75M  (encrypted)") == pytest.approx(1022.25 / 1024)
    assert runlib.parse_swapusage("total = 4.00G  used = 1.50G  free = 2.50G") == pytest.approx(1.5)
    assert runlib.parse_swapusage("garbage") is None

def test_rss_gb_reads_this_process():
    rss = runlib.rss_gb()
    assert rss is None or 0.001 < rss < 64

def test_apply_allowance_threads_and_cuda_fraction(monkeypatch):
    import types
    calls = {}
    cuda = types.SimpleNamespace(
        is_available=lambda: True,
        get_device_properties=lambda i: types.SimpleNamespace(total_memory=16 * 2**30),
        set_per_process_memory_fraction=lambda f, *a: calls.setdefault("fraction", f))
    fake = types.SimpleNamespace(set_num_threads=lambda n: calls.setdefault("threads", n), cuda=cuda)
    monkeypatch.setitem(sys.modules, "torch", fake)          # a stand-in: tests never import torch
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        monkeypatch.setenv(var, "x"); monkeypatch.delenv(var)  # restored after the test
    monkeypatch.setenv("FREELAB_THREADS", "3")
    monkeypatch.setenv("FREELAB_GPU_MEM_GB", "4")
    runlib.apply_allowance()
    assert os.environ["OMP_NUM_THREADS"] == "3" and os.environ["MKL_NUM_THREADS"] == "3"
    assert calls == {"threads": 3, "fraction": 0.25}

def test_apply_allowance_keeps_user_threads_and_survives_torch_errors(monkeypatch):
    import types
    def boom(*a): raise RuntimeError("no cuda here")
    fake = types.SimpleNamespace(set_num_threads=boom, cuda=types.SimpleNamespace(is_available=boom))
    monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("FREELAB_THREADS", "3")
    monkeypatch.setenv("FREELAB_GPU_MEM_GB", "4")
    runlib.apply_allowance()
    assert os.environ["OMP_NUM_THREADS"] == "1"

def test_apply_allowance_gpu_zero_skips_cuda_fraction(monkeypatch):
    import types
    calls = {}
    cuda = types.SimpleNamespace(
        is_available=lambda: True,
        get_device_properties=lambda i: types.SimpleNamespace(total_memory=16 * 2**30),
        set_per_process_memory_fraction=lambda f, *a: calls.setdefault("fraction", f))
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(set_num_threads=lambda n: calls.setdefault("threads", n), cuda=cuda))
    monkeypatch.setenv("FREELAB_THREADS", "3")
    monkeypatch.setenv("FREELAB_GPU_MEM_GB", "0")
    runlib.apply_allowance()
    assert calls == {"threads": 3}


def test_failed_status_is_one_line(tmp_path):
    import argparse, runlib
    args = argparse.Namespace(out=str(tmp_path / "run"), resume=False, max_minutes=0.0, smoke=False)
    try:
        with runlib.Run(args):
            raise RuntimeError("CUDA error: out of memory\nCUDA kernel errors might be reported later")
    except RuntimeError:
        pass
    assert (tmp_path / "run" / "status.txt").read_text() == "failed: CUDA error: out of memory\n"


# --- checkpoints after the run: only the final one is kept once it finishes ----------------------

def _ckpt_names(run):
    return sorted(p.name for p in (run.out / "ckpt").iterdir())

def test_finish_keeps_only_the_newest_checkpoint(tmp_path):
    with runlib.Run(make(tmp_path)) as run:
        for step in (100, 200, 290):
            run.save(lambda d: (d / "w.txt").write_text("x"), step=step)
        assert _ckpt_names(run) == ["step-00000200", "step-00000290"]   # KEEP = 2 while it runs
        (run.out / "ckpt" / "step-00000300").mkdir()                     # a torn write, newer than the last
        (run.out / "ckpt" / ".tmp-leftover").mkdir()
        run.finish({"accuracy": 0.8})
    assert _ckpt_names(run) == ["step-00000290"]
    assert (run.out / "ckpt" / "step-00000290" / "COMPLETE").exists()
    assert json.loads((run.out / "summary.json").read_text()) == {"accuracy": 0.8}
    assert (run.out / "status.txt").read_text().strip() == "done" and runlib.exit_code(run) == 0

def test_finish_restores_an_interrupted_overwrite_before_pruning(tmp_path):
    with runlib.Run(make(tmp_path)) as run:
        run.save(lambda d: (d / "w.txt").write_text("a"), step=1)
        run.save(lambda d: (d / "w.txt").write_text("b"), step=2)
        ckpt = run.out / "ckpt"
        (ckpt / "step-00000002").rename(ckpt / ".old-step-00000002")  # crash mid same-step overwrite
        run.finish({})
    assert _ckpt_names(run) == ["step-00000002"]
    assert (run.out / "ckpt" / "step-00000002" / "w.txt").read_text() == "b"

def test_finish_without_checkpoints_is_fine(tmp_path):
    with runlib.Run(make(tmp_path)) as run:
        (run.out / "ckpt" / "step-00000001").mkdir()  # torn, and no complete one: nothing to prefer, keep it
        run.finish({})
    assert _ckpt_names(run) == ["step-00000001"]

def test_stopped_run_keeps_two_checkpoints(tmp_path):
    a = make(tmp_path, "--max-minutes", "0.001")
    with runlib.Run(a, margin_minutes=0) as run:
        for step in (100, 200, 300):
            run.save(lambda d: (d / "w.txt").write_text("x"), step=step)
        time.sleep(0.1)
        assert run.should_stop() == "deadline"
    assert _ckpt_names(run) == ["step-00000200", "step-00000300"]
    assert runlib.exit_code(run) == 3

def test_failed_run_keeps_two_checkpoints(tmp_path):
    with pytest.raises(RuntimeError):
        with runlib.Run(make(tmp_path)) as run:
            for step in (100, 200, 300):
                run.save(lambda d: (d / "w.txt").write_text("x"), step=step)
            raise RuntimeError("CUDA error")
    assert _ckpt_names(run) == ["step-00000200", "step-00000300"]
    assert runlib.exit_code(run) == 1

def test_finish_after_a_stop_keeps_two_checkpoints(tmp_path):
    a = make(tmp_path, "--max-minutes", "0.001")
    with runlib.Run(a, margin_minutes=0) as run:
        for step in (100, 200):
            run.save(lambda d: (d / "w.txt").write_text("x"), step=step)
        time.sleep(0.1)
        run.should_stop()
        run.finish({})  # an experiment that writes a summary after stopping still stays resumable
    assert _ckpt_names(run) == ["step-00000100", "step-00000200"]


# --- 0.4.1 ---------------------------------------------------------------------------------------

def test_atomic_write_is_utf8_and_leaves_no_temporary_file(tmp_path):
    import runlib
    target = tmp_path / "status.txt"
    runlib.atomic_write(target, "failed: Café ✓\n")
    assert target.read_bytes() == "failed: Café ✓\n".encode("utf-8")
    assert [p.name for p in tmp_path.iterdir()] == ["status.txt"]


def test_launcher_alive(tmp_path):
    import os, runlib
    assert runlib.launcher_alive(tmp_path) is False                  # no marker
    marker = tmp_path / runlib.LAUNCHER_MARKER
    for text, alive in ((str(os.getpid()), True), ("999999999", False), ("0", False), ("-1", False),
                        ("", False), ("x", False)):
        marker.write_text(text)
        assert runlib.launcher_alive(tmp_path) is alive, text
