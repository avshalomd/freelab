---
name: compute
description: Use when a freelab lab needs compute - "how much of my machine can the lab use", "run the lab on a GPU", "run it tonight", "launch the run", "fetch the results", "the run was preempted", "move the run to another backend", "out of Kaggle quota". Places, launches, fetches, moves and recovers lab runs. Not for CI, builds or deploys.
---

# compute: this machine and the cloud

If the `lab` skill isn't loaded this session, load it first: it holds the rules. Each cloud backend's reference
file, `${CLAUDE_PLUGIN_ROOT}/skills/compute/references/<modal|lightning|kaggle>.md`, has the same sections:
**Free tier**, **Onboarding** (its step 0 is **Signed in already?**), **Connection check**, **Launch**, **Watch,
fetch, stop**, **Move in / out**, **Cost model**, **Clean up**, **Gotchas**. You follow those steps with the
service's own CLI; there is no cloud launcher script. This machine is in
`${CLAUDE_PLUGIN_ROOT}/skills/compute/references/local.md` (its launcher, `local_run.py`, stays).

## 1. The local allowance (first use)

Only a run on this machine needs the allowance. If `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/resources.py show` exits
2 (no allowance yet), set it with the `onboard` skill's step 3, **This machine** (plain-language presets from
`resources.py presets`, asked with AskUserQuestion, Custom numbers allowed). Before the first local run, say the
stored allowance in one line (it may be onboarding's defaults) and offer to change it.

It is kept in `$FREELAB_HOME/local.json` (default `~/.freelab/local.json`). To change it later, the same presets
or explicit numbers (which override the preset):
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/resources.py set --day-preset low|medium|high --night-preset none|partial|full --start HH:MM --end HH:MM [--idle-minutes N] [--day-ram GB --day-gpu GB --day-threads N --night-ram GB --night-gpu GB --night-threads N]`

## 2. Placement

**Cloud first.** A run the user wants now goes to a connected cloud backend while it has free credit left. This
machine is for when the user asks for it, when no cloud backend is connected, or when a long job would burn the
free quota. "Tonight" is offered as a choice, never picked silently.

For each stage: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/resources.py check --ram GB --gpu-mem GB --hours H [--cloud-available] [--prefer cloud|local]`.
Add `--cloud-available` when a charter-allowed cloud backend has passed its smoke and has free credit left; then
it answers `cloud`, with or without a local allowance. Add `--prefer local` when the user asked for this machine or the job would burn the free
quota. It prints `{"place", "why", "nights"}`:

- **cloud:** "I'll run it on BACKEND, about USD X of free credit." Pick a backend the charter allows and that is
  connected, in the order Modal, Lightning AI, Kaggle.
- **now:** "It fits your daytime allowance; I'll run it here now." Local, `--when now`.
- **tonight:** offer it, with the cloud as the other option when one is connected: "It fits your night
  allowance; it can run tonight, START to END (N nights)." Local, `--when night --nights N`, on a yes.
- **ask:** quote `why` and offer three choices, as for any job that would go over the allowance:
  1. **keep the limit:** use the cloud (connect a backend) or shrink the job;
  2. **raise it for this run only:** `local_run.py ... --raise-ram TOTAL_GB --raise-gpu TOTAL_GB
     --raise-threads TOTAL_N`, each the run's new limit, not an amount on top (recorded in `config.json`);
  3. **raise it permanently:** `resources.py set` with the new values.

Never go over the allowance silently.

## 3. Connect a backend

Onboarding (sign-up, card, spending cap, key, CLI) is the `onboard` skill, which follows each reference file's
**Onboarding**. Here, the connection check is the quick start's smoke on that backend, from its reference file's
**Connection check**, with a fresh run id `smoke-<backend>-<YYYYMMDD>` (a finished id resumes straight to `done`
and tests nothing). It spends a little free credit: state its estimate and get a yes first (`onboard` step 5j),
unless the user has just asked for this check. The backend is connected when the fetched `lab/runs/ID/status.txt` reads `done` and
`metrics.jsonl` holds `val` and `test` accuracy at steps 0 and 50. If it fails, say what the CLI said: a missing
CLI or key goes back to onboarding.

## 4. Launch, watch, fetch

1. **Before a launch:** the charter gate (`lab`; only a `--smoke` run may precede the charter), a connected
   backend, a minutes cap on the run (`--max-minutes`; Modal's `--minutes`), and this launch's estimate logged
   (section 6). freelab's guard hook knows freelab's launches by the forms in the references
   (`lab/backends/modal_app.py`, a kernel folder in `lab/backends/`, a job on the `freelab` Studio, the plugin's
   `local_run.py`) and blocks one that misses any of these, so launch only in those forms; the user's own
   launches are theirs and not gated.
2. **Keys:** every CLI call that needs a key runs as `${CLAUDE_PLUGIN_ROOT}/scripts/withenv CMD...`, which loads
   `.env` into that command only. In a chain, each command gets its own `withenv`.
3. **Launch** from the reference. The Modal app and the Kaggle runner are copied from
   `${CLAUDE_PLUGIN_ROOT}/scripts/backends/templates/` into `lab/backends/`; outputs are fetched to `lab/runs/ID/`.
4. **Give the user the run's page** on the provider, from the reference: Modal prints its
   `https://modal.com/apps/...` link at launch; Kaggle's is `https://www.kaggle.com/code/KAGGLE_USERNAME/freelab-ID`;
   Lightning's is in its reference. Say what it shows (the provider's own log and state).
5. **Watch** with the poll right after the launch (`status` §5: the command, cadence and exit codes; the
   reference adds its backend's flags).
6. **When it exits:** `0`: the small files are in `lab/runs/ID/` (a checkpoint is fetched only when needed);
   `status` updates `best` and the spend, then `report`. `3` or `1`: section 7.

## 5. Moving between backends

- **When:** a free quota is used up (the ledger, plus `kaggle quota` or the service's usage page); a session limit
  stops a run (Kaggle 12 h, Modal's timeout, a Lightning Studio's 4-hour restart or the 4-hour A100/H100 limit); a
  backend fails its connection check; or a cheaper place opens, such as this machine's night window.
- **How:** this machine is the hub.
  1. Stop the old job if it still runs (its reference's **Watch, fetch, stop**): one GPU job per run id at a time.
  2. Fetch the run into `lab/runs/ID/` and find the newest complete checkpoint, `ckpt/step-*/COMPLETE`.
  3. Upload it the target's way, from its reference file's **Move in / out** (with `metrics.jsonl`, so the history
     continues).
  4. Log the relaunch's estimate, then relaunch with `--resume` (the Modal app and `local_run.py` add it
     themselves) and the same flags, and start its poll.
  5. Add a status event naming both backends and the step (`status` §2).
- **Within the plan, no question:** the approved charter and plan are the user's yes (`lab` rule 2). A move to a
  backend the charter's allowed compute names, within the plan's total and free credit, goes ahead; say so in
  the next update. A move from Kaggle (no spend) to a backend that spends credit is spending: it needs the plan
  to allow that backend and the cost. Anything beyond free credit, the charter's budget or its allowed compute
  needs a new yes, with the estimate.
- **Comparability:** a moved run keeps its step count and schedule (same flags; only `--max-minutes` may differ).
  Its result notes each backend it ran on.

## 6. The ledger

Log each launch's estimate right before the launch (freelab's guard blocks a launch with no fresh estimate since
the last one), and the actual cost once known:
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py add --lab lab --backend BACKEND --run ID --usd 0.30 --kind estimate --note "30 min T4, free credit"`
(`--kind actual` for a real cost). Log the list price even when free credit covers it; local runs are `--usd 0`.

## 7. Recovery

- **`stopped (...)`** in `status.txt` (poll exit 3; local: exit 3): resumable. On Modal and this machine, launch
  again with the same run id (not a local night run whose launcher still waits for the next window: the poll
  shows it as queued); on Kaggle and Lightning AI, relaunch through the reference file's **Move in / out**
  (a new job with `--resume`). Each relaunch logs its own estimate first. Preemption notes are in each
  reference's **Move in / out**. `stopped (allowance)` (local) goes to the user (section 2), not straight back
  into a relaunch.
- **`failed: ...`** (poll exit 1; if the files could not be fetched, fetch them by hand first): read the log (`modal app logs`, `lightning job logs`, the log Kaggle's fetch
  brings); fix a bug, verify with a smoke run, relaunch. A design question goes to the user.
- Add a status event (`status` §2) and say what happened in the next update.

## 8. Secrets

`lab` rule 1. EXP never holds `.env` or a key file: every upload (the Modal image, the Lightning Studio, the
Kaggle Dataset) copies EXP whole, so if EXP is the project root, stage a copy without them first.
