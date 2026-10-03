# Changelog

0.4.0 is the first public release; earlier entries are kept for context.

## 0.4.1 - 2026-10-03

Fixes from five reviews of 0.4.0.

- **Honest numbers in the quick start.** The research loop keeps a change only when it was judged on the same
  validation items as the baseline (`val_ids_sha` in `summary.json`), and the split settings are frozen. With
  `--skip-test`, `train.py` no longer loads the test split at all, and the framing is chosen on the training
  sample. `summary.json` records the torch and transformers versions and the device. The docs say that ECE is
  measured at Laya's zero-shot temperature, that a keep inside the validation interval may be noise, and that
  each result is one run, one seed.
- **A shorter quick-start loop:** a 10-minute cap per experiment on Modal's L4, a time stop rule by each
  experiment's estimate rather than its cap, and one total that includes the scoring run (about 10-17 minutes on
  the L4). Train longer rounds skip the test split too; only the chosen round gets one scoring run.
- **The end of a research loop:** the agent offers to merge the branch for you ("merge the lab branch"), or
  says plainly that nothing was kept.
- **Setup:** no welcome question when you asked to set up; one question for this computer's defaults; the
  `.env` placeholders come at each provider's key step; a `lab/` folder that is not freelab's is left alone until
  you say so. The connection check's poll works before there is a charter.
- **Guard hooks:** more launch forms are recognised (a `cd` into `lab/backends`, `modal run -m`), more ways of
  reading a key are blocked, and false alarms are gone: copying `.env.example` to a new `.env`, `rsync
  --exclude .env`, and searching code for a key's name in folders without a `.env`.
- **Scripts:** the poll ends as failed when a finished run's files could not be fetched, and a poll for a run
  that never started can be forgotten; `resources.py check --cloud-available` needs no local allowance; text
  files are written as UTF-8 everywhere; the ETA after a resume is right.
- **Shipped templates:** the Modal app and the Kaggle runner are files in `scripts/backends/templates/`, copied
  into the lab, not written out from the docs.
- **Shorter skills:** one description of the poll, smaller `lab`, `status` and `report` skills, and descriptions
  that say what each skill is not for.
- **Docs:** README install notes for the desktop app and the minimum Claude Code version (2.1.284), plainer
  safety notes, a CI badge, and the Apache-2.0 licence of `laya_head.py` shipped beside it.

## 0.4.0 - 2026-10-02

Hooks that guard keys, money and the report; a poll that keeps the status page live; the research loop in its
own git worktree.

### Highlights

- **Guard hooks** that block reading `.env` and the services' key files, block one of freelab's launches without
  a numeric target, a budget and a logged estimate, ask before deleting freelab's cloud data, and remind the agent
  to write the report. They act only in a project that uses freelab, and only on freelab's own runs and storage.
- **A background poll** (`scripts/poll.py`) watches each run, keeps `status.json` and the page current, and
  prints only validation lines.
- **Race-free status edits:** `status_page.py set` and `event` replace hand edits of `status.json`.
- **The research loop in its own git worktree** (`lab/worktrees/loop`, branch `lab/<tag>`), so your files are
  never touched; experiment code goes in `experiments/<name>/`.
- **Train longer, in rounds**, each a warm start, stopping when validation stops improving.
- **Cloud first:** a run wanted now goes to a connected free tier; this machine when asked or for a night run.
- **A shorter quick-start loop** with `--skip-test` experiments that never see the test split.
- **Desktop-friendly setup:** the agent runs every install and sign-in itself.

### Details

