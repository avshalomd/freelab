"""train.py's flags (--init-from, --lr-scale, --skip-test): argument parsing and the validation paths. CPU only, no
downloads (the `example` fixture in conftest.py imports train.py with a torch stand-in when torch is missing)."""
import sys
import pytest


@pytest.fixture
def train(example):
    return example("train")


def args(train, tmp_path, *extra):
    return train.parser().parse_args(["--out", str(tmp_path / "run"), *extra])


def ckpt(tmp_path, name="prev", complete=True):
    d = tmp_path / name / "ckpt" / "step-00000290"
    d.mkdir(parents=True)
    (d / "state.pt").write_bytes(b"x")
    if complete:
        (d / "COMPLETE").write_text("")
    return d


def test_defaults_are_a_cold_start(train, tmp_path):
    a = args(train, tmp_path)
    assert a.init_from is None and a.lr_scale == 1.0 and a.epochs == 2
    train.check_args(a)


def test_skip_test_is_off_by_default_and_parses(train, tmp_path):
    assert args(train, tmp_path).skip_test is False
    a = args(train, tmp_path, "--skip-test", "--epochs", "1")
    assert a.skip_test is True and a.epochs == 1
    train.check_args(a)


def test_skip_test_leaves_no_test_fields(train):
    """With --skip-test no test item is scored (zero is None), so summary.json gets no test field; otherwise the
    test fields come from the zero-shot sample and the final pass."""
    assert train.test_fields(None, None, 0, 0) == {}
    zero = {"step": 0, "accuracy": 0.5, "ece": 0.3}
    last = {"step": 290, "accuracy": 0.81, "ece": 0.1, "sample_accuracy": 0.8, "sample_ece": 0.12}
    f = train.test_fields(zero, last, 500, 3076)
    assert f["final_accuracy"] == 0.81 and f["final_items"] == 3076 and f["zero_shot_items"] == 500
    assert f["gain_points"] == 30.0 and f["ece_before"] == 0.3 and f["ece_after"] == 0.12


def test_warm_start_flags_parse(train, tmp_path):
    a = args(train, tmp_path, "--init-from", "prev/ckpt/step-00000290", "--epochs", "1", "--lr-scale", "0.5")
    assert a.init_from == "prev/ckpt/step-00000290" and a.epochs == 1 and a.lr_scale == 0.5
    train.check_args(a)


@pytest.mark.parametrize("scale", ["0", "-0.5", "nan", "inf"])
def test_lr_scale_must_be_positive_and_finite(train, tmp_path, scale):
    with pytest.raises(train.BadInput, match="--lr-scale"):
        train.check_args(args(train, tmp_path, "--lr-scale", scale))


