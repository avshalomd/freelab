import ledger
def test_total_prefers_actuals(tmp_path):
    lab = tmp_path / "lab"
    ledger.add(lab, "modal", "r1", 0.50, "estimate")
    ledger.add(lab, "modal", "r1", 0.31, "actual")
    ledger.add(lab, "modal", "r2", 0.20, "estimate")
    assert abs(ledger.total(lab) - 0.51) < 1e-9
def test_rejects_bad_kind(tmp_path):
    import pytest
    with pytest.raises(ValueError): ledger.add(tmp_path, "modal", "r", 1.0, "guess")

def test_total_zero_actual_beats_nonzero_estimate(tmp_path):
    # A $0.00 actual (normal on a free compute tier) must still count as "this run has an
    # actual" -- it must not fall back to the earlier, nonzero estimate.
    lab = tmp_path / "lab"
    ledger.add(lab, "modal", "r1", 0.50, "estimate")
    ledger.add(lab, "modal", "r1", 0.0, "actual")
    assert ledger.total(lab) == 0.0
