import json
from datetime import datetime
import pytest, resources as r

MAC_DISPLAYS = json.dumps({"SPDisplaysDataType": [{"sppci_model": "Apple M4 Pro", "sppci_cores": "20"}]})

def test_parse_macos_unified():
    d = r.parse_macos(str(24 * 2**30), "14", "Apple M4 Pro", MAC_DISPLAYS)
    assert d["ram_gb"] == 24 and d["cpu_threads"] == 14
    assert d["gpu"]["kind"] == "apple" and d["gpu"]["unified"] is True and d["gpu"]["mem_gb"] == 24

def test_parse_linux_cuda():
    d = r.parse_linux("MemTotal:       65843200 kB\n", 16, "NVIDIA GeForce RTX 4070, 12282\n")
    assert d["gpu"] == {"kind": "cuda", "name": "NVIDIA GeForce RTX 4070", "mem_gb": 12.0, "unified": False}
    assert round(d["ram_gb"]) == 63

def test_parse_linux_no_gpu():
    assert r.parse_linux("MemTotal: 8000000 kB\n", 4, None)["gpu"]["kind"] == "none"

@pytest.mark.parametrize("now,inside,start_day", [
    ("2026-09-28 23:30", True, 28), ("2026-09-29 03:00", True, 28), ("2026-09-29 12:00", False, 29)])
def test_window_crosses_midnight(now, inside, start_day):
    s, e, ins = r.window(datetime.fromisoformat(now), "23:00", "07:00")
    assert ins is inside and s.day == start_day and (e - s).total_seconds() == 8 * 3600

ALLOW = {"probe": {"gpu": {"unified": True}}, "day": {"ram_gb": 8, "gpu_mem_gb": 0, "cpu_threads": 4},
         "night": {"ram_gb": 20, "gpu_mem_gb": 0, "cpu_threads": 10},
         "night_window": {"start": "00:05", "end": "07:35"}, "idle_check": False}
NOW = datetime.fromisoformat("2026-09-28 14:00")

@pytest.mark.parametrize("need,cloud,expect", [
    ({"ram_gb": 4, "gpu_mem_gb": 2, "hours": 1}, False, "now"),
    ({"ram_gb": 10, "gpu_mem_gb": 6, "hours": 2}, False, "tonight"),
    ({"ram_gb": 30, "gpu_mem_gb": 0, "hours": 2}, True, "cloud"),
    ({"ram_gb": 30, "gpu_mem_gb": 0, "hours": 2}, False, "ask"),
])
def test_place(need, cloud, expect):
    assert r.place(need, ALLOW, NOW, cloud)["place"] == expect

def test_place_multi_night():
    out = r.place({"ram_gb": 10, "gpu_mem_gb": 0, "hours": 12}, ALLOW, NOW, False)
    assert out["place"] == "tonight" and out["nights"] == 2

def test_show_without_allowance_exits_2(monkeypatch):
    monkeypatch.setattr("sys.argv", ["resources.py", "show"])
    with pytest.raises(SystemExit) as e: r.main()
    assert e.value.code == 2


@pytest.mark.parametrize("night", [["--night-ram", "4"], ["--night-gpu", "0"], ["--night-threads", "2"]])
def test_set_refuses_a_night_below_the_day(monkeypatch, capsys, night):
    args = {"--day-ram": "8", "--day-gpu": "4", "--day-threads": "4", "--night-ram": "8", "--night-gpu": "4",
            "--night-threads": "4", "--start": "23:00", "--end": "07:00"}
    args[night[0]] = night[1]
    monkeypatch.setattr(r, "probe", lambda: {"gpu": dict(r.DEFAULT_GPU)})
    monkeypatch.setattr("sys.argv", ["resources.py", "set", *[x for kv in args.items() for x in kv]])
    with pytest.raises(SystemExit) as e: r.main()
    assert e.value.code == 2 and "at least the day allowance" in capsys.readouterr().err
    assert not (r.home() / "local.json").exists()

def test_place_on_a_cuda_machine_counts_ram_and_gpu_apart():
    cuda = {"probe": {"gpu": {"kind": "cuda", "unified": False}}, "day": {"ram_gb": 8, "gpu_mem_gb": 6},
            "night": {"ram_gb": 16, "gpu_mem_gb": 12}, "night_window": {"start": "23:00", "end": "07:00"}}
    assert r.place({"ram_gb": 8, "gpu_mem_gb": 6}, cuda, NOW, False)["place"] == "now"   # 14 GB, but not unified
    assert r.place({"ram_gb": 4, "gpu_mem_gb": 10}, cuda, NOW, False)["place"] == "tonight"
    out = r.place({"ram_gb": 4, "gpu_mem_gb": 16}, cuda, NOW, False)
    assert out["place"] == "ask" and "4 GB RAM and 16 GB GPU memory" in out["why"]

