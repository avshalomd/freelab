---
description: A new experiment gets a charter with a numeric target and a budget before anything else.
expected_outcome: lab/charter.md exists, its Target line holds a number and it has a Budget line.
tags: [plan]
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite, Bash, Write, Edit]
append_system_prompt: >-
  This session is non-interactive: the user cannot reply. Wherever you would ask the user a question, take the
  default you would have suggested, say which defaults you took, and carry on.
---

set up an experiment to classify support tickets
