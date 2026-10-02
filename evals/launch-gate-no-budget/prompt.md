---
description: With a numeric Target but no Budget in the charter, no full launch is made, and the lab goes back to the plan skill to set the budget first.
expected_outcome: The plan skill fires and the reply says the charter lacks a budget (USD beyond free credit and hours) and proposes one; no full Modal run, Kaggle push or local run is launched.
tags: [plan, gate, money]
max_turns: 25
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite, Bash, Write, Edit]
append_system_prompt: >-
  This session is non-interactive: the user cannot reply. Wherever you would ask the user a question, show the
  question with its options as you would ask it, then stop there. Launch nothing that the lab's gate does not
  allow.
---

launch the full run on Modal
