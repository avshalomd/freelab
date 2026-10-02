"""freelab statistics: the Wilson score interval for a proportion (an accuracy measured on n items), so the
report's interval is computed, not worked out by hand.

    python3 scripts/stats.py wilson P N     prints `lo hi` (4 decimals), e.g. `wilson 0.8 3076` -> 0.7855 0.8138
"""
from __future__ import annotations
import argparse, math, sys


def wilson(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """The Wilson score interval (default 95 %, z = 1.96) for an observed proportion p over n items."""
    if n <= 0:
        raise ValueError(f"n must be a positive count, got {n}")
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"p must be a proportion between 0 and 1, got {p}")
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="stats.py", description="freelab statistics")
    sub = ap.add_subparsers(dest="command", required=True)
    w = sub.add_parser("wilson", help="Wilson score interval for proportion P over N items; prints `lo hi`")
    w.add_argument("p", type=float, help="observed proportion, 0..1 (e.g. accuracy 0.8)")
    w.add_argument("n", type=int, help="number of items it was measured on")
    w.add_argument("--z", type=float, default=1.96, help="z for the confidence level (default 1.96 = 95 %%)")
    args = ap.parse_args(argv)
    try:
        lo, hi = wilson(args.p, args.n, args.z)
    except ValueError as e:
        print(f"stats.py: {e}", file=sys.stderr)
        return 2
    print(f"{lo:.4f} {hi:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
