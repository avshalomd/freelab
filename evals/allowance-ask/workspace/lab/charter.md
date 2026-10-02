# Charter: bank-support intent routing

- **Goal:** find out how much fine-tuning lifts a small open model on bank-support intents.
- **Decision it feeds:** whether to fine-tune a small model for ticket routing or keep zero-shot.
- **Metric:** accuracy on the Banking77 test split (3,076 messages).
- **Target:** accuracy >= 0.80
- **Baseline:** zero-shot accuracy of the unchanged model on the same items, measured at step 0.
- **Data:** Banking77 (PolyAI, CC-BY-4.0), 30 examples per intent for training, the official test split.
- **Budget:** $0 beyond free credit and 4 wall-clock hours
- **Allowed compute:** this machine, Modal
- **Stop rules:** the target is met; three epochs are done; the budget is spent.
- **Out of scope:** hyperparameter tuning, other models.

The experiment is this project's own copy of the quick start, `experiments/banking77-laya/`: it is copied here
because this lab changes it (`train.py` follows the freelab run contract).
