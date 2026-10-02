# Handoff: 2026-09-30 22:40

## Still running
- full-local on this machine: running, step 120/435. Watch: `cat lab/runs/full-local/status.txt`. Stop: `pkill -f "train.py --out lab/runs/full-local"`. Fetch: nothing, the outputs are already in `lab/runs/full-local/`.

## Stopped or finished
- (none yet)

## Open decisions
- Stage 2 (lower learning rate) runs only if stage 1 ends under 0.80. Recommendation: wait for stage 1.

## Re-arm prompt
Paste this into a new session:
> Resume the freelab lab in this project: read lab/handoff.md first, then lab/charter.md and lab/plan.md; check the runs listed as running, refresh the status page, and continue from the end of stage 1.
