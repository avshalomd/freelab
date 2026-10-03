"""freelab quick start: fine-tune Laya on Banking77. Zero-shot evaluation, fine-tuning with cross-entropy
over the option markers, evaluation after each epoch; accuracy and ECE go to metrics.jsonl through runlib. A
validation split (up to VAL_PER_CLASS unused training messages per intent, seeded with seed + 1) is scored at
step 0 and after every epoch, and is what keep/discard decisions use. The test split is scored at step 0 (a
seeded sample of ZERO_SHOT_ITEMS items) and once at the end (the whole official test split). The gain and the
before/after ECE are measured on the zero-shot sample's items only, so both sides use the same items. ECE uses
Laya's shipped temperature for the option count (0.5 for all 77), before and after training: the trained model is
not recalibrated. The framing (all-77 or 10-way) is chosen on the training sample, never on test items.
summary.json also records val_ids_sha (a hash of the validation item ids, so a research loop can check that every
experiment was judged on the same items), the torch and transformers versions and the device name.
--smoke: 200 training items, 50 steps, 200 seeded test items (the split is sorted by intent) and SMOKE_VAL_ITEMS
seeded validation items, all of them scored before and after, training only the top SMOKE_TOP_LAYERS layers. A
step is one optimiser update (16 items).
Only Laya's head and the top TRAIN_TOP_LAYERS encoder layers are trained; a checkpoint holds just those tensors
(plus optimiser, scheduler, scaler and RNG state), and the frozen rest comes from the pinned download.
--init-from PATH (a warm start, to train longer): load only the trained tensors of a train.py checkpoint (a
ckpt/step-NNNNNNNN folder or its state.pt), then train --epochs N with a fresh optimiser and schedule, in a new
--out. The split, seeds and evaluation are unchanged, so step 0 scores the starting weights. --lr-scale X
multiplies both learning rates. Both are flags a --resume must match; the run's own checkpoints hold every
tensor that differs from the pinned download, so resuming it never reads PATH again.
--skip-test (a research loop's experiments and Train longer rounds, which decide on validation alone): the test
split is not loaded at all, so no test item is read or scored and the run is shorter; summary.json then has no
test fields. The chosen run is scored on test once, at the end, by a rerun without it.
Exit codes as in runlib, and 2 for bad input (an unavailable --device, --epochs below 1, a --lr-scale that is
not a positive number, an --init-from that is missing, inside --out or not a matching train.py checkpoint, or
--resume with different flags)."""
from __future__ import annotations
import argparse, hashlib, json, math, os, platform, random, sys, time
from pathlib import Path

import torch  # before runlib.Run, so the allowance guard can cap torch's threads

try:
    import runlib
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import runlib
import data
import laya_head

DATASET, DATASET_REVISION = "mteb/banking77", "18072d2685ea682290f7b8924d94c62acc19c0b2"
INSTRUCTIONS = "Which customer-support intent does this bank message express?"
BATCH, ACCUM, SAVE_EVERY = 4, 4, 200  # micro-batches of 4 keep activations small; 16 items per step
EVAL_BATCH, ZERO_SHOT_ITEMS = 8, 500  # the zero-shot pass scores a seeded sample; the final pass the whole split
TRAIN_TOP_LAYERS = 12  # encoder layers trained, counted from the top; the embeddings and the rest stay frozen
SMOKE_TOP_LAYERS = 2  # enough to prove download, device, metrics and checkpoints; a light run, a small checkpoint
VAL_PER_CLASS, SMOKE_VAL_ITEMS = 10, 50  # validation: up to 10 unused training messages per intent
LR_ENCODER, LR_HEAD = 2e-4, 1e-3  # measured: 4 or 8 trained layers underfit in one epoch (see the README)


class BadInput(Exception):
    """Exit 2 with this message."""


def pick_device(name: str) -> torch.device:
    if name == "auto":
        if os.environ.get("FREELAB_GPU_MEM_GB") == "0":  # a GPU allowance of 0 means no GPU
            return torch.device("cpu")
        if torch.cuda.is_available():
            return torch.device("cuda")
        return torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    available = {"cpu": True, "cuda": torch.cuda.is_available(), "mps": torch.backends.mps.is_available()}
    if not available.get(name):
        raise BadInput(f"--device {name} is not available here (use auto, cpu, cuda or mps)")
    return torch.device(name)


