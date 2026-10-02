---
name: status
description: Use when a freelab lab has runs to watch - "show the status", "how are the lab's runs doing", "update the status page", "is the run done yet", "watch the run", "check on the runs". Keeps lab/status.json and the live page current; opens and explains it.
---

# status: the live status page

If the `lab` skill isn't loaded this session, load it first: it holds the rules. Each backend's watch steps are in
`${CLAUDE_PLUGIN_ROOT}/skills/compute/references/<backend>.md`, **Watch, fetch, stop**.

The page, `lab/status.html`, is one self-contained file rendered from `lab/status.json` and the runs'
`metrics.jsonl` (its blocks: Building blocks, below; how to explain it to the user: §4). While a run is queued,
starting or running, it reloads itself every `refresh_seconds`, which the poll sets to its own cadence (§5).

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

`direction` is `max` or `min`. The ledger holds list prices, free credit included, so `usd_limit` is the
charter's budget plus the free credit the lab may use, `usd_free` (optional) is the free credit in dollars,
marked on the cost meter, and `free_credit_note` says how it splits. The schema is strict (unknown or missing
keys fail; the optional keys may be missing):
- `stages` (optional): the plan's stages, `{name, state, detail}`, `state` one of `planned`, `running`, `done`,
  `skipped`; shown as the plan's timeline. Keep them in step with `lab/plan.md`: the same names and order, the
  state changed when a stage starts, ends or is cut, `detail` one line;
