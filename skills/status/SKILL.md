---
name: status
description: Use when a freelab lab has runs to watch - "show the status", "how are the lab's runs doing", "update the status page", "is the run done yet", "watch the run", "check on the runs". Keeps lab/status.json and the live page current; opens and explains it. Not for CI or deploy runs.
---

# status: the live status page

If the `lab` skill isn't loaded this session, load it first: it holds the rules. The page, `lab/status.html`, is
one self-contained file rendered from `lab/status.json` and the runs' `metrics.jsonl`. While a run is queued,
starting or running, it reloads itself at the poll's cadence (§5).

## 1. Start `lab/status.json`

If it does not exist, create it from `status_page.new_status`, with the goal from `lab/charter.md` (for a
research loop, the goal's metric and target are the validation ones):

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 - <<'EOF'
import json, status_page
doc = status_page.new_status(
    {"text": "GOAL", "metric": "accuracy", "target": 0.80, "direction": "max"},
    {"usd_limit": 30, "usd_spent": 0, "free_credit_note": "limit = USD 0 budget + USD 30 Modal free credit",
     "usd_free": 30})
open("lab/status.json", "w").write(json.dumps(doc, indent=2) + "\n")
EOF
```

A poll started with no `status.json` (onboarding's connection check, before any charter) writes a minimal one
itself (target "none set yet"); once the charter exists, set its real goal and numeric target with
`status_page.py set --lab lab goal '<JSON>'` (§2).

`direction` is `max` or `min`. The ledger holds list prices, free credit included, so `usd_limit` is the
charter's budget plus the free credit the lab may use; `usd_free` (optional) is the free credit;
`free_credit_note` says how it splits. The schema is strict (unknown keys fail). `stages` are
`{name, state, detail}` (`planned`, `running`, `done`, `skipped`), the same names and order as `lab/plan.md`;
`best` is `{value, run, at}` or null; `decisions` are `{title, text, rec}`; `events` are `{t, text}`, newest
first; `runs` belong to the poll (§2).

## 2. What the poll writes, and what you write

**The poll** owns each watched run's entry: on every check it sets `state`, `step`, `total`, `metric` (the
latest validation value of the goal's metric), `eta`, `detail`, `link` and `expected_minutes`, adds an event for
each new validation check and each change of state, and renders the page. The state comes from the run's
`status.txt` (`done`, `stopped (...)`, `failed: ...`; none yet → starting; anything else → running) and, on
Kaggle and Lightning AI, from the provider's job state (their references, **Watch, fetch, stop**). `step` and
`total` come only from real data and stay null while unknown, so the page never shows a made-up "0% done".

**You** own the rest. After each poll exits, after each research-loop experiment, and when something happens:
1. `best`: the best value of the charter's metric across the runs (by `direction`); in a research loop, the best
   kept validation value in `lab/results.tsv`.
2. `budget.usd_spent`: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py total --lab lab`.
3. `stages`, `decisions` (the page flags one at the top when the user has to choose), and the events the poll
   does not write: a new best, the target met, a move, a cleanup, "research loop started" and "research loop
   ended".

Never edit `lab/status.json` with Edit or Write while it exists: the poll rewrites it on every check. Each change
is one command, safe while a poll runs (it takes the poll's lock, validates, writes atomically and re-renders):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/status_page.py event --lab lab "EVENT"
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/status_page.py set --lab lab best '{"value": 0.83, "run": "ID", "at": "ISO TIME"}'
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/status_page.py set --lab lab budget.usd_spent "$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py total --lab lab)"
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/status_page.py set --lab lab stages '[{"name": "Baseline", "state": "done", "detail": "0.81"}]'
```

`set` takes `best`, `budget` or one `budget.NAME`, `stages`, `decisions`, `goal`, `layout` or
`refresh_seconds`, and the value as JSON. A list is set whole: read the current one, change it, set it. Exit 2
says what is wrong. Events keep the latest 50, plus every "research loop ..." event. The page reads the metrics
and a research loop's `lab/results.tsv` itself: do not copy them into `status.json`.

## 3. Render and publish

- Render: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/status_page.py lab` writes `lab/status.html` (the poll does it on
  every check). Exit 2 means `status.json` is invalid: its message names the key.
- The local file is the live page: an open browser tab follows every check.
- Publish (optional): with the claude.ai Artifact tool, as a private artifact, when the user wants a link. It
  changes only when re-published: re-publish the same file to the same URL whenever you act (a poll's exit,
  each experiment, a user's message) and once at the end. Never publish it publicly.

## 4. Open it when the first run starts

When the first run after the charter starts, and whenever a run starts while the page is not reloading itself,
render the page and show it unasked: `open lab/status.html` (macOS) or `xdg-open lab/status.html` (Linux), with
the path, the published link if any, and the provider's run link (`compute` §4). Onboarding's connection check
opens no page. Then explain it in three short lines, for example:
1. "The top sentence says what is happening now, with a link to the run on <provider>; the cost box shows the
   spend against the limit."
2. "The first chart shows the score climbing from its start (lower dashed line) toward the target (upper one)."
3. "The Training health card shows the training loss (how wrong the model still is on its training examples; it
   should fall) and a verdict: still improving, levelling off or plateaued, so whether more training helps."

Say once that the page updates by itself while the run goes, that on Kaggle the charts arrive with the results
at the end while the top sentence follows the live log, and that the details at the bottom hold the numbers.

## 5. Watch with the poll

This is the one description of the poll; the other skills and the references point here.

- **Start:** right after every launch (a planned run or a research-loop experiment), with Bash
  `run_in_background`:
  `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/poll.py BACKEND ID --expected-minutes M --link URL`, plus the backend's
  extra flags from its reference. Pass `--expected-minutes` from the plan's estimate. Never wait with a `sleep`
  loop in the foreground: you are notified when the poll exits.
- **Cadence** (`--every SECONDS` overrides it): every 30 s in the first 5 minutes and for runs under 30 minutes;
  every 1-2 minutes up to about 3 hours; 5 minutes up to about 12 hours; 15 minutes beyond. The page reloads at
  the same interval.
- **Output:** validation lines only (never a test score), then `final: <state> step=<s>/<t> val=<v>`.
- **Exit codes:** `0` done, and the small files (`status.txt`, `metrics.jsonl`, `summary.json`) are in
  `lab/runs/ID/`; `3` stopped, resumable (`compute` §7); `1` failed, gave up after `--max-hours`, or the provider
  says the run ended but its files could not be fetched (fetch them by hand, the reference's **Watch, fetch,
  stop**). A local run paused between nights (`--nights N`) shows as queued ("Paused until the next night window"),
  and the poll keeps watching: never relaunch it.
- **A wrong run id:** `--once` on a run no provider knows exits 1 and records nothing (check the id, or wait a
  minute after the launch); an entry left by a run that never launched goes with `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/status_page.py forget --lab lab RUN_ID`.
- **When it exits:** update `best`, the spend and the stages (§2), re-publish if published, then for a planned
  run fetch what else is needed (`compute`) and go straight on to `report`. A research loop does this after every
  experiment (`research` §3).
- **Stay quiet** when nothing important changed: speak only for a change of state, a new best, the target met, a
  failure or stop, a decision for the user, or the budget running low.

## Building blocks

The default page fits a training run. For another kind of task (an LLM fine-tune with samples, a sweep, batch
inference, a benchmark, RL), pick its blocks at plan time from
`${CLAUDE_PLUGIN_ROOT}/skills/status/references/blocks.md`, which also explains custom blocks.
