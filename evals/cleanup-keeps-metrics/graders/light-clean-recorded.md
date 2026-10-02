---
type: regex
target: { source: file, path: lab/cleanup.jsonl }
pattern: '__pycache__|\.tmp-step'
---

The light clean ran without a question and recorded what it removed (the `__pycache__` folder or the unfinished
checkpoint write) in `lab/cleanup.jsonl`.
