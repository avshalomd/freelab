---
type: regex
target: { source: file, path: lab/report.md }
pattern: '(0\.82[34]|82\.[34])\d*\s*(%\s*)?\D{1,12}(0\.8[45]|8[45]\.)\d*'
---

The report holds the 95 % Wilson interval of 0.837 on 3,076 items, 0.8235 to 0.8496 (`stats.py wilson 0.837 3076`;
rounded forms such as 0.824-0.850 count).
