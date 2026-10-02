"""Banking77 helpers for the quick start: seeded sampling, 10-way candidate sets and metrics. Standard library only."""
from __future__ import annotations
import random


def per_class_sample(rows: list[dict], k: int, seed: int) -> list[dict]:
    """k rows per `label` (fewer if a class has fewer), chosen with `seed`, in input order within each class."""
    by_label: dict[int, list[int]] = {}
    for i, r in enumerate(rows):
        by_label.setdefault(r["label"], []).append(i)
    rng = random.Random(seed)
    keep = set()
    for label in sorted(by_label):
        idx = by_label[label]
        keep.update(rng.sample(idx, min(k, len(idx))))
    return [rows[i] for i in sorted(keep)]


def holdout(rows: list[dict], taken: list[dict], k: int, seed: int) -> list[dict]:
    """k rows per `label` from `rows` not in `taken` (matched by `id`), chosen with `seed`: a validation split
    disjoint from the training sample. A class with fewer spare rows gives what it has."""
    used = {r["id"] for r in taken}
    return per_class_sample([r for r in rows if r["id"] not in used], k, seed)


def candidates(gold: int, n_labels: int, k: int, seed: int, item_id: str) -> list[int]:
    """gold plus k - 1 other labels, shuffled; the same for a given (seed, item_id)."""
    rng = random.Random(f"{seed}:{item_id}")
    out = [gold] + rng.sample([l for l in range(n_labels) if l != gold], k - 1)
    rng.shuffle(out)
    return out


def accuracy(pred: list[int], gold: list[int]) -> float:
    return sum(p == g for p, g in zip(pred, gold)) / len(gold)


def ece(probs: list[list[float]], gold: list[int], bins: int = 10) -> float:
    """Expected calibration error of the top probability over equal-width bins (the first bin includes 0)."""
    total, n = 0.0, len(gold)
    groups: dict[int, list[tuple[float, bool]]] = {}
    for p, g in zip(probs, gold):
        conf = max(p)
        b = min(bins - 1, max(0, int(conf * bins - 1e-12)))
        groups.setdefault(b, []).append((conf, p.index(conf) == g))
    for items in groups.values():
        conf = sum(c for c, _ in items) / len(items)
        acc = sum(ok for _, ok in items) / len(items)
        total += len(items) / n * abs(conf - acc)
    return total


PROGRESS_EVERY = 25  # optimiser steps between progress lines


def progress_line(step: int, total: int, loss: float, elapsed_s: float) -> str:
    """One progress line for the job log, e.g. `step 50/290 (17%), loss 1.23, 2.1 min`."""
    pct = 100 * step // total if total else 0
    return f"step {step}/{total} ({pct}%), loss {loss:.2f}, {elapsed_s / 60:.1f} min"


def should_print_progress(step: int, total: int) -> bool:
    """The first step (the run is alive), every PROGRESS_EVERY steps, and the last."""
    return step == 1 or step % PROGRESS_EVERY == 0 or step == total


def eval_line(split: str, accuracy: float, step: int) -> str:
    """One line after an evaluation, e.g. `eval val accuracy 0.758 at step 145`."""
    return f"eval {split} accuracy {accuracy:.3f} at step {step}"
