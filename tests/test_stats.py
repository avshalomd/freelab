import subprocess, sys
from pathlib import Path
import pytest, stats

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "stats.py"


@pytest.mark.parametrize("p,n,lo,hi", [
    (0.5, 100, 0.4038, 0.5962),     # textbook value
    (0.6, 5, 0.2307, 0.8824),       # small n
    (0.8, 3076, 0.7855, 0.8138),    # the quick start's test split
    (0.0, 10, 0.0, 0.2775),         # p = 0: upper bound z^2 / (n + z^2)
    (1.0, 10, 0.7225, 1.0),         # p = 1: mirror image
    (1.0, 1, 0.2065, 1.0),          # n = 1
])
def test_wilson_known_values(p, n, lo, hi):
    got = stats.wilson(p, n)
    assert got == pytest.approx((lo, hi), abs=6e-5)
    assert 0.0 <= got[0] <= p <= got[1] <= 1.0


def test_wilson_is_symmetric_and_narrows_with_n():
    lo, hi = stats.wilson(0.3, 50)
    assert stats.wilson(0.7, 50) == pytest.approx((1 - hi, 1 - lo))
    assert (lambda a: a[1] - a[0])(stats.wilson(0.3, 500)) < hi - lo


def test_z_sets_the_level():
    assert stats.wilson(0.5, 100, z=2.576)[0] < stats.wilson(0.5, 100)[0]


@pytest.mark.parametrize("p,n", [(0.5, 0), (1.2, 10), (-0.1, 10)])
def test_bad_input_raises(p, n):
    with pytest.raises(ValueError):
        stats.wilson(p, n)


def test_cli_prints_lo_hi():
    r = subprocess.run([sys.executable, str(SCRIPT), "wilson", "0.8", "3076"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "0.7855 0.8138\n"


def test_cli_bad_n_exits_2():
    r = subprocess.run([sys.executable, str(SCRIPT), "wilson", "0.8", "0"], capture_output=True, text=True)
    assert r.returncode == 2 and "n must be" in r.stderr and r.stdout == ""
