---
description: A status refresh renders lab/status.html with freelab's status_page.py.
expected_outcome: lab/status.html exists after the run and carries the status_page generator comment.
tags: [status]
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite, Bash, Write, Edit]
---

refresh the status page
