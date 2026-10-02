# The quick start's charter, explained (a worked example)

This is the quality bar for `plan` §1: what the user reads before the question for the quick start. Adapt the
numbers to the backend (Kaggle, Lightning AI or Modal) and to the measured connection check. The times and costs
below are illustrative: the measured ones per provider are in the **Budget** of
`${CLAUDE_PLUGIN_ROOT}/examples/banking77-laya/charter.md`; take them from there. Keep the shape:
each decision with its recommendation, why, the alternatives and what it means. Plain words; a term is
explained the first time it appears. Fill in the angle-bracket parts.

---

**What we are about to do.** We teach a small open AI model (Laya, 421 million parameters) to sort bank-support
messages into 77 topics, such as "card arrived?" or "exchange rate". Before training it gets about half of them
right; after a short training run it should get at least 8 in 10. It is a real experiment, small enough to finish
in about <minutes on this provider> minutes, and it walks through every step you would use for your own.

An experiment needs a few decisions written down before it runs, so that the result means something. freelab
calls this the **charter**. Here are the decisions, with what I recommend and why.

**1. The question it answers (goal and decision).**
- Recommended: "How much does a few minutes of training on 30 examples per topic improve a small model at
  routing bank questions?" It feeds one decision: is fine-tuning a small model worth it for a routing task?
- Why: an experiment is worth running only if its answer changes what you do next.
- Alternatives: "just see if it runs" (proves the setup, teaches nothing about the model); a bigger question
  such as "which of three models is best" (several runs, about 1 hour).
- For you: you get a yes or no with a number, not just a finished job.

**2. The data, and how it is split.**
- Recommended: Banking77, a public dataset of 13,000 real bank-support messages. Three separate parts:
  - **training** (2,310 messages, 30 per topic): what the model learns from;
  - **validation** (up to 770 other messages): checked after each round of training, to see if it is improving;
  - **test** (3,076 messages): scored once, at the very end. Because nothing is chosen by looking at it, the
    test score is an honest estimate of how it would do on new messages.
- Why: scoring on the data you trained on, or picking the best version by looking at test, makes results look
  better than they are. Keeping the parts apart is what makes the number trustworthy.
- Alternatives: more training examples per topic (better accuracy, longer run); a smaller test set (faster, but a
  less precise number).
- For you: the final number is one you can believe.

**3. The starting point (baseline).**
- Recommended: score the model before any training, on 500 test messages. That is the "before" to compare with.
- Why: without a "before", an 80 % result says nothing; with it, you see the gain.
- Alternative: score the baseline on all 3,076 test messages: a more precise before-number, about 2-3 more minutes
  of evaluation.
- For you: the report says "from about 54 % to <result>".

**4. How success is measured (metric) and the target.**
- Recommended: **accuracy**, the share of test messages put in the right topic; target **at least 0.80** (8 in 10).
- Why: accuracy is easy to read and fits a sorting task. 0.80 is a clear step up from about 0.54 and was reached
  in earlier runs of this exact setup (0.82 on Modal, 0.83 on Kaggle), so it is ambitious but realistic for one
  short run.
- Alternatives: a higher target such as 0.85 (likely needs several tries: that is the "try to beat it" loop after
  this); other metrics such as calibration (how far the model's confidence is from its real accuracy) are
  logged beside it but are not the headline.
- For you: the report gives a clear "met" or "not met", with the uncertainty of the number.

**5. Where it runs, and what it costs (compute and budget).**
- Recommended: <Provider>'s <GPU> (a T4 on Kaggle and Lightning AI, an L4 on Modal), which just passed its
  connection check (<minutes> minutes, <cost>). About <minutes on this provider> minutes end to end (e.g. on
  Kaggle about 17: training about 9 minutes, the final test scoring about 6), <cost of the run> of free credit,
  nothing of your money. A hard cap stops it at 20 minutes.
- Why: <Provider> is connected and its check passed. A GPU makes this run take minutes instead of the better part
  of an hour.
- Alternatives: <another connected provider and how it compares, e.g. Modal's L4 finished in 9 minutes; Modal and
  Lightning use free credit, Kaggle uses none and shows the progress live but the charts only at the end>; this
  computer (free, but about 10 minutes for only half the training: the 1-epoch run on this computer reached
  0.767, under the 0.80 target, and it keeps your computer busy).
- For you: you pay nothing, and it cannot run away: it stops by itself.

**6. What stays fixed, and when it stops.**
- Recommended: the training settings stay as shipped (2 epochs, that is 2 passes over the training messages,
  with settings picked earlier); it stops after the 2 epochs or at 20 minutes, and the result is reported as
  measured, even under the target.
- Why: one run changes nothing, so the comparison is clean. Tuning settings is a separate experiment.
- Alternative: let it tune settings now (that is the research loop, offered after this run: a short one of about
  15-20 minutes, a few runs).
- For you: one clean answer now; improving it is the optional next step.

**The plan.** One stage: the training run on <Provider>. While it runs, a live status page opens: what is
happening, progress toward the target, charts of accuracy and of the training loss (how wrong the model still is;
it should go down), whether more training would still help, and the cost so far. <On Kaggle: the charts arrive
when the run ends; until then the top line follows the run's live log.> Then, without you asking, a short report: the result against the target, the "before", the cost,
and the caveats, and the next steps: try the trained model on this computer, train longer, try to beat it, or
clean up and stop.

**One honest caveat.** The training settings were picked in an earlier version by looking at some test messages,
so the 0.80 on test is not perfectly clean. Later changes are judged on validation only.

**For your own experiment.** The same six decisions apply; what changes is the question, the data and the model.
When you want to, say "set up my own experiment" and I will walk you through them the same way.

---

Then the question: **Go with recommended** (Recommended), **Change something**, **Explain a part more**.
