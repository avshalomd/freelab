import importlib, importlib.util, sys, types
import pytest

EXAMPLE = ("train", "laya_head", "demo")  # the quick start's modules (examples/banking77-laya, on pythonpath)


@pytest.fixture(autouse=True)
def freelab_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FREELAB_HOME", str(tmp_path / "home"))


@pytest.fixture
def example(monkeypatch):
    """Import one of the quick start's modules, CPU only and with no downloads. When torch is not installed (the
    plain test environment), a stand-in goes in sys.modules just for the import: train.py and demo.py need torch only
    for `@torch.no_grad()` and laya_head's `nn.Module` at import time. The modules are dropped again afterwards."""
    if importlib.util.find_spec("torch") is None:
        torch = types.ModuleType("torch")
        torch.no_grad = lambda: (lambda f: f)
        torch.nn = types.ModuleType("torch.nn")
        torch.nn.Module = object
        monkeypatch.setitem(sys.modules, "torch", torch)
        monkeypatch.setitem(sys.modules, "torch.nn", torch.nn)
    for m in EXAMPLE:
        sys.modules.pop(m, None)
    yield importlib.import_module
    for m in EXAMPLE:
        sys.modules.pop(m, None)
