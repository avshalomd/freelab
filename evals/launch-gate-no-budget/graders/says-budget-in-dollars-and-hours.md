---
type: regex
target: last_message
flags: i
pattern: '(?s)(?=.*(?:\$|USD\s*)\s*\d)(?=.*\b\d+(?:\.\d+)?\s*(?:wall[- ]clock\s+)?(?:hours?|h\b|minutes?|min\b))'
---

The reply names both parts of a budget with numbers: an amount in USD (or $) beyond free credit, and a
wall-clock time (hours or minutes).
