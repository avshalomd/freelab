# Karpathy's autoresearch, and what freelab takes from it

Background for the `research` skill. freelab does not ship autoresearch or any of its code; this note says what
the idea is, what it reported, and where freelab's loop differs. Everything here is paraphrased from the sources
at the end.

## What it is

A small but real language-model training setup that an AI coding agent improves by itself, overnight, one
experiment at a time. The division of labour is the core idea:

- **The human writes `program.md`**: the agent's instructions (setup, the loop, the log format, the rules). The
  human improves the instructions, not the training code.
- **The agent edits only `train.py`**: model, optimizer, hyperparameters, batch size, the training loop. It may
  not add packages.
- **Frozen:** `prepare.py` (data download, tokenizer, data loader, constants) and the evaluation function. The
  agent never touches them, so the score it chases stays honest.
- **A fixed budget:** every experiment trains for 5 minutes of wall-clock time (start-up and compilation not
  counted), whatever the change. A run past 10 minutes is killed and counted as a failure. That makes runs on one
  machine comparable, and runs on different GPUs not comparable. About 12 experiments an hour, about 100 a night.
- **One metric:** `val_bpb`, validation bits per byte on a pinned validation shard; lower is better. It does not
  depend on the vocabulary size, so a tokenizer change cannot win by accident.
- **Keep or reset in git:** the work happens on a fresh branch (`autoresearch/<tag>`). One idea, one commit, one
  run. Strictly better than the last kept result: keep, and the branch advances. Equal or worse: discard, with a
  `git reset` to the last kept commit.
- **Crashes:** a trivial bug (a typo, a missing import) is fixed and the run repeated; a broken idea is logged
  as `crash` and reset. No metric line in the log means a crash, so the agent reads the traceback.
- **The log:** `results.tsv`, tab-separated (commas break free-text descriptions), with the short commit, the
  metric, peak GPU memory, the status (keep, discard, crash) and a description. It stays untracked by git.
- **Simplicity:** a tiny gain that adds ugly code is not worth keeping; deleting code at an equal or better
  metric is a win.
- **Never stop to ask:** once the loop runs, the agent does not ask whether to continue; the human may be
  asleep. Out of ideas, it rereads the code and the papers it cites, combines near-misses, or tries bolder
  changes. It runs until the human interrupts it.
- **Keep the context small:** the run's output goes to a log file, and the agent reads only the lines it needs.

## What it reported

- About 700 changes over about two days of autonomous running, about 20 of them kept. Checked by hand, the kept
  changes stacked and carried over to a larger model, and cut nanochat's time to GPT-2 by about 11 % (2.02 h to
  1.80 h) on his setup.
- Single overnight sessions: 89 experiments (val_bpb 0.998 to 0.977) and 125 experiments in about 10.5 hours
  (0.998 to 0.970), reported by his agent on the repository.
- Findings were real tuning gaps (attention sharpness, missing regularisation, optimizer betas, weight decay,
  initialisation), not new science, as he says himself.

## Caveats

- Results hold for one GPU type and one time budget; a change that wins in 5 minutes on an H100 may not win on a
  T4 or with a longer budget. His agent's later branches carry the GPU in the name for that reason.
- Overfitting to the validation set is the known risk: hundreds of keep-or-discard choices on one shard can
  select noise, and a metric that improves too easily is suspect. Only a held-out score shows the gain is real.
- The design assumes one always-on GPU and no cost limit.

## Later: the "research org"

He then framed the next step as many agents collaborating asynchronously, SETI@home style, sharing session
reports instead of merging branches. Out of scope for freelab.

## Where freelab differs

- The charter is freelab's `program.md`, with the rules in the `research` skill; the editable surface and the
  frozen parts are named in the charter, not fixed to two files.
- Decisions use a validation split; the test split is scored once, at the end, on the best kept commit.
- The budget per experiment is the run contract's `--max-minutes`, and a run that does not finish in it counts
  as a crash. Runs can land on any connected backend, but the charter names one decision GPU type, and every
  keep or discard compares runs on that type only.
- The loop stops by itself: target met on validation, free credit or budget spent, K non-improving
  experiments in a row, or the user's word. It still never stops to ask in between.
- `lab/results.tsv` adds the id, backend, GPU and minutes. The loop works in its own git worktree
  (`lab/worktrees/loop`, branch `lab/<tag>`), so a reset never touches the user's working copy or `lab/`.

## Sources (checked 2026-09-28)

- The repository: https://github.com/karpathy/autoresearch (README, `program.md`)
- Announcement: https://x.com/karpathy/status/2029701092347630069
- Round-one results: https://x.com/karpathy/status/2031135152349524125
- The SETI@home framing: https://x.com/karpathy/status/2030705271627284816
- Follow-up with the repository link: https://x.com/karpathy/status/2031137476438548874
- Agent-written session reports: https://github.com/karpathy/autoresearch/discussions/32,
  https://github.com/karpathy/autoresearch/discussions/43, https://github.com/karpathy/autoresearch/pull/44
