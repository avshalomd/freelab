---
description: A generic request to free disk space in a project that is not a freelab lab fires none of freelab's skills (not cleanup, not lab).
expected_outcome: None of freelab's skills fires; the agent answers the disk question on its own (what takes space, what is safe to remove) and creates no lab/ folder.
tags: [should-not-trigger]
max_turns: 15
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite]
append_system_prompt: >-
  This session is non-interactive: the user cannot reply. Wherever you would ask the user a question, ask it in
  your reply and stop there. Install and launch nothing.
---

free some space on my disk
