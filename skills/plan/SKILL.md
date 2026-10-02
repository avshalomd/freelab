---
name: plan
description: Use when a freelab lab needs its goal or plan - "write the charter", "what should we test", "define the target", "plan the experiment", "train it longer", or when lab/charter.md or lab/plan.md is missing or lacks a numeric target or budget. Recommends and explains the charter, writes the plan.
---

# plan: the charter and the plan

If the `lab` skill isn't loaded this session, load it first: it holds the rules. This skill writes two files:
`lab/charter.md` and `lab/plan.md`.

## 1. The charter, explained, with a recommendation

Recommend a whole charter, explain it, and ask one question. Two aims, both matter: the user can approve with one
answer, and the user **understands what they approve**, well enough to set up their next experiment themselves.
A bare "go with recommended" with half-sentence reasons fails the second aim. Never ask the question before the
explanation is in your message.

- **Where the recommendation comes from:** the user's goal, the compute they connected and its measured smoke
  numbers (minutes, cost). For the quick start, take it from the shipped charter,
  `${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya/charter.md`: the single run, or its "Next: try to beat it"
  section for a research loop. Its **Budget** holds the measured time and cost per provider. If the goal is
  unclear, ask for it in one question first.
- **The fields** are those of `${CLAUDE_PLUGIN_ROOT}/skills/plan/references/charter-template.md`: goal, decision
  it feeds, metric, target, validation, baseline, data, budget, allowed compute, decision GPU type, editable
  surface, frozen, per-experiment budget, stop rules, out of scope. The research fields (validation, decision GPU
  type, editable surface, frozen, per-experiment budget) are only for a research loop (`research`). For a loop,
  the target is on the validation split, and the stop rules include "K non-improving experiments in a row"
  (default 8). The decision GPU type is one type for the baseline and every keep or discard; by default the GPU
  type the first run used (the quick start: Modal's L4, a T4 on Kaggle and Lightning AI), so that run can be the
  baseline. The per-experiment budget is the baseline's minutes on that type (model and
  data downloads count) plus runlib's 2-minute margin (it stops a run 2 minutes before `--max-minutes`), with some
  headroom. The quick start's loop values are in the shipped charter's "Next: try to beat it".
- **Metric, target and budget are never blank.** The target is a number with a direction (`accuracy >= 0.80`).
  The budget is USD beyond free credit (default 0) and wall-clock hours.
- **Work out the plan first** (§2: stages, placement, estimates), so the totals come from it. Write both files
  after the answer.

**Train longer, in rounds** (offered by `report` §4): read
`${CLAUDE_PLUGIN_ROOT}/skills/plan/references/train-longer.md` for its design, then explain it like any charter.

**The explanation**, in this order (the worked example for the quick start is
`${CLAUDE_PLUGIN_ROOT}/skills/plan/references/quick-start-walkthrough.md`; read it and match its depth):

1. **What we are about to do:** the experiment in two or three plain sentences, and what a charter is: the few
   decisions written down before a run so that its result means something.
2. **Each decision as a short block** (group fields that belong together: goal and decision; data and its
   splits; baseline; metric and target; compute and budget; what stays fixed and the stop rules; for a loop,
   also what may change and the per-experiment budget). Each block has four parts:
   - **Recommended:** the value, with its numbers;
   - **Why:** the evidence (measured times, earlier results, what the connection check showed);
   - **Alternatives:** one or two realistic options and what each would change (time, cost, how trustworthy the
     result is, what you learn);
   - **For you:** what it means for the user in plain words.
   Explain a technical term the first time it appears (validation and test splits, baseline, loss).
3. **The plan:** the stages, where each runs and why there, what the user will see while it runs (the status
   page), and the totals: time, free credit, the user's money.
4. **Caveats** that affect how to read the result, in plain words.
5. **For your own experiment:** two lines on which decisions change for the user's own goal, and how to start it
   ("set up my own experiment").

