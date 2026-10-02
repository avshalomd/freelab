# Behaviour evals

Each folder is one case for `claude plugin eval . --scaffold --allow-tools Bash Write Edit`: `prompt.md` (the
user's message and what should happen), `graders/` (the checks), and usually `case.yaml` with `scaffold.sh`, which
copies `workspace/` into the run's folder and writes the run's own temporary home (`home/`, an onboarded marker or
an allowance). A scaffold that writes a home refuses to run against the real home directory, so a case never
depends on, or changes, the machine it runs on.

**All workspace data is synthetic.** Charters, plans, ledgers, status files, metrics, summaries and tickets were
written for these cases; their numbers are made up and deliberately differ from the measured results in
[`examples/banking77-laya`](../examples/banking77-laya/README.md). The quick start itself is never copied into a
workspace for a single run: as in the skills, it runs in place from the plugin's `examples/` folder. Only a case
whose lab changes the experiment keeps its own copy in `experiments/banking77-laya/`, and the research loop copies
it into its own worktree.