def test_lr_scale_must_be_a_number(train, tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        args(train, tmp_path, "--lr-scale", "half")
    assert e.value.code == 2


def test_epochs_below_one_is_bad_input(train, tmp_path):
    with pytest.raises(train.BadInput, match="--epochs"):
        train.check_args(args(train, tmp_path, "--epochs", "0"))


def test_init_from_inside_out_is_bad_input(train, tmp_path):
    a = train.parser().parse_args(["--out", str(tmp_path / "run"), "--init-from",
                                   str(tmp_path / "run" / "ckpt" / "step-00000290")])
    with pytest.raises(train.BadInput, match="new --out"):
        train.check_args(a)
    train.check_args(train.parser().parse_args(["--out", str(tmp_path / "run2"), "--init-from",
                                                str(tmp_path / "run" / "ckpt" / "step-00000290")]))


def test_init_state_path_accepts_folder_or_file(train, tmp_path):
    d = ckpt(tmp_path)
    assert train.init_state_path(str(d)) == d / "state.pt"
    assert train.init_state_path(str(d / "state.pt")) == d / "state.pt"


def test_init_state_path_errors(train, tmp_path):
    with pytest.raises(train.BadInput, match="no such checkpoint"):
        train.init_state_path(str(tmp_path / "missing"))
    (tmp_path / "empty").mkdir()
    with pytest.raises(train.BadInput, match="no state.pt"):
        train.init_state_path(str(tmp_path / "empty"))
    with pytest.raises(train.BadInput, match="COMPLETE"):
        train.init_state_path(str(ckpt(tmp_path, "torn", complete=False)))


def test_init_key_names_the_folder(train):
    assert train.init_key(None) is None
    assert train.init_key("prev/ckpt/step-00000290/") == "prev/ckpt/step-00000290"
    assert train.init_key("prev/ckpt/step-00000290/state.pt") == "prev/ckpt/step-00000290"


def test_read_init_returns_the_model_tensors(train, tmp_path, monkeypatch):
    d = ckpt(tmp_path)
    seen = {}
    def load(f, **kw):
        seen.update(f=f, **kw)
        return {"model": {"head.w": "T"}, "opt": {}}
    monkeypatch.setattr(train.torch, "load", load, raising=False)
    assert train.read_init(str(d)) == {"head.w": "T"}
    assert seen["f"] == d / "state.pt" and seen["weights_only"] is True and seen["map_location"] == "cpu"


@pytest.mark.parametrize("state", [{}, {"model": {}}, {"model": "nope"}, ["not", "a", "dict"]])
def test_read_init_without_trained_tensors_is_bad_input(train, tmp_path, monkeypatch, state):
    d = ckpt(tmp_path)
    monkeypatch.setattr(train.torch, "load", lambda f, **kw: state, raising=False)
    with pytest.raises(train.BadInput, match="no trained tensors"):
        train.read_init(str(d))


def test_read_init_unreadable_file_is_bad_input(train, tmp_path, monkeypatch):
    d = ckpt(tmp_path)
    def load(f, **kw):
        raise RuntimeError("PytorchStreamReader failed reading zip archive\nmore")
    monkeypatch.setattr(train.torch, "load", load, raising=False)
    with pytest.raises(train.BadInput, match="could not be read .RuntimeError: PytorchStreamReader"):
        train.read_init(str(d), "--ckpt")


TRAINED = {"head.layers.0.w": (4, 4), "scorer.1.weight": (4, 4), "encoder.layers.27.w": (4,)}


def test_check_init_accepts_the_same_or_fewer_tensors(train):
    train.check_init(dict(TRAINED), TRAINED, "p")
    train.check_init({"scorer.1.weight": (4, 4)}, TRAINED, "p")  # e.g. a smoke checkpoint into a full run


def test_check_init_rejects_tensors_this_run_does_not_train(train):
    with pytest.raises(train.BadInput, match="1 of its tensors are not among the 3 trained here"):
        train.check_init({**TRAINED, "encoder.layers.3.w": (4,)}, TRAINED, "p")


def test_check_init_rejects_wrong_shapes(train):
    with pytest.raises(train.BadInput, match=r"scorer.1.weight \(4, 5\) vs \(4, 4\)"):
        train.check_init({**TRAINED, "scorer.1.weight": (4, 5)}, TRAINED, "p")


def test_bad_input_exits_2_before_any_model_or_data(train, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["train.py", "--out", str(tmp_path / "run"), "--lr-scale", "0"])
    monkeypatch.setattr(train, "experiment", lambda *a: pytest.fail("experiment must not start"))
    with pytest.raises(SystemExit) as e:
        train.main()
    assert e.value.code == 2 and "--lr-scale must be a positive number" in capsys.readouterr().err


def test_val_ids_sha_depends_on_the_ids_not_their_order(train):
    rows = [{"id": "train-3"}, {"id": "train-10"}, {"id": "train-7"}]
    sha = train.val_ids_sha(rows)
    assert len(sha) == 16 and int(sha, 16) >= 0
    assert train.val_ids_sha(list(reversed(rows))) == sha
    assert train.val_ids_sha(rows[:2]) != sha
    assert train.val_ids_sha([*rows[:2], {"id": "train-8"}]) != sha
    import hashlib
    assert sha == hashlib.sha256(b"train-10\ntrain-3\ntrain-7").hexdigest()[:16]
