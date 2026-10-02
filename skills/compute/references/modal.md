# Modal

The first cloud choice: per-second billing, a detached run, and a Volume that keeps checkpoints between launches.
You drive it with the `modal` CLI and one small app file you write into the lab. Each command that needs a key
runs through `${CLAUDE_PLUGIN_ROOT}/scripts/withenv`, which loads `.env` for that command only.

Contents: Free tier · Onboarding (0 Signed in already?, 3 Spending cap: the Usage limit) · Connection check ·
Launch (the app file, the launch line, the run's link) · Watch, fetch, stop (the poll) · Move in / out (Warm
start, Preemption) · Cost model · Clean up · Gotchas

## Free tier

- The Starter plan includes **$30 a month** of free compute (https://modal.com/pricing, checked 2026-09-28).
- **Card:** needed for the full $30; without one there is only a small credit (freelab's author saw $1). The
  billing guide says "you must have a payment method on file in order to use Modal"
  (https://modal.com/docs/guide/billing, checked 2026-09-28).
- A T4 is $0.000164/s (about $0.59/h), an L4 $0.000222/s (about $0.80/h) (pricing page, same date). CPU and memory
  are billed as well, so $30 is about 33 T4 hours for a typical job (4 cores, 16 GiB), about 51 for the GPU alone.
- Starter limits: 10 GPUs at once, logs kept for 1 day. Volumes: 1 TiB a month included.

## Onboarding

0. **Signed in already?**
   `${CLAUDE_PLUGIN_ROOT}/scripts/withenv modal app list >/dev/null 2>&1 && echo yes || echo no`
   (it prints only yes or no; signed out, the CLI exits 1). A missing `modal` CLI means no.
1. **Sign up** at https://modal.com/signup.
2. **Card:** the human adds one under Settings → Usage & billing ("Manage payment information"). You never
   type payment details.
3. **Spending cap:** Modal calls it the **Usage limit**: Settings → Usage & billing → Usage limit (as seen in
   freelab's third trial). It caps what Modal may charge the card in a month once the free credit is used
   up. On a new Starter account it was $5 on the card beyond the $30 credit; it can be raised up to a maximum
   the page shows. Explain it before asking (`onboard` step 5e); the human sets it, at the lowest value the page
   accepts unless they want more.
4. **Key:** Settings → API Tokens → New token (page name to verify live). When driving the browser, stop here:
   the human presses New token and copies it. You add these lines to the project's `.env` with empty
   values (`onboard` step 2), and the human pastes the values:

   ```
   MODAL_TOKEN_ID=ak-...
   MODAL_TOKEN_SECRET=as-...
   ```

   The CLI reads both from the environment, ahead of `~/.modal.toml`
   (https://modal.com/docs/reference/modal.config, checked 2026-09-28). The alternative, which needs no `.env`:
   you run `modal token new` yourself (Bash `run_in_background`; `~/.local/bin/modal` if it is not on PATH). It
   opens a browser tab where the human approves the sign-in, then stores the CLI's token in `~/.modal.toml`
   (never open or print it).
5. **CLI:** `uv tool install modal` (these steps checked against modal 1.5.5).
6. **Official skill:** Modal ships agent skills through its CLI (https://modal.com/docs/cli/latest/skills, checked
   2026-09-28). Offer them; on a yes: `modal skills install --claude` (into the project's `.claude/`; `-g` for
   the user's home).

## Connection check

The quick start's smoke on an L4, with a fresh run id `smoke-modal-<YYYYMMDD>` (a finished id resumes straight to
`done` and tests nothing). Write the app (Launch) first, then run this from the project root as one shell call:

```bash
FREELAB_EXP="${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya" FREELAB_RUNLIB="${CLAUDE_PLUGIN_ROOT}/scripts/runlib.py" \
  ${CLAUDE_PLUGIN_ROOT}/scripts/withenv modal run --detach lab/backends/modal_app.py::main --run-id smoke-modal-YYYYMMDD --gpu L4 --minutes 20 --args=--smoke
```

Watch and fetch it as below. It passes when the fetched `status.txt` reads `done` and `metrics.jsonl` holds `val`
and `test` accuracy at step 0 and step 50.

## Launch

Write this once to `lab/backends/modal_app.py`, verbatim:

```python
"""freelab Modal app, written from skills/compute/references/modal.md: runs EXP/train.py on a GPU, detached,
with its outputs on the private Volume freelab-runs (committed every minute, so they can be watched)."""
import os, shlex, subprocess, sys
import modal

EXP, RUNLIB = os.environ.get("FREELAB_EXP", ""), os.environ.get("FREELAB_RUNLIB", "")
image = modal.Image.debian_slim(python_version="3.12")
if EXP and modal.is_local():  # built on the laptop only; the container resolves the function without it
    image = (image.pip_install_from_requirements(f"{EXP}/requirements.txt")
             .add_local_dir(EXP, "/exp", ignore=["**/__pycache__", "**/lab", "**/.venv", "**/.env*", "**/.git", "runlib.py"])
             .add_local_file(RUNLIB, "/exp/runlib.py"))
app = modal.App("freelab")
vol = modal.Volume.from_name("freelab-runs", create_if_missing=True)


@app.function(image=image, volumes={"/runs": vol}, timeout=30 * 60)
def run(run_id: str, minutes: float, args: list[str]) -> int:
    sys.path.insert(0, "/exp")
    from runlib import has_checkpoint
    cmd = ["python", "-u", "/exp/train.py", "--out", f"/runs/{run_id}", "--max-minutes", f"{minutes:g}", *args]
    if has_checkpoint(f"/runs/{run_id}/ckpt"):  # a restart after preemption, or a moved-in checkpoint
        cmd.append("--resume")
    proc = subprocess.Popen(cmd, cwd="/exp")
    try:
        while True:
            try:
                return proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                try:
                    vol.commit()
                except Exception as e:  # a missed commit must not end the run
                    print(f"freelab: volume commit failed ({e})", flush=True)
    finally:
        if proc.poll() is None:  # preempted or stopped: let runlib checkpoint first
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
        vol.commit()


@app.local_entrypoint()
def main(run_id: str, gpu: str = "T4", minutes: float = 30, args: str = ""):
    call = run.with_options(gpu=gpu, timeout=int((minutes + 10) * 60)).spawn(run_id, minutes, shlex.split(args))
    print(f"started {run_id} on a {gpu}, up to {minutes:g} min; function call {call.object_id}")
```

Launch from the project root, as one shell call, once this launch's estimate is logged (`compute` §6). EXP is
the experiment directory (the quick start runs in place from `${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya`, as
in the connection check: then `FREELAB_EXP` is that path, not `$PWD/EXP`):

```bash
FREELAB_EXP="$PWD/EXP" FREELAB_RUNLIB="${CLAUDE_PLUGIN_ROOT}/scripts/runlib.py" \
  ${CLAUDE_PLUGIN_ROOT}/scripts/withenv modal run --detach lab/backends/modal_app.py::main --run-id ID --gpu L4 --minutes 20 --args="--epochs 2"
```

- GPUs: T4, L4, A10G, A100, H100. A research loop uses the charter's decision GPU type (the quick start's: L4,
  the type its run used). `--minutes` becomes `--max-minutes` (at most 1430: Modal stops any function at
  24 h); the function times out 10 minutes later.
- The app sets `--out`, `--max-minutes` and, when a checkpoint is there, `--resume`. The experiment's own flags go
  in `--args` as one string: `--args="--epochs 3 --seed 1"`.
- It returns once the run has started. Outputs go to `ID/` on the private Volume `freelab-runs`.
- **The run's link:** the launch prints the app's page, `https://modal.com/apps/...` (its logs and state). Give
  it to the user, and pass it to the poll as `--link`.

## Watch, fetch, stop

- **Watch** with the poll, started with Bash `run_in_background` right after the launch:
  `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/poll.py modal ID --expected-minutes M --link https://modal.com/apps/...`.
  Each check copies `status.txt`, `metrics.jsonl` and `summary.json` from the Volume into `lab/runs/ID/`
  (`modal volume get --force freelab-runs ID/<file>`), updates the status page, and the poll exits when
  `status.txt` reads `done`, `stopped (...)` or `failed: ...`. So when it exits 0, the small files are fetched.
  Always pass the app's link: the poll reads the app id (`ap-...`) from it and, if the app has stopped without
  writing `status.txt` (a container that died), ends the run as failed instead of waiting for `--max-hours`.
- One look by hand: `${CLAUDE_PLUGIN_ROOT}/scripts/withenv modal volume get freelab-runs ID/status.txt -`.
- Still running: `${CLAUDE_PLUGIN_ROOT}/scripts/withenv modal app list` (app `freelab`, note its APP_ID); logs:
  `${CLAUDE_PLUGIN_ROOT}/scripts/withenv modal app logs APP_ID`.
- Fetch the small files by hand: `mkdir -p lab/runs/ID; for f in metrics.jsonl status.txt summary.json; do
  ${CLAUDE_PLUGIN_ROOT}/scripts/withenv modal volume get --force freelab-runs ID/$f lab/runs/ID; done`. A stopped
  run has no `summary.json` yet. The checkpoints stay on the Volume.
- Stop: `${CLAUDE_PLUGIN_ROOT}/scripts/withenv modal app stop -y APP_ID`. The run gets SIGTERM and 20 s to
  checkpoint.

## Move in / out

- **Move in** (the newest complete checkpoint is in `lab/runs/ID/ckpt/`): upload it and the metrics so far, then
  launch with the same `--run-id` and flags; the app adds `--resume` when it finds a complete checkpoint.
  `${CLAUDE_PLUGIN_ROOT}/scripts/withenv modal volume put --force freelab-runs lab/runs/ID/ckpt ID/ckpt &&
  ${CLAUDE_PLUGIN_ROOT}/scripts/withenv modal volume put --force freelab-runs lab/runs/ID/metrics.jsonl ID/metrics.jsonl`. Then
  `${CLAUDE_PLUGIN_ROOT}/scripts/withenv modal volume ls freelab-runs ID/ckpt` must list `step-*` (to verify
  live: not `ckpt/ckpt`).
- **Move out:** the small files as in Fetch, plus
  `${CLAUDE_PLUGIN_ROOT}/scripts/withenv modal volume get --force freelab-runs ID/ckpt lab/runs/ID`
  (once a run finishes, runlib keeps only its final checkpoint: about 2.1 GB for the quick start's full run).
- **Warm start** (a Train longer round, `plan` §1), a new run id NEW from the finished run OLD: OLD's final checkpoint
  is still on the Volume, so nothing is uploaded. Launch NEW as usual with
  `--args="--init-from /runs/OLD/ckpt/step-N --epochs 1 --lr-scale 0.5"` (N: OLD's last step, 8 digits; check it
  with `${CLAUDE_PLUGIN_ROOT}/scripts/withenv modal volume ls freelab-runs OLD/ckpt`).
- **Preemption:** Modal restarts a preempted function on the same input; the app resumes from the newest committed
  checkpoint, so only the work since then is lost. After a timeout (`stopped (deadline)`), launch again with the
  same `--run-id`.

## Cost model

- Billed per second of GPU, CPU and memory while the container runs. Estimate `minutes / 60 × the GPU's hourly
  rate` plus about $0.32/h for CPU and memory, and log it in the ledger. The quick start's measured times per
  provider are in `${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya/charter.md`, **Budget**.
- A preempted run restarts with the full `--minutes`, so its GPU time and cost can exceed `--minutes`; say so when
  stating a long run's estimate.
- Old checkpoints stay on `freelab-runs` until the user removes them (1 TiB a month included; Clean up below).

## Clean up

For the `cleanup` skill's deep clean, only on the user's yes, and only for a finished run whose small files are
fetched into `lab/runs/ID/`. Flags checked against modal 1.5.5.
- List the run folders: `${CLAUDE_PLUGIN_ROOT}/scripts/withenv modal volume ls freelab-runs`; one
  run's checkpoints, with sizes: `${CLAUDE_PLUGIN_ROOT}/scripts/withenv modal volume ls freelab-runs
  ID/ckpt` (then `ID/ckpt/step-N`; `--json` for JSON; the size column to verify live).
- Delete a run's checkpoints: `${CLAUDE_PLUGIN_ROOT}/scripts/withenv modal volume rm -r freelab-runs
  ID/ckpt`. The run's small files stay on the Volume (a few kB), so its metrics are never in a removal.
- **The best run:** the fetch above leaves the checkpoints on the Volume, so this may be the only copy of the
  trained model. Delete the best run's `ID/ckpt` only once its final checkpoint is complete in `lab/runs/ID/ckpt/`;
  offer to fetch it first (Move out).
- freelab's guard asks the user before every `modal volume rm freelab-runs ...`, and blocks `modal volume delete
  freelab-runs`: it deletes every run on the Volume, running ones included.

## Gotchas

- **T4 has no native bf16:** use fp16 or fp32 there (the quick start uses fp16 autocast on CUDA).
- **"App completed" after a detached launch does not mean the run is done.** Check `status.txt` or `modal app list`.
- The first launch builds the image (about 1.5 min); later launches reuse it. Code changes need a new launch.
- Set both `FREELAB_EXP` and `FREELAB_RUNLIB` on every launch line: the app reads them when it is imported.
- Do not run `modal token info` or print `~/.modal.toml`: they show token details (the guard blocks both).
