# Copyright Convai Innovations (Laya, https://github.com/NandhaKishorM/laya).
# Modifications copyright the freelab authors.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance
# with the License. You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for
# the specific language governing permissions and limitations under the License.
"""Laya's decision head, rebuilt from its source for the freelab quick start (choice questions only).

Source, read in full on 2026-09-28: laya/common.py (DecisionModel, render_options, build_sequence) and laya/agent.py
(checkpoint loading, temperatures) at NandhaKishorM/laya commit 9d955671415fc19f069b9cc998928075c1f255ec, and the
model card, rl_agent_config.json and encoder/config.json of convaiinnovations/laya at Hugging Face revision
55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851 (the revision laya/revisions.py lists as reviewed).

- Limits (rl_agent_config.json): max_len 512 tokens, head_max_len 192; each option is cut to 48 tokens, and when
  the options overflow the head budget each is cut to max(4, (192 - 16) // n) tokens, as laya does.
- Temperature (choice): the per-bucket value, else 1.637 for the type. 10 options use "choice:6-10" = 1.0000;
  77 use "choice:11+" = 0.1006, which laya's runtime clamps to [0.5, 5], so 0.5. The same clamp is applied here.
- The laya package is not imported: on every load, laya.agent._fix_tokenizer_config rewrites
  tokenizer/tokenizer_config.json inside the Hugging Face cache snapshot (os.replace over the symlink) whenever
  that file lacks a usable tokenizer_class or lists its extra special tokens.
- Changes from the source: stock nn.MultiheadAttention (laya subclasses it for ONNX export, same parameters and
  maths); the act head's weights are loaded but it is not run; the tokenizer is read with `tokenizers` directly;
  `sequence()` takes the head budget as an argument, so a caller can lift it and keep every option whole.
The encoder is ModernBERT-large built by plain transformers (>= 5, which reads the checkpoint's per-layer
`rope_parameters`) from encoder/config.json, with no remote code and no random initialisation; the weights are
then copied in tensor by tensor from model.safetensors (stored in 16 bits, run in fp32)."""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path

import torch
from torch import nn

REPO = "convaiinnovations/laya"
REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
CHOICE = 0  # laya.common.QTYPES["choice"]
OPTION_TOKENS = 48


