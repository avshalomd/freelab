# Charter: <short name>

- **Goal:** <one sentence>
- **Decision it feeds:** <what we will do differently depending on the result>
- **Metric:** <name>, computed as <how, on which split and how many items>
- **Target:** <metric> >= or <= <number>, e.g. `accuracy >= 0.80`
- **Validation:** <the split decisions are made on, and its size; the test split is scored once, at the end>
- **Baseline:** <what is measured, how and where, e.g. the unchanged model on the same test items at step 0>
- **Data:** <source>, licence <licence>, splits <train / validation / test and sizes>
- **Budget:** $<USD beyond free credit, default 0> and <wall-clock hours>
- **Allowed compute:** <any of: this machine, Modal, Lightning AI, Kaggle>
- **Decision GPU type:** <one GPU type for the baseline and every keep or discard; default: the GPU type the first
  run used, so that run can be the baseline>
- **Editable surface:** <what experiments may change, e.g. `train.py`>
- **Frozen:** <what no experiment touches: data loading, evaluation, the test split>
- **Per-experiment budget:** <minutes per experiment, passed as `--max-minutes`: the baseline's minutes on the
  decision GPU type (model and data downloads count) plus 2 (runlib stops a run 2 minutes before
  `--max-minutes`), with some headroom>
- **Stop rules:** <e.g. the target is met on validation; the budget or free credit is spent; K non-improving
  experiments in a row (default 8)>
- **Out of scope:** <what this lab will not try>

A filled-in example: `${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya/charter.md`.
