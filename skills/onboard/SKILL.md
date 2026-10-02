---
name: onboard
description: Use when freelab is not set up yet or the user wants more free compute - "set up freelab", "onboard me", "connect my free GPUs", "connect Modal", "connect Lightning", "connect Kaggle", "add another provider", or when the session starts with freelab's not-set-up line. Sets up this computer and the free GPU services.
---

# onboard: set up freelab

If the `lab` skill isn't loaded this session, load it first: it holds the rules (secrets: rule 1). Each
service's facts (pages, key names, CLI, money, checks) are in its reference file,
`${CLAUDE_PLUGIN_ROOT}/skills/compute/references/kaggle.md`, `.../lightning.md` and `.../modal.md`, under
**Free tier**, **Onboarding**, **Connection check** and **Cost model**. The human may know nothing about GPUs:
plain words, one step at a time.

**How to ask:** every choice is an AskUserQuestion question when the tool is available: 2-4 options, the
recommended one first with "(Recommended)" in its label, one decision per question. Without the tool, the same
options as a short numbered list. Then wait for the answer.

Onboarding is also where the human learns how freelab works, so they can drive it later: explain before each
question (`lab` rule 10), and after each step say in a line what it set up and how it is used later (for
example: the allowance decides which runs stay on this computer and which go to the cloud). The human may have
no terminal (`lab` rule 11): you run every command; they act only in the browser and the app.

## 1. Welcome

Say, in three lines: freelab runs AI experiments for you; it trains on this computer or on free cloud GPUs and
tells you plainly whether it worked; setup takes about 15 minutes, and you type every password, card and key
yourself. Ask: **Set it up now** (Recommended), **Not now**, **Never**.
- **Not now:** say you won't bring it up again and that "set up freelab" starts it any time, then stop and go
  back to what the user was doing. Nothing to write: the session-start hook offers onboarding only once per machine.
- **Never:** write the marker (step 6) with `"services": []`.

## 2. Secrets first

- In a git repository (`git rev-parse --is-inside-work-tree` prints `true`), make sure `.env` and `lab/` are
  ignored: if `git check-ignore -q .env` fails, append `.env` to `.gitignore`; if `git check-ignore -q
  lab/results.tsv` fails, append `lab/` (create `.gitignore` if it is missing). Outside a git repository, leave
  `.gitignore` alone.
- **You create `.env` and its placeholders; the human only pastes the values.** Never ask the human to create
  the file or type variable names. For a provider, run, with that provider's variable names from its reference
  (Kaggle `KAGGLE_API_TOKEN`; Lightning `LIGHTNING_USER_ID LIGHTNING_API_KEY`; Modal
  `MODAL_TOKEN_ID MODAL_TOKEN_SECRET`):
  `${CLAUDE_PLUGIN_ROOT}/scripts/env.sh add KAGGLE_API_TOKEN`.
  It creates `.env` if missing (readable only by the user), adds a one-line comment and an empty `NAME=` line for
  each name not yet in the file, prints `added NAME`, and never prints a value or changes an existing line.
- Then give the human a clickable link to the file with its absolute path, `[.env](/abs/path/to/project/.env)`,
  and offer to open it in their text editor (`open -t .env` on macOS, `xdg-open .env` on Linux; this opens the
  editor, it does not read the file into this session). Say which line gets which value: `NAME=value`, one per
  line, no spaces around `=`, no quotes; and that the file is hidden in Finder because its name starts with a
  dot. When they say it is saved, check: `${CLAUDE_PLUGIN_ROOT}/scripts/env.sh check KAGGLE_API_TOKEN` prints
  `present` or `missing` per name (an empty placeholder reads `missing`).
- Tell the human: never paste a key into this chat (`lab` rule 1). If one is pasted anyway, do not repeat it;
  they revoke it on the service and make a new one.
- The marker (step 6) is per machine; keys are per project. In a new project, add the placeholders as above and
  the human pastes the same values again (or uses the CLI's own sign-in). A CLI auth error (401, "unauthorized",
  "credentials") means the key is missing from this project's `.env` or wrong.