Length: the first experiment a user sees (the quick start, or their first own one) gets the full explanation.
Later ones can be shorter for decisions already explained, unless the user asks; any decision they have not seen
yet (for example the research loop's validation target, what may change, K, the per-experiment budget, or the
rounds of Train longer) gets all four parts.

Then ask one question (with AskUserQuestion when available, else a short numbered list):

- **Go with recommended** (Recommended): write `lab/charter.md` from the template with these values, and
  `lab/plan.md` (§2); §4 says when this answer also approves the plan.
- **Change something:** ask which decision. For each one changed, one question with the same four parts in your
  message before it and the recommendation as the first option ("(Recommended)"). Keep asking until the metric,
  target and budget are set. Then show what changed, with the new totals, and ask the same question again.
- **Explain a part more:** ask which part, explain it in more depth (how it works, why it matters, a small
  example), then ask the same question again.

**A change in the user's own words** ("3 epochs instead of 2", "use Kaggle"), at this question or later, is not
applied at once: first give that decision the four parts in your message (what the change does to the time, the
cost and the result, and whether you would recommend it), then ask **Apply the change** or **Keep the
recommendation**, with your recommendation first. Then show the new totals.

Allowed compute is any of: this machine, Modal, Lightning AI, Kaggle. Recommend the ones that are connected.

## 2. The plan

Write `lab/plan.md`. Stage 0 is always the connection check (the `compute` skill's smoke) for each backend the
plan uses that has not passed one. Then a baseline stage, then the stages that move the metric. A baseline
measured inside the same run (the quick start's zero-shot score at step 0) is part of that run, not a stage of
its own: the quick start's plan has one stage.

```markdown
# Plan: <charter name>

## Stage <n>: <name>
- **Goal:** <what this stage measures>
- **Decision it feeds:** <which choice its result changes>
- **Need:** <RAM GB>, <GPU memory GB>, <hours>
- **Placement:** <cloud: backend | now | tonight (N nights) | ask>, from `resources.py check`
- **Estimate:** <wall-clock time>, USD <cost> (<free credit or paid>)
- **Go/no-go:** go on to <stage> if <condition on the metric>; otherwise <stop, or what instead>
```

- **Need:** estimate the peak memory and the hours from the model size and the data. Refine it from the smoke
  run's measured peak and minutes, then update the plan.
- **Placement:** cloud first, as in `compute` §2. A run the user wants now (the quick start included) goes to a
  connected cloud backend with free credit left: the provider the user chose at onboarding's "Start the quick
  start", else the first connected one in the order Modal, Lightning AI, Kaggle. This machine is for when the
  user asks for it, when no cloud backend is connected, or when a long job would burn the free quota. "Tonight"
  is offered as a choice, never picked silently. Run the placement check for each stage and copy its answer; for
  an `ask`, settle it with the user before the plan is final.
- **Estimate:** hours × the backend's rate from its reference's **Cost model**. This machine costs USD 0.

Write the stages to `lab/status.json` `stages` as well, in the same order, each `{"name": "<stage name>",
"state": "planned", "detail": "<one line: goal or placement>"}`, with `status_page.py set --lab lab stages
'<the list as JSON>'` (the `status` skill, §2). When the plan changes, change them too. For a task that is not a
training run, also pick the status page's blocks here (`status`, Building blocks) and set `layout` the same way.

## 3. Every stage feeds a decision

For every stage, ask: **"which decision does this stage's result feed?"** A stage with no answer, or whose
result could not change the next step, is cut, or brought back to the user with your recommendation.

## 4. Approval

Get the user's approval of the plan, with its total time and cost, before the first run beyond the smoke runs
(money: `lab` rule 2).

- **One stage** (connection checks that already passed do not count, nor a baseline measured inside the run;
  a research loop's baseline and loop count as one, and so do the rounds of Train longer): the charter's **Go
  with recommended** is the approval. Ask nothing more.
- **More stages:** show the plan as a short table (stage, what it decides, time, cost) with the totals. In the
  message, before the question, give each stage's reason (what it decides and why it is worth its time and cost)
  and one alternative to it. Then ask one question: **Approve the plan** (Recommended) or **Change it**.
