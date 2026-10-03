# Status page blocks

Read by the `status` skill, **Building blocks**, when a task is not a training run or no block shows what matters.

The page is a list of blocks, in the order of `layout` in `lab/status.json`. Without `layout`, the default fits a
training run: `headline`, `progress`, `charts`, `health`, `plan`, `cost_time`, `details`. The other blocks:
`cost` and `time` (apart), and the parts of `details` on their own: `runs`, `results`, `decisions`, `events`,
`measurements`, `glossary`. Unknown names are skipped.

Pick the blocks at plan time and set `layout` with `status_page.py set --lab lab layout '<JSON list>'`. When no
block shows what matters, write a custom block: `lab/blocks/<name>.html`, static HTML or inline SVG (no scripts:
they are stripped; no external requests), using the page's CSS tokens such as `var(--fg)`, and add
`custom:<name>` to `layout`. Update it when its numbers change.

Examples:
- **LLM fine-tune:** the default, plus `custom:samples-table` with a few prompts and answers before and after as a
  static table.
- **Research loop or sweep:** `headline`, `progress`, `charts`, `results`, `plan`, `cost_time`, `details`.
- **Batch inference or data processing:** `headline`, `progress`, `custom:throughput` (items done, items per
  minute, errors), `cost_time`, `events`.
- **Benchmark eval:** `headline`, `custom:scores` (a table of tasks and scores with intervals), `runs`,
  `cost_time`, `details`.
- **RL:** `headline`, `charts` (the reward as the goal's metric), `health`, `custom:episodes` (episode length and
  return over time, inline SVG), `cost_time`, `details`.