class DecisionModel(nn.Module):
    """laya.common.DecisionModel with the same parameter names: encoder, 2-layer head, type embedding, scorer."""

    def __init__(self, encoder: nn.Module, head_layers: int, n_act: int, dropout: float = 0.1):
        super().__init__()
        self.encoder = encoder
        d = encoder.config.hidden_size
        layer = nn.TransformerEncoderLayer(d, max(1, d // 64), 4 * d, dropout, batch_first=True, norm_first=True)
        self.head = nn.TransformerEncoder(layer, head_layers, enable_nested_tensor=False)
        self.type_emb = nn.Embedding(3, d)
        self.scorer = nn.Sequential(nn.LayerNorm(d), nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))
        self.act_head = nn.Sequential(nn.Linear(d + 4, 256), nn.GELU(), nn.Linear(256, n_act))  # loaded, unused
        self.register_buffer("temperature", torch.ones(3))

    def forward(self, input_ids, attention_mask, marker_pos, marker_mask, qtype):
        """Option logits, one per [MASK] marker; padding markers get -1e4."""
        h = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        h = h + self.type_emb(qtype)[:, None, :]
        pad = ~attention_mask.bool()
        for layer in self.head.layers:
            h = layer(h, src_key_padding_mask=pad)
        m = torch.gather(h, 1, marker_pos.clamp(min=0)[:, :, None].expand(-1, -1, h.size(-1)))
        return self.scorer(m).squeeze(-1).float().masked_fill(~marker_mask, -1e4)


class Laya:
    """The pinned checkpoint: model, tokenizer, limits, and laya's sequence format for one choice question."""

    def __init__(self):
        from huggingface_hub import snapshot_download
        from safetensors import safe_open
        from tokenizers import Tokenizer
        from transformers import AutoConfig, AutoModel
        from transformers.initialization import no_init_weights

        d = Path(snapshot_download(REPO, revision=REVISION, allow_patterns=[
            "rl_agent_config.json", "model.safetensors", "tokenizer/*", "encoder/*"]))
        self.cfg = json.loads((d / "rl_agent_config.json").read_text())
        tcfg = json.loads((d / "tokenizer" / "tokenizer_config.json").read_text())
        self.tok = Tokenizer.from_file(str(d / "tokenizer" / "tokenizer.json"))
        self.tok.no_truncation()
        self.tok.no_padding()
        self.mask_text = tcfg["mask_token"]
        self.cls, self.sep, self.mask, self.pad = (self.tok.token_to_id(tcfg[k]) for k in
                                                   ("cls_token", "sep_token", "mask_token", "pad_token"))
        self.max_len, self.head_max_len = int(self.cfg["max_len"]), int(self.cfg["head_max_len"])
        ecfg = AutoConfig.from_pretrained(str(d / "encoder"))
        with no_init_weights():  # every weight comes from the checkpoint; skip the random initialisation
            encoder = AutoModel.from_config(ecfg, attn_implementation="sdpa")
        try:
            encoder.config.reference_compile = False  # laya keeps ModernBERT eager too
        except AttributeError:
            pass
        self.model = DecisionModel(encoder, self.cfg.get("head_layers", 2), len(self.cfg.get("act_costs", {})) + 1)
        own = self.model.state_dict()
        with safe_open(str(d / "model.safetensors"), framework="pt") as f, torch.no_grad():
            if set(f.keys()) != set(own):
                raise RuntimeError(f"{REPO}@{REVISION}: checkpoint tensors do not match laya's DecisionModel")
            for k in f.keys():  # one tensor at a time: no second full copy of the weights in memory
                own[k].copy_(f.get_tensor(k))
        self.option_ids = lru_cache(maxsize=None)(lambda o: self.encode(" " + o)[:OPTION_TOKENS])

    def encode(self, text: str) -> list[int]:
        return self.tok.encode(text.replace(self.mask_text, " "), add_special_tokens=False).ids

    def sequence(self, state_ids: list[int], instructions: str, options: list[str], head_max_len: int):
        """laya.common.build_sequence for a choice question with undescribed options:
        [CLS] "choice question: ..." [SEP] [MASK] opt0 [MASK] opt1 ... [SEP] state [SEP].
        head_max_len is laya's budget for the question and options (self.head_max_len as shipped); when the
        options overflow it laya cuts each one. Returns (ids, marker positions, fits); fits is True when no
        option was cut and the whole state fits in max_len."""
        head = self.encode(f"choice question: {instructions}")
        opts = [[self.mask] + self.option_ids(o) for o in options]
        budget = head_max_len - sum(len(o) for o in opts)
        fits = budget >= 16
        if not fits:
            per = max(4, (head_max_len - 16) // len(opts))
            opts = [o[:per] for o in opts]
            budget = head_max_len - sum(len(o) for o in opts)
        ids = [self.cls] + head[: max(8, budget)] + [self.sep]
        markers = []
        for o in opts:
            markers.append(len(ids))
            ids += o
        ids.append(self.sep)
        room = max(0, self.max_len - len(ids) - 1)
        fits = fits and len(state_ids) <= room
        ids = (ids + state_ids[:room] + [self.sep])[: self.max_len]
        return ids, [m for m in markers if m < self.max_len], fits

    def temperature(self, k: int) -> float:
        """laya.agent: the choice bucket for k options, else the type's value, clamped to [0.5, 5]."""
        size = "2" if k <= 2 else "3-5" if k <= 5 else "6-10" if k <= 10 else "11+"
        t = self.cfg.get("temperature_by_options", {}).get(f"choice:{size}", self.cfg["temperature"][CHOICE])
        return min(5.0, max(0.5, float(t)))

    def batch(self, items: list[tuple[list[int], list[int]]], device) -> dict:
        """Pad (ids, markers) pairs into the model's inputs."""
        n, width, k = len(items), max(len(i) for i, _ in items), max(len(m) for _, m in items)
        ids = torch.full((n, width), self.pad, dtype=torch.long)
        att = torch.zeros((n, width), dtype=torch.long)
        mpos = torch.zeros((n, k), dtype=torch.long)
        mmask = torch.zeros((n, k), dtype=torch.bool)
        for r, (s, m) in enumerate(items):
            ids[r, : len(s)], att[r, : len(s)] = torch.tensor(s), 1
            mpos[r, : len(m)], mmask[r, : len(m)] = torch.tensor(m), True
        return {"input_ids": ids.to(device), "attention_mask": att.to(device), "marker_pos": mpos.to(device),
                "marker_mask": mmask.to(device), "qtype": torch.full((n,), CHOICE, dtype=torch.long, device=device)}
