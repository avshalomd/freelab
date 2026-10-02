---
type: regex
target: { source: file, path: lab/results.tsv }
flags: m
pattern: '^id\tcommit\tbackend\tgpu\tminutes\tmetric\tstatus\tchange'
---

`lab/results.tsv` exists with its tab-separated header line.
