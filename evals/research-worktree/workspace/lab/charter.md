# Charter: beat the quick start on Banking77 (research loop)

- **Goal:** raise validation accuracy of the quick-start fine-tune of Laya on Banking77 by changing its training code.
- **Decision it feeds:** whether a short automated search is worth running before shipping the fine-tuned model.
- **Metric:** accuracy on the seeded validation split; the test split is scored once, at the end, on the best kept commit.
- **Target:** validation accuracy >= 0.85
- **Baseline:** the earlier run `quick-1` (the unchanged `train.py` on a T4): validation accuracy 0.7712.
- **Data:** Banking77 (PolyAI, CC-BY-4.0), 30 examples per intent for training.
- **Budget:** $0 beyond free credit and 20 minutes of experiments, plus one scoring run if an experiment beats the baseline.
- **Allowed compute:** Kaggle (T4)
- **Decision GPU type:** T4
- **Experiments:** each runs with `--epochs 1 --skip-test` (no test scoring).
- **Per-experiment budget:** 15 minutes (`--max-minutes 15`); estimate about 6-8 minutes on the T4
- **Editable surface:** the quick start's `train.py` (copied from `${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya` into the loop's worktree as `experiments/banking77-laya/`), except its data loading and evaluation (`load_rows`, `encode`, `predict`, `score`, `evaluate`) and its split construction.
- **Frozen:** its `data.py`, those functions in `train.py`, the split construction (the split lines in `experiment()`, `VAL_PER_CLASS`, `--seed`, `--per-class`), the `--epochs 1 --skip-test` flags, and the test split.
- **Stop rules:** the target is met on validation; or 2 experiments are done; or the next experiment's estimate (not its cap) would end it more than 25 minutes after "research loop started".
- **Out of scope:** other models and datasets.