def load_rows(with_test: bool = True):
    """(train rows, test rows, the 77 intent names); no test rows (an empty list) when with_test is False."""
    from datasets import load_dataset
    ds = load_dataset(DATASET, revision=DATASET_REVISION)
    train = [{"id": f"train-{i}", **r} for i, r in enumerate(ds["train"].to_list())]
    test = [{"id": f"test-{i}", **r} for i, r in enumerate(ds["test"].to_list())] if with_test else []
    names = {r["label"]: r["label_text"].replace("_", " ") for r in train}
    return train, test, [names[i] for i in range(len(names))]


def encode(laya, rows, names, framing, seed):
    """(ids, markers, gold index among the options, fits) per row. All-77 lifts laya's head budget to max_len so
    no option is cut (the head attends over the whole sequence); 10-way keeps the shipped budget."""
    n, budget = len(names), laya.max_len if framing == "all" else laya.head_max_len
    out = []
    for r in rows:
        opts = list(range(n)) if framing == "all" else data.candidates(r["label"], n, 10, seed, r["id"])
        state = laya.encode(json.dumps({"message": r["text"]}, ensure_ascii=False))
        ids, markers, fits = laya.sequence(state, INSTRUCTIONS, [names[o] for o in opts], budget)
        out.append((ids, markers, opts.index(r["label"]), fits))
    return out


def choose_framing(laya, rows, names, seed):
    """All-77 when its whole sequence fits for 99 % of `rows` (the training sample: never test items)."""
    fit = sum(e[3] for e in encode(laya, rows, names, "all", seed)) / len(rows)
    opt_tokens = sum(len(laya.option_ids(n)) + 1 for n in names)
    why = (f"the all-77 sequence, no option cut, fits max_len {laya.max_len} for {fit:.1%} of the training sample's "
           f"items (all-77 needs 99%); its option section is {opt_tokens} tokens, longer than laya's head budget of "
           f"{laya.head_max_len}, which that budget would cut to 4 tokens per option")
    return ("all" if fit >= 0.99 else "10way"), why


@torch.no_grad()
def predict(laya, items, device):
    """Calibrated option probabilities and the gold index, per item."""
    laya.model.eval()
    probs, gold = [], []
    for i in range(0, len(items), EVAL_BATCH):
        chunk = items[i:i + EVAL_BATCH]
        logits = laya.model(**laya.batch([(s, m) for s, m, _, _ in chunk], device)).float().cpu()
        for row, (_, m, g, _) in zip(logits, chunk):
            probs.append(torch.softmax(row[: len(m)] / laya.temperature(len(m)), -1).tolist())
            gold.append(g)
    return probs, gold


def score(probs, gold) -> dict:
    return {"accuracy": data.accuracy([p.index(max(p)) for p in probs], gold), "ece": data.ece(probs, gold)}


def evaluate(laya, items, device, sample) -> dict:
    """Accuracy and ECE over `items`, plus both over the zero-shot sample's positions in them (the same pass)."""
    probs, gold = predict(laya, items, device)
    on_sample = score([probs[i] for i in sample], [gold[i] for i in sample])
    return {**score(probs, gold), "sample_accuracy": on_sample["accuracy"], "sample_ece": on_sample["ece"]}


def val_ids_sha(rows) -> str:
    """The first 16 hex digits of the sha256 of the sorted validation ids: equal hashes, the same validation items."""
    return hashlib.sha256("\n".join(sorted(r["id"] for r in rows)).encode()).hexdigest()[:16]


def environment(device) -> dict:
    """The library versions and the device name, for summary.json (a result is read beside them)."""
    from importlib import metadata
    def version(pkg):
        try:
            return metadata.version(pkg)
        except metadata.PackageNotFoundError:
            return None
    name = torch.cuda.get_device_name(device) if device.type == "cuda" else f"{device.type} ({platform.machine()})"
    return {"torch": version("torch"), "transformers": version("transformers"), "device_name": name}