## 3. This machine

If `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/resources.py show` exits 0, say the stored presets in one line and ask
**Keep them** (Recommended) or **Change them**. Otherwise, or on Change:

1. Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/resources.py presets`. Each option's description shows its numbers,
   e.g. "6 GB memory, 6 GB GPU memory, 3 CPU threads". No GPU (`gpu_mem_gb` 0): say "no GPU". On Apple Silicon,
   say memory is shared by the CPU and the GPU.
2. **Daytime**, while the human uses the computer: **Low** (Recommended; you will not notice it), **Medium**
   (busy, but the computer stays usable), **High** (the computer gets noticeably slower), **Custom** (ask for
   memory GB, GPU memory GB and CPU threads in one free-text answer).
3. **Night:** **Full** (Recommended; everything except a reserve for the system), **Partial**, **None** (no night
   runs), **Custom**. Unless None, ask the window: **23:00 to 07:00** (Recommended) or **Another window**; then
   the idle wait, how long the computer must be unused before a night run starts: **15 minutes** (Recommended),
   **Off**, **30 minutes**, **60 minutes**.
4. Store it, e.g. `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/resources.py set --day-preset low --night-preset full
   --start 23:00 --end 07:00 --idle-minutes 15` (no `--idle-minutes` for Off; for Custom add `--day-ram GB
   --day-gpu GB --day-threads N` or the `--night-` ones, which override the preset). For night None still pass
   `--start 23:00 --end 07:00` (`set` requires a window; it is unused). Custom night numbers must be at least the
   day's, or `set` refuses. Run `show` and confirm the numbers in one line. Night never takes less than day: if
   the night numbers were raised to the day's (Partial can equal High on a big machine), say so.

## 4. Which providers

One multi-select question (Kaggle, Lightning AI, Modal). Each option's description is one line from that
service's reference, **Free tier**: its free GPU time and what it needs (a phone, a card). Then go through the
chosen ones one at a time, in that order.

## 5. One provider

a. **Already connected?** Run the reference's **Signed in already?** check (it prints only a yes or no). If it says
   yes, or `env.sh check` reads `present` for the reference's key variables, say so, install the CLI if it is
   missing (g), and go straight to the connection check (j; for Lightning, find the teamspace first, h). Before
   it, say the money safety of step e in one sentence (Modal: is the usage limit set? Lightning: auto-reload off).
b. **How:** ask **I'll drive your browser** (Recommended when a browser tool is available) or **I'll follow the
   steps myself**. Without a browser tool, give the links and the steps. Driving means: you open the pages and
   navigate the menus. The human types account details, password, phone code, card and any CAPTCHA, accepts
   terms and cookie banners, and presses the button that creates or reveals the key. You never click that
   button and never read the key from the page or a screenshot: stop before it, add the `.env` placeholders
   (step 2), ask the human to press it and paste the key into the linked `.env`, and continue only once they say
   it is there and the key is off the screen.
c. **Sign up** and verify the phone where the service asks.
d. **Card** where needed. You never type payment details.
e. **Money safety**, from the reference's **Spending cap** step: explain it before asking anything.
   - **Modal:** the **Usage limit** caps what Modal may charge the card in a month once the free credit is used
     up. freelab's runs stay within the free credit, so recommend the lowest value the page accepts; the human
     sets it.
   - **Kaggle:** no card, nothing to set.
   - **Lightning has no cap setting.** Say plainly what its reference says: the documented behaviour is to warn
     when credits run low, then stop workloads, and the card is charged only by auto-reload (off by default) or
     by buying credits; that is documented behaviour, not a written guarantee. Recommend: auto-reload OFF
     (Organization → Billing), a low-credit alert if Billing offers one, and revoking a leaked key at once.
f. **Key:** where to create it (from the reference). Recommended: add the provider's placeholders with `env.sh
   add` and give the link (step 2); the human pastes the values; check them with `env.sh check`. The
   alternative, where the reference names it, is the CLI's own browser sign-in (`modal token new`, `kaggle auth
   login`): you run it yourself, with Bash `run_in_background`, once the CLI is installed (g); it opens a
   browser tab where the human signs in, and the CLI keeps its own credential (never open or print it). For
   Lightning use the `.env` key: `lightning login` can fail from inside this session.
g. **CLI:** first check the tools it needs: `command -v uv` (every CLI install and local run uses it) and, only
   when the user wants Lightning's official skills (i), `command -v npx`. A missing one: say what it is for and
   offer to install it; on a yes, you run the install: uv `curl -LsSf https://astral.sh/uv/install.sh | sh` (or
   `brew install uv` on macOS); Node.js (for `npx`) `brew install node` on macOS, else point to the installer at
   https://nodejs.org. Then ask, and install the CLI with the reference's exact line (`uv tool install ...`;
   Lightning needs `--python 3.12`); `pipx install` if the user declines uv. Both put the tool in
   `~/.local/bin`, which this session's PATH may lack: when `command -v` still finds nothing, call it by its
   full path (`~/.local/bin/uv`, `~/.local/bin/modal`) for the rest of the session, also after `withenv`. Never
   ask the human to open a terminal or change their PATH.
