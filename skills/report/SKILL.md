---
name: report
description: Use when a freelab lab has results to report or a session with freelab runs is ending - "write the report", "what did we find", "did we hit the target", "summarise the lab", "wrap up the lab", "hand off the lab", "I'm stopping the lab for today". Writes the report, the next steps and the handoff. Not for documents unrelated to the lab.
---

# report: the report and the handoff

If the `lab` skill isn't loaded this session, load it first: it holds the rules (rule 9: intervals, the
baseline beside every result, caveats stated plainly).

**The report always comes after a run.** When the last planned run ends (or a stop rule fires, or the user asks)
and is fetched (`status` §5), come here at once, unprompted; if the user's questions took over, answer them, then
return. Every finished freelab run gets its report, the next steps, the cleanup and the handoff; then go back to
what the user was doing. Write the handoff whenever a session with freelab runs ends, even mid-run. Both cover
freelab's runs only.

## 1. Gather

- `lab/charter.md` (target, baseline, budget), `lab/plan.md`, `lab/status.json` (runs, decisions);
- each run's `summary.json` and `metrics.jsonl` (fetched). For Train longer rounds and research experiments, read
  only validation; the test score only for the chosen one (its `<id>-test` scoring run; `research` §4);
- the Training health verdict of the best run, as the status page shows it:
  `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -c "import runlib, status_page;
  print(status_page.training_health(runlib.read_metrics('lab/runs/ID/metrics.jsonl'), 'accuracy', 'max'))"`
  (the charter's metric and direction): `state` `improving`, `levelling` or `plateau`, with the `reason`; None
  means too little data;
- the spend: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py total --lab lab` (`lab/ledger.jsonl` says which
  entries are estimates);
- for a research loop: `lab/results.tsv` and the branch `lab/<tag>`; log "research loop ended" if missing.

## 2. The interval

- A proportion (accuracy and the like) on n items: the Wilson 95 % interval,
  `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/stats.py wilson P N` prints `lo hi` (e.g. `wilson 0.828 3076`).
- Two runs on the same items: say whether the intervals overlap. Another metric: the spread over seeds, or say
  there is no interval and why.

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
<ledger total in USD, which parts are estimates, free credit used, against the budget in USD and hours>

## Caveats
<sample size, one seed, test-set reuse, framing, anything fixed or changed mid-lab>

## Decisions for you
1. **<decision>.** Recommendation: <what and why>.
```

**For a research loop**, add after "Target and result": the number of experiments, kept and crashed, and which
condition ended the loop; the baseline and the best kept result on validation, on the decision GPU type, with
their intervals on the validation items; the single test number of the best kept commit, with its interval (the
result the target is judged on); and the kept experiments from `lab/results.tsv`:

```markdown
## Kept experiments
| Id | Commit | GPU | Validation <metric> | Change |
|---|---|---|---|---|
```

Its caveats: a gain inside the validation interval may be noise; validation and test disagreeing by more than
the interval; the test split scored once; experiments that trained less than the baseline (the quick start's)
favoured the baseline. When nothing was kept, the bottom line says so plainly.

## 4. Next steps

Give the bottom line in the chat with the path. After a user's first experiment, add a short recap so they can
drive the next one: the steps that ran, where each file is in `lab/`, what the result means for its decision,
and how to start their own ("set up my own experiment").

Then ask one question (AskUserQuestion when available, else a short numbered list), up to 4 options chosen by
context, the recommended one first with "(Recommended)". Before it, explain each option in a line or two: what it
does, how long, what it costs, what they would learn.

- **Try the model** (Recommended after a user's first experiment that ships a demo, such as the quick start's
  `demo.py`): the trained model answers on this computer; nothing leaves it. USD 0, about 3.7 GB of disk (the
  final checkpoint, about 2.1 GB, plus the base model, about 1.7 GB unless cached). Fetch the final checkpoint
  (the backend's reference; this machine already has it), check its `COMPLETE` marker, then from the project
  root, with Bash `run_in_background` (EXP: `${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya`, or after a research
  loop `lab/worktrees/loop/experiments/banking77-laya`):
  `(p="$PWD"; cd "EXP" && PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" uv run --no-project --with-requirements requirements.txt python demo.py --ckpt "$p/lab/runs/ID/ckpt/step-NNNNNNNN")`.
  Give the link, http://127.0.0.1:8077. When the user is done, stop it (`pkill -f "demo.py --ckpt"`) and ask
  again with the remaining options; a demo still running goes in the handoff.
- **Train longer:** rounds of one epoch from the best run, each a warm start from the round before, until a
  round no longer improves validation (up to 3). `plan` §1 explains it (its design:
  `${CLAUDE_PLUGIN_ROOT}/skills/plan/references/train-longer.md`), with estimates from the measured run. The
  rounds skip the test split; the caveat: the chosen round's scoring run scores it once more.
- **Try to beat it:** a research loop on the same task, from the charter's "Next: try to beat it" when it has one
  (the quick start: at most 2 one-epoch experiments toward validation accuracy >= 0.85, about 10-17 minutes on
  Modal's L4, USD 0 beyond free credit). `plan` explains its setup, `research` runs it in its own git worktree:
  the user's files are never touched, and the best version ends on a branch.
- **Clean up and stop** (Recommended after a research loop): the `cleanup` skill, then the handoff (§5);
  nothing bigger than leftover process files goes without a yes.

How to choose, by the Training health verdict: "still improving" recommends Train longer; "levelling off" recommends Try to beat it, with Train
longer after it; "plateaued" (or no verdict) recommends Try to beat it and leaves Train longer out or last, saying
why (more of the same training will not help; a change will). Try the model stays first until offered or done.
After a research loop, "Clean up and stop" comes first; "Try to beat it" only when the target was not met and
free credit is left, with a new idea or a larger budget named; Try the model uses the best kept run's checkpoint.

A new charter (Train longer, Try to beat it) first keeps the first run's files: `mv lab/charter.md
lab/charter-run1.md`, the same for `plan.md` and `report.md` (later ones `-run2` and so on; run folders, ledger
and status stay).

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
  (`<change>`), validation <value>, test <value>; or "nothing kept". To take it: say "merge the lab branch".
- `lab/results.tsv` holds every experiment; `git log lab/<tag>` the kept ones.
- Stopped before its end condition: say "resume the research loop"; it goes on from the tip of `lab/<tag>`.

## Re-arm prompt
Paste this into a new session:
> Resume the freelab lab in <project path>: read lab/handoff.md first, then lab/charter.md and lab/plan.md;
> check the runs listed as running, refresh the status page, and continue from <next step>.
```

List every run still running with its stop command. Stop any poll when nothing runs; render the page a last
time (and re-publish, if published).
