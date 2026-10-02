---
description: A bare "run it on a GPU" in a repository that has nothing to do with an experiment lab fires none of freelab's skills (not compute, not lab).
expected_outcome: None of freelab's skills fires; the agent looks at what "it" is and answers on its own (or asks what to run) and launches nothing on Modal, Kaggle or Lightning.
tags: [should-not-trigger]
max_turns: 15
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite, Bash]
append_system_prompt: >-
  This session is non-interactive: the user cannot reply. Wherever you would ask the user a question, ask it in
  your reply and stop there. Install and launch nothing.
---

run it on a GPU
