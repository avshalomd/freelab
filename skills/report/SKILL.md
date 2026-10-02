---
name: report
description: Use when a freelab lab has results to report or a session with freelab runs is ending - "write the report", "what did we find", "did we hit the target", "summarise the lab", "wrap up the lab", "hand off the lab", "I'm stopping the lab for today". Writes the report, the next steps and the handoff.
---

# report: the report and the handoff

If the `lab` skill isn't loaded this session, load it first: it holds the rules (rule 9: intervals, the
baseline beside every result, caveats stated plainly). Write the handoff whenever a session with freelab runs
ends, even mid-run.

**The report always comes after a run.** When the last planned run ends (or a stop rule fires, or the user asks),
it is fetched and the status page updated (`status` §5), and you come here at once, with no prompt from the user
(freelab's Stop hook reminds you once per finished run without a report). If the user's questions took over in
the meantime, answer them, then return to the report and the next steps. Every finished freelab run gets its
report, the next steps, the cleanup and the handoff; then go back to what the user was doing. The report and the
handoff cover freelab's runs only, never the session's other work.

## 1. Gather

- `lab/charter.md` (target, baseline, budget), `lab/plan.md`, `lab/status.json` (runs, decisions);
- each run's `summary.json` and `metrics.jsonl` in `lab/runs/ID/` (fetch cloud runs first, `compute` skill;
  on Kaggle the small files, not the checkpoint). For the Train longer rounds and research experiments that
  were not chosen, read only validation (`final_val_accuracy`, the `val` lines); the test score is read only for
  the chosen one (the best round, or the research loop's test number, `research` §4);
- the Training health verdict of the run the next steps build on (the best run), as the status page shows it:
  `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -c "import runlib, status_page;
  print(status_page.training_health(runlib.read_metrics('lab/runs/ID/metrics.jsonl'), 'accuracy', 'max'))"`
  (the charter's metric and direction). Its `state` is `improving` (still improving), `levelling` or `plateau`,
  with the `reason`; None means too little data to judge;
- the spend: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py total --lab lab`, and `lab/ledger.jsonl` for which
  entries are estimates and which are actual;
- for a research loop (`research`): `lab/results.tsv`, the branch `lab/<tag>` and its tip, the best kept commit;
  the status event "research loop ended" is logged (`research` §4; log it now if it is missing).

## 2. The interval

- A proportion (accuracy and the like) on n test items: the Wilson 95 % interval, a standard interval for a
  share that stays sensible near 0 and 1: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/stats.py wilson P N` prints
  `lo hi` (e.g. `wilson 0.828 3076`).
- A difference between two runs on the same items: say whether the intervals overlap, or bootstrap the paired
  items when the per-item predictions are saved.
- Another metric: the spread over seeds when there are several; otherwise say that there is no interval and
  why.

## 3. `lab/report.md`

```markdown
# Report: <charter name>

**Bottom line:** <one or two sentences: target met or not, by how much, and what to do next>

## Target and result
| | <metric> | 95 % interval | n |
|---|---|---|---|
| Target | <e.g. >= 0.80> | | |
| Baseline | <value> | <lo–hi> | <n> |
| Best run (<id>) | <value> | <lo–hi> | <n> |

## What was run
| Run | Backend | What | Minutes | Outcome |
|---|---|---|---|---|

## Costs
<ledger total $X, which parts are estimates, how much free credit was used, against the budget of $Y and
Z hours>

## Caveats
<what could make the result wrong or not carry over: sample size, one seed, test-set reuse, framing, anything
fixed or changed mid-lab>

## Decisions for you
1. **<decision>.** Recommendation: <what and why>.
```

**For a research loop**, the report also has, after "Target and result":
- the number of experiments and how many were kept (and how many crashed), and which condition ended the loop;
- the baseline and the best kept result on validation, on the decision GPU type (say so if the tip was
  re-measured on another type), with their intervals on the validation items;
- the single test number of the best kept commit, with its interval: the result the target is judged on;
- a table of the kept experiments from `lab/results.tsv`, in order:

```markdown
## Kept experiments
| Id | Commit | GPU | Validation <metric> | Change |
|---|---|---|---|---|
```

- a caveat when validation and test disagree by more than the interval (selection on validation may have fit
  noise), a note that the test split was scored once, and, when the experiments trained less than the baseline
  (the quick start's one-epoch experiments), that the comparison favoured the baseline.

## 4. Next steps

After writing the report, give its bottom line in the chat with the path (and the status page link). After a
user's first experiment (the quick start, or their first own one), add a short recap so they can drive the next
one themselves: the steps that ran (charter, plan, launch on <backend>, watching, report), where each file is in
`lab/`, what the result means for the decision it fed, and how to start their own ("set up my own experiment",
with their goal, data and model).

Then ask one question (AskUserQuestion when available, else a short numbered list). AskUserQuestion takes at
most 4 options, so choose up to 4 from those below by context, the recommended one first with "(Recommended)".
Before the question, explain each offered option in a line or two: what it would do, how long, what it costs,
what they would learn.

- **Try the model** (Recommended after a user's first experiment, when the experiment ships a demo, such as the
  quick start's `demo.py`): the trained model answers on this computer. Say that it runs on this computer and
  nothing leaves it, and that it first downloads the final checkpoint, about 2 GB (USD 0; the first start also
  downloads the base model, about 1.7 GB, unless it is cached). Fetch the final checkpoint (the backend's
  reference, `${CLAUDE_PLUGIN_ROOT}/skills/compute/references/<backend>.md`: Kaggle's checkpoint fetch, Modal's
  and Lightning's Move out; this machine already has it), check its `COMPLETE` marker, then start the demo with
  Bash `run_in_background` from the project root (EXP is the experiment directory: the quick start's
  `${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya`, or after a research loop its copy in the loop's worktree,
  `lab/worktrees/loop/experiments/banking77-laya`, or once that branch is merged, `experiments/banking77-laya`):
  `(p="$PWD"; cd "EXP" && PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" uv run --no-project --with-requirements requirements.txt python demo.py --ckpt "$p/lab/runs/ID/ckpt/step-NNNNNNNN")`
  (`--port 8077` is the default; the `PYTHONPATH` lets a project copy of the experiment find the plugin's
  `runlib`, and `--no-project` keeps uv from writing a `.venv` into the plugin folder; without `uv`, offer its
  install line from `onboard` step 5g). Give the link,
  http://127.0.0.1:8077: type a bank message and see the top 5 intents. When the user is done, stop it (the
  background task, or `pkill -f "demo.py --ckpt"`), then ask this question again with the remaining options.
  A demo still running goes in the handoff with its stop command.
- **Train longer** (Recommended when the Training health verdict is "still improving", once Try the model is
  offered or done): more training from the best run, in rounds, each a warm start from the round before, until a
  round no longer improves validation (up to 3 rounds by default). `plan` §1 explains it like any charter (its
  design: `${CLAUDE_PLUGIN_ROOT}/skills/plan/references/train-longer.md`); estimate the time and cost from the measured run (the example
  charter's **Budget** for the quick start). The caveat: the test split is scored once more, for the chosen
  round. Then `compute` launches each round and `status` shows each as a run.
- **Try to beat it** (Recommended when the Training health verdict is "levelling off" or "plateaued", or there
  is no verdict, once Try the model is offered or done): a research loop on the same task, from the charter's
  "Next: try to beat it" section when it has one (the quick start: a short loop of about 15-20 minutes,
  at most 2 one-epoch experiments, validation accuracy >= 0.85, USD 0 beyond free credit). Then `plan` explains the loop's setup, and `research` runs it (its section 1 resets
  the status goal and logs "research loop started"). It works in its own git worktree, so the user's files are
  never touched; the best version ends on a branch they can merge.
- **Clean up and stop** (Recommended after a research loop): the `cleanup` skill, then the handoff (§5). Say in
  one line that the light clean removes only leftover process files, and that it lists the bigger items
  (checkpoints, cloud copies) with what deleting each one means before anything is removed.

How to choose:
- **By the Training health verdict:** "still improving" offers Train longer, recommended. "Levelling off" offers
  Try to beat it first, recommended, and Train longer after it. "Plateaued" (or no verdict) recommends Try to
  beat it and leaves Train longer out, or puts it last, and says why in a line: more of the same training will
  not help; a change will. Try the model stays first, and recommended, until it has been offered or done.
- **After a research loop:** "Clean up and stop" comes first; "Try to beat it" is offered only when the target
  was not met and free credit is left, with a new idea or a larger budget named in its description; Try the
  model uses the best kept run's checkpoint.
- **A new charter** (Train longer, Try to beat it): first keep the first run's files: `mv lab/charter.md
  lab/charter-run1.md`, `mv lab/plan.md lab/plan-run1.md`, `mv lab/report.md lab/report-run1.md` (later ones
  `-run2` and so on; the run folders, ledger and status stay).
- Each of these paths ends with the handoff for freelab's runs; then the session is the user's again.

## 5. `lab/handoff.md`

```markdown
# Handoff: <date and time>

## Still running
- <run id> on <backend>: <state, step/total>. Watch: `<command>`. Stop: `<command>`. Fetch: `<command>`.

## Stopped or finished
- <run id>: <done | stopped | failed>, outputs in `lab/runs/<id>/`, <resumable? the exact relaunch command>

## Open decisions
- <decision, with your recommendation>

## Research loop (if one ran)
- Branch `lab/<tag>` (worktree `lab/worktrees/loop` until the cleanup); best kept commit `<short sha>`
  (`<change>`), validation <value>, test <value>. To take it: `git merge lab/<tag>` in the user's branch.
- `lab/results.tsv` holds every experiment; `git log lab/<tag>` holds the kept ones.
- Stopped before its end condition: say "resume the research loop" in a session in this project; it goes on
  from the tip of `lab/<tag>`, with `lab/results.tsv` and the streak as they are.

## Re-arm prompt
Paste this into a new session:
> Resume the freelab lab in <project path>: read lab/handoff.md first, then lab/charter.md and lab/plan.md;
> check the runs listed as running, refresh the status page, and continue from <next step>.
```

List every run that is still running with its exact stop command, and every poll or refresh still going. Stop
any poll or refresh when nothing is running, then do a final status render (and re-publish, if published).
