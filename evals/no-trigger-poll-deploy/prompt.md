---
description: A request to watch a deploy on an interval, in a project that is not a freelab lab, fires none of freelab's skills (not status, not lab).
expected_outcome: None of freelab's skills fires; the agent handles the polling on its own (a loop or a schedule) and writes no lab/status.json.
tags: [should-not-trigger]
max_turns: 15
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite]
append_system_prompt: >-
  This session is non-interactive: the user cannot reply. Wherever you would ask the user a question, ask it in
  your reply and stop there. Install and launch nothing.
---

check every few minutes on my deploy and tell me when it is live
