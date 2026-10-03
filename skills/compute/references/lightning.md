# Lightning AI

Free credits and T4/L4 jobs without a session limit. You drive it with the `lightning` CLI: the code lives in a
Studio named `freelab`, and each run is a job started from a snapshot of it. Keys: `lab` rule 1 (through
`${CLAUDE_PLUGIN_ROOT}/scripts/withenv`, one per command in a chain).

Contents: TEAMSPACE · Free tier · Onboarding (0 Signed in already?, 3 Spending cap: there is none, 4 Key, 5 CLI,
6 Teamspace, 7 Official skills) · Connection check · Launch (1 the Studio, 2 upload, 3 run the job, the run's
link) · Watch, fetch, stop (the poll and its state mapping) · Move in / out (Warm start) · Cost model · Clean up ·
Gotchas

**TEAMSPACE** below is the `<org>/<teamspace>` slug, e.g. from the address `lightning.ai/<org>/<teamspace>/home`.
Every command passes `--teamspace TEAMSPACE`, and every `lit://` path starts with `lit://TEAMSPACE/`: the CLI does
not find the teamspace by itself. Onboarding keeps it in the onboarded marker as `lightning_teamspace`.

## Free tier

- **Credits** (1 credit = $1; https://lightning.ai/pricing, checked 2026-10-01): 5 free credits at sign-up, after
  phone verification; adding a card gives 25 more: "up to 30 free credits to start". The current pages read as a
  one-time grant; an older docs page describes a monthly top-up to 15 (unconfirmed). Unused credits expire after
  12 months. Read the balance on lightning.ai before a long run.
- **Measured** (2026-10): a T4 job billed about **$0.90 an hour** (the pricing table lists $0.55), so the
  quick start's measured time and cost are in `${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya/charter.md`, **Budget**.
  30 credits are about 30 T4 hours of jobs.
- "80 free GPU hours" (Studio docs) counts interruptible machines and is a Studio offer, not job time.
- **Phone:** a non-virtual number is needed, and Lightning AI is not open in every country.
- One CPU Studio runs free, restarted every 4 hours. On the Free plan T4, L4 and L40S have no session limit;
  A100, H100 and H200 stop at 4 hours. 10 GB of storage is free (pricing page).

## Onboarding

0. **Signed in already?** `[ -f ~/.lightning/credentials.json ] && echo yes || echo no` (it tests that the CLI's
   sign-in file exists; never open it), or both `LIGHTNING_USER_ID` and `LIGHTNING_API_KEY` are `set`. Do not use
   `lightning auth whoami`: signed out, it opens a browser tab.
1. **Sign up** at https://lightning.ai and verify the phone (5 credits).
2. **Card (optional):** the human adds one for the extra 25 credits. You never type payment details.
3. **Spending cap: there is none.** The Free plan has no budget setting ("Spending limits" is a Teams feature).
   What the docs say: "When credits are running low, Lightning AI will warn users and then attempt to gracefully
   shut down all workloads and Studios" (https://lightning.ai/docs/overview/faq/billing, checked 2026-10-01). The
   only automatic card charge documented is "Auto-reload credits" (Organization → Billing), "disabled for
   Organizations by default" (https://lightning.ai/docs/platform/team-management/organizations/manage-costs,
   same date); otherwise the card is charged only when the human buys credits. Not documented: what happens if a
   job runs past zero, or whether a negative balance is billed, and the Terms let Lightning charge the card for
   all fees on the account. So say: with auto-reload off, Lightning's documented behaviour is to warn and stop
   workloads, not charge the card; that is documented behaviour, not a guarantee. The human: confirms auto-reload
   is OFF, sets a low-credit alert in Billing if it offers one (to verify live), buys no credit pack, and revokes a
   leaked key at once (Keys page). freelab keeps `--max-minutes` on every run and states each estimate. For
   certainty, ask Lightning support for written confirmation.
