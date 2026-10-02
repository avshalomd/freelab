---
name: cleanup
description: Use when a freelab lab takes up space or is finished - "clean up the lab", "free some space in the lab", "delete the lab's checkpoints", "how much space is the lab using", "remove the old runs", "clear the lab's cloud storage". Light clean unasked; deep clean only on a yes.
---

# cleanup: free space without losing results

If the `lab` skill isn't loaded this session, load it first: it holds the rules. The local work is done by
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cleanup.py` (run from the project root): `inventory` (JSON, deletes
nothing), `light` (the light clean) and `remove PATH...` (named items only). It applies §1 and §2 below,
re-checks each item just before deleting it, and records every removal in `lab/cleanup.jsonl` first. Add
`--exp EXP` (the experiment directory) so its `__pycache__` is included. Cloud copies are listed and deleted
with each backend's CLI, from the **Clean up** section of
`${CLAUDE_PLUGIN_ROOT}/skills/compute/references/<backend>.md`; freelab's guard asks the user before each delete
of freelab's cloud storage. Cleanup covers only what freelab made (`lab/`, its runs, its cloud copies), never the
rest of the project or the user's own cloud data.

**When:** the user asks; and offer it once after a report (`report` §4), after a research loop, and when a
provider's storage nears its free limit (Lightning AI keeps 10 GB free, and each full run of the quick start
leaves about 2.1 GB of artifacts: once a run finishes, only its final checkpoint is kept). Two tiers:
1. **Light clean** (§3): leftover process files nobody needs. Done without asking, whenever cleanup runs and at
   the end of a lab.
2. **Deep clean** (§4–§6): checkpoints, worktrees and cloud copies. Suggested with an inventory and a plain
   explanation per item; done only on a yes.

## 1. Which runs are finished

The script classes every local run before removing anything of it (its inventory's `runs`); use the same classes
for cloud copies:
- **Finished:** `summary.json` is in `lab/runs/ID/` (for a cloud run: fetched) and `lab/status.json` does not list
  the run as `queued`, `starting` or `running`; or the experiment has a row in `lab/results.tsv`.
- **Running:** listed as `queued`, `starting` or `running`, or `status.txt` reads anything other than `done`,
  `stopped (...)` or `failed: ...`; for a cloud run not yet fetched, its backend's watch decides.
- **Resumable:** no `summary.json`, and `stopped (...)`, or `failed: ...` with a complete checkpoint (`compute` §7).

**Never removed:** anything of a running or resumable run, here or in the cloud, unless the user names that run
(`remove ... --include-run ID`). When in doubt, a run counts as not finished.

## 2. Always kept

- Every record in `lab/` (charter, plan, report, handoff, ledger, results, status, `cleanup.jsonl`, `blocks/`,
  the `*-run1.md` files, the hooks' and the poll's small process files), and in each run folder its
  `metrics.jsonl`, `status.txt`, `summary.json`, `config.json` and logs: a run folder is never removed whole, so
  the report's run table stays valid. Also `.env`, the experiment's code, git history and the backend templates
  in `lab/backends/`. The script removes only checkpoints, staged copies, worktrees (with `git worktree remove`,
  never `--force`), `.poll-tmp` folders and `__pycache__`, by literal path.
- **Recommended to keep:** the best run's final checkpoint, the result (the newest complete `ckpt/step-*` of
  `best.run` in `lab/status.json`; in a research loop, of the best kept experiment), removed only when the user
  picks it. The same holds in the cloud: Modal's fetch leaves the checkpoints on the Volume, so the cloud copy
  may be the only one. Keep the best run's cloud checkpoint unless that final checkpoint is already complete in
  `lab/runs/ID/ckpt/` (offer to fetch it first: the backend's **Move out**).

## 3. Light clean (no question)

Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cleanup.py light --exp EXP`. It removes only leftovers of finished
runs: `__pycache__`, staged upload copies whose originals are in `lab/runs/` (staged again at the next launch),
unfinished checkpoint writes (`.tmp-*`, `step-*` without `COMPLETE`), a killed poll's `.poll-tmp`, and the
research candidates' worktrees whose experiment has its row in `lab/results.tsv`; never metrics, results,
checkpoints or cloud data. Copies you made in this session only to peek at a file go too, by their exact paths.

Then say in one line what went and how much it freed, from its last line, e.g. "Light clean: removed 3
worktrees, `__pycache__` and a staged Kaggle copy, 1.9 GB freed. Metrics, results and checkpoints are
untouched." Nothing to remove: say so in a few words, or nothing at the end of a lab.

## 4. Deep clean: the inventory first

Delete nothing yet. Take the local items from `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cleanup.py inventory --exp EXP`
(its `deep` list: each item's `path`, `bytes`, `recommendation` and `why`, the base of "what deleting it
means"), and the cloud items from
each connected backend's list commands (its reference's **Clean up**). Show one table:

