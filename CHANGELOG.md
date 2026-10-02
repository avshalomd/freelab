# Changelog

## 0.4.0 - 2026-10-02

Hooks that guard keys, money and the report; a poll that keeps the status page live; fixes from the third live
trial and from an audit of the skills.

- **Hooks** (they act only in a project that uses freelab: `lab/` holds one of freelab's files, or `.env` has the
  line onboarding wrote; a `lab/` folder alone is not enough. Even there, the delete and launch rules cover only
  freelab's own runs and storage: the user's own launches and deletes get no output):
  - **Guard** (`PreToolUse`): denies reading or editing `.env` and the key files (`~/.modal.toml`, `~/.kaggle/`,
    `~/.lightning/`) and commands that print a key or the whole environment; asks before deleting freelab's
    cloud data (`modal volume rm freelab-runs ...`, deletes of a `freelab-...` Kaggle kernel or dataset, Lightning
    deletes of the `freelab` Studio, `freelab-runs/`, `freelab-init/` or a freelab run's job) and denies `modal
    volume delete freelab-runs`; blocks one of freelab's launches (`modal run` of `lab/backends/modal_app.py`,
    `kaggle kernels push` of a kernel folder under `lab/backends/` or with a `freelab-` id, `lightning job run` on
    the `freelab` Studio or into `freelab-runs`, the plugin's `local_run.py`) unless the charter has a numeric
    Target and a Budget, an estimate was logged in the ledger since the last launch, and a Modal, Lightning AI or
    local run has a minutes cap. Smoke runs and `--help` are exempt (from the delete ask too).
    Code run with `python -c`, `node -e`, `perl -e`, `ruby -e` or awk that prints the environment or a key is
    denied. Git commands are left alone: freelab adds no rule to git.
  - **Launch record** (`PostToolUse`, Bash): one of freelab's launches (the guard's test) is recorded in
    `lab/.launches` only once its command has run, so a denied, declined or failed launch does not use up its
    estimate.
  - **Stop:** asks once for the report when a run has finished that no `lab/report*.md` names or postdates (the
    kept `report-run1.md` of a Train longer round counts). Quiet while a poll runs, during a research loop (the
    newest loop event is "research loop started"), and for smoke runs.
  - **Session start:** the onboarding offer comes once per machine: after printing it, the hook writes
    `~/.freelab/nudged` (under `FREELAB_HOME` when set) and stays quiet from then on; "Not now" needs nothing
    written.
- **Scope:** freelab handles the experiments the user asks for; the rest of the project and the session is the
  user's other work. The `lab` skill says so near its top: `lab/` is the experiments' area, the charter, report,
  next steps and handoff cover freelab's runs only, and after the report and next steps the agent goes back to
  what the user was doing. The hooks follow the same scope.
- **Keys, one rule:** the secrets rule is written once, in `lab`, and the guard enforces it. `scripts/withenv`
  loads `.env` into one command (it replaces every `set -a; [ -f .env ] ...` prefix); `scripts/env.sh add`
  writes empty placeholders and `env.sh check` says which keys are filled in, never printing a value.
- **The poll:** `scripts/poll.py BACKEND RUN_ID`, started in the background, replaces the hand-written poll
  loops. It checks the run, updates `status.json` under a lock and renders the page on every check: every 30
  seconds in the first 5 minutes and for short runs, then every 90 seconds up to about 3 hours, 5 minutes up to
  12 and 15 minutes beyond. It exits 0 when the run is done, 3 when it stopped and can resume, and 1 when it
  failed or gave up, and prints only validation lines, so a research loop never sees a test score. On Kaggle it
  restarts the live log stream up to 3 times; on Modal it reads the app id from `--link` and ends the run as
  failed when the app stopped without writing `status.txt`; on Lightning AI a job the provider reports as
  running reads as running before its first status line.
- **Status edits without races:** `status_page.py event` adds an event and `status_page.py set KEY JSON` sets
  `best`, `budget` (or one `budget.NAME`), `stages`, `decisions`, `goal`, `layout` or `refresh_seconds`, each
  under the poll's lock, validated, written atomically and rendered; the skills use them instead of editing
  `status.json`. Events stay newest first and capped at 50, but "research loop ..." events are never trimmed.
- **Run links:** each launch gives the run's page on the provider (passed to the poll as `--link`); the status
  page shows it.
- **Status page blocks:** the page is built from blocks in a `layout` list in `status.json` (headline, progress,
  charts, health, plan, cost and time, details, runs, results, decisions, events, measurements, glossary), plus
  custom static blocks from `lab/blocks/`. `status.json` may also carry `link`, `expected_minutes` and
  `refresh_seconds`. The `status` skill has a Building blocks section with examples (a fine-tune, a research
  loop or sweep, batch inference, a benchmark, RL). The local file is the live page; a claude.ai copy is
  re-published when the agent acts.
- **Placement is cloud first:** a run wanted now goes to a connected cloud service while free credit is left
  (`resources.py check --prefer cloud`); this machine is used when asked, when nothing is connected or for a
  night run, which is offered, never chosen silently.
- **The research loop in its own worktree:** `lab/worktrees/loop` on branch `lab/<tag>`; every edit, commit and
  reset happens there, never in the user's working copy. The quick start's copy goes in
  `experiments/banking77-laya/` in the worktree (experiment code freelab writes or copies into a project goes in
  `experiments/<name>/`, never the project root). At the end the agent names the branch to merge. Candidates use
  sibling worktrees. `autoresearch.md` is marked optional reading.
- **Train longer, in rounds:** up to 3 rounds of one more epoch by default, each a warm start from the round
  before under its own run id, stopping when validation stops improving; only the chosen round's test score is
  read. Written once, in `plan`; each round shows on the status page as a run.
- **Scripts for the arithmetic and the cleanup:** `stats.py wilson P N` replaces the hand formula in the report;
  `cleanup.py inventory|light|remove` does the local cleanup inside a fixed scope.
- **Third-trial fixes:**
  - Modal's money safety is the **Usage limit** (Settings → Usage & billing), explained before asking: what the
    card may be charged beyond the credit; set it as low as the page allows.
  - The measured time and cost per provider live in one place, the Budget of the example's charter; the other
    files point there.
  - A charter change in the user's own words gets the same four parts (what, why, alternatives, what it means)
    before it is applied, then Apply the change or Keep the recommendation.
  - Onboarding checks for `uv` and `npx` and offers the install line, installing only on a yes.
- **Skill text (from the audit):** the eight descriptions shrink from 3,975 to about 2,300 characters; every
  skill but `lab` starts by loading `lab`; cross-skill paths are anchored on `${CLAUDE_PLUGIN_ROOT}`; repeated
  facts are written once; the three cloud references gain a contents line; `local.json` is described under
  `FREELAB_HOME`; the lab's file list is complete, including the poll's small files.
- **Moved here from the `status` skill:** in the second trial the published page sat unchanged for the whole run
  until the user asked, because a published Artifact changes only when re-published. 0.3.1 re-published it on
  every poll; 0.4.0 makes the local file, rendered by the poll, the live page.
- **README:** a Requirements section, the hooks described plainly, and a verification table of what has run live
  and what has not.
- **A shorter quick-start loop:** "Try to beat it" targets validation accuracy of at least 0.85 against the quick
  start's own run, with 2 one-epoch experiments of at most 15 minutes and a 20-minute cap, about 15-20 minutes in
  all (an estimate, not yet measured). The new `--skip-test` flag in `train.py` leaves out the test scoring, so
  experiments never see test; a scoring run without it is needed only when an experiment wins. The decision GPU
  type defaults to the type of the first run. The single quick-start run stops after its 2 epochs or 20 minutes.
- **Desktop-friendly setup:** the agent runs every install and sign-in itself (`modal token new` and `kaggle auth
  login` in the background, tools in `~/.local/bin` by full path) and never asks the user to open a terminal or
  change their PATH; Lightning AI uses the `.env` key. `.gitignore` is touched only inside a git repository.
- **Money asks:** the connection check is asked first, with its estimate (**Run the check** or **Not now**); an
  approved charter or plan is the yes for the runs inside it; moving a run from Kaggle to a paid service counts as
  spending; a loop compares the ledger total with `budget.usd_limit`.
- **Report:** for runs and rounds that were not chosen, only validation scores are read.
- **Cloud names:** the Kaggle and Lightning AI names come from the experiment folder's name, lowercased.
- **Docs and evals:** internal planning notes are gone from `docs/`; the status-page picture is re-shot on a
  Modal L4 quick start; the evals use only synthetic data, seed their own home, and gain `charter-has-target`
  and `onboard-modal-key`. CI tests Python 3.10 and 3.12.

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
