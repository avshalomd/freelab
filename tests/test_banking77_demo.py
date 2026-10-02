"""demo.py's pure parts: request validation and top-k formatting, without loading the model (the `example` fixture
in conftest.py imports it with a torch stand-in when torch is missing)."""
import json
import pytest


@pytest.fixture
def demo(example):
    return example("demo")


def body(obj):
    return json.dumps(obj).encode()


def test_parse_request_text_and_default_top_k(demo):
    assert demo.parse_request(body({"text": "  Where is my card?  "})) == ("Where is my card?", 5)
    assert demo.parse_request(body({"text": "x", "top_k": 3})) == ("x", 3)


def test_parse_request_clamps_top_k(demo):
    assert demo.parse_request(body({"text": "x", "top_k": 0}))[1] == 1
    assert demo.parse_request(body({"text": "x", "top_k": 500}))[1] == 77
    assert demo.parse_request(body({"text": "x", "top_k": 500}), n_labels=10)[1] == 10


@pytest.mark.parametrize("raw, message", [
    (b"not json", "send JSON"), (b"[1, 2]", "send JSON"), (b"", "text is empty"), (b"\xff\xfe", "send JSON"),
    (body({"text": "   "}), "text is empty"), (body({"text": 5}), "text is empty"),
    (body({"text": "x" * 2001}), "longer than 2000"),
    (body({"text": "x", "top_k": "5"}), "whole number"), (body({"text": "x", "top_k": 2.5}), "whole number"),
    (body({"text": "x", "top_k": True}), "whole number"),
])
def test_parse_request_rejects(demo, raw, message):
    with pytest.raises(ValueError, match=message):
        demo.parse_request(raw)


def test_top_intents_most_probable_first(demo):
    names = ["card arrival", "pin blocked", "top up failed", "lost or stolen card"]
    out = demo.top_intents([0.1, 0.6, 0.1, 0.2], names, 3)
    assert out == [{"intent": "pin blocked", "probability": 0.6}, {"intent": "lost or stolen card", "probability": 0.2},
                   {"intent": "card arrival", "probability": 0.1}]  # the tie keeps label order
    assert len(demo.top_intents([0.25] * 4, names, 10)) == 4
    assert demo.top_intents([0.123456, 0.876544], names[:2], 1) == [{"intent": "pin blocked", "probability": 0.8765}]


def test_page_embeds_data_safely_and_loads_nothing_external(demo):
    html = demo.page({"model": "base", "intents": 77, "device": "cpu", "note": "</script><b>"}).decode()
    assert "</script><b>" not in html and "\\u003c/script>" in html
    assert "http://" not in html and "https://" not in html and "__DATA__" not in html
    assert "prefers-color-scheme: dark" in html and "width=device-width" in html
