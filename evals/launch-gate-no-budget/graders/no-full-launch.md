---
type: tool_used
tool: Bash
input_match: 'modal\s+run\b(?![^\n]*--smoke)(?![^\n]*--help)|kaggle\s+kernels\s+push|local_run\.py(?!.*--(smoke|dry-run|help))|python3?\s+(\S*/)?train\.py(?!.*--smoke)|lightning\s+(run|launch)'
min: 0
max: 0
arm: both
---

No full launch without a budget (only the `--smoke` connection check may run before the charter is complete).
