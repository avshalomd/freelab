---
name: research
description: Use when a freelab lab should improve an experiment by itself until a target - "start the research loop", "autoresearch", "keep improving it", "run experiments until the target", "try to beat it", "resume the research loop". Runs the keep-or-reset loop in its own git worktree.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/poll.py:*), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py:*), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/status_page.py:*), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/stats.py:*), Bash(git -C lab/worktrees/loop add:*), Bash(git -C lab/worktrees/loop commit:*), Bash(git -C lab/worktrees/loop reset --hard:*)
---

# research: the research loop

If the `lab` skill isn't loaded this session, load it first: it holds the rules. The loop follows the pattern of
Karpathy's autoresearch, adapted to free compute and a charter. `references/autoresearch.md` is optional
background on what that is and where freelab differs: read it only if the user asks about the method.

## 1. Before the loop (you, now)

- `lab/charter.md` has the research fields: the validation metric and target, the decision GPU type, the
  editable surface, the frozen parts, the per-experiment budget and estimate, and the stop rules (`plan`). If
  not, go back to `plan`.
- The project is a git repository with at least one commit. If not, propose `git init` and a first commit, and
  ask.
- **The loop works in its own git worktree,** `lab/worktrees/loop`, on its own branch `lab/<tag>` (a short tag
  from the charter, e.g. `banking77`). Every edit, commit and `git reset --hard` of the loop happens there, never
  in the user's working copy, so their files and uncommitted work are never touched.
  - `lab/` is ignored in the user's copy (`git check-ignore -q lab/results.tsv` passes; `onboard` step 2), so
    the worktree never shows up in their `git status`.
  - New: from the project root, `git worktree add lab/worktrees/loop -b lab/<tag>`. It starts from the user's
    current commit, so their uncommitted changes are not in it: if `git status --porcelain` shows changes the
    experiment needs, ask the user to commit them first (you may do it on their yes, by path).
  - Resuming: `git worktree list` shows `lab/worktrees/loop`. If the folder is gone but the branch exists:
    `git worktree add lab/worktrees/loop lab/<tag>`.
- **One setup commit in the worktree,** before the baseline. The experiment lives in `experiments/<name>/` there
  (never the project root): for the quick start, copy `${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya` to
  `lab/worktrees/loop/experiments/banking77-laya/` (without `__pycache__`); for the user's own experiment, its
  tracked files are already there (copy in any untracked file it needs, never `.env` or a key file). Then
  `git -C lab/worktrees/loop add experiments/banking77-laya && git -C lab/worktrees/loop commit -m "lab: set up <tag>"`.
  Add by path, here and for every experiment. Runs write to the project root's `lab/`, never into the worktree,
  so the commit holds only the experiment.
- **EXP is the experiment's folder in the worktree** (`lab/worktrees/loop/experiments/banking77-laya` for the
  quick start) for every launch. Launch from the project root, where `.env` and `lab/` are; runs write to
  `lab/runs/ID/` there.
- `lab/results.tsv` exists with its header line, tab-separated; if it is missing:
  `printf 'id\tcommit\tbackend\tgpu\tminutes\tmetric\tstatus\tchange\n' > lab/results.tsv`
