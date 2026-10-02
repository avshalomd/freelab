---
description: A stage that needs more memory than the local allowance, with no cloud connected, goes to the user.
expected_outcome: The agent does not launch; it offers to keep the limit (cloud or a smaller job) or raise it (this run or for good).
tags: [compute, allowance]
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite]
---

run stage 1 of the plan
