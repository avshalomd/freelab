---
description: A lab with a handoff is resumed by reading the handoff first, then the charter and plan, and checking the run it lists as running before anything new starts.
expected_outcome: lab/handoff.md is read before the charter and plan; the reply reports the state of the run full-local and the next step from the handoff (stage 1 first, then stage 2 only if it ends under 0.80); no new run is launched.
tags: [lab, resume]
max_turns: 25
timeout_seconds: 500
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite]
append_system_prompt: >-
  This session is non-interactive: the user cannot reply. Wherever you would ask the user a question, show the
  question with its options as you would ask it, then stop there. Launch nothing.
---

resume the lab
