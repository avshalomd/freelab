---
type: regex
target: last_message
flags: i
pattern: '\b(no|missing|without|lacks?|lacking|needs?|add(s|ing)?|sets?|setting|propos\w*)\b[^\n.]{0,40}\bbudget\b|\bbudget\b[^\n.]{0,30}\b(is missing|missing|not set|absent|empty|blank|is not there|isn.t there)\b'
---

The reply says the charter has no budget ("no Budget", "the budget is missing", "add a budget", "I propose a
budget of ..."), not merely the word "budget".
