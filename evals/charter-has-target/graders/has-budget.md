---
type: regex
target: { source: file, path: lab/charter.md }
flags: im
pattern: '^[\s>*#-]*(\*\*)?Budget\s*(\*\*)?\s*:[^\n]*[\w$]'
---

The charter has a Budget line with a value, e.g. `- **Budget:** $0 and 2 hours`.
