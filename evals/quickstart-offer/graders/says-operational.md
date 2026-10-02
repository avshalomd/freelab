---
type: regex
target: last_message
flags: i
pattern: '(✅\s*)?\**modal( ai)?\**\s*(:|is|—|-)?\s*(now\s+)?(fully\s+)?operational'
---

The reply says Modal is operational ("✅ Modal is operational", or a close variant such as "Modal is now
operational" or "Modal: operational").