4. **Key:** profile icon → Global Settings → Keys → "Programmatic access" shows the user id and API key
   (https://lightning.ai/docs/overview/ai-studio/sdk, checked 2026-09-28). When driving the browser, stop at
   Global Settings and take no screenshot: the human opens Keys, reveals and copies the key, and says when it is
   off the screen. You add these lines to the project's
   `.env` with empty values (`onboard` step 5f), and the human pastes the values:

   ```
   LIGHTNING_USER_ID=...
   LIGHTNING_API_KEY=...
   ```

   The CLI reads both from the environment (lightning-sdk 2026.9.18.post1 source). Use this `.env` key:
   `lightning login` (a browser sign-in) can fail from inside an agent session, so do not rely on it.
5. **CLI:** `uv tool install --python 3.12 lightning-sdk` (it provides `lightning`; Python 3.14 is too new for
   it; these steps checked against 2026.9.18.post1).
6. **Teamspace:** the human reads the `<org>/<teamspace>` part of the lightning.ai address after signing in
   (when driving, read it from the tab's URL). Once a Studio exists, `lightning studio list --teamspace TEAMSPACE
   --json` confirms it. It is not a secret.
7. **Official skills (optional):** Lightning publishes agent skills, including `lightning-jobs`,
   `lightning-studios` and `lightning-cost-estimation` (https://github.com/Lightning-AI/skills, checked
   2026-09-28); freelab does not need them. Offer them in one line; on a yes, install them without prompts:
   `npx -y skills add Lightning-AI/skills --skill '*' -a claude-code -y` (into the project; the flags are from
   the skills CLI's README, to verify live). Plain `npx skills add` asks questions and would hang in Bash: if the
   command still waits for input, stop it and skip the skills.

## Connection check

The quick start's smoke on a T4: EXP is `${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya` (NAME `banking77-laya`, so
`~/freelab/banking77-laya` in the Studio), run id `smoke-lightning-<YYYYMMDD>`, `--max-minutes 20 --smoke`. Follow Launch, then fetch. It
passes when `status.txt` reads `done` and `metrics.jsonl` holds `val` and `test` accuracy at step 0 and step 50.

## Launch

1. **The Studio, once:** `${CLAUDE_PLUGIN_ROOT}/scripts/withenv lightning studio create --name freelab
   --teamspace TEAMSPACE`.
2. **Upload the code** after each change. EXP is the experiment directory, a path; NAME is its folder name (its
   basename, e.g. `banking77-laya`), lowercased, and its folder in the Studio is `~/freelab/NAME`. `cp -r`
   copies SRC whole. SRC is EXP itself, or, when EXP is the project root, a staged copy in
   `lab/backends/lightning-NAME/` without `.env`, key files, `lab/`, `.git/` and `.venv/`; never upload `.env`,
   `lab/runs` or `.git`:
   `${CLAUDE_PLUGIN_ROOT}/scripts/withenv lightning cp -r SRC/ lit://TEAMSPACE/studios/freelab/freelab/NAME/ &&
   ${CLAUDE_PLUGIN_ROOT}/scripts/withenv lightning cp ${CLAUDE_PLUGIN_ROOT}/scripts/runlib.py lit://TEAMSPACE/studios/freelab/freelab/NAME/runlib.py`.
   If a copy fails because the Studio is stopped:
   `${CLAUDE_PLUGIN_ROOT}/scripts/withenv lightning studio start --name freelab --teamspace TEAMSPACE`,
   copy, then `${CLAUDE_PLUGIN_ROOT}/scripts/withenv lightning studio stop --name freelab --teamspace
   TEAMSPACE`. The same applies if the job submission asks for a running Studio (to verify live).
3. **Run the job** (the name is the run id, unique in the teamspace), once this launch's estimate is logged
   (`compute` §6):

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/scripts/withenv lightning job run --name ID --teamspace TEAMSPACE --studio freelab --machine T4 \
     --command "cd ~/freelab/NAME && pip install -q -r requirements.txt && python -u train.py --out ~/freelab-runs/ID --max-minutes 20 --smoke"
   ```

   Machines: T4, L4, L40S, A100, H100 (`lightning job run --help` lists all). What the job writes in its home is
   kept as its artifacts, so `--out ~/freelab-runs/ID` lands at `lit://TEAMSPACE/jobs/ID/freelab-runs/ID/`.
4. **The run's link:** the job's page on lightning.ai. Use the link `lightning job run` prints, if it prints
   one; otherwise the teamspace's jobs page, `https://lightning.ai/TEAMSPACE/jobs` (to verify live). Give it to
   the user and pass it to the poll as `--link`.

## Watch, fetch, stop

- **Watch** with the poll (`status` §5), right after the launch:
  `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/poll.py lightning ID --expected-minutes M --link URL` (TEAMSPACE comes
  from `lightning_teamspace` in the onboarded marker, else `--teamspace TEAMSPACE`; a resumed job adds
  `--job ID-r<N>`). Each check runs `lightning job inspect JOB --teamspace TEAMSPACE` and copies `status.txt`,
  `metrics.jsonl` and `summary.json` from `lit://TEAMSPACE/jobs/JOB/freelab-runs/ID/` into `lab/runs/ID/` (copying
  from a running job works, measured).
- **How the poll reads the state:** it takes the first `status`, `state` or `phase` text in the `inspect` JSON (the
  key and its values are to verify live): pending, queued, starting or provisioning → queued; running → running;
  completed, succeeded, finished or done → ended; failed or error → ended with an error; stopped or cancelled →
  ended, stopped. While the job runs, the run's own `status.txt` gives the detail. Once the job has ended, the
  fetched `status.txt` says how (`done`, `stopped (...)`, `failed: ...`); if it cannot be fetched after a few
  checks, the poll ends the run as failed (exit 1) and says to fetch it by hand.
- Logs: `${CLAUDE_PLUGIN_ROOT}/scripts/withenv lightning job logs ID --teamspace TEAMSPACE --tail 20` (`-f` to
  follow). The quick start's `train.py` prints a progress line at least every 25 steps.
- Status and cost as JSON: `${CLAUDE_PLUGIN_ROOT}/scripts/withenv lightning job inspect ID --teamspace TEAMSPACE`.
- Fetch everything (the checkpoint too), once finished: `${CLAUDE_PLUGIN_ROOT}/scripts/withenv lightning cp -r
  lit://TEAMSPACE/jobs/ID/freelab-runs/ID/ lab/runs/ID/`. If it is not found,
  `${CLAUDE_PLUGIN_ROOT}/scripts/withenv lightning ls -r lit://TEAMSPACE/jobs/ID/` shows where it is. A
  research-loop job (Cost model) writes its small files only at its end.
- Stop: `${CLAUDE_PLUGIN_ROOT}/scripts/withenv lightning job stop ID --teamspace TEAMSPACE`.

## Move in / out

- **Move in** (also Lightning's resume: a job is never restarted): copy the checkpoint and the metrics so far into
  the Studio, then start a new job `ID-r<N>` with the same command plus `--resume` and the same
  `--out ~/freelab-runs/ID`:
  `${CLAUDE_PLUGIN_ROOT}/scripts/withenv lightning cp -r lab/runs/ID/ckpt/
  lit://TEAMSPACE/studios/freelab/freelab-runs/ID/ckpt/ && ${CLAUDE_PLUGIN_ROOT}/scripts/withenv lightning cp
  lab/runs/ID/metrics.jsonl lit://TEAMSPACE/studios/freelab/freelab-runs/ID/metrics.jsonl`.
  Watch it with `poll.py lightning ID --job ID-r<N>` and fetch from `lit://TEAMSPACE/jobs/ID-r<N>/freelab-runs/ID/`
  into `lab/runs/ID/`.
- **Move out:** the fetch above; the checkpoint is then in `lab/runs/ID/ckpt/`.
- **Warm start** (a Train longer round, `plan` §1), a new job NEW from the finished run OLD: with OLD fetched, upload
  its final checkpoint into the Studio,
  `${CLAUDE_PLUGIN_ROOT}/scripts/withenv lightning cp -r lab/runs/OLD/ckpt/step-N/
  lit://TEAMSPACE/studios/freelab/freelab-init/OLD/step-N/`, then run NEW with the usual command plus
  `--init-from ~/freelab-init/OLD/step-N --epochs 1 --lr-scale 0.5 --skip-test` (to verify live); the chosen
  round's scoring run (job `NEW-test`) runs the same command without `--skip-test`. The upload counts toward
  the 10 GB of free storage: delete `freelab-init/OLD/` in the Studio afterwards (Clean up).

## Cost model

Billed per second of machine time from the credits; storage over 10 GB is billed daily. Estimate
`minutes / 60 × hourly price`, with about $0.90 an hour for a T4 (measured; the list price is lower), and log it
in the ledger (even on free credits); `inspect` shows `total_cost` afterwards. Count machine setup and install
(about 3 minutes, measured). The free storage is about 10 GB, and each job keeps its checkpoints as
artifacts (once a run finishes, runlib keeps only its final checkpoint: the quick start's full run about 2.1 GB,
its smoke about 0.6 GB), so a few runs fill it: after
fetching, tell the user which old job artifacts they can delete (Clean up below). A research loop runs many
experiments and never resumes one, so run its experiments without keeping checkpoints on Lightning: `--out` in
`/tmp`, then copy only the small files into the job's home, e.g. `--command "cd ~/freelab/NAME && pip install -q -r
requirements.txt && python -u train.py --out /tmp/ID --max-minutes N; mkdir -p ~/freelab-runs/ID && cp
/tmp/ID/*.jsonl /tmp/ID/*.txt /tmp/ID/*.json ~/freelab-runs/ID/"` (to verify live). Otherwise delete each
fetched job's artifacts before the next.

## Clean up

For the `cleanup` skill's deep clean, only on the user's yes, and only for a finished run fetched into
`lab/runs/ID/`. The CLI was not checked for a delete command, so the human deletes on lightning.ai.
- **What is there:** `${CLAUDE_PLUGIN_ROOT}/scripts/withenv lightning ls -r lit://TEAMSPACE/jobs/ID/`
  (a job's artifacts) and `${CLAUDE_PLUGIN_ROOT}/scripts/withenv lightning ls -r lit://TEAMSPACE/studios/freelab/` (the Studio's uploaded code and moved-in
  checkpoints, under `freelab/`, `freelab-runs/` and `freelab-init/`; to verify live). Sizes: the teamspace's
  storage settings list the data by type (to verify live).
- **Job artifacts:** the job's page under the teamspace's Jobs, or the teamspace Drive: hover over a folder, the
  three-dots menu, Delete (https://lightning.ai/docs/platform/build/ai-studio/add-data, checked 2026-10-01; to verify
  live). The docs also show `lightning job delete ID`, which deletes the job with its artifacts
  (https://lightning.ai/docs/platform/inference/batch-jobs/CLI, same date); not checked against the installed CLI:
  run `lightning job delete --help` first and add `--teamspace TEAMSPACE` (freelab's guard asks the user before
  a `lightning ... delete` of a freelab run's job or of the `freelab` Studio).
- **Studio files:** open the `freelab` Studio's file browser and delete `freelab-runs/ID/` (a moved-in checkpoint)
  and `freelab-init/ID/` (a warm start's checkpoint, once that run has finished), and the uploaded code under `freelab/` only when no more Lightning runs are planned (to verify live).
- **The best run:** its job artifacts hold the trained model. Delete them only once its final checkpoint is
  complete in `lab/runs/ID/ckpt/` (the fetch above copies it); otherwise fetch it first.
- When driving the browser, open the page and point at each item; the human presses Delete.
- Storage beyond the free 10 GB costs $0.10 per GB a month (same page), so this also stops storage billing.

## Gotchas

- **T4 has no native bf16:** use fp16 or fp32 there.
- **A silent log looks stuck:** the job log shows only what the script prints. Run Python with `-u` and print
  progress (the quick start's `train.py` does, every 25 steps); for anything else, copy `metrics.jsonl` (Watch).
- **No teamspace, no luck:** a command without `--teamspace TEAMSPACE` (or a `lit://` path without it) may look in
  the wrong place or fail.
- **Python 3.14** is too new for lightning-sdk: install with `--python 3.12` (Onboarding).
- A job runs in a snapshot of the Studio taken when it is submitted: upload the change, then launch again.
- Job names are unique in a teamspace: a reused id fails; a relaunch is `ID-r<N>`.
- Do not use `lightning auth whoami` as a sign-in check: signed out, it opens a browser tab.
- `lightning cp -r` copies everything in SRC (see Launch): never upload the project root itself; `.env`, key files, `.git`, `lab/runs`, data dumps and virtual environments stay out of SRC.