def trainable(name: str, n_layers: int, top: int) -> bool:
    """Laya's head (not the unused act head) and the top `top` encoder layers plus the final norm."""
    if name.startswith(("head.", "type_emb.", "scorer.", "encoder.final_norm.")):
        return True
    parts = name.split(".")
    return parts[:2] == ["encoder", "layers"] and int(parts[2]) >= n_layers - top


def init_state_path(path: str, flag: str = "--init-from") -> Path:
    """The state.pt of a checkpoint given as its folder (which must hold the COMPLETE marker) or as the file."""
    p = Path(path)
    if p.is_dir():
        if not (p / "state.pt").is_file():
            raise BadInput(f"{flag} {path}: no state.pt in that folder (give a checkpoint folder such as "
                           f"runs/ID/ckpt/step-00000290, or its state.pt)")
        if not (p / "COMPLETE").exists():
            raise BadInput(f"{flag} {path}: that checkpoint has no COMPLETE marker, so its write never finished")
        return p / "state.pt"
    if not p.is_file():
        raise BadInput(f"{flag} {path}: no such checkpoint (give a checkpoint folder such as "
                       f"runs/ID/ckpt/step-00000290, or its state.pt)")
    return p


def init_key(path: str | None) -> str | None:
    """--init-from as recorded in the flags: the checkpoint folder, as given (so a relaunch with the same command
    matches on any machine), whether PATH named the folder or its state.pt."""
    if not path:
        return None
    p = Path(path)
    return (p.parent if p.name == "state.pt" else p).as_posix()


def read_init(path: str, flag: str = "--init-from") -> dict:
    """The trained tensors (name -> tensor) of a train.py checkpoint, memory-mapped; BadInput if unreadable."""
    f = init_state_path(path, flag)
    try:
        state = torch.load(f, map_location="cpu", mmap=True, weights_only=True)
    except Exception as e:  # a torn copy, or not a torch checkpoint at all
        raise BadInput(f"{flag} {path}: {f} could not be read ({type(e).__name__}: "
                       f"{(str(e).splitlines() or [''])[0]})") from None
    model = state.get("model") if isinstance(state, dict) else None
    if not isinstance(model, dict) or not model:
        raise BadInput(f"{flag} {path}: {f} holds no trained tensors (a train.py checkpoint keeps them under "
                       f"'model')")
    return model


def check_init(shapes: dict, trained: dict, path: str, flag: str = "--init-from") -> None:
    """The checkpoint's tensors (name -> shape) must be some of this run's trained tensors, with the same shapes,
    so every checkpoint this run writes still holds all the weights it changed."""
    extra = sorted(set(shapes) - set(trained))
    if extra:
        raise BadInput(f"{flag} {path}: {len(extra)} of its tensors are not among the {len(trained)} trained here "
                       f"(Laya's head and top encoder layers), for example {', '.join(extra[:3])}; it comes from a "
                       f"run that trained more layers, or from another model")
    wrong = [f"{n} {tuple(shapes[n])} vs {tuple(trained[n])}" for n in sorted(shapes)
             if tuple(shapes[n]) != tuple(trained[n])]
    if wrong:
        raise BadInput(f"{flag} {path}: tensor shapes differ from the model's: {'; '.join(wrong[:3])}")


