---
type: regex
target: { source: file, path: lab/charter.md }
flags: im
pattern: '^[\s>*#-]*(\*\*)?Target\s*(\*\*)?\s*:[^\n]*(>=|<=|≥|≤|>|<|\bat least\b|\bat most\b)\s*`?\d*\.?\d'
---

The charter's Target line holds a number with a direction, e.g. `- **Target:** accuracy >= 0.80`.
