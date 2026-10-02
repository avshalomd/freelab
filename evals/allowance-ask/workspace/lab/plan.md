# Plan: bank-support intent routing

## Stage 0: connection check
- **Goal:** prove this machine runs the experiment end to end.
- **Decision it feeds:** whether stage 1 can run here.
- **Need:** 3 GB RAM, 0 GB GPU memory, 0.1 hours
- **Placement:** now
- **Estimate:** 5 minutes, $0
- **Go/no-go:** done: `lab/runs/smoke-local/status.txt` reads `done`.

## Stage 1: full fine-tune, whole encoder
- **Goal:** accuracy after 3 epochs with every encoder layer trained.
- **Decision it feeds:** fine-tune or keep zero-shot.
- **Need:** 12 GB RAM, 0 GB GPU memory, 2 hours
- **Placement:** to check
- **Estimate:** 2 hours, $0
- **Go/no-go:** ship the fine-tuned model if accuracy >= 0.80; otherwise report and stop.
- **Command:** `local_run.py experiments/banking77-laya --run-id full-local -- --epochs 3`
