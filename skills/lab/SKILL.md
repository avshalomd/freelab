---
name: lab
description: Use when the user wants to set up, run or resume an AI or ML experiment with freelab (a model training or evaluation, not a product A/B test) - "set up an experiment", "run an experiment", "start a lab", "fine-tune this and tell me if it helps", "resume the lab", "run the quick start", "what is the lab doing". The entry point: the loop and the rules.
---

# freelab lab

You run the experiments the user asks for, inside their project: a charter, a plan, compute (this machine
within its allowance, and the free tiers the user connected), a live status page, a report, a cleanup and a
handoff.

**Scope.** The rest of the project and the session is the user's other work, often the bigger part. `lab/` is the
experiments' area, not the project. The charter, report,
next steps and handoff cover freelab's runs only. After the report and the next steps, go back to what the user
was doing.

- `${CLAUDE_PLUGIN_ROOT}` is the freelab plugin directory. `python3` is the project's Python (`python` where
  `python3` is missing).
- `lab/` holds the lab's records (charter, plan, `status.json` and `status.html`, ledger, report, handoff,
  `results.tsv`, `cleanup.jsonl`, `blocks/`, `*-run1.md` copies), `runs/<run-id>/`, `backends/` (the Modal app,
  Kaggle kernel folders, staged copies), `worktrees/` and small process files of the poll and the hooks.
- Experiment code you write or copy goes in `experiments/<name>/` (or where the user chooses), never the project
  root.

## Start or resume

0. If `${FREELAB_HOME:-$HOME/.freelab}/onboarded` is missing, go to `onboard` first. The marker is per machine,
   the keys per project: in a project whose `.env` lacks them, a CLI's auth error goes to `onboard` step 5f.
1. If `lab/handoff.md` exists, read it first. Then read `lab/charter.md`, `lab/plan.md` and `lab/status.json`,
   and check every run the handoff lists as running (its watch command) before starting anything new.
2. **"Resume the lab" with nothing running:** say where the lab stands in a few lines (the last report's bottom
   line, a research loop's branch `lab/<tag>` and what it kept, open decisions), then ask the next-steps question
   of `report` §4. Do not restart the first-run checklist.
3. No lab yet: the first-run checklist below.

## The gate

No run is launched until `lab/charter.md` holds a numeric target (a number and a direction) and a budget (USD
beyond free credit, and wall-clock hours); if either is missing, go back to `plan`. The one exception is the
`--smoke` connection check (`compute` §3). Every launch logs its cost estimate first (`compute` §6).

## First-run checklist

After every run comes the report (`report`), with no prompt from the user.

1. **Onboard** (`onboard`): the free services the user wants, each through its connection check, and this
   machine's allowance.
2. **Charter and plan** (`plan`): the recommended charter, each decision explained, then one question.
3. **Run it:** a planned set of runs ("fine-tune this and tell me if it helps"; `compute`, watched with
   `status`), or a research loop ("try to beat it"; `research`), one experiment after another without asking
   in between while within the budget.
4. **Report** (`report`): the report, the next steps in one question, then the handoff.
5. **Clean up** (`cleanup`): the light clean always; the deep clean only on a yes.

**The hooks** act only in a project that uses freelab, on freelab's own runs and storage: the guard blocks
reading `.env` and key files and a launch that fails the gate, and asks before deleting freelab's cloud data; the
Stop hook reminds you of a missing report. When one blocks a call, do what its message says; never work around it.

## Operating rules

1. **Secrets** (the guard enforces this; `onboard` step 5f has the procedure).
   - Keys live in the project's `.env`, which the human fills in. In a git repository, `.env` is in `.gitignore`.
     You create `.env` and its empty placeholders with `${CLAUDE_PLUGIN_ROOT}/scripts/env.sh add NAME...`; never
     ask the human to create it.
   - Never read `.env` or a key file (`~/.modal.toml`, `~/.kaggle/`, `~/.lightning/`) into this session, never
     copy or commit them, never print a token or the environment. Allowed: `env.sh add`, `env.sh check NAME...`
     (prints only `present` or `missing`), and opening `.env` in the user's editor (`open -t .env`).
   - Keys reach a command only through `${CLAUDE_PLUGIN_ROOT}/scripts/withenv CMD...`, which loads `.env` into
     that one command and prints nothing.
   - Never type a card number, password or key into a form; the human types. A key that appears in the chat or
     output is not repeated, and the human revokes it.
2. **Money.** Free credit is the default. Before cloud credit is spent, state the cost and time estimate and get
   a yes. The approved charter and plan are that yes for the runs they list; anything beyond them, beyond free
   credit or beyond the budget needs a new yes. Every estimate goes in the ledger. A move between backends within
   the plan needs no new question, but a move from Kaggle (no spend) to a backend that spends is spending.
3. **Every experiment feeds a decision**, or it is dropped or brought back to the user.
4. **Bugs are fixed; decisions go to the user,** with a recommendation.
5. **Smoke before scale.** Nothing runs longer than a smoke on a backend that has not passed its connection check.
6. **Resumable runs only.** Long runs follow the run contract (`--out`, `--resume`, `--max-minutes`, `--smoke`;
   `metrics.jsonl`, `status.txt`, checkpoints; exit 3 means stopped and resumable). A preemption is recovered.
7. **Third-party code** (`trust_remote_code`, vendored heads) is read in full before it runs.
8. **The user's machine.** Stay within the allowance. One GPU job at a time. Big local jobs go in the night
   window. Anything above the allowance is the user's call.
9. **Honest reporting.** Numbers with intervals, the baseline beside every result, caveats stated plainly.
10. **Explain before you ask.** Before any question: what is being decided and why it matters, each option and
    what it means for them (time, money, their computer, what they learn), your recommendation and why.
11. **No terminal assumed.** The user may work in the Claude Code desktop app with no terminal. Do setup steps
    yourself where safe (installs, CLI sign-ins that open a browser tab, files), and describe what only the user
    can do in app or browser terms. Never ask them to run a command in a terminal.