- **Hooks:** they act only where `lab/` holds one of freelab's files or `.env` has the line onboarding wrote.
  - **Guard** (`PreToolUse`): denies reading or editing `.env` and the key files (`~/.modal.toml`, `~/.kaggle/`,
    `~/.lightning/`) and commands that print a key or the whole environment, including `python -c`, `node -e`,
    `perl -e`, `ruby -e` and awk code that does; asks before deleting freelab's cloud data (`modal volume rm
    freelab-runs ...`, deletes of a `freelab-...` Kaggle kernel or dataset, Lightning deletes of the `freelab`
    Studio or a freelab run's job) and denies `modal volume delete freelab-runs`; blocks one of freelab's launches
    (`modal run` of `lab/backends/modal_app.py`, `kaggle kernels push` of a kernel folder under `lab/backends/`,
    `lightning job run` on the `freelab` Studio, the plugin's `local_run.py`) unless the charter has a numeric
    Target and a Budget, an estimate was logged since the last launch, and a Modal, Lightning AI or local run has
    a minutes cap. Smoke runs and `--help` are exempt. Git is left alone.
  - **Launch record** (`PostToolUse`): a launch is recorded in `lab/.launches` only once its command has run.
  - **Stop:** asks once for the report when a finished run has none; quiet while a poll or a research loop runs.
  - **Session start:** the onboarding offer comes once per machine.
- **Scope:** freelab handles the experiments you ask for; `lab/` is their area, and after the report the agent
  goes back to what you were doing.
- **Keys:** the secrets rule is written once, in `lab`. `scripts/withenv` loads `.env` into one command;
  `scripts/env.sh add` writes empty placeholders and `env.sh check` says which keys are filled in.
- **The poll:** every 30 seconds in the first 5 minutes and for short runs, then every 90 seconds up to about 3
  hours, 5 minutes up to 12 and 15 minutes beyond; exit 0 done, 3 stopped and resumable, 1 failed. On Kaggle it
  streams the live log; on Modal it reads the app id from `--link`.
- **Run links:** each launch gives the run's page on the provider; the status page shows it.
- **Status page blocks:** the page is built from a `layout` list of blocks, plus custom static blocks from
  `lab/blocks/`. The local file is the live page; a claude.ai copy is re-published when the agent acts.
- **Train longer:** up to 3 rounds of one more epoch by default, each under its own run id; only the chosen
  round's test score is read.
- **Scripts:** `stats.py wilson P N` for the report's intervals; `cleanup.py inventory|light|remove` for the
  local cleanup inside a fixed scope.
- **Money and Modal:** Modal's money safety is the Usage limit, explained before asking; the connection check
  is asked first with its estimate; an approved charter or plan is the yes for the runs inside it; moving a run
  from Kaggle to a paid service counts as spending.
- **Charter changes** in your own words get the same explanation (what, why, alternatives, what it means)
  before they are applied.
- **Timings** per provider live in one place, the Budget of the example's charter.
- **Skill text:** shorter descriptions, every skill loads `lab` first, cross-skill paths start at
  `${CLAUDE_PLUGIN_ROOT}`, each fact is written once.
- **Onboarding** checks for `uv` and `npx` and installs them only on a yes; Lightning AI uses the `.env` key;
  `.gitignore` is touched only inside a git repository.
- **Cloud names** come from the experiment folder's name, lowercased.
- **Docs and evals:** the status-page picture is rendered from a synthetic `status.json` shaped like a Modal L4
  quick start; the evals use only synthetic data and seed their own home; CI tests Python 3.10 and 3.12.

## 0.3.1 - 2026-10-01

Fixes from the second live trial.

- **The charter is explained, not just recommended.** `plan` explains each decision (the data and its splits,
  the baseline, the metric and target, compute and budget, what stays fixed): the recommendation, why, the
  alternatives and what each means for the user, then Go with recommended, Change something or Explain a part
  more. A worked example for the quick start is in `skills/plan/references/quick-start-walkthrough.md`.
  Onboarding explains each question before asking it and what the connection check proved; the report recaps
  the steps after a user's first experiment.
- **The agent creates `.env`.** Onboarding creates the project's `.env` (or adds to an existing one) with an empty
  line for each key the provider needs, links it, and the user only pastes the values.
- **Dollar amounts in skills.** Claude Code replaces `$0`, `$1` in a skill file with the skill's arguments, so
  "$0.25" reached the agent as "<argument>.25". Skills now write "USD 0.25"; a test keeps it that way.
- **Live progress on Kaggle.** In the trial the user saw nothing for 17 minutes. Right after the push the agent
  now streams the run's log (`kaggle kernels logs -f` into `lab/runs/ID/live.log`, in the background), and each
  poll reads the newest progress and eval lines from it; `kernels status` and
  the run's kaggle.com page are the fallback. (Corrected in 0.4.0: this entry first said the stream's exit also
  signals the end. It does not: the stream can end early, and only `kernels status` says the run ended.) The fetch brings the small files first (`--file-pattern`), in
  seconds, and the final checkpoint only when it is needed (the demo, a warm start, a resume); fetching
  everything had downloaded 2 GB of checkpoints first and taken about 10 minutes.
- **The status page is re-published on every poll.** A published Artifact changes only when re-published (its
  30-second reload loads the same version), and in the trial it sat unchanged until the user asked. A run's
  `step` and `total` come only from real data and stay null while unknown, so the page never shows a made-up
  "0% done". The page gains a Training health card (a smoothed loss chart, the accuracy per evaluation, and a
  verdict: still improving, levelling off or plateaued, with the reason), and the agent explains it.
- **The report always comes after a run.** When a run ends, the agent fetches it, updates the page and goes to
  the report with no prompt from the user; if the user's questions took over meanwhile, it answers them and
  returns to the report and the next steps. In the trial the flow had stopped at the finished run.
- **New next steps.** Up to four, chosen by context, each explained before the question: **Try the model** (the
  example's local demo, `demo.py`, after fetching the final checkpoint, about 2 GB; recommended after a first
  experiment), **Train longer** (a warm start, `--init-from <run>/ckpt/step-00000290 --epochs 1 --lr-scale 0.5`,
  when the Training health verdict is still improving; `plan` explains it like any charter), **Try to beat it**
  (recommended when the verdict is levelling off or plateaued, or there is none; Train longer is recommended
  when it is still improving) and **Clean up and stop**. Each backend's reference says how to
  warm-start there.
- **`python3` by default.** Skill commands run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/...`: on the user's Mac
  `python` did not exist, and the first command failed.
