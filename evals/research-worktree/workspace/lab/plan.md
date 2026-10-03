# Plan: research loop

## Stage 1: baseline (earlier run quick-1)
- **Goal:** the unchanged experiment on a T4.
- **Decision it feeds:** the number every experiment must beat.
- **Need:** 0 GB (done)
- **Placement:** Kaggle (T4)
- **Estimate:** done, $0
- **Go/no-go:** done: `lab/runs/quick-1/status.txt` reads `done`.

## Stage 2: the research loop
- **Goal:** keep or discard one change per experiment until a stop rule holds.
- **Decision it feeds:** whether the fine-tune can reach 0.85 on validation.
- **Need:** one T4 at a time, up to 15 minutes per experiment
- **Placement:** Kaggle (T4)
- **Estimate:** about 12-16 minutes of experiments, plus a scoring run of about 12-14 if one wins, $0
- **Go/no-go:** stop at the target, after 2 experiments, or when the next experiment's estimate would end after 25 minutes.