| Item | Where | Size | Recommendation | What deleting it means |
|---|---|---|---|---|
| Checkpoints of exp-02 (discarded) | `lab/runs/exp-02/ckpt/` | 2.1 GB | Remove | Frees disk; exp-02 can no longer be resumed, and its model is gone (it did not beat the best). |
| Final checkpoint of the best run | `lab/runs/exp-04/ckpt/step-00000500/` | 2.1 GB | Keep | This is the trained model; deleting it loses the result (the numbers stay). |
| Modal copy of exp-02 | Volume `freelab-runs`, `exp-02/ckpt` | 2.1 GB | Remove | Frees Volume space; that copy cannot be fetched again. The local metrics stay. |
| Modal copy of the best run | Volume `freelab-runs`, `exp-04/ckpt` | 2.1 GB | Keep | It may be the only copy of the trained model. Removable once its final checkpoint is fetched into `lab/runs/exp-04/ckpt/`. |
| Checkpoints of exp-05 (stopped, resumable) | `lab/runs/exp-05/ckpt/` | 2.1 GB | Keep | Needed to resume exp-05. |
| The research loop's worktree | `lab/worktrees/loop` | 40 MB | Remove (after the demo) | Frees disk; the best version stays on the branch `lab/<tag>`. |
| Hugging Face cache | `~/.cache/huggingface` | 3.4 GB | Not offered | Shared with other projects; the next run downloads the model again. |

- **Cloud:** Modal Volume run folders (`freelab-runs`), Lightning AI job artifacts and the `freelab` Studio's
  uploaded files, Kaggle private datasets and kernels freelab created (`freelab-*`). Recommend removing a cloud
  copy only when the run is finished and `lab/runs/ID/` holds its fetched `metrics.jsonl`, `status.txt` and
  `summary.json`, and, for a copy that holds checkpoints, only when the run is not the best one or its final
  checkpoint is already complete in `lab/runs/ID/ckpt/` (§2). Otherwise it reads "Keep", with an offer to fetch
  the checkpoint first.
- **The research loop's worktree** `lab/worktrees/loop`: the inventory lists it as an item to remove. Offer it
  once the loop has ended and the demo no longer needs it. It is refused (listed with `blocked`) while a run is
  running or when it has uncommitted changes (`git -C lab/worktrees/loop status --porcelain`): say so, and leave
  it. Removing it keeps the branch `lab/<tag>`, so the best version can still be merged.
- **Shared caches** (the inventory's `shared_caches`): mention them with their size
  (`du -sh "${HF_HOME:-$HOME/.cache/huggingface}"`); never offer them by default.

What deleting means, in plain words, for each kind:
- **A checkpoint:** frees disk, but that run can no longer be resumed or continued, and the trained model is
  gone unless the best one is kept. The numbers stay.
- **Provider storage** (a Modal Volume folder, Lightning AI job artifacts or Studio files, a Kaggle dataset or
  kernel): frees the provider's free storage and stops any storage billing (Lightning AI bills storage over
  10 GB), but those copies cannot be fetched again. Deleting a Kaggle kernel also deletes its outputs and
  versions; deleting the experiment's code Dataset (`freelab-<name>`) means the next Kaggle launch creates it again.
- **A worktree:** frees disk; the experiment's numbers stay in `lab/results.tsv`, and the kept commits are on
  `lab/<tag>`.

## 5. Ask once

One question (AskUserQuestion when available, else a short numbered list):
- **Remove the recommended items** (Recommended): "frees N GB here and M GB in the cloud".
- **Let me choose:** then a multi-select of the items (AskUserQuestion takes up to 4: group them, e.g. "old
  checkpoints here, 6.3 GB"; with more, a numbered list the user answers with numbers).
- **Keep everything.**

Name every cloud deletion in the question, e.g. "Modal: `freelab-runs/exp-02/ckpt`; Kaggle: kernel
`freelab-exp-02`". Say that deletion is permanent: nothing goes to a trash, and a deleted checkpoint or cloud
copy cannot be brought back. Say too that the permission prompt will ask once more for each cloud deletion.

## 6. Remove and record

On a yes:
- **Local items:** `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cleanup.py remove "PATH" ... --exp EXP` with the chosen
  paths, exactly as the inventory printed them (add `--include-run ID` only for a run the user named). It checks
  §1 again, records each item in `lab/cleanup.jsonl` before deleting it, and prints `removed` or `refused` with
  the reason per path; say what was refused and why. The loop's worktree goes the same way (`remove
  "lab/worktrees/loop"`): the script runs `git worktree remove` on it, never `--force`.
- **Cloud items:** for each one, check §1 again (a run that has started or been resumed since the inventory is
  skipped and said so), append one line to `lab/cleanup.jsonl` **before** deleting: `t` (ISO time), `where`
  (`modal`, `lightning` or `kaggle`), `path`, `bytes` (the provider's size, or null when it shows none):
  `printf '%s\n' '{"t": "2026-10-01T21:04:00Z", "where": "modal", "path": "freelab-runs/exp-02/ckpt", "bytes": 2254857830}' >> lab/cleanup.jsonl`
  then run the backend's delete command (its reference's **Clean up**). For Lightning AI, open the page and the
  human presses Delete.

Then:
- add one status event (`status` §2: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/status_page.py event --lab lab "..."`),
  e.g. "Cleanup: removed 3 checkpoints and 2 Modal copies, 8.4 GB freed; the best run's final checkpoint is kept",
  and re-publish (`status` §3);
- say in the chat what was removed, the space freed here and in the cloud, and what was kept.