- **Timing and storage.** The quick start takes about 15-20 minutes end to end (about 17 on Kaggle: training about
  9.3 minutes, the final test scoring about 6; $0 there), still capped at 20. A finished run keeps only its
  final checkpoint, about 2.1 GB for the quick start, not the newest two; the references and cleanup say so.

## 0.3.0 - 2026-10-01

Onboarding, compute by each service's own CLI, the research loop in the session, a plain-language status page
and cleanup. 0.2.0 was never released; its changes are folded in here, with the fixes from the first live trial.

- **Onboarding:** a new `onboard` skill takes a first-time user through all of setup with AskUserQuestion
  choices, the recommended one first: a three-line welcome; this machine as presets (day Low, Medium or High;
  night Full, Partial or None; the night window and an idle wait), each with its numbers, or custom values;
  Kaggle, Lightning AI and Modal picked in one multi-select, then one at a time. For each service: "I'll drive
  your browser" or "I'll follow the steps myself" (when driving, the agent never presses the button that creates
  or reveals a key and never types account details, passwords, phone codes, cards or CAPTCHAs), money safety,
  the key in `.env`, the CLI, an optional official integration and the connection check. Then "✅ <Provider> is
  operational" and one question: start the quick start, connect another provider, set up my own experiment, or
  stop. A service that is already signed in goes straight to its check. The marker `~/.freelab/onboarded` holds
  the machine presets and Lightning's teamspace too. A `SessionStart` hook offers onboarding until it is done.
- **Secrets:** keys live in the project's `.env`, which the human edits; the agent never reads it and loads it
  into one command's environment only (`set -a; [ -f .env ] && . ./.env 2>/dev/null; set +a; <command>`, so a
  malformed line cannot echo a key). `.env` and `lab/` go in `.gitignore`.
- **This machine:** `resources.py presets` prints the computed presets; `set --day-preset low|medium|high
  --night-preset none|partial|full` stores them (explicit numbers still override; night never below day);
  `--idle-minutes N` sets the idle wait, which `local_run.py` reads (15 when only the idle check is on).
- **Compute:** the Modal, Lightning AI and Kaggle launchers are removed. Each service is driven with its own CLI,
  from `skills/compute/references/<service>.md` (free tier, onboarding, connection check, launch, watch, fetch,
  stop, move in and out, cost, clean up, gotchas). `local_run.py` stays for this machine. A run moves between
  services, through this machine, when a free quota or a session limit runs out; within free credit without
  asking.
