# Train longer, in rounds

Read by `plan` §1 when the user picks **Train longer** (offered by `report` §4). A charter like any other, for
more training from a finished run (the first run).

- **Rounds:** up to N (the user's cap, default 3). Each round is a warm start from the previous round's final
  checkpoint (the first round: the first run's), under a new run id (`<first run id>-round1`, `-round2`, ...):
  `--init-from <previous final checkpoint> --epochs 1 --lr-scale 0.5 --skip-test`, on the same backend (its
  reference's **Warm start**). With `--skip-test` a round never reads the test split.
- **Stop rule:** after each round, compare its final validation score with the best so far (the first run's
  included): better, and it becomes the best and the next round starts from it; not better, and the rounds stop.
  They also stop at the cap or the budget.
- **The result:** the best round's checkpoint. The test split is scored once, for that round only: one scoring
  run relaunches it with the same flags without `--skip-test` (run id `<round id>-test`, its estimate logged),
  as in a research loop; read its `final_accuracy`, and report its validation beside the round's. If no round
  beat the first run, there is no scoring run: the first run's test number stands. Each round and the scoring
  run show on the status page as runs, and together they are one stage of the plan.
- **The goal:** does more training lift the score? The baseline is the first run's result. The metric, data and
  splits stay. The target is a number: the charter's target if the first run missed it, otherwise its score plus
  a step worth having (e.g. one point), on validation for choosing and test for the one final number.
- **The budget** comes from the measured run (the example charter's **Budget** for the quick start): each round
  is about half of a 2-epoch run's training minutes plus setup, with no test scoring; the scoring run adds one
  round plus the test pass. The total is the cap times a round, plus one scoring run. Each launch logs its own
  estimate first.
- **The new decisions** each get the four parts: the starting weights, the number of rounds and the stop rule,
  the epochs per round (`--epochs 1`), the learning-rate scale (`--lr-scale 0.5`: the weights are already
  trained, and the full rates can undo some of that) and the one scoring run at the end.
- **The caveat:** the test split is scored once more (for the chosen round), so it has been seen twice.