@pytest.mark.parametrize("text", ["[]", "3", '"x"'])
def test_non_object_allowance_file_exits_2(monkeypatch, capsys, text):
    r.home().mkdir(parents=True)
    (r.home() / "local.json").write_text(text)
    monkeypatch.setattr("sys.argv", ["resources.py", "show"])
    with pytest.raises(SystemExit) as e: r.main()
    assert e.value.code == 2 and "expected a JSON object" in capsys.readouterr().err


# --- machine presets and the idle wait (0.3.0) --------------------------------------------------

MAC24 = {"os": "macos", "cpu": "Apple M4 Pro", "cpu_threads": 14, "ram_gb": 24.0,
         "gpu": {"kind": "apple", "name": "Apple M4 Pro", "mem_gb": 24.0, "unified": True}}
SMALL = {"os": "linux", "cpu": "4-thread CPU", "cpu_threads": 4, "ram_gb": 8.0, "gpu": dict(r.DEFAULT_GPU)}
CUDA = {"os": "linux", "cpu": "16-thread CPU", "cpu_threads": 16, "ram_gb": 32.0,
        "gpu": {"kind": "cuda", "name": "RTX 4070", "mem_gb": 12.0, "unified": False}}


def A(ram, gpu, threads):
    return {"ram_gb": ram, "gpu_mem_gb": gpu, "cpu_threads": threads}


def test_presets_on_a_24gb_unified_machine():
    p = r.presets(MAC24)
    assert p["day"] == {"low": A(6, 6, 3), "medium": A(12, 12, 7), "high": A(18, 18, 10)}
    assert p["night"] == {"none": None, "partial": A(14.4, 14.4, 8), "full": A(20, 20, 13)}


def test_presets_on_a_cuda_machine_keep_ram_and_gpu_apart():
    p = r.presets(CUDA)
    assert p["day"]["medium"] == A(16, 6, 8)
    assert p["night"]["full"] == A(32 - 4.8, 12, 15)   # reserve is max(4, 15% of 32) of RAM only


def test_presets_on_a_small_machine_without_gpu():
    p = r.presets(SMALL)
    for a in [*p["day"].values(), p["night"]["partial"], p["night"]["full"]]:
        assert a["ram_gb"] >= 1 and a["cpu_threads"] >= 1 and a["gpu_mem_gb"] == 0
        assert a["ram_gb"] <= 8 - 4 and a["cpu_threads"] <= 3   # leaves the reserve
    assert p["day"]["high"]["ram_gb"] == 4 and p["day"]["low"]["ram_gb"] == 2
    assert p["night"]["full"] == A(4, 0, 3)
    for key in ("ram_gb", "gpu_mem_gb", "cpu_threads"):
        assert p["night"]["full"][key] >= p["day"]["high"][key]
        assert p["night"]["partial"][key] <= p["night"]["full"][key]


@pytest.mark.parametrize("probe", [
    {"cpu_threads": 1, "ram_gb": 2.0, "gpu": dict(r.DEFAULT_GPU)},
    {"cpu_threads": 0, "ram_gb": 0.0, "gpu": None},
    {"cpu_threads": 2, "ram_gb": 3.0, "gpu": {"kind": "apple", "mem_gb": 3.0, "unified": True}}])
def test_presets_never_go_below_the_minimums(probe):
    p = r.presets(probe)
    for a in [*p["day"].values(), p["night"]["partial"], p["night"]["full"]]:
        assert a["ram_gb"] >= 1 and a["cpu_threads"] >= 1 and a["gpu_mem_gb"] >= 0
        assert a["gpu_mem_gb"] == 0 or a["gpu_mem_gb"] >= 1
    assert p["night"]["full"]["ram_gb"] >= p["day"]["high"]["ram_gb"]