def check_args(args) -> None:
    """The bad inputs that need neither the model nor the data."""
    if args.epochs < 1:
        raise BadInput(f"--epochs must be at least 1, got {args.epochs}")
    if not (math.isfinite(args.lr_scale) and args.lr_scale > 0):
        raise BadInput(f"--lr-scale must be a positive number, got {args.lr_scale}")
    if args.init_from:
        out, src = Path(args.out).resolve(), Path(args.init_from).resolve()
        if src == out or out in src.parents:
            raise BadInput(f"--init-from {args.init_from} is inside --out {args.out}: give the warm start a new "
                           f"--out, so its checkpoints do not mix with the ones it starts from")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    runlib.add_args(p)
    p.add_argument("--framing", choices=("auto", "all", "10way"), default="auto")
    p.add_argument("--epochs", type=int, default=2)
    p.add_argument("--per-class", type=int, default=30)
    p.add_argument("--seed", type=int, default=20260928)
    p.add_argument("--device", default="auto")
    p.add_argument("--init-from", metavar="PATH", default=None,
                   help="warm start: load the trained tensors of a train.py checkpoint (a ckpt/step-NNNNNNNN folder "
                        "or its state.pt), then train --epochs N with a fresh optimiser and schedule; use a new --out")
    p.add_argument("--lr-scale", metavar="X", type=float, default=1.0,
                   help="multiply both learning rates (default 1.0; 0.5 is recommended with --init-from)")
    p.add_argument("--skip-test", action="store_true",
                   help="score no test items (neither the step-0 sample nor the final pass): for a research loop's "
                        "experiments, which decide on validation; summary.json then has no test fields")
    return p


def test_fields(zero: dict | None, last: dict | None, n_zero: int, n_test: int) -> dict:
    """summary.json's test fields: on the zero-shot sample (zero_shot_*, final_accuracy_on_zero_shot_items,
    gain_points, ece_before and ece_after) and on the whole test split (final_accuracy, final_ece); none with
    --skip-test (zero is None)."""
    if zero is None or last is None:
        return {}
    return {"zero_shot_accuracy": zero["accuracy"], "zero_shot_items": n_zero, "final_accuracy": last["accuracy"],
            "final_ece": last["ece"], "final_items": n_test,
            "final_accuracy_on_zero_shot_items": last["sample_accuracy"],
            "gain_points": round(100 * (last["sample_accuracy"] - zero["accuracy"]), 2),
            "ece_before": zero["ece"], "ece_after": last["sample_ece"]}


def main() -> None:
    args = parser().parse_args()
    try:
        check_args(args)
        device = pick_device(args.device)
        with runlib.Run(args) as run:
            experiment(args, run, device)
    except BadInput as e:
        print(f"train.py: {e}", file=sys.stderr)
        sys.exit(2)
    sys.exit(runlib.exit_code(run))