- **Lightning AI:** the facts checked 2026-10-01: 5 credits at sign-up with phone verification, 25 more with a
  card, "up to 30 to start", likely once; no spending-cap setting (it warns, then stops workloads when credits
  run out; the card is charged only by auto-reload, off by default, or by buying credits); about $0.90 per T4
  hour measured. Install with `uv tool install --python 3.12 lightning-sdk`; the teamspace is found once and
  passed on every command; live metrics with `lightning cp`.
- **Experiment setup:** the `plan` skill recommends the whole charter as one card (each field's value, why and
  what it means, the total time and cost) and asks one question: Go with recommended, or Customise (one field
  at a time, each with its recommendation). For a one-stage plan the same answer approves the plan.
- **Quick start:** one run of about 15 minutes end to end on a free T4 (`--max-minutes 20`, at most about $0.30
  of free credit), target test accuracy >= 0.80, then the report. A seeded validation split (up to 10 unused
  training messages per intent) is scored at step 0 and after every epoch; the test split is scored once, at the
  end. `train.py` prints a progress line at least every 25 steps and at each evaluation, so job logs never look
  stuck.
- **Research loop:** a new `research` skill, after Karpathy's autoresearch: a branch `lab/<tag>`, one change per
  experiment, keep or reset on validation, `lab/results.tsv`, the test split scored once at the end, only runs
  that read `done` count. It runs in the ordinary session: a background poll per run, a one-line update per
  experiment, and an offer to turn on auto mode first (the human switches it). It stops at the target, the
  charter's budget or free credit, K non-improving experiments in a row, or the user's word. `/goal` is no
  longer used. The charter gains the validation split, the decision GPU type (default T4), the editable
  surface, the frozen parts and the per-experiment budget. The quick start's "try to beat it" loop: about 1
  hour, validation accuracy >= 0.85, 20 minutes per experiment, K = 3, $0 beyond free credit.
- **Status page:** it opens by itself when the first run starts (a private artifact, or the local file) and is
  explained in three lines. Top to bottom: a plain "Now" sentence, a progress-to-target bar, charts (the metric
  per split with start and target lines, the training loss, the kept metric per experiment), the plan as a
  timeline, a cost meter with the free credit marked, and the details collapsed. The local page reloads itself
  every 30 s while a run is active. `status.json` gains the plan's `stages`; files from 0.1.0 still render.
- **Report:** ends with next steps: try to beat it, clean up, or stop here.
- **Cleanup:** a new `cleanup` skill. A light clean (leftover process files) runs without asking; a deep clean
  (checkpoints, cloud copies) shows an inventory with what deleting each item means and runs only on a yes.
  Metrics, summaries, results and anything of a running or resumable run are never removed. Removals are logged
  in `lab/cleanup.jsonl`.
- **README:** install (and a local checkout for testers), onboarding with presets and browser driving, the free
  GPU hours, the quick start as one 15-minute run, try to beat it, the status page, cleanup.
- **Evals:** `modal-signin` becomes `onboard-modal-key`; `smoke-before-scale` checks for a full `modal run`; new
  `quickstart-offer` and `cleanup-keeps-metrics`.
- **Verification:** the CLI steps for Modal, Lightning AI and Kaggle are pending live checks.

## 0.1.0 - 2026-09-28

First release.

- **Skills:** `lab` (the loop and the operating rules), `plan` (charter and plan), `compute` (allowance,
  placement, backends, recovery), `status` (the live status page) and `report` (report and handoff).
- **Compute:** launchers for this machine (`local_run.py`, with a day/night allowance, night windows and a
  one-run lock), Modal, Lightning AI and Kaggle, all on one run contract (`scripts/runlib.py`).
- **Lab tools:** `resources.py` (machine probe, allowance, placement), `status_page.py` (self-contained HTML
  status page) and `ledger.py` (cost estimates and actuals).
- **Quick start:** Laya fine-tuned on Banking77 (`examples/banking77-laya`), with a smoke run that doubles as
  each backend's connection check.
- **Verification:** local runs verified on macOS; Modal live-verified (2026-09-28), a full run on an L4 reaching
  0.822 (target 0.80) in 8.7 minutes for about $0.12; Lightning AI and Kaggle implemented, not yet
  live-verified. The quick start defaults to 2 epochs on Modal L4, with the Mac's `--epochs 1` run kept as the
  alternative. pytest and `claude plugin validate --strict` in CI; five plugin eval cases in `evals/`.