h. **Lightning only: the teamspace.** First reuse `lightning_teamspace` from an existing marker. Else, when
   driving, read the `<org>/<teamspace>` part of the lightning.ai address from the tab's URL. Else ask the human
   for that part of the address. Keep it for the marker.
i. **Official skill:** if the reference names one, offer it in one line; install only on a yes.
j. **Connection check** (`compute` §3, the reference's **Connection check**). Say what it is (a 50-step run of
   the quick start on <Provider>'s GPU that proves the whole path) and its estimate from the reference's **Cost
   model**, then ask: **Run the check** (Recommended; "about N minutes, about USD X of free credit", on Kaggle
   "USD 0, from the weekly GPU quota") or **Not now**. On a yes, log the estimate (`compute` §6), run it, and
   record pass or fail with the run id. On a fail, say what the CLI said; a missing CLI or key goes back to f or
   g. Not now: the provider stays out of `services` until its check passes.
k. **Operational.** Rewrite the marker (step 6). Say "✅ <Provider> is operational" and the check's numbers in one
   line (run id, minutes, val accuracy at step 50, cost). Explain in two or three lines what the check proved:
   the code reached <Provider>, ran on its GPU, wrote its numbers and checkpoints, and came back here, so a real
   run will work the same way. Then ask one question. Put the Recommended option first: **Start the quick start**
   after the first provider, or when no picked provider is left; **Connect another provider** after a later
   provider while picked ones are left.
   - **Start the quick start**: say in two lines: one training run on <Provider>'s GPU, capped at 20 minutes,
     with its measured time and cost on <Provider> (from the **Budget** of
     `${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya/charter.md`), target test accuracy of at least 0.80 on sorting
     banking questions into 77 topics; a live status page opens by itself. Then the `plan` skill with its
     recommended charter, then `compute`.
   - **Connect another provider**: its description names the extra free hours (its reference's **Free tier**).
     Go to step 5 with it.
   - **Set up my own experiment:** the `plan` skill takes the human's goal.
   - **Stop here:** say what is connected; they can say "run the quick start" any time.

## 6. The marker

Write `${FREELAB_HOME:-$HOME/.freelab}/onboarded` with a heredoc: the date, the machine presets, the connected
services, each check's result, and Lightning's teamspace when connected. No keys.

```bash
mkdir -p "${FREELAB_HOME:-$HOME/.freelab}"
cat > "${FREELAB_HOME:-$HOME/.freelab}/onboarded" <<'EOF'
{"date": "YYYY-MM-DD", "machine": {"day": "low", "night": "full"}, "services": ["lightning"], "checks": {"lightning": "smoke-lightning-YYYYMMDD done"}, "lightning_teamspace": "ORG/TEAMSPACE"}
EOF
```

A service whose check failed stays out of `services`, with its failure in `checks`. A service added later:
rewrite the marker with every connected service. Later requests ("connect Modal", "add another provider") start
at step 5.