- `runs`: a list of `{id, backend, state, step, total, metric, eta, detail, started}`, plus the optional `link`
  (the provider's page for the run, an http(s) URL) and `expected_minutes`. `state` is one of `queued`,
  `starting`, `running`, `stopped`, `done`, `failed`. `backend` is the backend's name, then the GPU type if any
  (`lightning T4`, `modal L4`, `kaggle T4`, `local`): the page says "Lightning AI (T4)" or "this computer";
- `best`: `{value, run, at}` or null;
- `budget`: `{usd_limit, usd_spent, free_credit_note}`, and `usd_free` if known;
- `decisions`: a list of `{title, text, rec}`;
- `events`: a list of `{t, text}`, newest first: the latest 50, plus every "research loop ..." event;
- `layout` (optional): the page's blocks, in order (Building blocks, below); `refresh_seconds` (optional): the
  reload interval, set by the poll;
- `updated`: an ISO time.

## 2. What the poll writes, and what you write

**The poll** (`poll.py`, §5) owns each watched run's entry: on every check it sets `state`, `step`, `total`,
`metric` (the latest validation value of the goal's metric), `eta`, `detail`, `link` and `expected_minutes`, adds
an event for each new validation check and each change of state, and renders the page. How it maps the state:
- the run's `status.txt` (all backends; local runs read it in place): none yet → starting (queued stays queued);
  `done` → done; `stopped (...)` → stopped; `failed: ...` → failed; anything else → running;
- Kaggle, from `kaggle kernels status`: queued → queued; running → running once a progress line or a metric
  exists, else starting; complete, error or cancelled → the fetched `status.txt` decides;
- Lightning AI, from `lightning job inspect`: see its reference, **Watch, fetch, stop**; running with no
  `status.txt` line yet → running; once the job has ended, the fetched `status.txt` decides;
- a run whose provider says it ended but whose files cannot be fetched after a few checks ends as done, failed or
  stopped from the provider's word, with a detail saying to fetch it by hand.

`step` and `total` come only from real data (a metrics line or a progress line) and stay null while unknown, so
the page never shows a made-up "0% done". In a research loop the poll prints and records validation lines only,
never test lines.

**You** own the rest. After each poll exits, after each research-loop experiment, and when something happens:
1. `best`: the best value of the charter's metric across the runs (by `direction`); in a research loop, the best
   kept validation value in `lab/results.tsv`.
2. `budget.usd_spent`: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py total --lab lab`.
3. `stages`, `decisions` (the page flags one at the top when the user has to choose), and events the poll does
   not write: a new best, the target met, a move, a cleanup, "research loop started" and "research loop ended".
4. A run's entry is the poll's: it adds the run, with the `link` and `expected_minutes` you pass it (`--link`,
   `--expected-minutes`).

Never edit `lab/status.json` with Edit or Write while it exists: the poll rewrites it on every check, and a hand
edit can undo the poll's or be undone by it. Each change is one command, safe while a poll runs (it takes the lock
the poll uses, validates the result, writes `status.json` atomically, sets `updated` and re-renders the page):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/status_page.py event --lab lab "EVENT"
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/status_page.py set --lab lab best '{"value": 0.83, "run": "ID", "at": "ISO TIME"}'
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/status_page.py set --lab lab budget.usd_spent "$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py total --lab lab)"
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/status_page.py set --lab lab stages '[{"name": "Baseline", "state": "done", "detail": "0.81"}]'
```

`set` takes `best`, `budget` or one `budget.NAME`, `stages`, `decisions`, `goal`, `layout` or
`refresh_seconds`, and the value as JSON. A list (`stages`, `decisions`) is set whole: read the current one, change
it, set it. Exit 2 says what is wrong and writes nothing. Events stay newest first; the list keeps the latest 50,
plus every "research loop ..." event.

The page reads the rest itself from `lab/runs/ID/metrics.jsonl` (the start, each split, the loss, the Training
health verdict) and from a research loop's `lab/results.tsv` (the experiments chart and table): do not copy
those into `status.json`.

## 3. Render and publish

- Render: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/status_page.py lab` writes `lab/status.html` (the poll does it on
  every check). Exit 2 means `status.json` is invalid: its message names the key; fix it and render again.
- The local file is the live page: it reloads itself while a run is active, so an open browser tab follows
  every check.
- Publish (optional): with the claude.ai Artifact tool, publish `lab/status.html` as a private artifact when the
  user wants a link (for example away from this computer). A published page changes only when it is
  re-published: re-publish the same file to the same URL whenever you act (a poll's exit, each research-loop
  experiment, a user's message) and once more at the end. Where only the published page can be seen (no local
  browser), watch with `/loop` or a session cron every few minutes running the poll with `--once`, and
  re-publish after each. Never publish it publicly.

## 4. Open it when the first run starts

When the first run after the charter starts (the quick start's run, or a lab's first stage), and again whenever a
run starts while the page is not reloading itself, render the page and show it without being asked. Onboarding's
connection check opens no page. To show it: open the local file, `open lab/status.html` (macOS) or
`xdg-open lab/status.html` (Linux), and give the path (and the published link, if any). Give the provider's run
link too (`compute` §4).

Then explain it in three short lines, for example:
1. "The sentence at the top says what is happening now, in plain words, with a link to the run on <provider>; the
   cost box shows what has been spent against the limit, all from free credit so far."
2. "The first chart shows the score climbing from where it started (the lower dashed line) toward the target
   (the upper dashed line; for a loss-like metric it falls); the bar above it shows how far it has come."
3. "The Training health card shows the training loss, how wrong the model still is on its training examples
   (it should fall), and a verdict: still improving, levelling off or plateaued, with the reason. It tells us
   whether more training would help."

Say once that the page updates by itself while the run is going (every 30 seconds early on, less often for a
long run), that on Kaggle the charts and the Training health card arrive with the results at the end while the
top sentence follows the run's progress, and that the details at the bottom hold the technical numbers.

## 5. Watch with the poll

- **Every run gets a poll**, a planned run as a research-loop experiment: right after the launch, start
  `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/poll.py BACKEND ID --expected-minutes M --link URL` with Bash
  `run_in_background` (the backend's extra flags are in its reference). It runs until the run ends, then prints
  `final: <state> step=<s>/<t> val=<v>` and exits `0` (done), `3` (stopped) or `1` (failed, or it gave up after
  `--max-hours`). You are notified then. Never wait with a `sleep` loop in the foreground.
- **Cadence** (a guideline the poll follows; `--every SECONDS` overrides it): every 30 s in the first 5 minutes
  after the launch, to catch an early crash; then by the expected length: under 30 minutes every 30 s; up to
  about 3 hours every 1-2 minutes; up to about 12 hours every 5 minutes; longer every 15 minutes. The page's
  reload follows the same interval. Pass `--expected-minutes` from the plan's estimate.
- **When it exits:** update `best`, the spend and the stages with `status_page.py set` (§2; it renders), and
  re-publish if published. Then, for a planned run that ended, fetch what is still needed (`compute`) and go
  straight on to `report` (a research loop: its §3, step 4).
- In a research loop (`research`), the loop does this after every experiment; set up nothing else.
- **Stay quiet in the chat when nothing important changed:** the page updates on every check, but say something
  only for a change of state, a new best, the target met, a failure or stop, a decision for the user, or the
  budget running low.

## Building blocks

The page is a list of blocks, in the order of `layout` in `status.json`. Without `layout`, the default fits a
training run: `headline`, `progress`, `charts`, `health`, `plan`, `cost_time`, `details`. The other blocks:
`cost` and `time` (apart), and the parts of `details` on their own: `runs`, `results`, `decisions`, `events`,
`measurements`, `glossary`. Unknown names are skipped.

For another kind of compute-hungry task, pick the blocks at plan time and set `layout`. When no block shows what
matters, write a custom block: `lab/blocks/<name>.html`, static HTML or inline SVG (no scripts: they are
stripped; no external requests), using the page's CSS tokens such as `var(--fg)`, and add `custom:<name>` to
`layout`. Update it when its numbers change. For example:
- **LLM fine-tune:** the default, plus `custom:samples-table` with a few prompts and answers before and after as a
  static table (galleries of samples come in a later version).
- **Research loop or sweep:** `headline`, `progress`, `charts`, `results`, `plan`, `cost_time`, `details`.
- **Batch inference or data processing:** `headline`, `progress`, `custom:throughput` (items done, items per
  minute, errors), `cost_time`, `events`.
- **Benchmark eval:** `headline`, `custom:scores` (a table of tasks and scores with intervals), `runs`,
  `cost_time`, `details`.
- **RL:** `headline`, `charts` (the reward as the goal's metric), `health`, `custom:episodes` (episode length and
  return over time, inline SVG), `cost_time`, `details`.
