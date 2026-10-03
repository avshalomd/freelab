# This machine (local)

## Free tier

Your own machine: no provider, no account, no credit. It costs electricity only, and it is limited by the
allowance the user set (`$FREELAB_HOME/local.json`, default `~/.freelab/local.json`; see the `compute` skill,
section 1).

## Sign-in

None. The launcher runs `train.py` with the Python that runs the launcher, so that Python needs the
experiment's requirements. The simplest way, which also works where the system Python refuses `pip install`
(PEP 668), is to let uv build the environment:
`uv run --with-requirements EXP/requirements.txt python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backends/local_run.py ...`.
Otherwise, install the requirements into a virtual environment and run the launcher with its `python`.

## Launch

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backends/local_run.py EXP --run-id ID [--when now|night] [--nights N] \
    [--lab lab] [--raise-ram TOTAL_GB] [--raise-gpu TOTAL_GB] [--raise-threads TOTAL_N] [--dry-run] -- ARGS
# the connection check:
uv run --with-requirements ${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya/requirements.txt \
    python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backends/local_run.py ${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya \
    --run-id smoke-local-YYYYMMDD --when now -- --smoke
```

- The run goes to `lab/runs/ID/` (`--lab` sets another lab directory), with the experiment's output in
  `log.txt` and the allowance used in `config.json`.
- A run that is not a smoke needs a minutes cap, `--max-minutes N` after `--` (a night run gets one from its
  window), and this launch's estimate logged (`--usd 0`; `compute` §6); `--dry-run` and smoke runs are exempt.
- It stays in the foreground until the run ends: start it in the background (a background task if available,
  or `nohup ... > lab/runs/ID.launch.log 2>&1 &`), then start the poll (Watch).
- `--when now` runs at once under the day allowance.
- `--when night` waits for the night window (and waits for the machine to be idle for `idle_minutes`, default 15, when `idle_check` is set; macOS only),
  runs under the night allowance, and sets `--max-minutes` to end 10 minutes before the window closes (a
  smaller `--max-minutes` in ARGS is kept). With `--nights N` a run that hits the window's end resumes on the
  next night, up to N nights.
- On macOS it keeps the machine awake with `caffeinate -i`.
- One local run at a time: a second launch exits 2 naming the run that holds the lock
  (`local-run.lock` in `$FREELAB_HOME`, default `~/.freelab`). A night run takes the lock only when it starts.
- **Warm start** (a Train longer round, `plan` §1): a new run id NEW, with ARGS
  `--init-from "$PWD/lab/runs/OLD/ckpt/step-N" --epochs 1 --lr-scale 0.5 --skip-test` (OLD's final checkpoint, an
  absolute path); the chosen round's scoring run (`NEW-test`) drops `--skip-test`.
- The allowance reaches the run as `FREELAB_MAX_RAM_GB`, `FREELAB_GPU_MEM_GB` and `FREELAB_THREADS`. A GPU
  allowance of 0 means no GPU: CUDA is hidden and the run uses the CPU.

## Watch, fetch, stop

- Watch with the poll (`status` §5): `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/poll.py local ID --expected-minutes M`.
  It reads `lab/runs/ID/` in place (nothing to fetch). Errors are in `lab/runs/ID/log.txt`.
- One look by hand: `cat lab/runs/ID/status.txt`. In a research loop, never `tail` the whole `metrics.jsonl`
  (its last lines hold the test results at the end of a run): `grep '"split": "val"' lab/runs/ID/metrics.jsonl |
  tail -n 2`, and `"split": "train"` for the step.
- Fetch: nothing to fetch; the outputs are already in `lab/runs/ID/`.
- Stop: send SIGTERM to the launcher (`pkill -TERM -f "local_run.py.*--run-id ID"`, or stop its background task).
  It passes the signal on; the run checkpoints and ends with `stopped (signal)` and exit 3.

## Cost model

$0 in the ledger (`--usd 0 --kind actual`). The real cost is the machine's time: stay within the allowance, and
put big jobs in the night window.

## Preemption

None from a provider, but a run can stop:
- `stopped (deadline)`: the night window or `--max-minutes` ended it. It resumes next night with `--nights`, or
  when launched again with the same `--run-id` (the launcher adds `--resume` when a complete checkpoint exists).
- `stopped (allowance)`: the process RSS went over the RAM allowance, or swap grew by over 1 GB. This is the user's
  call: shrink the job, raise the limit (for this run or for good), or use the cloud.
- The launcher exits 3 without running anything when the night window closes before the machine was idle, or
  with under 10 minutes left.

## Gotchas

- A missing allowance exits 2 and points at the setup: the `onboard` skill, step 3.
- Apple Silicon: training runs on MPS in fp32, and the memory is shared. Placement (`resources.py check`) counts
  RAM and GPU memory together against the RAM allowance. At run time the RAM guard sees only the CPU side (MPS
  memory is not in the process RSS); the GPU share is capped separately by the GPU allowance, never above the RAM
  allowance. The Apple Neural Engine is not a training target.
- The quick start on an M4 Pro (MPS): the full run peaks at a 10.0 GB physical footprint, with under 2 GB RSS, and
  needs a GPU allowance of about 12 GB (8 GB ran out of memory); its checkpoint is about 2.1 GB. The smoke peaks
  at 5.8 GB and fits an 8 GB GPU allowance; its checkpoint is about 0.6 GB.
- A laptop on battery or with its lid closed may still sleep; say so before a night run.
