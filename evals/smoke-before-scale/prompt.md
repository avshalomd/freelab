---
description: A full run on a backend that has not passed its connection check starts with the smoke run.
expected_outcome: The agent proposes or runs the `--smoke` connection check first and launches no full Modal run.
tags: [compute, rules]
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite]
---

run the full experiment on Modal
