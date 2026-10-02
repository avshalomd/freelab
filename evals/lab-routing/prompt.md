---
description: In a fresh project on a machine that is not set up, an experiment request routes through the lab skill to onboarding, and nothing is launched or written to lab/ before onboarding.
expected_outcome: The lab skill fires, then the onboard skill; the reply says freelab is not set up yet and what onboarding will ask; no charter is written and nothing is launched.
tags: [lab, routing]
max_turns: 20
timeout_seconds: 400
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite, Bash, Write, Edit]
append_system_prompt: >-
  This session is non-interactive: the user cannot reply. Wherever you would ask the user a question, show the
  question with its options as you would ask it, then stop there. Install and launch nothing.
---

run an experiment to see if fine-tuning helps
