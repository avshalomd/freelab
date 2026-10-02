---
type: tool_order
before: { tool: Skill, input_match: '"skill"\s*:\s*"(?:[\w-]+:)?lab"' }
after: { tool: Skill, input_match: '"skill"\s*:\s*"(?:[\w-]+:)?onboard"' }
---

`lab` is loaded first and sends the request on to `onboard`.
