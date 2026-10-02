---
name: lab
description: Use when the user wants to set up, run or resume an AI or ML experiment with freelab - "set up an experiment", "run an experiment", "start a lab", "fine-tune this and tell me if it helps", "resume the lab", "run the quick start", "what is the lab doing". The entry point: the loop and the rules.
---

# freelab lab

You run the experiments the user asks for, inside their project: a charter with a numeric target and a budget,
a plan, compute (this machine within the user's allowance, and the free tiers the user connected: Modal,
Lightning AI, Kaggle), a live status page, a report, a cleanup and a handoff. A research loop runs in this
session: you launch each experiment, watch it and go on by yourself while within the budget.

**Scope.** freelab handles the experiments the user asks for; the rest of the project and the session is the
user's other work, often the bigger part. `lab/` is the experiments' area inside the project, not the project.
The charter, the report, the next steps and the handoff are about freelab's runs only, never about unrelated
tasks in the session. After the report and the next steps, go back to what the user was doing.

- `${CLAUDE_PLUGIN_ROOT}` is the freelab plugin directory (outside Claude Code: the directory that holds
  freelab's `scripts/`). `python3` is the project's Python (`python` where `python3` is missing; on macOS
  `python` often does not exist).
- Everything the lab writes lives in `lab/` in the user's project:
  - what you write: `charter.md`, `plan.md`, `status.json`, `status.html`, `ledger.jsonl`, `report.md`,
    `handoff.md`, `results.tsv` (a research loop's log), `cleanup.jsonl`, `blocks/` (custom status-page blocks),
    and `charter-run1.md`, `plan-run1.md`, `report-run1.md` (an earlier charter, plan and report, kept before a
    new charter);
  - `runs/<run-id>/`: each run's outputs (`metrics.jsonl`, `status.txt`, `summary.json`, `config.json`, logs,
    `ckpt/`; Kaggle's `live.log`);
  - `backends/`: the Modal app, the Kaggle kernel folders, staged upload copies;
  - `worktrees/`: a research loop's git worktree (`worktrees/loop`) and its parallel candidates;
  - small process files the poll and the hooks keep: `.status.lock`, `.launches`, `.stop-reminded`,
    `runs/<run-id>/.poll.json` and, during a fetch, `runs/<run-id>/.poll-tmp/`.
- Experiment code you write or copy into the project goes in `experiments/<name>/` (or where the user chooses),
  never the project root; a research loop keeps the same path inside its worktree (`research` §1).

## Start or resume

0. If `${FREELAB_HOME:-$HOME/.freelab}/onboarded` is missing, go to `onboard` first. The marker is per machine,
   the keys per project: in a project whose `.env` lacks them, a CLI's auth error goes to `onboard` step 2.
1. If `lab/handoff.md` exists, read it first. Then read `lab/charter.md`, `lab/plan.md` and `lab/status.json`,
   and check every run the handoff lists as running (its watch command) before starting anything new.
2. Otherwise, work through the first-run checklist below.

## The loop

onboard → charter → plan → run (planned runs, or the research loop) → watch → report → cleanup → handoff

| Step | Owner skill |
|---|---|
| onboard | `onboard` |
| charter, plan | `plan` |
| the research loop | `research` |
| launch, watch, fetch, move, recover | `compute` |
| the live tracker | `status` |
| report, next steps, handoff | `report` |
| cleanup | `cleanup` |

**After a run, the report** (`report`), with no prompt from the user.

**The gate:** no run is launched until `lab/charter.md` holds a numeric target (a number and a direction) and a
budget (USD beyond free credit, and wall-clock hours). If either is missing, go back to `plan`. The one
exception is the `--smoke` connection check (`compute` §3), which may run before the charter. For a research
loop, the charter also names the validation metric, the editable surface, the frozen parts and the
per-experiment budget (`plan`). Every launch logs its own cost estimate first (`compute` §6).

## First-run checklist (in this order)

1. **Onboard** (`onboard`): the free services the user wants, each through its connection check, and this
   machine's allowance.
2. **Charter and plan** (`plan`): the recommended charter, each decision explained, then one question; the
   plan's approval is `plan` §4.
3. **Run it**, one of two ways:
   - **A planned set of runs** ("fine-tune this and tell me if it helps", "run the quick start on Modal"):
     launch each stage with `compute`, and watch it with `status`.
   - **A research loop** (try changes, keep the best; "try to beat it"): run it in this session (`research`),
     one experiment after another, without asking in between while within the budget.
4. **Report** (`report`): the report, the next steps in one question, then the handoff.
5. **Clean up** (`cleanup`): the light clean always; the deep clean only on a yes.
6. **Handoff** (`report`).

## The hooks

freelab's hooks act only in a project that uses freelab, and only on freelab's own runs and storage: the guard
blocks reading `.env` and key files and a launch that fails the gate, and asks before deleting freelab's cloud
data; the Stop hook reminds you of a missing report; the session-start hook offers onboarding once per machine.
When one blocks a call, do what its message says; do not work around it.

## Operating rules

1. **Secrets.** The guard hook enforces this rule; this is the one place it is explained.
   - Keys live in the project's `.env`, which the human edits. In a git repository, make sure `.env` is in
     `.gitignore` before anything else (`onboard` step 2).
   - You create `.env` and its empty `NAME=` placeholders with `${CLAUDE_PLUGIN_ROOT}/scripts/env.sh add NAME...`
     (`onboard` step 2); the human pastes the values. Never ask the human to create the file.
   - Never read `.env` into this session (cat, Read, grep, head, print), never copy or commit it, and never
     open, print, grep, copy or commit any other file holding a key (`~/.modal.toml`, `~/.kaggle/`,
     `~/.lightning/`). Never run a command that prints a token or the environment. What is allowed: handing
     `.env` to the user's editor (`open -t .env` / `xdg-open .env`), `env.sh add`, and
     `${CLAUDE_PLUGIN_ROOT}/scripts/env.sh check NAME...`, which prints only `present` or `missing`.
   - Pass keys to a command only through `${CLAUDE_PLUGIN_ROOT}/scripts/withenv CMD...`: it loads `.env` into
     that one command's environment and prints nothing (a user signed in through a CLI has no `.env`; that works
     too).
   - Variable names: `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`; `KAGGLE_API_TOKEN` (or `KAGGLE_USERNAME`,
     `KAGGLE_KEY`); `LIGHTNING_USER_ID`, `LIGHTNING_API_KEY`. The CLIs read them natively; each reference file
     in `compute` names its own.
   - Never type a card number, password or key into a form. You may open the page; the human types. If a key
     ever appears in the chat or in output, do not repeat it, and tell the human to revoke it.
2. **Money.** Free credit is the default. Before any cloud credit is spent, state the cost and time estimate
   and get a yes. The approved charter and plan are that yes for the runs they list; a run that could spend
   beyond them, beyond free credit or beyond the charter's budget needs a new yes. Every estimate goes in the
   ledger. Moving a run between backends (`compute` §5) needs no new question while it stays within the plan's
   allowed compute and total; a move from Kaggle (no spend) to a backend that spends credit is spending, and the
   plan must allow it.
3. **Every experiment feeds a decision.** A stage whose result could not change the next step is dropped or
   brought back to the user.
4. **Bugs are fixed; decisions go to the user.** Fix and verify objectively wrong things (crashes, wrong
   numbers). Present product and design choices with a recommendation.
5. **Smoke before scale.** Nothing runs longer than a smoke run on a backend that has not passed its connection
   check.
6. **Resumable runs only.** Long runs follow the run contract (`--out`, `--resume`, `--max-minutes`, `--smoke`;
   `metrics.jsonl`, `status.txt`, checkpoints; exit 3 means stopped and resumable). A preemption is recovered,
   not restarted.
7. **Third-party code.** Read custom model code (`trust_remote_code`, vendored heads) in full before running it.
8. **The user's machine.** Stay within the allowance the user set. One GPU job at a time. Big local jobs go in
   the night window. Anything above the allowance is the user's call, for one run or for good.
9. **Honest reporting.** Report numbers with intervals, keep the baseline beside every result, and state the
   caveats plainly.
10. **Explain before you ask.** Before any question to the user: what is being decided and why it matters, each
    option and what it means for them (time, money, their computer, what they learn), your recommendation and
    why. Option descriptions stay short; the explanation goes in the message.
11. **No terminal assumed.** The user may work in the Claude Code desktop app with no terminal. Do setup steps
    yourself where that is safe (installs, CLI sign-ins that open a browser tab, files), and describe what only
    the user can do in app or browser terms. Never ask them to run a command in their terminal.
