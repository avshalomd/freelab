# Plan: bank-support intent routing

## Stage 1: fine-tune on this machine
- **Goal:** accuracy after the default epochs.
- **Decision it feeds:** fine-tune or keep zero-shot.
- **Need:** 4 GB RAM, 0 GB GPU memory, 1 hour
- **Placement:** this machine, night window
- **Estimate:** 1 hour, $0
- **Go/no-go:** ship the fine-tuned model if accuracy >= 0.80; otherwise run stage 2.
- **Command:** `local_run.py experiments/banking77-laya --run-id full-local -- --epochs 2`

## Stage 2: lower learning rate
- **Goal:** accuracy with the encoder learning rate halved.
- **Decision it feeds:** whether a gentler fit closes the gap to the target.
- **Need:** 4 GB RAM, 0 GB GPU memory, 1 hour
- **Placement:** this machine, night window
- **Estimate:** 1 hour, $0
- **Go/no-go:** run only if stage 1 ends under 0.80.
