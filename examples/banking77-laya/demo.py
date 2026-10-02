"""Try the trained model: a small local demo of Laya fine-tuned on Banking77.

    python demo.py --ckpt runs/ID/ckpt/step-00000290 [--port 8077]
    python demo.py --base [--port 8077]      # the pinned Laya checkpoint, untrained, for a quick check

It loads the pinned Laya checkpoint plus the trained tensors of a train.py checkpoint (its folder or state.pt;
use the run's final one), frames each message the way train.py scores it (one choice over all 77 intents, the
same instruction text, train.encode and train.predict), and serves on 127.0.0.1 only:
  GET  /               one page: type a bank customer message, or click an example, and see the top 5 intents
  POST /api/classify   {"text": "...", "top_k": 5} -> {"intents": [{"intent", "probability"}], "truncated", "ms"}
The 77 intent names come from train.load_rows (the pinned mteb/banking77 revision). The device is chosen like
train.py's: CUDA, then Apple MPS, then CPU. Exit code 2 for bad input (a missing or mismatched checkpoint)."""
from __future__ import annotations
import argparse, json, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import train  # also imports torch, runlib, data and laya_head
import laya_head

MAX_TEXT, MAX_BODY, DEFAULT_TOP_K = 2000, 64 * 1024, 5
EXAMPLES = [
    "I ordered a card two weeks ago and it still hasn't arrived",
    "Why was I charged an extra fee for taking cash out?",
    "My top-up didn't go through but the money left my account",
    "I think someone used my card without permission",
    "How do I change my PIN?",
    "The exchange rate on my transfer looks wrong",
]


def parse_request(body: bytes, n_labels: int = 77) -> tuple[str, int]:
    """(text, top_k) from a /api/classify body; ValueError with a message the page can show."""
    try:
        req = json.loads(body or b"{}")
    except (ValueError, UnicodeDecodeError):
        raise ValueError('send JSON like {"text": "...", "top_k": 5}') from None
    if not isinstance(req, dict):
        raise ValueError('send JSON like {"text": "...", "top_k": 5}')
    text = req.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text is empty")
    if len(text) > MAX_TEXT:
        raise ValueError(f"text is longer than {MAX_TEXT} characters")
    top_k = req.get("top_k", DEFAULT_TOP_K)
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise ValueError("top_k must be a whole number")
    return text.strip(), max(1, min(top_k, n_labels))


def top_intents(probs: list[float], names: list[str], k: int) -> list[dict]:
    """The k most probable intents, most probable first (ties keep label order), probabilities to 4 places."""
    order = sorted(range(len(probs)), key=lambda i: -probs[i])[:k]
    return [{"intent": names[i], "probability": round(float(probs[i]), 4)} for i in order]


class Classifier:
    """The pinned Laya checkpoint, optionally with a run's trained tensors, scoring all 77 intents."""

    def __init__(self, ckpt: str | None):
        t0 = time.monotonic()
        tensors = train.read_init(ckpt, "--ckpt") if ckpt else None  # fails fast, before the 1.7 GB model loads
        self.device = train.pick_device("auto")
        self.names = train.load_rows()[2]
        self.laya = laya_head.Laya()
        self.info = {"model": "base", "trained_tensors": 0, "intents": len(self.names), "device": self.device.type}
        if tensors is not None:
            model = self.laya.model
            n_layers = model.encoder.config.num_hidden_layers
            params = {n: q for n, q in model.named_parameters()
                      if train.trainable(n, n_layers, train.TRAIN_TOP_LAYERS)}
            train.check_init({n: tuple(t.shape) for n, t in tensors.items()},
                             {n: tuple(q.shape) for n, q in params.items()}, ckpt, "--ckpt")
            with train.torch.no_grad():
                for n, t in tensors.items():
                    params[n].copy_(t)
            self.info.update(model="trained", trained_tensors=len(tensors), ckpt=train.init_key(ckpt),
                             **checkpoint_facts(train.init_state_path(ckpt, "--ckpt").parent))
            del tensors
        self.laya.model.to(self.device).eval()
        self.lock = threading.Lock()
        self.info["load_seconds"] = round(time.monotonic() - t0, 1)

    def classify(self, text: str, top_k: int) -> dict:
        t0 = time.monotonic()
        row = {"id": "demo", "text": text, "label": 0}  # the label only picks the gold index, unused here
        item = train.encode(self.laya, [row], self.names, "all", 0)  # all-77 ignores the seed
        with self.lock:
            probs, _ = train.predict(self.laya, item, self.device)
        return {"intents": top_intents(probs[0], self.names, top_k), "truncated": not item[0][3],
                "ms": round((time.monotonic() - t0) * 1000)}


