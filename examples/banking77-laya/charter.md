# Charter: Laya × Banking77 (the freelab quick start)

- **Goal:** find out how much a small open decision model gains on bank-support intent routing from a few minutes
  of fine-tuning on 30 examples per intent. One run, about 10-17 minutes end to end on a free GPU, depending on the
  provider (Budget).
- **Decision it feeds:** whether fine-tuning a small typed-decision model is worth it for a routing task.
- **Metric:** accuracy on the Banking77 test split (3,076 messages): the share whose top-probability option is the
  gold intent. Expected calibration error (10 equal-width bins over the top probability) is logged beside it.
  Validation accuracy is logged per epoch; the headline number is accuracy on the whole test split, measured once
  at the end of the single run. This run chooses nothing on the test split, so scoring it once is honest (see the caveat).
- **Target:** test accuracy >= 0.80, in the all-77 framing (one choice over every intent) that `train.py` picks
  when the whole sequence fits the model's 512 tokens for 99 % of test items; it did for 100 %. If it ever fell
  back to the 10-way framing (chance 10 %), 0.80 would not be comparable and the report would say so.
- **Validation:** the seeded validation split (up to 10 unused training messages per intent, disjoint from the
  training sample; the exact count is `val_items` in `summary.json`), scored at step 0 and after every epoch.
  Per-epoch and keep/discard decisions use it; the test split is scored once, at the end.
- **Baseline:** zero-shot accuracy of the unchanged checkpoint in the same framing, measured by `train.py` at step 0
  on a seeded 500-item sample of the test split. The gain compares those same 500 items after training.
- **Data:** Banking77 (PolyAI, CC-BY-4.0), read from the `mteb/banking77` parquet mirror at a pinned revision.
  Train: 30 seeded examples per intent (2,310), 2 epochs by default. Validation: up to 10 unused training
  messages per intent, seeded and disjoint from the training sample (the exact count is `val_items` in
  `summary.json`); scored at step 0 and after every epoch, and used for per-epoch and keep/discard decisions.
  Test: the official test split (3,076) for the final number, scored once at the end; a seeded 500-item sample
  of it for the zero-shot baseline, which keeps the run short.
- **Budget:** $0 beyond free credit: at most about $0.30 and 30 minutes of wall clock for the quick start;
  `--max-minutes 20` caps the run. Measured end to end, the full run (the per-provider numbers live here only; the
  skills and READMEs give at most the overall range and point to this list):
  - **Lightning AI (T4):** about 15 minutes, about $0.25 at about $0.90 per T4 hour: machine setup 1.7 minutes,
    install and load about 1, 2 epochs (290 steps) about 8.5, final evaluation and checkpoint about 2.5.
  - **Kaggle (T4):** about 17 minutes, $0: training about 9.3 minutes, the final test scoring about 6.
  - **Modal (L4):** 8.7 minutes for the default 2 epochs (0.1.0), about $0.16 at Modal's list prices: the L4
    about $0.12 (0.80 an hour × 8.7 / 60) plus CPU and memory about $0.05 (about 0.32 an hour); about 10 minutes with 3
    epochs (the third trial).
  - **This machine** (Apple M4 Pro, MPS, `--epochs 1`): 9.4 minutes, $0.
  - **One more epoch** (a Train longer round): about half of the 2-epoch run's training minutes, plus setup and
    the final test scoring; on Kaggle about 4.7 + 6 minutes plus setup, about 12-15 minutes in all.
  - **A research-loop experiment** ("Next: try to beat it": `--epochs 1 --skip-test`, no test scoring), an
    estimate not yet measured: about 4-5 minutes on Modal's L4, about 6-8 on a T4 (Kaggle, Lightning AI). The
    loop's final scoring run, only when an experiment beat the baseline (the same flags without `--skip-test`),
    about 6-7 minutes on the L4 and 12-14 on a T4 (also an estimate).
- **Allowed compute:** all: this machine, Modal, Lightning AI, Kaggle.
- **Decision GPU type:** the GPU type the quick-start run used (Modal's L4; a T4 on Kaggle and Lightning AI), so a
  research loop can reuse that run as its baseline. Every keep or discard compares runs on it; other backends only
  add parallel candidates on the same type.
- **Editable surface:** `train.py`, except its data loading and evaluation (`load_rows`, `encode`, `predict`,
  `score`, `evaluate`). Only a research loop edits it; the single run uses it as it is.
- **Frozen:** `data.py`, those functions in `train.py`, and the test split.
- **Stop rules:** the 2 epochs are done, or the 20 minutes are spent. The result is reported as measured, even
  when it lands under the target.
- **Out of scope:** for the single run, tuning hyperparameters (the depth and the learning rates were picked
  once, on a test sample; see the README) and training the whole encoder (only Laya's head and the top 12
  encoder layers are trained); a research loop may change these within the editable surface. Always: other
  models, refitting calibration temperatures, the multilingual checkpoint.
- **Caveat:** The depth and learning rates were chosen in 0.1.0 on 400 test items, before the validation split
  existed, so the 0.80 on test is not fully clean; later changes are judged on validation.

## Next: try to beat it

One of the next steps offered after the report (with trying the model, training longer, and cleaning up). A short
research loop (the `research` skill) on the same task, on its own fields, about 15-20 minutes in all (an estimate,
not yet measured; Budget above):

- **Target:** validation accuracy >= 0.85; the test split is scored once, at the end, on the best kept commit.
- **Baseline:** the quick-start run itself (its validation accuracy, on its GPU type): no new baseline run. Its
  test number was already seen once and is not scored again.
- **Experiments:** each runs with `--epochs 1 --skip-test`: half the baseline's training and no test scoring, so
  it is short and never sees the test split. A change is kept only when its validation accuracy beats the
  2-epoch baseline in that one epoch. This bias is deliberate: it can discard a change that would help at 2
  epochs, but it never keeps one that does not beat the baseline.
- **Per-experiment budget:** `--max-minutes 15` (the Modal app's `--minutes 15`), on the decision GPU type; a run
  that does not finish within it counts as a crash.
- **Stop rules:** the target is met on validation; or 2 experiments are done; or 20 minutes have passed since
  "research loop started" (no experiment starts that would end after them).
- **The test number:** when the baseline stays the best, it is the quick-start run's test number. When an
  experiment beat it, one scoring run relaunches the best kept commit with the same flags without `--skip-test`
  (run id `<experiment id>-test`, `--max-minutes 20`), and its test accuracy, read once, is the result.
- **Budget:** about 20 minutes of experiments plus the scoring run when one is needed, $0 beyond free credit.
- **Editable surface:** `train.py`, except its data loading and evaluation (`load_rows`, `encode`, `predict`,
  `score`, `evaluate`); it may change the depth and learning rates the single run keeps fixed.
- **Frozen:** `data.py`, those functions in `train.py`, the `--epochs 1 --skip-test` flags, and the test split.
