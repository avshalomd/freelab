---
description: A request to hand off a git branch to a teammate, in a session that is not a freelab lab, fires none of freelab's skills (not report, not lab).
expected_outcome: None of freelab's skills fires; the agent writes or shows a plain note about the branch and creates no lab/handoff.md.
tags: [should-not-trigger]
max_turns: 15
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite, Bash]
append_system_prompt: >-
  This session is non-interactive: the user cannot reply. Wherever you would ask the user a question, ask it in
  your reply and stop there. Install and launch nothing.
---

hand off this branch to my teammate: write her a short note on where it stands
