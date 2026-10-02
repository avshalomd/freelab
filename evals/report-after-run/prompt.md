---
description: After a planned run has ended and been fetched, the lab goes to the report with no prompt (lab/report.md with the target against the result and a Wilson interval from stats.py), the next steps offered in one question, and the handoff.
expected_outcome: lab/report.md exists with a bottom line, the target, baseline and result with the 95 % interval 0.8235-0.8496 (stats.py wilson 0.837 3076), the costs and the caveats; lab/handoff.md exists; the reply gives the bottom line and offers next steps (try the model, train longer or try to beat it, clean up and stop); nothing is launched.
tags: [report]
max_turns: 40
timeout_seconds: 800
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite, Bash, Write, Edit]
append_system_prompt: >-
  This session is non-interactive: the user cannot reply. Wherever you would ask the user a question, show the
  question with its options as you would ask it, then stop there. Do the steps that need no question first.
---

the full run on Modal just finished and its outputs are fetched in lab/runs/full-modal. Carry on.