def test_presets_cli_prints_a_plain_description_per_preset(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(r, "probe", lambda: calls.append(1) or MAC24)
    monkeypatch.setattr("sys.argv", ["resources.py", "presets"])
    with pytest.raises(SystemExit) as e: r.main()
    out = json.loads(capsys.readouterr().out)
    assert e.value.code == 0
    assert out["day"]["low"]["description"] == "you will not notice it"
    assert out["day"]["medium"]["description"] == "busy, but the computer stays usable"
    assert out["day"]["high"]["description"] == "the computer gets noticeably slower"
    assert out["night"]["partial"]["description"] == "most of the machine at night"
    assert out["night"]["full"]["description"] == "everything except a reserve for the system"
    assert out["night"]["none"] == {"description": "no night runs"}
    assert out["day"]["medium"]["ram_gb"] == 12 and out["night"]["full"]["cpu_threads"] == 13
    assert len(calls) == 1   # one probe (system_profiler on macOS) for every preset


def run_set(monkeypatch, *argv, probe=MAC24):
    monkeypatch.setattr(r, "probe", lambda: probe)
    monkeypatch.setattr("sys.argv", ["resources.py", "set", "--start", "23:00", "--end", "07:00", *argv])
    with pytest.raises(SystemExit) as e: r.main()
    return e.value.code


def test_set_with_presets_and_idle_minutes_round_trips_through_show(monkeypatch, capsys):
    assert run_set(monkeypatch, "--day-preset", "medium", "--night-preset", "full", "--idle-minutes", "30") == 0
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["resources.py", "show"])
    with pytest.raises(SystemExit): r.main()
    doc = json.loads(capsys.readouterr().out)
    assert doc["day"] == A(12, 12, 7) and doc["night"] == A(20, 20, 13)
    assert doc["day_preset"] == "medium" and doc["night_preset"] == "full" and doc["night_runs"] is True
    assert doc["idle_check"] is True and doc["idle_minutes"] == 30
    assert doc["night_window"] == {"start": "23:00", "end": "07:00"}


def test_explicit_numbers_override_the_preset_value(monkeypatch):
    assert run_set(monkeypatch, "--day-preset", "low", "--day-ram", "9", "--night-preset", "full",
                   "--night-threads", "12") == 0
    doc = r.load_allowance()
    assert doc["day"] == A(9, 6, 3) and doc["night"] == A(20, 20, 12)


def test_night_preset_is_raised_to_the_chosen_day(monkeypatch):
    assert run_set(monkeypatch, "--day-preset", "high", "--night-preset", "partial") == 0
    doc = r.load_allowance()   # partial is 14.4 / 8 but the high day is 18 / 10
    assert doc["day"] == A(18, 18, 10) and doc["night"] == A(18, 18, 10)


def test_night_none_stores_night_as_day_and_no_night_runs(monkeypatch):
    assert run_set(monkeypatch, "--day-preset", "low", "--night-preset", "none") == 0
    doc = r.load_allowance()
    assert doc["night"] == doc["day"] == A(6, 6, 3)
    assert doc["night_runs"] is False and doc["night_preset"] == "none"
    assert doc["idle_check"] is False and doc["idle_minutes"] is None


def test_explicit_numbers_still_work_and_idle_check_keeps_the_default(monkeypatch):
    assert run_set(monkeypatch, "--day-ram", "8", "--day-gpu", "4", "--day-threads", "4", "--night-ram", "16",
                   "--night-gpu", "8", "--night-threads", "8", "--idle-check") == 0
    doc = r.load_allowance()
    assert doc["day"] == A(8, 4, 4) and doc["night"] == A(16, 8, 8) and doc["night_runs"] is True
    assert doc["idle_check"] is True and doc["idle_minutes"] is None
    assert "day_preset" not in doc and "night_preset" not in doc


@pytest.mark.parametrize("argv", [
    ["--night-preset", "full"],                                       # no day values at all
    ["--day-preset", "low"],                                          # no night values at all
    ["--day-preset", "low", "--night-preset", "full", "--day-ram", "x"],
    ["--day-preset", "low", "--night-preset", "full", "--idle-minutes", "0"],
    ["--day-preset", "low", "--night-preset", "none", "--night-ram", "9"],
    ["--day-ram", "8", "--day-gpu", "4", "--night-ram", "16", "--night-gpu", "8", "--night-threads", "8"]])
def test_set_without_a_preset_or_all_numbers_exits_2(monkeypatch, argv):
    assert run_set(monkeypatch, *argv) == 2
    assert not (r.home() / "local.json").exists()


# --- placement: cloud first (0.4.0) ---------------------------------------------------------------

@pytest.mark.parametrize("need", [{"ram_gb": 4, "gpu_mem_gb": 2, "hours": 1},      # fits the day allowance
                                  {"ram_gb": 10, "gpu_mem_gb": 6, "hours": 2},     # fits the night allowance
                                  {"ram_gb": 30, "gpu_mem_gb": 0, "hours": 2}])    # fits nowhere here
def test_cloud_first_when_a_cloud_backend_is_connected(need):
    out = r.place(need, ALLOW, NOW, True)
    assert out["place"] == "cloud" and out["nights"] == 0 and "cloud first" in out["why"]


