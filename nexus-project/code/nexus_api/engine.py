"""EngineAdapter: how the gateway talks to an inference engine.

`NexusPipelineEngine` runs the staged demo pipeline. A future `AtenheaEngine`
(local engine from NEXUS/atenhea) only needs to implement the same two methods.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from nexus_runtime.model_demo import tok_encode
from nexus_runtime.models import load_head
from nexus_runtime.pipeline import Pipeline


MAX_PROMPT_TOKENS = 1024


class EngineAdapter(ABC):
    @abstractmethod
    def list_models(self) -> List[Dict]:
        """[{'id': str, 'owned_by': str}]"""

    @abstractmethod
    def chat(self, model: str, messages: List[Dict], max_tokens: int, temperature: float,
             seed: int) -> Dict:
        """Return {'text','prompt_tokens','completion_tokens', 'extra': {...}}. Raise KeyError on unknown model."""


class NexusPipelineEngine(EngineAdapter):
    def __init__(self, coordinator_url: str, model_dir: str):
        self.model = load_head(model_dir)  # embedding/head only
        self.pipe = Pipeline(coordinator_url, self.model)

    def list_models(self):
        return [{"id": self.model.model_id, "owned_by": "nexus-real" if getattr(self.model, "stateful", False) else "nexus-demo"}]

    def chat(self, model, messages, max_tokens, temperature, seed):
        if model != self.model.model_id:
            raise KeyError(model)
        if getattr(self.model, "stateful", False):
            ids = self.model.encode(self.model.chat_prompt(messages))
            if len(ids) > MAX_PROMPT_TOKENS:
                raise ValueError("prompt too long")
            r = self.pipe.generate(ids, max_tokens, temperature=temperature, seed=seed)
            return {"text": r["text"], "prompt_tokens": len(ids), "completion_tokens": len(r["tokens"]),
                    "finish_reason": r["finish_reason"],
                    "extra": {"tok_s": round(r["tok_s"], 2), "mean_hop_ms": round(r["mean_hop_ms"], 2),
                              "receipts": len(r["receipts"]), "failovers": r["failovers"]}}
        prompt = "\n".join("%s: %s" % (m.get("role", "user"), m.get("content", "")) for m in messages)
        ids = tok_encode(prompt)
        r = self.pipe.generate(ids, max_tokens, temperature=temperature, seed=seed)
        return {"text": r["text"], "prompt_tokens": len(ids), "completion_tokens": len(r["tokens"]),
                "extra": {"tok_s": round(r["tok_s"], 2), "mean_hop_ms": round(r["mean_hop_ms"], 2),
                          "receipts": len(r["receipts"]), "failovers": r["failovers"],
                          "note": "demo model: untrained random weights, output is not meaningful text"}}


class AtenheaEngine(EngineAdapter):
    """Single-node engine: forwards to a local Atenhea OpenAI-compatible server (default :11436, the engine, not the agent proxy).

    This is NOT the distributed path: the whole model runs on one machine. It exists so the same gateway/API keys/rate limits
    front either backend. Loopback HTTP only unless the URL says otherwise; no credentials are forwarded.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:11436", timeout: float = 300.0):
        self.base, self.timeout = base_url.rstrip("/"), timeout

    def _req(self, path, body=None):
        import json
        import urllib.request
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=self.timeout) as f:
            return json.loads(f.read())

    def list_models(self):
        return [{"id": m["id"], "owned_by": m.get("owned_by", "atenhea")} for m in self._req("/v1/models").get("data", [])]

    def chat(self, model, messages, max_tokens, temperature, seed):
        if model not in {m["id"] for m in self.list_models()}:
            raise KeyError(model)
        r = self._req("/v1/chat/completions", {"model": model, "messages": messages, "max_tokens": max_tokens,
                                              "temperature": temperature, "stream": False})
        u = r.get("usage", {})
        return {"text": r["choices"][0]["message"]["content"], "prompt_tokens": u.get("prompt_tokens", 0),
                "completion_tokens": u.get("completion_tokens", 0),
                "extra": {"engine": "atenhea-single-node", "note": "not distributed: one machine holds the full model"}}