def experiment(args, run, device) -> None:
    """Everything inside the run; returns early (resumably) when run.should_stop() says so."""
    t0 = time.monotonic()
    cuda = device.type == "cuda"
    top = SMOKE_TOP_LAYERS if args.smoke else TRAIN_TOP_LAYERS
    flags = {"smoke": args.smoke, "epochs": args.epochs, "per_class": args.per_class, "seed": args.seed,
             "top_layers": top, "init_from": init_key(args.init_from), "lr_scale": args.lr_scale,
             "skip_test": args.skip_test}
    ckpt = run.latest_checkpoint() if args.resume else None
    meta = json.loads((ckpt / "meta.json").read_text()) if ckpt else {}
    if meta:
        before = dict(meta["flags"])
        before.setdefault("init_from", None)  # checkpoints written before these two flags existed
        before.setdefault("lr_scale", 1.0)
        before.setdefault("skip_test", False)
        if before["init_from"] != flags["init_from"]:
            said = {k: f"--init-from {v}" if v else "no --init-from"
                    for k, v in (("was", before["init_from"]), ("got", flags["init_from"]))}
            raise BadInput(f"--resume continues the run in --out, which started with {said['was']}; got "
                           f"{said['got']} (pass the same --init-from, or start a new --out without --resume)")
        if before != flags:
            raise BadInput(f"--resume needs the flags of the stopped run, {before}; got {flags}")
    init = read_init(args.init_from) if args.init_from and not ckpt else None  # a resume uses its own checkpoint
    torch.manual_seed(args.seed)
    run.status("loading Banking77 and Laya")
    train, test, names = load_rows(with_test=not args.skip_test)  # --skip-test: no test rows at all
    pool = train
    # The split construction (these lines, VAL_PER_CLASS, --seed and --per-class) is frozen for a research loop:
    # every experiment must be judged on the same validation items (val_ids_sha in summary.json).
    train = data.per_class_sample(pool, args.per_class, args.seed)
    val = data.holdout(pool, train, VAL_PER_CLASS, args.seed + 1)
    if args.smoke:
        train = random.Random(args.seed).sample(train, 200)
        test = random.Random(args.seed).sample(test, 200) if test else []
        val = random.Random(args.seed).sample(val, SMOKE_VAL_ITEMS)
    laya = laya_head.Laya()
    n_layers = laya.model.encoder.config.num_hidden_layers
    for n, q in laya.model.named_parameters():
        q.requires_grad_(trainable(n, n_layers, top))
    laya.model.to(device)
    if meta:
        framing, why = meta["framing"], meta["framing_reason"]
    elif args.framing == "auto":
        framing, why = choose_framing(laya, train, names, args.seed)
    else:
        framing, why = args.framing, "set with --framing"
    train_items = encode(laya, train, names, framing, args.seed)
    test_items = [] if args.skip_test else encode(laya, test, names, framing, args.seed)
    val_items = encode(laya, val, names, framing, args.seed)
    n_zero = min(ZERO_SHOT_ITEMS, len(test_items))  # the smoke's 200 items are all scored
    sample = sorted(random.Random(args.seed).sample(range(len(test_items)), n_zero))  # fixed by the seed
    epochs = 1 if args.smoke else args.epochs
    per_epoch = 50 if args.smoke else math.ceil(len(train_items) / (BATCH * ACCUM))
    total = epochs * per_epoch

    params = {n: q for n, q in laya.model.named_parameters() if q.requires_grad}
    if init is not None:  # the warm start: the trained tensors, before the step-0 evaluation
        check_init({n: tuple(t.shape) for n, t in init.items()}, {n: tuple(q.shape) for n, q in params.items()},
                   args.init_from)
        with torch.no_grad():
            for n, t in init.items():
                params[n].copy_(t)
        run.status(f"warm start: {len(init)} trained tensors from {args.init_from}")
        del init
    lr_enc, lr_head = LR_ENCODER * args.lr_scale, LR_HEAD * args.lr_scale
    opt = torch.optim.AdamW([{"params": [q for n, q in params.items() if n.startswith("encoder.")], "lr": lr_enc},
                             {"params": [q for n, q in params.items() if not n.startswith("encoder.")], "lr": lr_head}])
    warm = max(1, total // 10)
    sched = torch.optim.lr_scheduler.LambdaLR(  # linear warm-up over 10 % of the steps, then linear decay
        opt, lambda s: min((s + 1) / warm, max(0.0, (total - s) / (total - warm + 1))))
    scaler = torch.amp.GradScaler("cuda", enabled=cuda)

    if ckpt:
        state = torch.load(ckpt / "state.pt", map_location="cpu", mmap=True, weights_only=True)
        with torch.no_grad():
            for n, t in state["model"].items():
                params[n].copy_(t)
        opt.load_state_dict(state["opt"])
        sched.load_state_dict(state["sched"])
        scaler.load_state_dict(state["scaler"])
        torch.set_rng_state(state["rng"])
        if cuda and "cuda_rng" in state:
            torch.cuda.set_rng_state_all(state["cuda_rng"])
        if device.type == "mps" and "mps_rng" in state:  # dropout on MPS draws from the MPS generator
            torch.mps.set_rng_state(state["mps_rng"])
        del state
        step, zero, last, spent = meta["step"], meta["zero_shot"], meta["last_eval"], meta["minutes"]
        zero_val, last_val = meta.get("zero_val") or {}, meta.get("last_val") or {}
        run.status(f"resumed at step {step}/{total}")
    else:
        step, spent = 0, 0.0
        run.status(f"zero-shot evaluation ({framing}, {n_zero} test and {len(val_items)} validation items)")
        zero = last = None  # --skip-test: no test item is scored
        if not args.skip_test:
            probs, gold = predict(laya, [test_items[i] for i in sample], device)
            zero = last = {"step": 0, **score(probs, gold)}
            for k in ("accuracy", "ece"):
                run.log(0, total, "test", k, zero[k])
            print(data.eval_line("test", zero["accuracy"], 0), flush=True)
        zero_val = last_val = {"step": 0, **score(*predict(laya, val_items, device))}
        for k in ("accuracy", "ece"):
            run.log(0, total, "val", k, zero_val[k])
        print(data.eval_line("val", zero_val["accuracy"], 0), flush=True)

    def minutes() -> float:
        return spent + (time.monotonic() - t0) / 60

    def save() -> None:
        def write(d: Path) -> None:
            state = {"model": {n: q.detach() for n, q in params.items()}, "opt": opt.state_dict(),
                     "sched": sched.state_dict(), "scaler": scaler.state_dict(), "rng": torch.get_rng_state()}
            if cuda:
                state["cuda_rng"] = torch.cuda.get_rng_state_all()
            if device.type == "mps":
                state["mps_rng"] = torch.mps.get_rng_state()
            torch.save(state, d / "state.pt")
            (d / "meta.json").write_text(json.dumps({"step": step, "flags": flags, "framing": framing,
                                                     "framing_reason": why, "zero_shot": zero, "last_eval": last,
                                                     "zero_val": zero_val, "last_val": last_val,
                                                     "minutes": minutes()}))
        run.save(write, step)
        saved[0] = step

    saved = [step if ckpt else -1]
    while step < total:
        epoch, first = divmod(step, per_epoch)
        order = random.Random(args.seed + epoch).sample(range(len(train_items)), len(train_items))
        laya.model.train()
        for s in range(first, per_epoch):
            if run.should_stop():
                if saved[0] != step:
                    save()
                return
            step_loss = 0.0
            for a in range(ACCUM):
                at = (s * ACCUM + a) * BATCH
                rows = [train_items[order[(at + j) % len(order)]] for j in range(BATCH)]
                b = laya.batch([(ids, m) for ids, m, _, _ in rows], device)
                target = torch.tensor([g for _, _, g, _ in rows], device=device)
                with torch.autocast("cuda", dtype=torch.float16, enabled=cuda):
                    loss = torch.nn.functional.cross_entropy(laya.model(**b), target) / ACCUM
                scaler.scale(loss).backward()
                step_loss += loss.item()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(params.values(), 1.0)
            scaler.step(opt)
            scaler.update()
            opt.zero_grad(set_to_none=True)
            sched.step()
            step += 1
            run.log(step, total, "train", "loss", step_loss)
            run.status(f"epoch {epoch + 1}/{epochs}, step {step}/{total}, loss {step_loss:.3f}")
            if data.should_print_progress(step, total):
                print(data.progress_line(step, total, step_loss, minutes() * 60), flush=True)
            if step % SAVE_EVERY == 0 and step % per_epoch:
                save()
        run.status(f"evaluating after epoch {epoch + 1}/{epochs} ({len(val_items)} validation items)")
        last_val = {"step": step, **score(*predict(laya, val_items, device))}
        for k in ("accuracy", "ece"):
            run.log(step, total, "val", k, last_val[k])
        print(data.eval_line("val", last_val["accuracy"], step), flush=True)
        if step == total and not args.skip_test:  # the test split is scored once, at the end
            run.status(f"final evaluation ({len(test_items)} test items)")
            last = {"step": step, **evaluate(laya, test_items, device, sample)}
            for k in ("accuracy", "ece"):
                run.log(step, total, "test", k, last[k])
            print(data.eval_line("test", last["accuracy"], step), flush=True)
        save()
    # The test fields (test_fields) are on the zero-shot sample and the whole test split; zero_shot_val_accuracy,
    # final_val_accuracy, final_val_ece and val_items: the validation split, scored at step 0 and every epoch.
    # With --init-from, "zero-shot" (step 0) means the starting weights, and the gain is over them.
    run.finish({"framing": framing, "framing_reason": why, **test_fields(zero, last, n_zero, len(test_items)),
                "minutes": round(minutes(), 2), "device": device.type, **environment(device),
                "val_ids_sha": val_ids_sha(val),
                "zero_shot_val_accuracy": zero_val.get("accuracy"), "final_val_accuracy": last_val.get("accuracy"),
                "final_val_ece": last_val.get("ece"), "val_items": len(val_items), "init_from": flags["init_from"],
                "lr_scale": args.lr_scale, "skip_test": args.skip_test})


if __name__ == "__main__":
    main()
