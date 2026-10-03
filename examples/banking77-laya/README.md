# Quick start: Laya × Banking77

Fine-tune [Laya](https://github.com/NandhaKishorM/laya), an open 421M-parameter typed-decision model
(ModernBERT-large and a decision head that scores one `[MASK]` per option), on 77 bank-support intents.

It has two jobs:

- **Smoke run (`--smoke`), a connection check for each backend:** 50 training steps on 200 items, training only
  the top 2 encoder layers, then evaluation on 200 test items. It proves that the model downloads, the GPU and
  precision work, `metrics.jsonl` and checkpoints are written, and the outputs can be fetched. The smoke never
  stops, so it does not prove resume; resume was verified separately on this machine (CPU and MPS).
- **Full run, the quick start: one run, about 10-17 minutes end to end on a free GPU:** zero-shot evaluation on a seeded sample of 500 test messages and on
  a seeded validation split (up to 10 unused training messages per intent), then 2 epochs (the default) on 30
  examples per intent, scoring validation after every epoch (what keep/discard decisions use), then a single
  evaluation on the whole 3,076-message test split at the end. It reached 0.828 on Kaggle (T4) and 0.822 on
  Modal (L4), meeting the charter's 0.80 target, and 0.767 on this machine with `--epochs 1`. The measured time
  and cost per provider, with the stage breakdowns, are in [charter.md](charter.md), **Budget** (the one list
  freelab keeps).

The goal, metric and target are in [charter.md](charter.md).

## What it does

- `train.py` follows the freelab run contract (`--out`, `--resume`, `--max-minutes`, `--smoke`) and adds
  `--framing {auto,all,10way}`, `--epochs 2`, `--per-class 30`, `--seed 20260928` and `--device auto`, plus
  `--init-from PATH` and `--lr-scale X` to [train longer](#train-longer-from-the-trained-weights), and
  `--skip-test` for a research loop's experiments and Train longer rounds: the test split is not loaded at all
  (neither the step-0 sample nor the final pass), so the run is shorter and never reads a test item;
  `summary.json` then has no test fields.
- It prints one progress line to stdout at least every 25 optimiser steps and after each evaluation, so a cloud
  job's log never looks stuck: `step 50/290 (17%), loss 1.23, 2.1 min` and `eval val accuracy 0.758 at step 145`.
  The lines come from `progress_line` and `eval_line` in `data.py`; `metrics.jsonl` is unchanged.
- The device is chosen automatically: CUDA, then Apple MPS, then CPU. A local GPU allowance of 0 means CPU.
- Each message is one choice question: "Which customer-support intent does this bank message express?".
- **Framing:** `auto` asks one question over all 77 intents (chance 1.3 %) when the whole sequence, with no
  option cut, fits Laya's 512 tokens for 99 % of the training sample's items (it never looks at test items);
  otherwise it falls back to **10-way**, where each message gets a fixed, seeded set of the gold intent plus 9
  others (chance 10 %). `summary.json` records the choice and the measured fit.
  - **Measured:** all-77 fitted 100 % of test items when 0.4.0 still measured it there, so `auto` picks
    **all-77**.
  - Laya cuts the option section to a budget of 192 tokens (`head_max_len`), which would leave each of the 77
    intents 4 tokens (73 distinct names of 77). The head attends over the whole sequence, so for all-77 this
    example lifts that budget and keeps every option whole (up to Laya's 48 tokens each): 342 tokens of options.
  - That option section is longer than anything Laya's head saw in training, so its zero-shot accuracy here may
    sit below the published 42.5 %.
- **Training:** Laya's head and the top 12 encoder layers (about 173M of 421M parameters); the embeddings and
  the lower 16 layers stay frozen. 2 epochs by default (290 steps); the Mac alternative uses `--epochs 1` (145
  steps) to stay near 10 minutes. AdamW (encoder layers 2e-4, head 1e-3, warm-up then linear decay) and
  cross-entropy over the option markers. Micro-batches of 4 with accumulation to 16; one step is one optimiser
  update. fp16 autocast on CUDA, fp32 on MPS and CPU.
  - **Why these settings (measured on an M4 Pro):** with the top 4 layers trained, the model could not even
    memorise 32 items in 30 steps (loss 2.72 → 1.63), and a 52-minute, 3-epoch CPU run moved test accuracy only
    from 0.55 to 0.58. The fit improves steadily with depth: loss 1.30 with 6 layers, 0.73 with 8 and 0.003 with
    12. After one epoch, on a 400-item test sample: 8 layers at 1e-4 / 5e-4 reached 0.67; 12 layers reached
    0.79 at the same rates and 0.80 at 2e-4 / 1e-3.
- **Evaluation:** a full pass over the test split takes about 3.4 minutes on MPS, so the zero-shot pass scores
  a seeded 500-item sample (fixed by `--seed`) to keep the run short; the test split's final pass
  (the whole official split) happens once, at the end. A validation split (up to 10 unused training messages
  per intent, seeded with `--seed + 1` and disjoint from the training sample; the exact count is `val_items` in
  `summary.json`, since the smallest intents may have fewer than 10 spare messages) is scored at step 0 and
  after every epoch, and is what per-epoch and keep/discard decisions use. ECE is computed at Laya's shipped
  temperature for 77 options (0.5), before and after training: the trained model is not recalibrated, so its
  ECE is reported at that zero-shot temperature. In `summary.json`:
  - on the 500-item test sample: `zero_shot_accuracy`, `final_accuracy_on_zero_shot_items`, `gain_points`,
    `ece_before` and `ece_after` (the "after" figures come from the final pass, with no extra pass);
  - on the whole test split, scored once at the end: `final_accuracy` and `final_ece`;
  - on the validation split: `zero_shot_val_accuracy` (step 0), `final_val_accuracy` and `final_val_ece` (the
    last epoch scored), `val_items` (its size) and `val_ids_sha` (the first 16 hex digits of the sha256 of its
    sorted item ids: a research loop keeps a change only when it matches the baseline's);
  - `zero_shot_items` and `final_items` give the test counts; `torch`, `transformers` and `device_name` the
    library versions and the GPU or device the run used.

  The smoke scores its 200 test items both times, and `SMOKE_VAL_ITEMS` (50) seeded validation items both times.
- **Checkpoints:** every 200 steps, at the end of each epoch, and when the run is stopped (SIGTERM or the
  deadline). A checkpoint holds the trained tensors and the optimiser state, about 2.1 GB (about 0.6 GB for the
  smoke, which trains 2 layers); the frozen rest comes from the pinned download. The number of trained layers is
  part of the flags a `--resume` must match. While the run goes, the newest two complete checkpoints are kept,
  so a stopped or failed run can resume; once it finishes, only the final one is kept (one 2.1 GB folder, not
  two, for the fetch).
- The model (`convaiinnovations/laya`) and the dataset (`mteb/banking77`) are downloaded at run time, each
  pinned to a revision. `laya_head.py` rebuilds Laya's head from its source rather than importing the `laya`
  package, because that package rewrites files in the Hugging Face cache when it loads.

## Train longer from the trained weights

The final checkpoint can be the start of a longer run. `--resume` only continues a stopped run with the same
flags, and a finished run's learning rate has already decayed to zero, so use a warm start instead:

```bash
python train.py --out runs/longer --init-from runs/ID/ckpt/step-00000290 --epochs 1 --lr-scale 0.5 --skip-test
```

The agent runs each round with `--skip-test` and compares rounds on validation; the chosen round alone is then
rerun once without it (run id `<round id>-test`) to score the test split.

- `--init-from PATH` takes a checkpoint folder (`.../ckpt/step-NNNNNNNN`, with its `COMPLETE` marker) or its
  `state.pt`. It loads only the trained tensors, then trains `--epochs N` more with a fresh optimiser and a fresh
  warm-up and decay. Give it a new `--out`; a PATH inside `--out` is refused.
- `--lr-scale X` multiplies both learning rates (default 1.0). Use 0.5 for a warm start: the weights are already
  trained, and the full rates can undo some of it.
- The data split, seeds and evaluation are unchanged, so the numbers stay comparable. Step 0 now scores the
  starting weights: in that run's `summary.json`, `zero_shot_*` and `gain_points` are relative to them, not to
  the untrained checkpoint. `summary.json` and every checkpoint's `meta.json` record `init_from` and `lr_scale`.
- The warm-started run is itself resumable: relaunch the same command with `--resume` (the launchers add it
  themselves). `--init-from` and `--lr-scale` are part of the flags it must match, and a different `--init-from`
  is refused. Its own checkpoints hold every trained tensor, so a resume does not read PATH again.
- A missing or torn checkpoint, a file that is not a `train.py` checkpoint, or tensors this run does not train
  (for example a full run's checkpoint into `--smoke`, which trains 2 layers) exit with code 2.
- On a cloud backend, the checkpoint has to be there too: upload it with the run (on Kaggle, as a Dataset
  attached to the kernel) and pass its path there.

## Try the trained model

`demo.py` serves the trained model on this machine, on `127.0.0.1` only. It needs the run's final checkpoint
locally (fetch `runs/ID/ckpt/step-00000290/`, about 2.1 GB):

```bash
cd examples/banking77-laya
uv run --no-project --with-requirements requirements.txt python demo.py --ckpt ../../lab/runs/ID/ckpt/step-00000290
```

Then open <http://127.0.0.1:8077> (`--port` changes it). Type a bank customer message, or click an example, and
the page shows the top 5 of the 77 intents with their probabilities. The same is available as JSON:

```bash
curl -s http://127.0.0.1:8077/api/classify -H 'Content-Type: application/json' \
  -d '{"text": "Where is my new card?", "top_k": 3}'
```

- It loads the pinned Laya checkpoint plus the trained tensors and asks each message the way `train.py` scores
  it: one choice over all 77 intents, with the same instruction, through `train.encode` and `train.predict`.
  The intent names come from the same pinned `mteb/banking77` revision.
- The device is chosen like `train.py`'s: CUDA, then Apple MPS, then CPU. On the page's first load the model
  is already in memory; the first start downloads the model (about 1.7 GB) and the dataset.
- `--base` runs it without trained tensors, for a quick check before a run has finished. The page says clearly
  that this model is untrained.
- The page loads nothing from the internet and follows the system's light or dark theme.

## Timings

The measured time and cost per provider, with the stage breakdowns (machine setup, install and load, training,
the final test scoring), are in [charter.md](charter.md), **Budget**: freelab keeps them there only.

On Kaggle (T4, 2 epochs): zero-shot 0.544 → final 0.828 on the whole test split; validation 0.533 → 0.723
(epoch 1) → 0.805 (epoch 2); ECE 0.29 → 0.10 (both at Laya's zero-shot temperature, 0.5). Every provider stays within the quick start's cap of
`--max-minutes 20` and about $0.30 of free credit.

## Run it

Ask the agent: "run the quick start's connection check on Modal" (or Lightning AI, Kaggle), or "run the quick
start on Lightning AI" for the full run (one run, timed per provider in the charter's **Budget**, then the report; afterwards it offers the
next steps: try the trained model on this machine, train longer, "try to beat it" (a short research loop
towards validation accuracy 0.85, about 10-17 minutes on Modal's L4), or clean up and stop). It follows each service's steps with that service's own CLI, from
[`skills/compute/references/`](../../skills/compute/references/) (`<modal|lightning|kaggle>.md`), gives you the
run's page on the provider, and keeps the status page current while the run goes.

On this machine, from a clone of the freelab repo (replace `ID` with a run id of your choice). `local_run.py`
runs `train.py` with the Python that runs it; `uv run` builds that environment from the requirements:

```bash
uv run --with-requirements examples/banking77-laya/requirements.txt \
  python scripts/backends/local_run.py examples/banking77-laya --run-id ID --when now -- --smoke
```

For a full run, leave out `-- --smoke`. On Modal (L4) it reached 0.822; on this machine, with `--epochs 1`
through `local_run.py`, 0.767 (the times: [charter.md](charter.md), **Budget**; a 20-minute cap gives headroom).

**Memory on this machine.** Measured on an Apple M4 Pro with MPS, fp32:
- The process RSS stays under 2 GB.
- Its physical footprint, which includes the GPU's share of the unified memory, peaks at 10.0 GB.
- A GPU allowance of 8 GB ran out of memory during training (MPS allocated 8.1 GiB against a 7.8 GiB cap). 12
  GB works.
- The smoke is lighter: 1.8 GB RSS and a 5.8 GB physical footprint at its peak, so an 8 GB GPU allowance fits.
- On CPU the run is much slower: one pass over the test split alone takes about 6.5 minutes.

## Expected smoke output

The run directory holds:

- `status.txt`: `done`.
- `metrics.jsonl`: `accuracy` and `ece` on the split `test` at step 0 (zero-shot) and at step 50, on the split
  `val` at step 0 and at step 50, and the training `loss` at every step. In a full run the step-0 test point is
  on the 500-item sample, the test point at the end is on the whole split (scored once), and the `val` points
  are on the validation split, at step 0 and after every epoch.
- `ckpt/step-00000050/`: `state.pt` (about 0.6 GB), `meta.json` and the `COMPLETE` marker.
- `summary.json`, like this one from Modal on an L4 (the numbers vary a little by backend; this run predates
  the validation split, so it has no `*_val_*` fields — a current run adds `zero_shot_val_accuracy`,
  `final_val_accuracy`, `final_val_ece` and `val_items`):

```json
{"framing": "all", "framing_reason": "the all-77 sequence, no option cut, fits max_len 512 for 100.0% of test
 items (all-77 needs 99%); its option section is 342 tokens, ...", "zero_shot_accuracy": 0.53,
 "zero_shot_items": 200, "final_accuracy": 0.535, "final_ece": 0.318, "final_items": 200, "final_accuracy_on_zero_shot_items": 0.535,
 "gain_points": 0.5, "ece_before": 0.335, "ece_after": 0.318, "minutes": 0.95, "device": "cuda"}
```

50 smoke steps on the top 2 layers prove the plumbing, not the method: accuracy barely moves, and mostly the
ECE drops. It took 0.95 minutes of experiment time (`summary.json`'s `minutes`) on Modal once the
image was built (an Apple M4 Pro through `local_run.py` took 1.7 minutes).

The exit code is 0 when the run is done, and 3 when it was stopped and can resume with `--resume`.

## Full-run results

Measured runs. Zero-shot is on the seeded 500-item sample; final accuracy is on the whole 3,076-item test split;
the gain compares the same 500 items before and after. Minutes and cost per provider: [charter.md](charter.md),
**Budget**.

| Backend | GPU | Epochs | Framing | Zero-shot accuracy | Final accuracy (95 % interval) | Gain (points) | ECE |
|---|---|---|---|---|---|---|---|
| Kaggle | T4 | 2 (default) | all-77 | 0.544 | 0.828 (0.814–0.841) | — | 0.29 (500-item sample, before) → 0.10 (full 3,076, after) |
| Modal | L4 | 2 (default) | all-77 | 0.544 | 0.822 (0.808–0.835) | +28.2 (0.544 → 0.826) | 0.295 (500-item sample, before) → 0.113 (full 3,076, after) |
| This machine, `local_run.py` | Apple M4 Pro, MPS | 1 (`--epochs 1`) | all-77 | 0.544 | 0.767 (0.752–0.782) | +23.8 (0.544 → 0.782) | 0.295 (500-item sample, before) → 0.140 (full 3,076, after) |

One run per backend, one seed. ECE before and after is at Laya's zero-shot temperature (0.5); the trained model
is not recalibrated.

The charter's target is 0.80. The Kaggle run met it at 0.828 and the Modal run at 0.822; the Mac's one-epoch
alternative landed 3.3 points under it. All stand as measured. On Kaggle the validation accuracy rose from
0.533 to 0.723 after epoch 1 and 0.805 after epoch 2, and the loss was still falling:
[train longer](#train-longer-from-the-trained-weights) continues from there.

The depth and learning rates were chosen in 0.1.0 on 400 test items, before the validation split existed;
later changes are judged on validation.

After the report the quick start offers next steps: try the trained model (`demo.py`, above), train longer in
rounds of one epoch from the final checkpoint (`--init-from`, `--lr-scale 0.5`, until a round no longer
improves validation; each round with `--skip-test`, the chosen one scored on test once), clean up, or "try to
beat it": a short research loop on the same task, target validation accuracy >= 0.85, about 10 minutes on Modal's
L4, about 17 when an experiment wins and the test split gets its one scoring run (an estimate, not yet measured).
It reuses the quick-start run as its baseline, runs at most 2 experiments of one epoch each with `--skip-test`,
and scores the test split once at the end; $0 beyond free credit. Its fields are in the charter's "Next" section.

## Credits

- **Laya** by Convai Innovations ([GitHub](https://github.com/NandhaKishorM/laya),
  [Hugging Face](https://huggingface.co/convaiinnovations/laya)), Apache-2.0. `laya_head.py` is adapted from
  its `laya/common.py` and `laya/agent.py`, keeps the Apache-2.0 notice and is under that licence
  ([LICENSE-APACHE-2.0](LICENSE-APACHE-2.0)); the rest of freelab is MIT.
- **Banking77** by PolyAI (Casanueva et al., 2020, "Efficient Intent Detection with Dual Sentence Encoders"),
  CC-BY-4.0, read from the [`mteb/banking77`](https://huggingface.co/datasets/mteb/banking77) parquet mirror.