@pytest.mark.parametrize("need,cloud,expect", [
    ({"ram_gb": 4, "gpu_mem_gb": 2, "hours": 1}, True, "now"),
    ({"ram_gb": 10, "gpu_mem_gb": 6, "hours": 2}, True, "tonight"),
    ({"ram_gb": 30, "gpu_mem_gb": 0, "hours": 2}, True, "cloud"),
    ({"ram_gb": 30, "gpu_mem_gb": 0, "hours": 2}, False, "ask"),
])
def test_prefer_local_keeps_now_tonight_cloud_ask(need, cloud, expect):
    assert r.place(need, ALLOW, NOW, cloud, prefer="local")["place"] == expect


def test_prefer_is_checked():
    with pytest.raises(ValueError):
        r.place({"ram_gb": 1}, ALLOW, NOW, True, prefer="tonight")


def _check(monkeypatch, capsys, *extra):
    r.home().mkdir(parents=True, exist_ok=True)
    (r.home() / "local.json").write_text(json.dumps(ALLOW))
    monkeypatch.setattr("sys.argv", ["resources.py", "check", "--ram", "4", "--gpu-mem", "2", "--hours", "1", *extra])
    with pytest.raises(SystemExit) as e: r.main()
    assert e.value.code == 0
    return json.loads(capsys.readouterr().out)["place"]


def test_check_cli_defaults_to_cloud_and_takes_prefer_local(monkeypatch, capsys):
    assert _check(monkeypatch, capsys, "--cloud-available") == "cloud"
    assert _check(monkeypatch, capsys, "--cloud-available", "--prefer", "local") == "now"
    assert _check(monkeypatch, capsys) == "now"


def test_no_allowance_points_to_onboard_step_3(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["resources.py", "check", "--ram", "1", "--gpu-mem", "0", "--hours", "1"])
    with pytest.raises(SystemExit) as e: r.main()
    err = capsys.readouterr().err
    assert e.value.code == 2 and "onboard skill, step 3" in err and "compute skill" not in err


# --- 0.4.1: cloud needs no allowance, a missing night window, positive numbers --------------------

def _check_code(monkeypatch, capsys, *extra):
    monkeypatch.setattr("sys.argv", ["resources.py", "check", "--ram", "4", "--gpu-mem", "2", "--hours", "1", *extra])
    with pytest.raises(SystemExit) as e: r.main()
    return e.value.code, capsys.readouterr()


def test_check_cloud_available_needs_no_allowance(monkeypatch, capsys):
    code, out = _check_code(monkeypatch, capsys, "--cloud-available")
    assert code == 0 and json.loads(out.out)["place"] == "cloud"
    code, out = _check_code(monkeypatch, capsys, "--cloud-available", "--prefer", "local")
    assert code == 2 and "onboard skill, step 3" in out.err   # a local placement still needs the allowance


@pytest.mark.parametrize("nw", [None, {}, {"start": "23:00"}, {"start": "23:00", "end": "23:00"}, "x"])
def test_no_night_window_means_never_tonight(nw):
    allow = {k: v for k, v in ALLOW.items() if k != "night_window"}
    if nw is not None:
        allow["night_window"] = nw
    need = {"ram_gb": 10, "gpu_mem_gb": 6, "hours": 2}   # fits only the night allowance
    assert r.place(need, allow, NOW, False)["place"] == "ask"
    assert r.place(need, allow, NOW, True, prefer="local")["place"] == "cloud"
    assert r.place({"ram_gb": 4, "gpu_mem_gb": 2, "hours": 1}, allow, NOW, False)["place"] == "now"


def test_check_cli_with_an_allowance_lacking_a_night_window(monkeypatch, capsys):
    r.home().mkdir(parents=True, exist_ok=True)
    (r.home() / "local.json").write_text(json.dumps({k: v for k, v in ALLOW.items() if k != "night_window"}))
    code, out = _check_code(monkeypatch, capsys, "--prefer", "local")
    assert code == 0 and json.loads(out.out)["place"] == "now"


def test_night_runs_off_means_never_tonight():
    allow = dict(ALLOW, night_runs=False)
    assert r.place({"ram_gb": 10, "gpu_mem_gb": 6, "hours": 2}, allow, NOW, False)["place"] == "ask"


@pytest.mark.parametrize("bad", [["--day-ram", "0"], ["--day-ram", "-1"], ["--night-threads", "0"],
                                 ["--day-gpu", "-2"], ["--day-ram", "nan"]])
def test_set_rejects_zero_or_negative_values(monkeypatch, bad):
    assert run_set(monkeypatch, "--day-preset", "low", "--night-preset", "full", *bad) == 2
    assert not (r.home() / "local.json").exists()


def test_set_accepts_a_gpu_of_zero(monkeypatch):
    assert run_set(monkeypatch, "--day-preset", "low", "--day-gpu", "0", "--night-preset", "full") == 0
    assert r.load_allowance()["day"]["gpu_mem_gb"] == 0
