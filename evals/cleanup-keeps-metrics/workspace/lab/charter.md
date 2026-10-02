# Charter: Laya on Banking77, two learning rates

- **Goal:** compare two learning rates for the quick start's fine-tuning on this machine.
- **Decision it feeds:** which learning rate the next experiments use.
- **Metric:** test accuracy on the Banking77 test split.
- **Target:** test accuracy >= 0.80
- **Baseline:** zero-shot accuracy at step 0 (0.517 on the 500-item sample).
- **Data:** Banking77, 30 examples per intent, the official test split.
- **Budget:** $0; 3 hours of this machine.
- **Allowed compute:** this machine.
- **Stop rules:** the three runs are done.
- **Out of scope:** other models and datasets.

The experiment is this project's own copy of the quick start, `experiments/banking77-laya/`: it is copied here
because this lab changes its learning rates.
