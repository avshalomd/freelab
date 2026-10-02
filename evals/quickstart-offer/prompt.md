---
description: After a provider's connection check passes, onboarding says the provider is operational and offers the quick start in plain words, with its time, cost and target, as the recommended option.
expected_outcome: The reply says Modal is operational, offers the quick start as the recommended option with the measured time and cost from the example charter (on Modal about 9-10 minutes and about USD 0.12-0.16 of free credit) and a 0.80 accuracy target, and prints no slash-goal command.
tags: [onboard, quickstart]
max_turns: 25
timeout_seconds: 500
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite, Bash, Write, Edit]
append_system_prompt: >-
  This session is non-interactive: the user cannot reply. Wherever you would ask the user a question, show the
  question with its options as you would ask it, then stop there. Install nothing.
---

I'm onboarding freelab and picked Modal only. The machine is set up, my Modal keys are in .env, and the Modal
connection check has just passed: its outputs are in lab/runs/smoke-modal-20261001. Carry on.
