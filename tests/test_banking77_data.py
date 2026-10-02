import data
ROWS = [{"text": f"t{i}", "label": i % 5} for i in range(100)]
def test_per_class_sample_deterministic():
    a = data.per_class_sample(ROWS, 3, 1); b = data.per_class_sample(ROWS, 3, 1)
    assert a == b and len(a) == 15 and all(sum(r["label"] == c for r in a) == 3 for c in range(5))
def test_candidates_contain_gold_once():
    c = data.candidates(7, 77, 10, 1, "x1")
    assert len(c) == 10 and c.count(7) == 1 and len(set(c)) == 10 and c == data.candidates(7, 77, 10, 1, "x1")
def test_metrics():
    assert data.accuracy([1, 2, 3], [1, 2, 0]) == 2 / 3
    assert data.ece([[1.0, 0.0]], [0]) == 0.0
ID_ROWS = [{"id": f"r{i}", "text": f"t{i}", "label": i % 5} for i in range(100)] + \
          [{"id": f"s{i}", "text": f"s{i}", "label": 5} for i in range(4)]  # a short class: 4 messages
def test_holdout_is_disjoint_per_class_and_deterministic():
    train = data.per_class_sample(ID_ROWS, 3, 1)
    val = data.holdout(ID_ROWS, train, 2, 2)
    assert val == data.holdout(ID_ROWS, train, 2, 2)
    assert not {r["id"] for r in val} & {r["id"] for r in train}
    assert all(sum(r["label"] == c for r in val) == 2 for c in range(5))
    assert sum(r["label"] == 5 for r in val) == 1  # 4 messages, 3 taken for training: the one left
def test_progress_line_format():
    assert data.progress_line(50, 290, 1.234, 126) == "step 50/290 (17%), loss 1.23, 2.1 min"
    assert data.progress_line(1, 290, 2.0, 3) == "step 1/290 (0%), loss 2.00, 0.1 min"
    assert data.progress_line(290, 290, 0.01, 510) == "step 290/290 (100%), loss 0.01, 8.5 min"
    assert data.progress_line(0, 0, 1.0, 0) == "step 0/0 (0%), loss 1.00, 0.0 min"  # no division by zero
def test_eval_line_format():
    assert data.eval_line("val", 0.7584, 145) == "eval val accuracy 0.758 at step 145"
    assert data.eval_line("test", 0.822, 290) == "eval test accuracy 0.822 at step 290"
def test_should_print_progress():
    shown = [s for s in range(1, 291) if data.should_print_progress(s, 290)]
    assert shown[0] == 1 and shown[-1] == 290 and 25 in shown and 50 in shown and 26 not in shown
    assert all(b - a <= 25 for a, b in zip(shown, shown[1:]))
