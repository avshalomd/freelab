---
type: regex
target: last_message
pattern: '(?:\$|USD\s*)0(?:\.(?:0+|1\d?|2\d?|30?))?(?!\.?\d)|\b(?:1\d|2\d|30)\s*cents\b'
---

The offer says what the quick start costs, as in the example charter's Budget line: Modal about USD 0.12 of GPU
time or about USD 0.16 with CPU and memory, Kaggle USD 0, Lightning AI about USD 0.25, at most about USD 0.30
(written with $ or USD, or in cents).
