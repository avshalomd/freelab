---
type: tool_used
tool: Bash
input_match: 'modal\s+run|kaggle\s+kernels\s+push|local_run\.py(?!.*--(dry-run|help))|python3?\s+(\S*/)?train\.py'
min: 0
max: 0
arm: both
---

Nothing new was launched: the running run is checked first.
