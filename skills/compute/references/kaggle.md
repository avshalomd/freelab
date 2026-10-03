# Kaggle

Free GPU hours with no card. You drive it with the `kaggle` CLI: the code travels as a private Dataset, and each
run is a private GPU script kernel. Keys: `lab` rule 1 (through `${CLAUDE_PLUGIN_ROOT}/scripts/withenv`). Below, KAGGLE_USERNAME is the
user's Kaggle user name: ask for it once (it is not a secret) and write it into the JSON files; never read it from
`.env`.

Contents: Free tier · Onboarding (0 Signed in already?, 3 Key, 4 CLI and quota) · Connection check · Launch (1 the
code Dataset, 2 the kernel folder, 3 push, 4 the run's link and the poll; the accelerator) · Watch, fetch, stop
(the poll and its live log, the small files, the checkpoint) · Move in / out (Warm start, Preemption) · Cost
model · Clean up · Gotchas

## Free tier

- A weekly GPU quota, "30 hours or sometimes higher depending on demand and resources"
  (https://www.kaggle.com/docs/efficient-gpu-usage, checked 2026-09-28): about 130 hours a month.
- A GPU session runs at most 12 hours and keeps up to 20 GB in `/kaggle/working`
  (https://www.kaggle.com/docs/notebooks, checked 2026-09-28). In busy times a run may queue.
- No card, nothing billed. **Phone:** a verified phone is needed for GPUs and internet (Kaggle forum answers, e.g.
  https://www.kaggle.com/product-feedback/268333, checked 2026-09-28; the docs do not say it).
- The GPU is a T4 pair ("GPU T4 ×2"), not a P100, which the default image's PyTorch cannot use
  (https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md and issue #1196, checked 2026-09-28).

## Onboarding

0. **Signed in already?**
   `${CLAUDE_PLUGIN_ROOT}/scripts/withenv kaggle quota >/dev/null 2>&1 && echo yes || echo no`
   (it prints only yes or no; signed out, the CLI exits 1). A missing `kaggle` CLI means no.
1. **Sign up** at https://www.kaggle.com.
2. **Phone:** the human verifies it under Settings → Phone verification. No card, so no spending cap is needed.
3. **Key:** Settings (https://www.kaggle.com/settings) → API → "Generate New Token"; it starts with `KGAT`
   (https://www.kaggle.com/docs/mcp, checked 2026-09-28). When driving the browser, stop here: the human presses
   "Generate New Token" and copies it. You add this line to the project's `.env` with an empty value (`onboard`
   step 5f), and the human pastes the value:

   ```
   KAGGLE_API_TOKEN=KGAT...
   ```

   With this token the user name is not needed in `.env`: it is not a secret (ask for it once, see the top). A
   legacy key ("Create Legacy API Key") goes in as `KAGGLE_USERNAME` + `KAGGLE_KEY`. The CLI reads every
   `KAGGLE_*` variable from the environment (kaggle 2.2.4 source). The alternative, which needs no `.env`: you
   run `kaggle auth login` yourself once the CLI is installed (Bash `run_in_background`; `~/.local/bin/kaggle` if
   it is not on PATH): it opens a browser tab where the human signs in (to verify live: whether it also asks for
   a code to paste; if it waits for typed input, stop it and use the `.env` key).
4. **CLI:** `uv tool install kaggle` (these steps checked against kaggle 2.2.4). Quota left:
   `${CLAUDE_PLUGIN_ROOT}/scripts/withenv kaggle quota` (no arguments; `--format json` for JSON).
5. **Official skill/plugin:** none found for Claude Code (the `kaggle` skill on skills.sh says it is unofficial).
   Kaggle runs an official remote MCP server, https://www.kaggle.com/mcp (https://www.kaggle.com/docs/mcp, checked
   2026-09-28); freelab does not need it, so do not offer it. If the user asks for it, it is added as a custom
   connector with that URL in the app's connector settings.

## Connection check

The quick start's smoke: EXP is `${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya` (Dataset `freelab-banking77-laya`),
run id `smoke-kaggle-<YYYYMMDD>`, `ARGS = ["--max-minutes", "20", "--smoke"]`, push timeout 1800 s. Follow Launch,
then fetch. It passes when `status.txt` reads `done` and `metrics.jsonl` holds `val` and `test` accuracy at step 0
and step 50. Record which accelerator value worked.

## Launch

Below, SLUG is EXP's folder name (its basename, e.g. `banking77-laya`), lowercased, with any character other than
a letter, a digit or `-` replaced by `-`; EXP itself is a path and never goes into a Kaggle name.

1. **Code as a private Dataset.** Stage `lab/backends/kaggle-data-SLUG/`: a copy of EXP without `__pycache__`,
   `lab`, `.venv`, `.git` and `.env*` (or any other key file), plus `${CLAUDE_PLUGIN_ROOT}/scripts/runlib.py`, plus `dataset-metadata.json`:

   ```json
   {"title": "freelab-SLUG", "id": "KAGGLE_USERNAME/freelab-SLUG", "licenses": [{"name": "other"}]}
   ```

   The title `freelab-SLUG` needs 6–50 characters. First time:
   `${CLAUDE_PLUGIN_ROOT}/scripts/withenv kaggle datasets create -p lab/backends/kaggle-data-SLUG -r zip`
   (private by default). Later: `${CLAUDE_PLUGIN_ROOT}/scripts/withenv kaggle datasets version -p
   lab/backends/kaggle-data-SLUG -m "run ID" -r zip`. Wait until `${CLAUDE_PLUGIN_ROOT}/scripts/withenv kaggle
   datasets status KAGGLE_USERNAME/freelab-SLUG` reads `ready`.
2. **The kernel folder** `lab/backends/kaggle-ID/` (ID: lowercase letters, digits, `-`, at most 42 characters)
   holds `kernel-metadata.json`:

   ```json
   {"id": "KAGGLE_USERNAME/freelab-ID", "title": "freelab-ID", "code_file": "run.py", "language": "python",
    "kernel_type": "script", "is_private": true, "enable_gpu": true, "enable_internet": true,
    "dataset_sources": ["KAGGLE_USERNAME/freelab-SLUG"], "machine_shape": "NvidiaTeslaT4"}
   ```

   and `run.py`, copied from freelab's template:
   `cp "${CLAUDE_PLUGIN_ROOT}/scripts/backends/templates/kaggle_run.py" lab/backends/kaggle-ID/run.py`.
   Then set its one placeholder, the `ARGS = [...]` line: `train.py`'s arguments for this run, where
   `--max-minutes` is the run's budget (the template holds the smoke's `["--max-minutes", "20", "--smoke"]`).
   `run.py` copies the code out of the attached Dataset, installs `requirements.txt`, adds `--resume` when the
   Dataset holds a `ckpt/`, and runs `train.py --out /kaggle/working`.
3. **Push**, once this launch's estimate is logged (`compute` §6), with a timeout of the run's minutes + 10, in seconds:
   `${CLAUDE_PLUGIN_ROOT}/scripts/withenv kaggle kernels push -p lab/backends/kaggle-ID -t SECONDS --accelerator NvidiaTeslaT4`
4. **The run's link and the poll.** Give the user the run's page, https://www.kaggle.com/code/KAGGLE_USERNAME/freelab-ID
   (its live log, for example in the browser pane when the user is signed in), and start the poll (Watch, fetch,
   stop) at once: it starts the live log stream itself once the kernel runs, so the user sees progress from the
   first minutes.

**Accelerator, to verify live:** open CLI issues (kaggle-cli #1196, #1197) question the values. A reply on #1196
says `NvidiaTeslaT4` gives the T4 pair and `NvidiaTeslaT4Highmem` is internal. If the push is refused or lands on
a P100, try `NvidiaTeslaT4Highmem` or a value the error lists, and record what worked here.

## Watch, fetch, stop

- **Watch** with the poll (`status` §5), right after the push:
  `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/poll.py kaggle ID --expected-minutes M` (it reads OWNER/SLUG from
  `lab/backends/kaggle-ID/kernel-metadata.json` and links the run's page; a resumed kernel `ID-r<N>` adds
  `--kernel KAGGLE_USERNAME/freelab-ID-r<N>`). Each check reads `kaggle kernels status` (queued, running,
  complete, error, cancelled). While the kernel runs, the poll keeps `kaggle kernels logs -f` streaming into
  `lab/runs/ID/live.log` and takes the step and the latest validation score from its progress lines
  (`step 50/290 (17%), loss 1.23, 2.1 min`, `eval val accuracy 0.758 at step 145`). The stream's exit is not the
  end of the run: the poll restarts it up to 3 times, and only `kernels status` says the run ended (to verify
  live: `kernels logs -f` is from the kaggle 2.x source and `--help`, not yet tried on a run).
- **The small files** come once the kernel has ended: the poll fetches them with a pattern, so when it exits 0
  they are in `lab/runs/ID/`; when it exits 1 saying they could not be fetched, fetch them by hand:
  `${CLAUDE_PLUGIN_ROOT}/scripts/withenv kaggle kernels output KAGGLE_USERNAME/freelab-ID -p
  lab/runs/ID --file-pattern '^(metrics\.jsonl|status\.txt|summary\.json|config\.json|.*\.log)$'`.
  `--file-pattern` is a Python regex searched in each output file's relative name (`metrics.jsonl`,
  `ckpt/step-00000290/state.pt`). They land flat in `lab/runs/ID/` within seconds. A fetch without the pattern
  brings the checkpoint first: measured, about 2 GB and about 10 minutes before the small files arrived.
- The log saved so far, by hand: `${CLAUDE_PLUGIN_ROOT}/scripts/withenv kaggle kernels logs KAGGLE_USERNAME/freelab-ID`.
- **Fetch the final checkpoint** only when it is needed: the demo, a warm start (a Train longer round, `plan`
  §1), a resume or a move. N is the run's last step in 8 digits (`step-00000290` for the quick start's full run, whose
  progress lines end at `step 290/290`):
  `${CLAUDE_PLUGIN_ROOT}/scripts/withenv kaggle kernels output KAGGLE_USERNAME/freelab-ID -p
  lab/runs/ID --file-pattern '^ckpt/step-N/'`. Once a run finishes, runlib keeps only that final checkpoint
  (about 2.1 GB for the quick start). For a stopped run, `'^ckpt/'` brings its newest two. Check that
  `lab/runs/ID/ckpt/step-N/COMPLETE` exists.
- Stop: the CLI has none. The user stops it on the kernel's page; otherwise it ends at the push timeout. Never use
  `kaggle kernels delete` as a stop: it deletes the kernel.

## Move in / out

- **Move in** (also Kaggle's resume, since `/kaggle/working` starts empty): copy the newest complete checkpoint
  into the Dataset folder, `lab/runs/ID/ckpt/step-N/` to `lab/backends/kaggle-data-SLUG/ckpt/step-N/`, with
  `lab/runs/ID/metrics.jsonl` next to `ckpt/`. Then `datasets version`, wait for `ready`, and push a new kernel
  id `ID-r<N>` with the same ARGS (`run.py` adds `--resume`). Fetch it into `lab/runs/ID/`.
- **Move out:** the small files and the checkpoint, as in Watch, fetch, stop; the checkpoint is then in
  `lab/runs/ID/ckpt/`.
- **Warm start** (a Train longer round, `plan` §1), a new run id NEW from the finished run OLD: fetch OLD's final
  checkpoint (Watch, fetch, stop), copy `lab/runs/OLD/ckpt/step-N/` to `lab/backends/kaggle-data-SLUG/init/step-N/`
  (not `ckpt/`, which `run.py` treats as a resume), `datasets version`, wait for `ready`, and push kernel NEW with
  `ARGS = ["--max-minutes", "20", "--init-from", "init/step-N", "--epochs", "1", "--lr-scale", "0.5",
  "--skip-test"]` (`run.py` copies `init/` next to `train.py`). The chosen round's scoring run (kernel
  `NEW-test`) uses the same ARGS without `"--skip-test"`, so keep `init/` until it has run. Remove `init/` and version the Dataset again before a run that is not a
  warm start from OLD.
- **Preemption:** Kaggle does not restart a kernel. A run stopped by the 12-hour limit or the timeout resumes only
  by Move in.

## Cost model

$0 within the weekly quota. The whole session counts against it, including the package install and the model
download. Log `--usd 0` and put the GPU hours in the note. The quick start's measured time on Kaggle is in
`${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya/charter.md`, **Budget**.

## Clean up

For the `cleanup` skill's deep clean, only on the user's yes, and only for a finished run fetched into
`lab/runs/ID/`. Flags checked against kaggle 2.2.4.
- List what freelab created: `${CLAUDE_PLUGIN_ROOT}/scripts/withenv kaggle datasets list -m -s freelab`
  (with sizes) and `${CLAUDE_PLUGIN_ROOT}/scripts/withenv kaggle kernels list -m -s freelab`.
- Delete a run's kernel (its outputs and versions go with it):
  `${CLAUDE_PLUGIN_ROOT}/scripts/withenv kaggle kernels delete -y KAGGLE_USERNAME/freelab-ID`, and
  each `freelab-ID-r<N>` it was resumed as. Never for a kernel still running. For the best run, only once its
  final checkpoint is complete in `lab/runs/ID/ckpt/`; otherwise fetch it first (the checkpoint fetch in Watch,
  fetch, stop: the small-file fetch leaves it on Kaggle).
- Delete the code Dataset: `${CLAUDE_PLUGIN_ROOT}/scripts/withenv kaggle datasets delete -y
  KAGGLE_USERNAME/freelab-SLUG`. Each version keeps what it held, so a checkpoint uploaded for a move in stays in an
  old version until the Dataset is deleted (to verify live). Recommend it when no more Kaggle runs of this experiment are
  planned and no running or resumable run uses it, and, if it holds the best run's checkpoint, only once that
  checkpoint is complete in `lab/runs/ID/ckpt/`; the next launch then uses `datasets create`, not `version`.
- `-y` skips the CLI's own prompt: use it only after the user's yes (freelab's guard also asks the user before
  each `kaggle kernels delete` and `kaggle datasets delete` of a `freelab-...` slug). Nothing is billed, so this frees Kaggle
  storage and tidies the account; it saves no money.

## Gotchas

- **The `ckpt/` in the Dataset folder belongs to one run.** Remove it (and `metrics.jsonl`) and version the
  Dataset before launching a different run id, or that run resumes someone else's checkpoint. The same holds for
  a warm start's `init/`.
- **During a run, progress comes from the live log:** the outputs (`metrics.jsonl` and the rest) come with the
  fetch, once the run has ended, so the status page's charts and Training health card fill in then, while the
  poll's live log gives the step and the latest evaluation as the run goes.
- Uploading a ~2 GB checkpoint as a Dataset version takes minutes; so does Kaggle's processing before `ready`.
- `-r zip` uploads `ckpt/` as a zip that Kaggle unpacks into a folder (https://www.kaggle.com/docs/datasets,
  checked 2026-09-28); to verify live that `run.py` finds `ckpt/step-*` there.
- Datasets convert tabular files to CSV unless you add `-t`; add it if EXP ships spreadsheets it reads as-is.
- **No native bf16** on a T4: use fp16 or fp32. Scheduling is flaky: a queued kernel can wait; say so rather than
  relaunching.
- Pushing again to the same kernel id starts a new version with an empty output: use a new id instead.
- Never run `kaggle auth print-access-token` or `kaggle config view`: they show credentials (the guard blocks both).
