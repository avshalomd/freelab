import json, re
import pytest, status_page as sp

GOAL = {"text": "Route bank messages", "metric": "accuracy", "target": 0.8, "direction": "max"}
BUDGET = {"usd_limit": 0, "usd_spent": 0.0, "free_credit_note": "Modal $30/month"}
NAN = re.compile(r"\bnan\b", re.I)   # a NaN that leaked into the page, not "finance" or "nanosecond"

def write(lab, doc, metrics=None):
    lab.mkdir(parents=True, exist_ok=True)
    (lab / "status.json").write_text(json.dumps(doc))
    for rid, rows in (metrics or {}).items():
        d = lab / "runs" / rid; d.mkdir(parents=True, exist_ok=True)
        (d / "metrics.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + '\n{"torn')

def test_empty_lab_renders(tmp_path):
    write(tmp_path / "lab", sp.new_status(GOAL, BUDGET))
    html = sp.render(tmp_path / "lab")
    assert "Route bank messages" in html and "0.8" in html

def test_running_lab_with_chart(tmp_path):
    doc = sp.new_status(GOAL, BUDGET)
    doc["runs"] = [{"id": "r1", "backend": "modal", "state": "running", "step": 5, "total": 10,
                    "metric": 0.61, "eta": "4 min", "detail": "epoch 1", "started": "2026-09-28T10:00:00+00:00"}]
    doc["best"] = {"value": 0.61, "run": "r1", "at": "2026-09-28T10:05:00+00:00"}
    rows = [{"t": "x", "step": s, "total": 10, "split": "test", "name": "accuracy", "value": 0.4 + s / 20} for s in range(1, 6)]
    write(tmp_path / "lab", doc, {"r1": rows})
    html = sp.render(tmp_path / "lab")
    assert "<svg" in html and "r1" in html and "running" in html

def test_no_external_urls(tmp_path):
    write(tmp_path / "lab", sp.new_status(GOAL, BUDGET))
    html = sp.render(tmp_path / "lab")
    assert not re.search(r'(src|href)="https?://', html)

@pytest.mark.parametrize("mutate,key", [
    (lambda d: d.pop("goal"), "goal"),
    (lambda d: d.update(extra=1), "extra"),
    (lambda d: d["runs"].append({"id": "r", "backend": "local", "state": "weird", "step": 0, "total": 1,
                                 "metric": None, "eta": "", "detail": "", "started": ""}), "state"),
])
def test_validate_rejects(mutate, key):
    d = sp.new_status(GOAL, BUDGET); mutate(d)
    with pytest.raises(ValueError, match=key): sp.validate(d)

def test_main_exit_2_on_invalid(tmp_path, monkeypatch):
    (tmp_path / "lab").mkdir(); (tmp_path / "lab" / "status.json").write_text("{}")
    monkeypatch.setattr("sys.argv", ["status_page.py", str(tmp_path / "lab")])
    with pytest.raises(SystemExit) as e: sp.main()
    assert e.value.code == 2

def test_progress_min_direction_best_zero_is_full(tmp_path):
    # A "lower is better" metric that has reached its floor (0) has met or exceeded any
    # target: there's no target/0 ratio to take, and it must read as 100%, not "no progress".
    goal = {"text": "Minimize error", "metric": "error", "target": 0.1, "direction": "min"}
    doc = sp.new_status(goal, BUDGET)
    doc["best"] = {"value": 0.0, "run": "r1", "at": "2026-09-28T10:00:00+00:00"}
    write(tmp_path / "lab", doc)
    html = sp.render(tmp_path / "lab")
    assert 'bar-large"><div class="bar-fill" style="width:100.0%"' in html
    assert "no result yet" not in html.lower()

def test_progress_nan_best_is_not_full(tmp_path):
    # A non-finite best value must not read as "goal met" via min(100.0, nan) == 100.0; it
    # must fall back to the same "no result yet" / 0% state as having no best at all.
    doc = sp.new_status(GOAL, BUDGET)
    doc["best"] = {"value": float("nan"), "run": "r1", "at": "2026-09-28T10:00:00+00:00"}
    write(tmp_path / "lab", doc)
    html = sp.render(tmp_path / "lab")
    assert 'bar-large"><div class="bar-fill" style="width:100.0%"' not in html
    assert "no result yet" in html.lower() and not NAN.search(html)

def test_header_shows_rounded_target_with_direction_symbol(tmp_path):
    doc = sp.new_status(GOAL, BUDGET)  # accuracy, target 0.8, direction max
    write(tmp_path / "lab", doc)
    html = sp.render(tmp_path / "lab")
    assert "accuracy ≥ 80%" in html  # an accuracy-like (0-1) metric reads as a percentage

    goal_min = {"text": "Minimize error", "metric": "loss", "target": 0.1, "direction": "min"}
    doc_min = sp.new_status(goal_min, BUDGET)
    write(tmp_path / "lab_min", doc_min)
    html_min = sp.render(tmp_path / "lab_min")
    assert "loss ≤ 0.10" in html_min


def test_disp_rounds_floats_to_three_decimals(tmp_path):
    doc = sp.new_status(GOAL, BUDGET)
    doc["runs"] = [{"id": "r1", "backend": "local", "state": "running", "step": 5, "total": 10,
                    "metric": 0.5776983094928478, "eta": "", "detail": "", "started": ""}]
    doc["best"] = {"value": 0.5776983094928478, "run": "r1", "at": "2026-09-28T10:00:00+00:00"}
    write(tmp_path / "lab", doc)
    html = sp.render(tmp_path / "lab")
    assert "0.578" in html
    assert "0.5776983094928478" not in html
    # step/total are ints and must render unrounded, unaffected by the float rounding.
    assert "step 5 / 10" in html


def test_main_renders_and_exits_0_with_non_numeric_metrics_row(tmp_path, monkeypatch):
    # A non-numeric or non-finite step/value row in metrics.jsonl (bad data, distinct from a
    # torn/incomplete JSON line, which read_metrics() already drops) must be skipped when
    # building the chart rather than raising out of the SVG math and taking main() down with
    # a traceback and exit 1.
    doc = sp.new_status(GOAL, BUDGET)
    doc["runs"] = [{"id": "r1", "backend": "modal", "state": "running", "step": 5, "total": 10,
                    "metric": 0.61, "eta": "4 min", "detail": "epoch 1", "started": "2026-09-28T10:00:00+00:00"}]
    rows = [
        {"t": "x", "step": 1, "total": 10, "split": "test", "name": "accuracy", "value": 0.5},
        {"t": "x", "step": "bad", "total": 10, "split": "test", "name": "accuracy", "value": 0.6},
        {"t": "x", "step": 2, "total": 10, "split": "test", "name": "accuracy", "value": "oops"},
        {"t": "x", "step": 3, "total": 10, "split": "test", "name": "accuracy", "value": float("nan")},
        {"t": "x", "step": 4, "total": 10, "split": "test", "name": "accuracy", "value": 0.7},
    ]
    lab = tmp_path / "lab"
    write(lab, doc, {"r1": rows})
    monkeypatch.setattr("sys.argv", ["status_page.py", str(lab)])
    sp.main()  # must return normally (exit code 0), not raise
    html = (lab / "status.html").read_text()
    assert "<svg" in html


@pytest.mark.parametrize("key, value", [("text", ""), ("metric", None), ("target", None), ("target", "0.8"),
                                        ("target", float("nan"))])
def test_validate_checks_the_goal(tmp_path, monkeypatch, capsys, key, value):
    doc = sp.new_status({**GOAL, key: value}, BUDGET)
    with pytest.raises(ValueError, match=f"goal.{key}"): sp.validate(doc)
    doc["goal"].pop(key)
    write(tmp_path / "lab", doc)
    monkeypatch.setattr("sys.argv", ["status_page.py", str(tmp_path / "lab")])
    with pytest.raises(SystemExit) as e: sp.main()
    assert e.value.code == 2 and f"goal.{key}" in capsys.readouterr().err

def test_chart_has_axis_labels_a_legend_and_dashed_start_and_target(tmp_path):
    doc = sp.new_status(GOAL, BUDGET)
    doc["runs"] = [{"id": "r1", "backend": "local", "state": "done", "step": 2, "total": 2, "metric": 0.7,
                    "eta": "", "detail": "done", "started": ""}]
    rows = [{"t": "x", "step": s, "total": 2, "split": "test", "name": "accuracy", "value": v}
            for s, v in ((0, 0.544), (2, 0.767))]
    write(tmp_path / "lab", doc, {"r1": rows})
    fig = sp._render_chart(tmp_path / "lab", "r1", GOAL)
    svg = re.search(r"<svg.*?</svg>", fig, re.S).group(0)
    assert re.search(r'class="ref ref-target"[^>]*stroke-dasharray', svg)
    assert re.search(r'class="ref ref-baseline"[^>]*stroke-dasharray', svg)
    assert ">Training step<" in svg and ">Accuracy<" in svg               # labelled axes
    assert ">80%<" in svg and ">50%<" in svg                              # y ticks as percentages
    for m in re.finditer(r'<text class="tick-y" x="([\d.]+)"', svg):        # y ticks sit left of the plot
        assert float(m.group(1)) < sp.CHART_LEFT
    assert 'class="legend"' in fig and "Target (80%)" in fig and "Start (54%)" in fig
    other = sp._render_chart(tmp_path / "lab", "r1", {**GOAL, "metric": "loss"})
    assert "<svg" in other and "ref-target" not in other                 # another metric: no target line


STAGES = [{"name": "connection check", "state": "done", "detail": ""},
          {"name": "baseline", "state": "running", "detail": "2 of 3 epochs"},
          {"name": "ablation", "state": "skipped", "detail": "target met"}]
HEADER = "id\tcommit\tbackend\tgpu\tminutes\tmetric\tstatus\tchange\n"


def write_results(lab, text):
    lab.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        (lab / "results.tsv").write_bytes(text)
    else:
        (lab / "results.tsv").write_text(text)


def test_stages_render_as_a_timeline(tmp_path):
    doc = sp.new_status(GOAL, BUDGET)
    assert doc["stages"] == []
    doc["stages"] = STAGES
    write(tmp_path / "lab", doc)
    html = sp.render(tmp_path / "lab")
    plan = re.search(r'<section class="card plan">.*?</section>', html, re.S).group(0)
    assert "stage-done" in plan and "stage-running" in plan and "stage-skipped" in plan
    assert "baseline" in plan and "2 of 3 epochs" in plan and "Running now" in plan


def test_status_json_without_stages_still_renders(tmp_path):
    doc = sp.new_status(GOAL, BUDGET)
    doc.pop("stages")  # a lab made with freelab 0.1.0
    write(tmp_path / "lab", doc)
    assert "Route bank messages" in sp.render(tmp_path / "lab")


@pytest.mark.parametrize("stages,key", [
    ("not a list", "stages"),
    ([{"name": "x", "state": "weird", "detail": ""}], "state"),
    ([{"name": "x", "state": "done"}], "detail"),
    ([{"name": "", "state": "done", "detail": ""}], "name"),
])
def test_validate_rejects_bad_stages(stages, key):
    d = sp.new_status(GOAL, BUDGET); d["stages"] = stages
    with pytest.raises(ValueError, match=key): sp.validate(d)


def test_results_table_and_kept_chart(tmp_path):
    lab = tmp_path / "lab"
    write(lab, sp.new_status(GOAL, BUDGET))
    write_results(lab, HEADER
                  + "e1\ta1b2c3d\tmodal\tL4\t9.5\t0.781\tkeep\tbaseline\n"
                  + "e2\tb2c3d4e\tkaggle\tT4\t9.9\t0.770\tdiscard\tlr 3e-4\n"
                  + "e3\tc3d4e5f\tmodal\tL4\t9.4\t0.804\tkeep\t<b>16 layers</b>\n"
                  + "e4\td4e5f6a\tmodal\tL4\t2.0\t\tcrash\tbatch 64 (OOM)\n"
                  + "bad\trow\twith\tseven\tfields\t0.1\tkeep\n"
                  + "e5\te5f6a7b\tmodal\tL4\t9.0\tabc\tkeep\tbad metric\n"
                  + "e6\tf6a7b8c\tmodal\tL4\t9.0\t0.79\tmaybe\tbad status\n")
    rows = sp.read_results(lab / "results.tsv")
    assert [r["id"] for r in rows] == ["e1", "e2", "e3", "e4"]
    assert rows[3]["metric"] is None and rows[0]["minutes"] == 9.5
    html = sp.render(lab)
    section = re.search(r'<section class="results">.*?</section>', html, re.S).group(0)
    assert "4 experiments, 2 kept" in section and "res-keep" in section and "res-crash" in section
    assert section.index(">e3<") < section.index(">e1<")          # newest first
    assert "&lt;b&gt;16 layers&lt;/b&gt;" in section              # escaped
    chart = re.search(r'<figure class="chart-card" data-chart="experiments">.*?</figure>', html, re.S).group(0)
    assert "<svg" in chart and "Target (80%)" in chart and "ref-target" in chart  # the kept metric vs the target
    assert chart.count('class="dot dot-keep"') == 2 and chart.count('class="dot dot-discard"') == 1


def test_results_edge_inputs_never_crash(tmp_path):
    lab = tmp_path / "lab"
    write(lab, sp.new_status(GOAL, BUDGET))
    write_results(lab, HEADER.replace("\n", "\r\n") + "e1\ta\tmodal\tL4\t9\t0.7\tkeep\tx\r\n")
    assert [r["metric"] for r in sp.read_results(lab / "results.tsv")] == [0.7]
    write_results(lab, HEADER)  # header only: no section
    assert '<section class="results">' not in sp.render(lab)
    write_results(lab, HEADER + "e1\ta\tmodal\tL4\t9\t0.7\tkeep\tlr\t3e-4\n")  # a tab inside change
    assert sp.read_results(lab / "results.tsv") == []
    write_results(lab, b"\xff\xfe\x00junk\n")  # not UTF-8
    assert sp.read_results(lab / "results.tsv") == []
    assert "Route bank messages" in sp.render(lab)


def test_results_are_capped(tmp_path):
    lab = tmp_path / "lab"
    write(lab, sp.new_status(GOAL, BUDGET))
    write_results(lab, HEADER + "".join(f"e{i}\tc\tmodal\tL4\t9\t0.5\tdiscard\tx\n" for i in range(60)))
    html = sp.render(lab)
    assert "10 older experiments in results.tsv" in html and ">e59<" in html and ">e5<" not in html


def test_no_results_file_no_section(tmp_path):
    write(tmp_path / "lab", sp.new_status(GOAL, BUDGET))
    assert '<section class="results">' not in sp.render(tmp_path / "lab")


def test_run_chart_shows_each_split_as_its_own_series(tmp_path):
    doc = sp.new_status(GOAL, BUDGET)
    doc["runs"] = [{"id": "r1", "backend": "modal", "state": "done", "step": 20, "total": 20, "metric": 0.8,
                    "eta": "", "detail": "done", "started": ""}]
    rows = [{"t": "x", "step": 0, "total": 20, "split": "test", "name": "accuracy", "value": 0.54},
            {"t": "x", "step": 0, "total": 20, "split": "val", "name": "accuracy", "value": 0.55},
            {"t": "x", "step": 10, "total": 20, "split": "val", "name": "accuracy", "value": 0.75},
            {"t": "x", "step": 20, "total": 20, "split": "val", "name": "accuracy", "value": 0.81},
            {"t": "x", "step": 20, "total": 20, "split": "test", "name": "accuracy", "value": 0.82}]
    write(tmp_path / "lab", doc, {"r1": rows})
    svg = sp._render_chart(tmp_path / "lab", "r1", GOAL)
    val = re.search(r'<polyline data-series="val" points="([^"]+)"', svg).group(1).split()
    test = re.search(r'<polyline data-series="test" points="([^"]+)"', svg).group(1).split()
    assert len(val) == 3 and len(test) == 2
    assert "Validation" in svg and "Test" in svg                         # named in the legend


# --- the redesigned page (0.3.0) ---

RUN = {"id": "quick", "backend": "lightning T4", "state": "running", "step": 145, "total": 290, "metric": 0.758,
       "eta": "4 min", "detail": "epoch 1/2, step 145/290, loss 0.412", "started": "2026-10-01T10:00:00+00:00"}
VAL = [(0, 0.544), (145, 0.758)]


def running_doc(**run):
    doc = sp.new_status(GOAL, BUDGET)
    doc["runs"] = [{**RUN, **run}]
    return doc


def test_now_sentence_while_running():
    assert sp.now_sentence(running_doc(), {"val": VAL}) == (
        "Training on Lightning AI (T4): 50% done, about 4 min left. "
        "Accuracy went from 54% to 76%; the target is 80%.")


def test_now_sentence_when_done():
    doc = running_doc(state="done", step=290, eta="", detail="done")
    doc["best"] = {"value": 0.812, "run": "quick", "at": "2026-10-01T10:15:00+00:00"}
    series = {"val": VAL + [(290, 0.79)], "test": [(0, 0.54), (290, 0.812)]}
    assert sp.now_sentence(doc, series) == (
        "Finished on Lightning AI (T4). Accuracy went from 54% to 81%; the target of 80% is reached.")
    doc["best"]["value"] = 0.776
    series["test"][-1] = (290, 0.776)
    assert sp.now_sentence(doc, series).endswith("from 54% to 78%; the target of 80% is not reached.")
    series["test"][-1] = (290, 0.812)  # a best that matches no point: its split, so its start, is unknown
    assert sp.now_sentence(doc, series).endswith("Accuracy is 78%; the target of 80% is not reached.")


def test_now_sentence_with_no_data():
    doc = sp.new_status(GOAL, BUDGET)
    assert sp.now_sentence(doc, {}) == "Nothing has run yet. Target: accuracy 80%."
    doc = running_doc(id="smoke", backend="modal", state="starting", step=None, total=None, metric=None, eta="")
    assert sp.now_sentence(doc, {}) == "Starting on Modal. No results yet. Target: accuracy 80%."
    doc["runs"][0]["state"] = "queued"
    assert sp.now_sentence(doc, {}).startswith("Waiting to start on Modal.")
    one = sp.now_sentence(running_doc(step=0, eta=""), {"val": [(0, 0.544)]})
    assert one == ("Training on Lightning AI (T4): started 10:00 UTC. Accuracy is 54% at the start; "
                   "the target is 80%.")                              # step 0 before any training is not "0% done"


def test_now_sentence_for_a_min_metric():
    goal = {"text": "Lower the loss", "metric": "loss", "target": 0.3, "direction": "min"}
    doc = sp.new_status(goal, BUDGET)
    doc["runs"] = [{**RUN, "backend": "local", "eta": ""}]
    assert sp.now_sentence(doc, {"train": [(0, 2.31), (145, 0.42)]}) == (
        "Training on this computer: 50% done. Loss went from 2.31 to 0.42; the target is 0.30 or lower.")
    doc["runs"][0]["state"] = "done"
    doc["best"] = {"value": 0.25, "run": "quick", "at": ""}
    assert sp.now_sentence(doc, {"train": [(0, 2.31), (290, 0.25)]}).endswith(
        "Loss went from 2.31 to 0.25; the target of 0.30 or lower is reached.")


def test_now_sentence_failed_stopped_and_close_values():
    failed = sp.now_sentence(running_doc(state="failed", detail="failed: CUDA out of memory"), {"val": VAL})
    assert failed.startswith("The last run failed on Lightning AI (T4): CUDA out of memory. Accuracy went")
    stopped = sp.now_sentence(running_doc(state="stopped", detail="stopped (time limit)"), {"val": VAL})
    assert stopped.startswith("The last run stopped on Lightning AI (T4) at 50% done.")
    close = sp.now_sentence(running_doc(), {"val": [(0, 0.544), (145, 0.795)]})
    assert "to 79.5%; the target is 80.0%" in close             # one decimal when whole numbers would collide


def test_target_bar_positions():
    width = lambda h: float(re.search(r'class="bar-fill" style="width:([\d.]+)%"', h).group(1))
    assert width(sp._render_target_bar(0.544, 0.758, 0.8, "max", percent=True)) == pytest.approx(83.6, abs=0.1)
    assert width(sp._render_target_bar(2.0, 1.0, 0.5, "min")) == pytest.approx(66.7, abs=0.1)
    assert width(sp._render_target_bar(None, 0.4, 0.8, "max", percent=True)) == pytest.approx(50.0)
    assert width(sp._render_target_bar(0.544, 0.85, 0.8, "max", percent=True)) == 100.0
    assert width(sp._render_target_bar(0.544, 0.5, 0.8, "max", percent=True)) == 0.0
    bar = sp._render_target_bar(0.544, 0.758, 0.8, "max", percent=True)
    assert "Start 54%" in bar and "Target 80%" in bar and "76%" in bar and "of the way" in bar
    assert "Target reached" in sp._render_target_bar(2.0, 0.2, 0.5, "min")
    empty = sp._render_target_bar(0.544, None, 0.8, "max", percent=True)
    assert width(empty) == 0.0 and "No result yet" in empty


def write_metrics(lab, rid, rows):
    d = lab / "runs" / rid
    d.mkdir(parents=True, exist_ok=True)
    (d / "metrics.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def trial_rows(last=145, total=290):
    rows = [{"t": "x", "step": 0, "total": total, "split": s, "name": n, "value": v}
            for s in ("test", "val") for n, v in (("accuracy", 0.544), ("ece", 0.21))]
    rows += [{"t": "x", "step": s, "total": total, "split": "train", "name": "loss", "value": 4.3 / (1 + s / 20)}
             for s in range(1, last + 1)]
    rows += [{"t": "x", "step": last, "total": total, "split": "val", "name": n, "value": v}
             for n, v in (("accuracy", 0.758), ("ece", 0.06))]
    return rows


def test_refresh_only_while_a_run_is_active(tmp_path):
    lab = tmp_path / "lab"
    for state, refresh in (("queued", True), ("starting", True), ("running", True), ("done", False),
                           ("failed", False), ("stopped", False)):
        write(lab, running_doc(state=state))
        assert ('<meta http-equiv="refresh" content="30">' in sp.render(lab)) is refresh, state
    write(lab, sp.new_status(GOAL, BUDGET))
    assert "http-equiv" not in sp.render(lab)


def test_details_are_collapsed_and_hold_the_technical_parts(tmp_path):
    lab = tmp_path / "lab"
    doc = running_doc()
    doc["decisions"] = [{"title": "Try a bigger GPU?", "text": "L4 is faster", "rec": "yes"}]
    doc["events"] = [{"t": "2026-10-01T10:00:00+00:00", "text": "run quick started"}]
    write(lab, doc)
    write_metrics(lab, "quick", trial_rows())
    html = sp.render(lab)
    details = re.search(r"<details[^>]*>.*?</details>", html, re.S).group(0)
    assert re.match(r'<details class="details">', details)            # closed: no `open` attribute
    for part in ('class="runs"', 'class="decisions"', 'class="events"', "Try a bigger GPU?", "run quick started"):
        assert part in details
    assert "how far the model's confidence is from its real accuracy" in details  # ECE explained
    assert "1 decision is waiting for you" in html.split("<details")[0]           # but flagged up top


def test_full_page_order_charts_and_no_urls(tmp_path):
    lab = tmp_path / "lab"
    doc = running_doc()
    doc["stages"] = STAGES
    doc["best"] = {"value": 0.758, "run": "quick", "at": "2026-10-01T10:08:00+00:00"}
    doc["budget"] = {"usd_limit": 5, "usd_spent": 0.12, "free_credit_note": "Lightning free credit", "usd_free": 5}
    write(lab, doc)
    write_metrics(lab, "quick", trial_rows(last=600, total=600))
    write_results(lab, HEADER + "e1	a1b2c3d	lightning	T4	9.5	0.781	keep	baseline\n")
    html = sp.render(lab)
    order = [html.index(k) for k in ('class="now"', 'class="progress', 'class="charts"', 'class="card plan"',
                                     'class="card cost"', "<details")]
    assert order == sorted(order)
    assert "Training on Lightning AI (T4)" in html and "about 4 min left" in html
    loss = re.search(r'<figure class="chart-card" data-chart="loss">.*?</figure>', html, re.S).group(0)
    raw = re.search(r'<polyline data-series="loss" points="([^"]+)"', loss).group(1).split()
    assert 2 <= len(raw) <= sp.MAX_POINTS                              # long series are downsampled
    assert ">Loss<" in loss and 'data-chart="experiments"' in html
    assert "$0.12" in html and "free credit" in html.lower()
    assert "http://" not in html and "https://" not in html and not NAN.search(html)


@pytest.mark.parametrize("case", ["no runs", "no metrics yet", "smoke only", "min direction", "bad rows"])
def test_edge_labs_render_sensibly(tmp_path, case):
    lab = tmp_path / "lab"
    goal = GOAL
    doc = sp.new_status(goal, BUDGET)
    rows = None
    if case == "no metrics yet":
        doc = running_doc(state="starting", step=None, total=None, metric=None, eta="")
    elif case == "smoke only":
        doc = running_doc(id="smoke", state="done", step=50, total=50, eta="")
        rows = [{"t": "x", "step": s, "total": 50, "split": sp_, "name": "accuracy", "value": v}
                for s, v in ((0, 0.5), (50, 0.6)) for sp_ in ("val", "test")]
    elif case == "min direction":
        goal = {"text": "Lower the loss", "metric": "loss", "target": 0.3, "direction": "min"}
        doc = sp.new_status(goal, BUDGET)
        doc["runs"] = [{**RUN, "backend": "local"}]
        rows = [{"t": "x", "step": s, "total": 290, "split": "train", "name": "loss", "value": 2.3 / (1 + s)}
                for s in range(0, 146)]
    elif case == "bad rows":
        doc = running_doc()
        rows = [[1, 2], {"step": "x", "value": 1}, {"step": 1, "split": "val", "name": "accuracy", "value": None},
                {"step": 2, "split": "val", "name": "accuracy", "value": 0.6}]
    write(lab, doc)
    if rows is not None:
        write_metrics(lab, doc["runs"][0]["id"], rows)
    html = sp.render(lab)
    assert not NAN.search(html) and "None" not in html and 'class="now"' in html
    if case == "min direction":
        assert "Loss went from 2.30 to" in html and "or lower" in html
        assert 'data-chart="loss"' not in html                         # the metric chart already is the loss


def test_old_status_json_files_still_render(tmp_path):
    lab = tmp_path / "lab"
    doc = {"version": 1, "updated": "2026-09-28T10:00:00+00:00", "goal": GOAL,  # 0.1.0: no stages
           "best": {"value": 0.61, "run": "r1", "at": "2026-09-28T10:05:00+00:00"},
           "runs": [{"id": "r1", "backend": "modal", "state": "done", "step": 10, "total": 10, "metric": 0.61,
                     "eta": "", "detail": "done", "started": "2026-09-28T10:00:00+00:00"}],
           "budget": {"usd_limit": 0, "usd_spent": 0.0, "free_credit_note": "Modal $30/month"},
           "decisions": [], "events": [{"t": "2026-09-28T10:00:00+00:00", "text": "started"}]}
    write(lab, doc)
    html = sp.render(lab)
    assert "Finished on Modal. Accuracy is 61%; the target of 80% is not reached." in html
    write(lab, {**doc, "stages": STAGES})  # 0.2.0
    assert "stage-running" in sp.render(lab)


def test_percent_only_for_accuracy_like_metrics():
    assert sp._percent_metric("accuracy", "max", [0.5, 0.8])
    assert not sp._percent_metric("loss", "min", [0.2, 0.5])
    assert not sp._percent_metric("accuracy", "max", [0.5, 80.0])     # already in percent units
    assert not sp._percent_metric("bleu", "max", [12.0, 30.0])


def test_container_column_can_shrink_on_phones(tmp_path):
    # an implicit auto grid column grows to the widest table when Details opens; minmax(0, 1fr) keeps phone width
    assert "grid-template-columns: minmax(0, 1fr)" in sp._CSS


# --- the live trial (0.3.2): one split for before and after, no fake progress, training health ---

def trial_split_rows():
    """The quick start as the trial logged it: val accuracy 53% -> 81%, test accuracy 54% -> 83%."""
    acc = [("val", 0, 0.5333), ("val", 145, 0.7229), ("val", 290, 0.8052), ("test", 0, 0.544), ("test", 290, 0.8283)]
    rows = [{"t": "x", "step": s, "total": 290, "split": sp_, "name": "accuracy", "value": v} for sp_, s, v in acc]
    rows += [{"t": "x", "step": s, "total": 290, "split": "train", "name": "loss", "value": 4.3 / (1 + s / 20)}
             for s in range(1, 291)]
    return rows


def test_before_and_after_come_from_the_same_split(tmp_path):
    lab = tmp_path / "lab"
    doc = running_doc(state="done", step=290, eta="", detail="done")
    doc["best"] = {"value": 0.8283, "run": "quick", "at": "2026-10-01T10:15:00+00:00"}
    write(lab, doc)
    write_metrics(lab, "quick", trial_split_rows())
    html = sp.render(lab)
    now = re.search(r'<p class="now">(.*?)</p>', html).group(1)
    assert "from 54% to 83%" in now and "53%" not in now
    bar = re.search(r'<section class="card progress">.*?</section>', html, re.S).group(0)
    assert "Start 54%" in bar and "53%" not in bar
    fig = re.search(r'<figure class="chart-card" data-chart="metric">.*?</figure>', html, re.S).group(0)
    assert "start 54%" in fig and "start 53%" not in fig
    series = sp._metric_series(trial_split_rows(), "accuracy")
    assert "from 54% to 83%" in sp.now_sentence(doc, series)


def test_no_went_from_without_a_start_on_the_same_split():
    doc = running_doc(state="done", step=290, eta="", detail="done")
    doc["best"] = {"value": 0.8283, "run": "quick", "at": ""}
    series = {"val": [(0, 0.5333), (290, 0.8052)], "test": [(290, 0.8283)]}  # test scored only at the end
    sentence = sp.now_sentence(doc, series)
    assert "went from" not in sentence and "53%" not in sentence and "83%" in sentence


def test_no_fake_progress_before_the_first_numbers(tmp_path):
    lab = tmp_path / "lab"
    doc = running_doc(backend="kaggle T4", step=0, total=290, metric=None, eta="12 min",
                      started="2026-10-01T10:05:00+00:00")
    write(lab, doc)
    assert sp.now_sentence(doc, {}) == ("Training on Kaggle (T4): started 10:05 UTC, about 12 min left. "
                                        "No results yet. Target: accuracy 80%.")
    html = sp.render(lab)
    assert "0% done" not in html and "step 0 of 290" not in html
    time = re.search(r'<section class="card time">.*?</section>', html, re.S).group(0)
    assert 'class="bar meter"' not in time and "started 10:05 UTC" in time
    progress = re.search(r'<section class="card progress">.*?</section>', html, re.S).group(0)
    assert ">0%<" not in progress and "No result yet" in progress
    none = running_doc(step=None, total=290, metric=None, eta="", started="")
    assert sp.now_sentence(none, {}) == "Training on Lightning AI (T4). No results yet. Target: accuracy 80%."
    write_metrics(lab, "quick", trial_rows(last=20))                  # once it trains, the step counts again
    assert "Training on Lightning AI (T4): 0% done" not in sp.render(lab)


def health_rows(loss, val=(), test=(), total=None):
    """Train loss at steps 1..n, and (step, value) evaluations of accuracy on val and test."""
    total = total or len(loss)
    rows = [{"t": "x", "step": i + 1, "total": total, "split": "train", "name": "loss", "value": v}
            for i, v in enumerate(loss)]
    rows += [{"t": "x", "step": s, "total": total, "split": sp_, "name": "accuracy", "value": v}
             for sp_, points in (("val", val), ("test", test)) for s, v in points]
    return rows


def test_training_health_still_improving():
    loss = [4.3 / (1 + s / 20) for s in range(1, 291)]
    h = sp.training_health(health_rows(loss, val=[(0, 0.5333), (145, 0.7229), (290, 0.8052)],
                                       test=[(0, 0.544), (290, 0.8283)]))
    assert h["state"] == "improving" and h["verdict"] == "Still improving"
    assert "72.3%" in h["reason"] and "80.5%" in h["reason"] and "loss" in h["reason"]
    assert "more training would likely help" in h["hint"].lower()


def test_training_health_plateaued():
    loss = [0.41 + 0.01 * ((-1) ** s) for s in range(300)]          # noisy but flat
    h = sp.training_health(health_rows(loss, val=[(0, 0.5), (100, 0.805), (200, 0.806), (300, 0.8055)]))
    assert h["state"] == "plateau" and h["verdict"] == "Plateaued"
    assert "80.6%" in h["reason"] or "80.5%" in h["reason"]
    assert "won't" in h["hint"] and "change" in h["hint"]


def test_training_health_levelling_off():
    loss = [1.0 - 0.0005 * s for s in range(300)]                    # about 3.5% down in the last 20%
    h = sp.training_health(health_rows(loss, val=[(0, 0.5), (150, 0.80), (300, 0.805)]))
    assert h["state"] == "levelling" and h["verdict"] == "Levelling off"


def test_training_health_held_out_score_decides_over_the_loss():
    loss = [4.3 / (1 + s / 20) for s in range(1, 291)]               # the loss is still falling clearly
    h = sp.training_health(health_rows(loss, val=[(0, 0.53), (145, 0.80), (290, 0.801)]))
    assert h["state"] == "levelling" and h["verdict"] == "Levelling off"   # but the held-out score is flat
    assert h["reason"].startswith("the gains are small:") and "still falling" in h["reason"]
    flat_loss = [0.41 + 0.01 * ((-1) ** s) for s in range(290)]
    h = sp.training_health(health_rows(flat_loss, val=[(0, 0.53), (145, 0.80), (290, 0.801)]))
    assert h["state"] == "plateau"                                   # flat score and a flat loss


def test_training_health_for_a_min_metric_and_a_falling_val():
    loss = [0.41 + 0.001 * ((-1) ** s) for s in range(200)]
    rows = health_rows(loss)
    rows += [{"t": "x", "step": s, "total": 200, "split": "val", "name": "error", "value": v}
             for s, v in ((0, 0.5), (100, 0.30), (200, 0.20))]
    h = sp.training_health(rows, metric="error", direction="min")
    assert h["state"] == "improving" and "30.0%" in h["reason"] and "20.0%" in h["reason"]
    worse = sp.training_health(health_rows([4.3 / (1 + s / 20) for s in range(1, 291)],
                                           val=[(0, 0.5), (145, 0.80), (290, 0.75)]))
    assert worse["state"] != "improving"                            # val fell: more of the same won't help


def test_training_health_needs_enough_data_and_survives_nan():
    assert sp.training_health([]) is None
    assert sp.training_health(health_rows([1.0] * 5, val=[(0, 0.5), (5, 0.6)])) is None    # too few loss points
    assert sp.training_health(health_rows([4.3 / (1 + s) for s in range(50)])) is None      # no evaluation
    loss = [float("nan")] * 40 + [4.3 / (1 + s / 20) for s in range(1, 291)] + [float("inf")]
    rows = health_rows(loss, val=[(0, 0.5), (145, float("nan")), (200, 0.7), (290, 0.8)])
    rows += [{"step": None, "split": "train", "name": "loss", "value": 1}, {"value": "x"}, [1]]
    h = sp.training_health(rows)
    assert h is not None and not NAN.search(h["reason"] + h["hint"])
    assert sp.training_health(health_rows([float("nan")] * 50, val=[(0, 0.5), (50, 0.6)])) is None


def test_training_health_card_follows_the_charts(tmp_path):
    lab = tmp_path / "lab"
    doc = running_doc(state="done", step=290, eta="", detail="done")
    doc["stages"] = STAGES
    doc["best"] = {"value": 0.8283, "run": "quick", "at": ""}
    write(lab, doc)
    write_metrics(lab, "quick", trial_split_rows() + [
        {"t": "x", "step": s, "total": 290, "split": sp_, "name": "ece", "value": v}
        for sp_, s, v in (("val", 0, 0.21), ("val", 290, 0.05), ("test", 0, 0.2), ("test", 290, 0.04))])
    html = sp.render(lab)
    order = [html.index(k) for k in ('class="charts', 'class="card health"', 'class="card plan"')]
    assert order == sorted(order)
    card = re.search(r'<section class="card health"[^>]*>.*?</section>', html, re.S).group(0)
    assert "Still improving" in card and "<svg" in card and 'data-series="trend"' in card
    assert 'data-series="loss"' in card and "Moving average" in card
    table = re.search(r"<table.*?</table>", card, re.S).group(0)
    for text in (">145<", ">290<", "72.3%", "82.8%", "ECE", "0.05"):
        assert text in table
    assert html.count('data-chart="loss"') == 1                     # the loss chart moved into the card
    glossary = re.search(r'<section class="glossary">.*?</section>', html, re.S).group(0)
    assert "Plateau" in glossary and "how wrong the model still is on its training examples" in glossary
    assert not NAN.search(html) and "http://" not in html and "https://" not in html


def test_training_health_hidden_with_little_data(tmp_path):
    lab = tmp_path / "lab"
    write(lab, running_doc())
    write_metrics(lab, "quick", health_rows([4.3, 3.9, 3.5], val=[(0, 0.5)]))
    assert 'class="card health"' not in sp.render(lab)
    write(lab, {k: v for k, v in running_doc().items() if k != "stages"})   # 0.1.0 shape
    write_metrics(lab, "quick", trial_split_rows())
    assert 'class="card health"' in sp.render(lab)


# --- building blocks, layout, refresh and the provider link (freelab 0.4.0) ---

def test_default_layout_is_the_page_and_a_layout_reorders_it(tmp_path):
    lab = tmp_path / "lab"
    doc = running_doc()
    doc["stages"] = STAGES
    write(lab, doc)
    write_metrics(lab, "quick", trial_rows())
    default = sp.render(lab)
    doc["layout"] = list(sp.DEFAULT_LAYOUT)
    write(lab, doc)
    assert sp.render(lab) == default
    doc["layout"] = ["plan", "headline", "no-such-block", "events"]
    write(lab, doc)
    html = sp.render(lab)
    assert html.index('class="card plan"') < html.index('class="now"') < html.index('class="events"')
    assert 'class="card progress"' not in html and "<details" not in html and "no-such-block" not in html
    assert '<div class="card block"><section class="events">' in html and "<footer>" in html


def test_custom_block_is_inlined_without_scripts(tmp_path):
    lab = tmp_path / "lab"
    doc = running_doc()
    doc["layout"] = ["headline", "custom:samples", "custom:missing", "custom:../status"]
    write(lab, doc)
    (lab / "blocks").mkdir()
    (lab / "blocks" / "samples.html").write_text(
        '<h2>Samples</h2><p>hello</p><script>alert(1)</script><SCRIPT src="x.js"></SCRIPT><p>after</p><script>bad(')
    html = sp.render(lab)
    block = re.search(r'<section class="card custom" data-block="samples">(.*?)</section>', html, re.S).group(1)
    assert "<h2>Samples</h2><p>hello</p>" in block and "<p>after</p>" in block
    assert "script" not in block.lower() and "alert" not in html
    assert html.count('class="card custom"') == 1


@pytest.mark.parametrize("text, kept, gone", [
    ('<img src="a.png" onerror="alert(1)">', '<img src="a.png">', "onerror"),
    ("<div ONCLICK='x()' class=\"c\">hi</div>", '<div class="c">hi</div>', "ONCLICK"),
    ('<a href="javascript:alert(1)">x</a>', '<a href="#alert(1)">x</a>', "javascript:"),
    ('<p>a</p><iframe src="https://evil.example"></iframe><p>b</p>', "<p>a</p><p>b</p>", "iframe"),
    ('<object data="x.swf"></object><embed src="x.swf"><p>ok</p>', "<p>ok</p>", "swf"),
    ("<p>onboard = on time; javascript: is a word here</p>", "<p>onboard = on time; javascript: is a word here</p>",
     None),
])
def test_strip_scripts_is_a_basic_filter(text, kept, gone):
    out = sp.strip_scripts(text)
    assert kept in out
    if gone:
        assert gone not in out


@pytest.mark.parametrize("seconds, label", [(30, "30 s"), (90, "90 s"), (60, "1 min"), (300, "5 min"),
                                            (900, "15 min")])
def test_refresh_seconds_sets_the_reload_and_its_label(tmp_path, seconds, label):
    lab = tmp_path / "lab"
    doc = running_doc()
    doc["refresh_seconds"] = seconds
    write(lab, doc)
    html = sp.render(lab)
    assert f'<meta http-equiv="refresh" content="{seconds}">' in html
    assert f"Live · reloads every {label}<" in html


def test_provider_link_in_the_header_and_the_runs_table(tmp_path):
    lab = tmp_path / "lab"
    doc = running_doc(backend="modal L4", link="https://modal.com/apps/me/main/ap-1?a=1&b=2")
    write(lab, doc)
    html = sp.render(lab)
    top = html.split("</header>")[0]
    assert ('<a class="run-link btn" href="https://modal.com/apps/me/main/ap-1?a=1&amp;b=2" target="_blank" '
            'rel="noopener">Open on Modal') in top
    runs = re.search(r'<section class="runs">.*?</section>', html, re.S).group(0)
    assert "<th>Provider page</th>" in runs and 'rel="noopener">Open on Modal' in runs
    doc = running_doc(backend="kaggle T4", link="https://www.kaggle.com/code/alice/freelab-quick")
    write(lab, doc)
    assert ">Open on Kaggle<" in sp.render(lab)
    write(lab, running_doc())
    body = sp.render(lab).split("</style>")[1]
    assert "Provider page" not in body and "run-link" not in body


@pytest.mark.parametrize("mutate, key", [
    (lambda d: d["runs"][0].update(link="javascript:alert(1)"), "link"),
    (lambda d: d["runs"][0].update(link='https://x.io/"><script>'), "link"),
    (lambda d: d["runs"][0].update(link="https://"), "link"),
    (lambda d: d["runs"][0].update(expected_minutes=-5), "expected_minutes"),
    (lambda d: d["runs"][0].update(colour="red"), "colour"),
    (lambda d: d.update(layout="headline"), "layout"),
    (lambda d: d.update(layout=["headline", 3]), "layout"),
    (lambda d: d.update(refresh_seconds=1), "refresh_seconds"),
    (lambda d: d.update(refresh_seconds="30"), "refresh_seconds"),
])
def test_validate_checks_the_new_optional_keys(mutate, key):
    doc = running_doc()
    mutate(doc)
    with pytest.raises(ValueError, match=key):
        sp.validate(doc)


def test_new_optional_keys_validate():
    doc = running_doc(link="https://lightning.ai/org/ts/jobs/quick", expected_minutes=15)
    doc.update(layout=["headline", "custom:x"], refresh_seconds=90)
    sp.validate(doc)


def test_event_command_adds_event_under_lock_and_renders(tmp_path, monkeypatch):
    lab = tmp_path / "lab"
    doc = sp.new_status(GOAL, BUDGET)
    doc["events"] = [{"t": "2026-10-01T10:00:00+00:00", "text": f"old {i}"} for i in range(sp.EVENTS_CAP)]
    write(lab, doc)
    monkeypatch.chdir(tmp_path)
    sp.main(["event", "--lab", "lab", "research loop started"])
    out = json.loads((lab / "status.json").read_text())
    assert out["events"][0]["text"] == "research loop started" and out["events"][0]["t"] == out["updated"]
    assert out["events"][1]["text"] == "old 0" and len(out["events"]) == sp.EVENTS_CAP   # capped, newest first
    assert "research loop started" in (lab / "status.html").read_text()
    assert (lab / ".status.lock").exists() and not (lab / "status.json.tmp").exists()
    sp.validate(out)


def test_event_command_waits_for_the_poll_lock(tmp_path):
    import fcntl, subprocess, sys, time
    lab = tmp_path / "lab"
    write(lab, sp.new_status(GOAL, BUDGET))
    script = str(__import__("pathlib").Path(sp.__file__))
    with (lab / ".status.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        proc = subprocess.Popen([sys.executable, script, "event", "--lab", str(lab), "while locked"])
        time.sleep(0.5)
        assert proc.poll() is None and json.loads((lab / "status.json").read_text())["events"] == []
        fcntl.flock(lock, fcntl.LOCK_UN)
    assert proc.wait(timeout=20) == 0
    assert json.loads((lab / "status.json").read_text())["events"][0]["text"] == "while locked"


def test_event_command_exit_2_on_bad_status_or_empty_text(tmp_path):
    lab = tmp_path / "lab"; lab.mkdir()
    (lab / "status.json").write_text("{}")
    with pytest.raises(SystemExit) as e: sp.main(["event", "--lab", str(lab), "x"])
    assert e.value.code == 2
    write(lab, sp.new_status(GOAL, BUDGET))
    with pytest.raises(SystemExit) as e: sp.main(["event", "--lab", str(lab), "   "])
    assert e.value.code == 2


def test_render_invocation_still_works_with_the_lab_as_the_only_argument(tmp_path):
    write(tmp_path / "lab", sp.new_status(GOAL, BUDGET))
    sp.main([str(tmp_path / "lab")])
    assert (tmp_path / "lab" / "status.html").exists()


def test_trim_keeps_research_loop_events():
    loop = [{"t": "t", "text": "research loop started"}, {"t": "t", "text": "Research loop ended: target met"}]
    events = [{"t": "t", "text": f"e{i}"} for i in range(70)]
    events[60:60] = [loop[1]]
    events.append(loop[0])   # the oldest
    sp.trim_events(events)
    assert len(events) == sp.EVENTS_CAP
    assert events[-1] == loop[0] and loop[1] in events
    assert [e["text"] for e in events[:3]] == ["e0", "e1", "e2"]   # the newest stay, the oldest others go
    short = [{"t": "t", "text": "x"}]
    sp.trim_events(short)
    assert short == [{"t": "t", "text": "x"}]


def test_event_command_keeps_the_loop_start_past_the_cap(tmp_path):
    lab = tmp_path / "lab"
    write(lab, sp.new_status(GOAL, BUDGET))
    sp.main(["event", "--lab", str(lab), "research loop started"])
    for i in range(sp.EVENTS_CAP + 10):
        sp.main(["event", "--lab", str(lab), f"exp-{i} discarded"])
    events = json.loads((lab / "status.json").read_text())["events"]
    assert len(events) == sp.EVENTS_CAP and events[-1]["text"] == "research loop started"


@pytest.mark.parametrize("key,value,check", [
    ("best", '{"value": 0.86, "run": "exp-02", "at": "2026-10-02T10:00:00+00:00"}',
     lambda d: d["best"]["run"] == "exp-02"),
    ("best", "null", lambda d: d["best"] is None),
    ("budget.usd_spent", "0.42", lambda d: d["budget"]["usd_spent"] == 0.42 and d["budget"]["usd_limit"] == 1.0),
    ("budget.free_credit_note", '"USD 30 credit"', lambda d: d["budget"]["free_credit_note"] == "USD 30 credit"),
    ("stages", '[{"name": "baseline", "state": "done", "detail": "0.81"}]', lambda d: d["stages"][0]["state"] == "done"),
    ("decisions", '[{"title": "Train longer?", "text": "Validation still rises.", "rec": "Yes"}]',
     lambda d: d["decisions"][0]["title"] == "Train longer?"),
    ("goal", '{"text": "Beat 0.85", "metric": "accuracy", "target": 0.85, "direction": "max"}',
     lambda d: d["goal"]["target"] == 0.85),
    ("layout", '["headline", "runs"]', lambda d: d["layout"] == ["headline", "runs"]),
    ("refresh_seconds", "90", lambda d: d["refresh_seconds"] == 90),
])
def test_set_command_sets_one_field_under_lock_and_renders(tmp_path, key, value, check):
    lab = tmp_path / "lab"
    doc = sp.new_status(GOAL, {"usd_limit": 1.0, "usd_spent": 0.0})
    doc["updated"] = "2026-10-01T10:00:00+00:00"
    write(lab, doc)
    sp.main(["set", "--lab", str(lab), key, value])
    out = json.loads((lab / "status.json").read_text())
    assert check(out) and out["updated"] != "2026-10-01T10:00:00+00:00"
    assert (lab / "status.html").exists() and (lab / ".status.lock").exists()
    assert not (lab / "status.json.tmp").exists()
    sp.validate(out)


@pytest.mark.parametrize("key,value", [
    ("runs", "[]"),                      # the poll owns runs
    ("events", "[]"),                    # events go through `event`
    ("version", "2"),
    ("best.value", "0.9"),               # only budget takes a dotted path
    ("budget.a.b", "1"),
    ("budget.usd_spent", '"a lot"'),     # dollars are numbers
    ("budget.usd_spent", "-1"),
    ("goal", '{"text": "x"}'),           # the validator refuses it
    ("stages", '[{"name": "a", "state": "maybe", "detail": ""}]'),
    ("refresh_seconds", "1"),
    ("best", '{"value": 1}'),
    ("decisions", "not json"),
])
def test_set_command_refuses_bad_keys_and_values_and_writes_nothing(tmp_path, key, value):
    lab = tmp_path / "lab"
    write(lab, sp.new_status(GOAL, BUDGET))
    before = (lab / "status.json").read_text()
    with pytest.raises(SystemExit) as e:
        sp.main(["set", "--lab", str(lab), key, value])
    assert e.value.code == 2
    assert (lab / "status.json").read_text() == before


def test_set_command_waits_for_the_poll_lock(tmp_path):
    import fcntl, subprocess, sys, time
    lab = tmp_path / "lab"
    write(lab, sp.new_status(GOAL, BUDGET))
    script = str(__import__("pathlib").Path(sp.__file__))
    with (lab / ".status.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        proc = subprocess.Popen([sys.executable, script, "set", "--lab", str(lab), "budget.usd_spent", "0.25"])
        time.sleep(0.5)
        assert proc.poll() is None
        fcntl.flock(lock, fcntl.LOCK_UN)
    assert proc.wait(timeout=20) == 0
    assert json.loads((lab / "status.json").read_text())["budget"]["usd_spent"] == 0.25
