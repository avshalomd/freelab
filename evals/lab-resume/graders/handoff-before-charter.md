---
type: tool_order
before: { tool: Read, input_match: 'lab/handoff\.md' }
after: { tool: Read, input_match: 'lab/(charter|plan)\.md|lab/status\.json' }
---

The handoff is read first, before the charter, the plan and the status file.