- `lab/status.json` has `stages` from the plan (`plan`, `status`), and the status page is rendered.
- **A lab that already holds a run** (the quick start's "Try to beat it", `report` §4): the first run's
  charter, plan and report were kept as `lab/charter-run1.md`, `lab/plan-run1.md` and `lab/report-run1.md`
  before the new charter was written; if not, keep them now. Its run folders, `ledger.jsonl` and events stay.
  In `lab/status.json`, set `goal` to the validation metric and its target and replace `stages` with the loop's,
  each with `status_page.py set --lab lab goal|stages '<JSON>'` (`status` §2).
- Every loop starts with the status event, in these exact words, **"research loop started"**:
  `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/status_page.py event --lab lab "research loop started"`; the loop's time
  counts from that event. Resuming a loop keeps its first such event.

## 2. Run the loop in this session

There is nothing for the human to type. Once the charter is approved (`plan` §1 or §4), finish section 1
and start the loop (section 3) at once, in this session.

**Permission prompts.** The loop runs unattended (the quick start's for 10-20 minutes, a longer one for hours),
and a permission prompt stalls it until someone answers. This skill pre-approves the poll, the ledger, the page,
`stats.py` and the loop's git commands in its worktree; launches still ask. Before the first experiment, say so
in one line and ask one question: **Turn on auto mode** (Recommended; the human switches it: the permission-mode
menu in the app, or Shift+Tab in the terminal; you never change the permission mode or settings yourself) or
**Keep asking me** (the loop waits at each prompt). Skip the question when auto mode is already on.

For the quick start's "Next: try to beat it", the values are in that section of
`${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya/charter.md` (its baseline is the quick-start run; every
experiment runs with `--epochs 1 --skip-test`); the branch is `lab/banking77`.

**Watch each run with the poll** (`status` §5), one per run, started right after its launch; when it exits, go
on with section 3, step 4.

**Say one line per experiment**, and nothing in between unless something needs the user: its id, keep, discard
or crash, its validation metric with its 95 % interval on the validation items
(`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/stats.py wilson P N`, N = `val_items`), the best kept so far against the
target, the change, the non-improving streak, and the free credit and time left. For example:

`exp-03 keep: val accuracy 0.842 (0.815-0.866, n 770; best 0.842, target 0.85); deeper head; streak 0; USD 0 spent, 8 min left`

The human can interrupt at any time (Esc, or a message); stop where you are and answer. "Stop the loop" is a
stop condition (section 4).

## 3. The loop

If anything in section 1 is missing, do it first. Set the plan's stages to `running` or `done` as you go. One
experiment at a time per backend:

1. **Baseline first:** the unchanged experiment on the charter's decision GPU type, logged as `keep`. Every
   keep or discard compares runs on that type only. A finished earlier run of the same code on the same GPU type
   may be the baseline when the charter says so (the quick start's single run): log it as `keep` with its id and
   change "baseline (earlier run)". Its validation score counts. Its test score was already seen once; it is
   never scored again, and if the baseline stays the best kept result, the report gives that same test number.
   If the baseline's `status.txt` does not read `done`, the per-experiment budget is too small: tell the human
   its measured minutes and ask for a new budget. If the baseline already meets the target on validation, the
   loop is done: go to section 4, and suggest a higher target in the handoff.
2. **One idea:** change only the editable surface, in the worktree; commit it by path,
   `git -C lab/worktrees/loop add <editable files> && git -C lab/worktrees/loop commit -m "exp: <change>"`.
   **Never change** the frozen parts: data loading and evaluation, the split construction (for the quick start
   the split lines in `experiment()`, `VAL_PER_CLASS`, `--seed`, `--per-class`), the charter's experiment
   flags, and the test split.
3. **Run** it with `--max-minutes <N>` (Modal: `--minutes <N>`) and the charter's experiment flags (the quick
   start: `--epochs 1 --skip-test`) on a connected backend (`compute` §4) with the decision GPU type and a fresh
   run id, its estimate logged first (`compute` §6). A backend not yet checked gets a smoke first. Pass the
   provider's run link to the poll (`--link`). Send the output to the run's log and read only the lines you need.
4. **Decide** on the validation metric alone, and only for a run whose `status.txt` reads `done`. Anything else
   (`stopped (deadline)`, `failed: ...`) is a `crash`: say why in `change` (e.g. "over budget"), reset, and
   never read its validation lines. A `failed` run with a trivial bug is fixed and rerun once first. Read only
   the validation fields, never the test ones (a run without `--skip-test` writes `final_accuracy` and test
   lines too):
   `python3 -c "import json; s = json.load(open('lab/runs/ID/summary.json')); print(s['final_val_accuracy'], s['val_items'], s.get('val_ids_sha'))"`.
   Never `cat` or print `summary.json` or the whole `metrics.jsonl` during the loop.
   - **Same validation items:** its `val_ids_sha` must equal the baseline's. A different hash means the split
     changed: a `crash` ("validation split changed"), reset. A baseline from before 0.4.1 has none: then the
     first experiment's hash is the reference.
   - Higher than the last kept result: `keep`, and the branch advances. Equal or lower: `discard` and
     `git -C lab/worktrees/loop reset --hard <last kept commit>`. This never keeps a change that scored lower
     on validation; a gain inside the interval may still be noise, and the report says so.
5. **Log** one row in `lab/results.tsv`: id, short commit, backend, GPU, minutes (a number even for a crash:
   the minutes elapsed, or 0), validation metric (empty for a crash), status, change (no tabs in it). Update
   `best`, the spend, stages and events with `status_page.py set` and `event` (`status` §2).
6. **In parallel:** other backends only add candidates on the same decision GPU type, at most one Kaggle
   candidate at a time (Kaggle runs read the code from one shared Dataset). Each candidate gets its own worktree
   off the last kept commit: `git worktree add --detach lab/worktrees/<id> <last kept commit>` (an id other than
   `loop`), and its commit there (`git -C lab/worktrees/<id> ...`). Launch it from the project root with EXP
   pointing into that worktree, and log it to `lab/results.tsv`. Keep only the best of a batch: advance
   `lab/<tag>` with `git -C lab/worktrees/loop merge --ff-only <sha>`; another winner is retried on top of the
   new kept commit. Remove each candidate's worktree afterwards (`git worktree remove lab/worktrees/<id>`).
   If the decision GPU type is no longer available anywhere, re-measure the current tip on the new type before
   comparing anything against it, and log that re-measure as its own row (`keep`, change "re-measure on
   <type>"); the new type is the decision type from then on.
7. **Simplicity:** a tiny gain that adds complexity is not worth keeping; a simplification at an equal metric is.
8. **Never stop to ask** while within the charter's budget and free credit (the one exception: a baseline that
   does not finish, step 1). Out of ideas, reread the code, combine near-misses, try a bolder change. Anything
   beyond the budget or free credit goes to the user.
9. **Move a run** when a quota or a session limit runs out (`compute` §5); it keeps its id and its row.

Before each launch, check the money left: `ledger.py total` against `budget.usd_limit` in `lab/status.json` (the
ledger logs list prices even when free credit covers them), and `kaggle quota` for Kaggle. Check the time too:
take the next experiment's **estimate** (the last experiment's measured minutes, else the charter's estimate),
never its `--max-minutes` cap. If no connected backend has credit left for that estimate, or it would end after
the charter's time since "research loop started", that stop condition holds.

## 4. The end

When a stop condition holds (the target met on validation, the free credit spent, the charter's budget in USD
or time spent, K non-improving experiments in a row or the charter's experiment cap, or the user says stop):
1. Score the test split once, on the best kept commit (the tip of `lab/<tag>`), and read it now, never before:
   - the baseline (an earlier run) is still the best: its test number, already seen once, is the result;
   - the best kept run scored test itself (no `--skip-test`): read its `final_accuracy`
     (`python3 -c "import json; print(json.load(open('lab/runs/ID/summary.json'))['final_accuracy'])"`);
   - it ran with `--skip-test`: one scoring run relaunches that commit with the same flags without `--skip-test`
     (run id `<id>-test`, the charter's minutes, its estimate logged), then read its `final_accuracy` as above.
     Report its validation beside the experiment's.
2. Log the status event, in these exact words, **"research loop ended"** (with the reason after it, e.g.
   `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/status_page.py event --lab lab "research loop ended: target met"`),
   mark the stages `done` or `skipped`, render the page a last time.
3. Say in one or two lines which condition ended the loop, the best validation number and the one test number.
   If an experiment was kept: "The best version is on the branch `lab/<tag>`; nothing in your files has
   changed. Say 'merge the lab branch' and I'll merge it for you." On that request, merge it from the project
   root (`git merge lab/<tag>`, which adds `experiments/<name>/`) and say what it added. If nothing beat the
   baseline, say so plainly: no change was kept, so there is nothing to merge.
4. `report` writes `lab/report.md` with the results table, offers the next steps (`report` §4; "Clean up and
   stop" is offered after every research loop) and writes the handoff. The worktree stays until the cleanup
   (the demo uses it); `cleanup` removes it (`git worktree remove`; the branch stays).

## 5. The overfitting guard

The test split never chooses anything: not a keep, not an idea, not when to stop. If validation and test
disagree by more than the interval (`report` §2), say so in the report as a caveat. A test score under the
target is reported as measured; it is not a reason to go on, and there is no second test score.