def checkpoint_facts(folder: Path) -> dict:
    """The step and, when that checkpoint was scored on the test split at that step, its test accuracy."""
    try:
        meta = json.loads((folder / "meta.json").read_text())
    except (OSError, ValueError):
        return {}
    facts = {"step": meta.get("step")}
    last = meta.get("last_eval") or {}
    if last.get("step") == meta.get("step") and "accuracy" in last:
        facts["test_accuracy"] = round(last["accuracy"], 3)
    return facts


def page(info: dict) -> bytes:
    blob = json.dumps({"info": info, "examples": EXAMPLES}).replace("<", "\\u003c")
    return PAGE.replace("__DATA__", blob).encode()


def make_handler(clf: Classifier, html: bytes):
    class Handler(BaseHTTPRequestHandler):
        def send(self, code: int, body: bytes, kind: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def json(self, code: int, obj) -> None:
            self.send(code, json.dumps(obj).encode())

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self.send(200, html, "text/html; charset=utf-8")
            else:
                self.json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/api/classify":
                return self.json(404, {"error": "not found"})
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                size = -1
            if not 0 <= size <= MAX_BODY:
                return self.json(400, {"error": f"send a JSON body of at most {MAX_BODY} bytes"})
            try:
                text, top_k = parse_request(self.rfile.read(size), len(clf.names))
            except ValueError as e:
                return self.json(400, {"error": str(e)})
            self.json(200, clf.classify(text, top_k))

        def log_message(self, fmt, *args):
            print(f"{self.command} {self.path} {args[1] if len(args) > 1 else ''}", flush=True)

    return Handler


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--ckpt", metavar="PATH", help="a train.py checkpoint: ckpt/step-NNNNNNNN or its state.pt")
    src.add_argument("--base", action="store_true", help="no trained tensors: the pinned Laya checkpoint, untrained")
    p.add_argument("--port", type=int, default=8077)
    args = p.parse_args()
    print("loading Banking77's intent names and Laya (the first run downloads about 1.7 GB)...", flush=True)
    try:
        clf = Classifier(None if args.base else args.ckpt)
    except train.BadInput as e:
        print(f"demo.py: {e}", file=sys.stderr)
        sys.exit(2)
    i = clf.info
    what = (f"trained ({i['trained_tensors']} tensors from {i['ckpt']})" if i["model"] == "trained"
            else "base, untrained (no fine-tuning)")
    print(f"model ready on {i['device']} in {i['load_seconds']}s: {what}", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(clf, page(i)))
    print(f"open http://127.0.0.1:{args.port}  (Ctrl+C stops it)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Banking77 Intent Demo</title>
<style>
:root {
  --bg: #f6f7f6; --surface: #ffffff; --fg: #151817; --muted: #59605c; --line: #dfe3e0; --track: #eceeed;
  --accent: #2a6fd0; --accent-fg: #ffffff; --accent-soft: #e7eefa; --warn-bg: #fff4dc; --warn-fg: #6b4a00;
  --bad: #b3261e;
  --f-body: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --f-mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #121514; --surface: #1a1e1c; --fg: #eceeed; --muted: #a0a8a4; --line: #2b312e; --track: #242a27;
    --accent: #4a8ce6; --accent-fg: #0b1220; --accent-soft: #1c2a3e; --warn-bg: #3a2e12; --warn-fg: #f3d58c;
    --bad: #f2756d; color-scheme: dark; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.5 var(--f-body); }
.wrap { max-width: 720px; margin: 0 auto; padding: 28px 16px 48px; display: grid; gap: 16px; }
.eyebrow { font: 12px/1.4 var(--f-mono); color: var(--muted); }
h1 { margin: 4px 0 0; font-size: 1.7rem; font-weight: 600; letter-spacing: -0.01em; }
.warn { background: var(--warn-bg); color: var(--warn-fg); border-radius: 10px; padding: 10px 14px; font-size: 14px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 16px; display: grid; gap: 12px; min-width: 0; }
label { font-weight: 600; font-size: 14px; }
textarea { width: 100%; min-height: 84px; resize: vertical; font: inherit; color: var(--fg); background: var(--bg);
  border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }
textarea:focus-visible, button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
button { font: inherit; cursor: pointer; border-radius: 8px; border: 1px solid var(--line); background: var(--surface);
  color: var(--fg); padding: 6px 12px; }
button.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-fg); font-weight: 600; padding: 8px 18px; }
button:disabled { opacity: 0.55; cursor: default; }
.chip { font-size: 13px; padding: 4px 10px; border-radius: 999px; background: var(--accent-soft); border-color: transparent; text-align: left; }
.hint { font-size: 13px; color: var(--muted); }
.top { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.top .name { font-size: 1.25rem; font-weight: 600; overflow-wrap: anywhere; }
.top .p { font: 1.25rem var(--f-mono); }
.bars { display: grid; gap: 10px; }
.bar-row { display: grid; grid-template-columns: minmax(0, 1fr) 64px; gap: 4px 12px; align-items: center; font-size: 14px; }
.bar-row .n { overflow-wrap: anywhere; }
.bar-row .v { font-family: var(--f-mono); text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
.bar { grid-column: 1 / -1; height: 6px; background: var(--track); border-radius: 999px; overflow: hidden; }
.bar > span { display: block; height: 100%; background: var(--accent); border-radius: 999px; }
.meta { font: 12px var(--f-mono); color: var(--muted); }
.error { color: var(--bad); font-size: 14px; margin: 0; }
pre { margin: 0; font: 12.5px/1.5 var(--f-mono); background: var(--bg); border: 1px solid var(--line); border-radius: 8px;
  padding: 10px 12px; overflow-x: auto; }
</style>
</head>
<body>
<main class="wrap">
  <header>
    <div class="eyebrow" id="eyebrow"></div>
    <h1>Banking77 intent demo</h1>
  </header>
  <div class="warn" id="warn" hidden>Untrained: this is the base Laya checkpoint with no fine-tuning, started
    with <code>--base</code>. Its guesses show the zero-shot starting point, not the trained model.</div>
  <section class="card">
    <label for="msg">Bank customer message</label>
    <textarea id="msg" maxlength="2000" placeholder="e.g. My card payment was declined at the supermarket"></textarea>
    <div class="row">
      <button class="primary" id="go">Classify</button>
      <span class="hint">or Ctrl/Cmd + Enter</span>
    </div>
    <div class="row" id="examples" aria-label="Example messages"></div>
  </section>
  <section class="card" id="out" hidden aria-live="polite">
    <div class="bars" id="results"></div>
    <div class="meta" id="meta"></div>
  </section>
  <section class="card">
    <label>Call it from code</label>
    <pre id="curl"></pre>
  </section>
</main>
<script>
const DATA = __DATA__;
const $ = id => document.getElementById(id);
const info = DATA.info;
const bits = [info.model === "trained" ? "Laya fine-tuned on Banking77" : "Laya, base checkpoint (untrained)"];
if (info.step != null) bits.push("step " + info.step);
if (info.test_accuracy != null) bits.push("test accuracy " + info.test_accuracy.toFixed(3));
bits.push(info.intents + " intents", "on " + info.device.toUpperCase());
$("eyebrow").textContent = bits.join(" · ");
$("warn").hidden = info.model === "trained";
$("curl").textContent = "curl -s " + location.origin + "/api/classify \\\n  -H 'Content-Type: application/json' \\\n" +
  "  -d '{\"text\": \"Where is my new card?\", \"top_k\": 3}'";
DATA.examples.forEach(t => {
  const b = document.createElement("button"); b.className = "chip"; b.textContent = t;
  b.onclick = () => { $("msg").value = t; classify(); }; $("examples").appendChild(b);
});
const pct = p => (p * 100).toFixed(1) + "%";
async function classify() {
  const text = $("msg").value.trim();
  if (!text) { $("msg").focus(); return; }
  $("go").disabled = true; $("out").hidden = false;
  $("results").innerHTML = '<span class="hint">Classifying...</span>'; $("meta").textContent = "";
  try {
    const r = await fetch("/api/classify", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, top_k: 5 }) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || r.statusText);
    const res = $("results"); res.textContent = "";
    const top = document.createElement("div"); top.className = "top";
    const name = document.createElement("span"); name.className = "name"; name.textContent = d.intents[0].intent;
    const p = document.createElement("span"); p.className = "p"; p.textContent = pct(d.intents[0].probability);
    top.append(name, p); res.appendChild(top);
    d.intents.forEach(i => {
      const row = document.createElement("div"); row.className = "bar-row";
      const n = document.createElement("span"); n.className = "n"; n.textContent = i.intent;
      const v = document.createElement("span"); v.className = "v"; v.textContent = pct(i.probability);
      const bar = document.createElement("div"); bar.className = "bar";
      const fill = document.createElement("span"); fill.style.width = pct(i.probability);
      bar.appendChild(fill); row.append(n, v, bar); res.appendChild(row);
    });
    $("meta").textContent = d.ms + " ms · top " + d.intents.length + " of " + info.intents + " intents" +
      (d.truncated ? " · the message was cut to fit 512 tokens" : "");
  } catch (e) {
    const res = $("results"); res.textContent = "";
    const p = document.createElement("p"); p.className = "error"; p.textContent = "Could not classify: " + e.message;
    res.appendChild(p);
  } finally { $("go").disabled = false; }
}
$("go").onclick = classify;
$("msg").addEventListener("keydown", e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) classify(); });
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
