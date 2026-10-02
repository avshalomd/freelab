# Plan: bank-support intent routing

## Stage 1: fine-tune on Modal
- **Goal:** accuracy after the default 2 epochs.
- **Decision it feeds:** fine-tune or keep zero-shot.
- **Need:** one L4, 0.2 hours
- **Placement:** Modal
- **Estimate:** 10 minutes, USD 0.12
- **Go/no-go:** ship the fine-tuned model if accuracy >= 0.80; otherwise report and stop.
- **Command:** `modal run`, run id `full-modal`
