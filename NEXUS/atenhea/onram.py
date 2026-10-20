#!/usr/bin/env python3
"""Onram: an Ollama-shaped local API with supervised NRA-M evolution.

This is an experimental compatibility layer around llama.cpp and the existing
NRA-M training/export pipeline. It is not a fork or feature-complete clone of
Ollama.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from episodic_memory import DEFAULT_MEMORY, EpisodicMemory
from interaction_learning import (InteractionBuffer, extract_completion,
                                 extract_pair, extract_prompt)

ROOT = Path(__file__).resolve().parent
MODEL_POINTER = ROOT / "models" / "onram-current.gguf"
DEFAULT_MODEL = MODEL_POINTER
DEFAULT_BUNDLE = ROOT / "models" / "distilgpt2-nra-qa.nram"
def _default_llama_server() -> Path:
    candidates = []
    if os.environ.get("ONRAM_LLAMA_SERVER"):
        candidates.append(Path(os.environ["ONRAM_LLAMA_SERVER"]))
    candidates.extend((ROOT / "build" / "bin" / "llama-server",
                       ROOT.parent.parent / "deps" / "llama.cpp" / "build" / "bin" / "llama-server"))
    discovered = shutil.which("llama-server")
    if discovered:
        candidates.append(Path(discovered))
    return next((path for path in candidates if path.is_file()), candidates[0])


DEFAULT_LLAMA_SERVER = _default_llama_server()
DEFAULT_STRATA_DIR = ROOT / "third_party" / "strata"
ALLOWED_DATASETS = {
    "nra_qa_train.jsonl",
    "nra_qa_validation.jsonl",
    "general_guardrail.jsonl",
}


class Onram:
    def __init__(self, model_path: Path, llama_server: Path, host: str, port: int,
                 backend_port: int, bundle: Path, api_key: str | None = None,
                 model_name: str | None = None, ctx_size: int = 0,
                 auto_learn: bool = False, learn_batch_size: int = 24,
                 inference_debug: bool = False, backend_kind: str = "llama.cpp",
                 strata_dir: Path | None = None, strata_config: Path | None = None,
                 strata_python: Path | None = None, llama_args: list[str] | None = None,
                 chl_memory: Path = DEFAULT_MEMORY):
        if backend_kind not in {"llama.cpp", "strata", "nram"}:
            raise ValueError("Unknown backend")
        self.episodic = EpisodicMemory(chl_memory)
        self.episodic.call("recall", query="", top_k=1)
        self.memory_error = None
        self.llama_args = list(llama_args or [])
        self.backend_kind = backend_kind
        self.strata_dir = (strata_dir or DEFAULT_STRATA_DIR).resolve()
        self.strata_config = strata_config.resolve() if strata_config else None
        self.strata_python = (strata_python or self.strata_dir / ".venv/bin/python").absolute()
        if backend_kind == "nram":
            auto_learn = inference_debug = False
            model_name = model_name or "athenea-e2b:latest"
        if backend_kind == "strata":
            auto_learn = inference_debug = False
            model_name = model_name or "qwen3.8-flash-next:latest"
        self._stable_model_alias = model_name or ("distilgpt2-nram:latest" if model_path.name == MODEL_POINTER.name else None)
        self.model_path = model_path.resolve()
        self.llama_server = llama_server.resolve()
        self.host = host
        self.port = port
        self.backend_port = backend_port
        self.bundle = bundle.resolve()
        self.ctx_size = ctx_size
        self.model_pointer = MODEL_POINTER if model_path.name == MODEL_POINTER.name else self.bundle.with_name(self.bundle.stem + "-current.gguf")
        self.api_key = api_key
        self.auto_learn = auto_learn
        self.inference_debug = inference_debug
        self.learn_batch_size = learn_batch_size
        self.learning_lock = threading.Lock()
        self.learning = InteractionBuffer(ROOT / "models" / f"{self.bundle.stem}-learning")
        self.trace_scratch = self.learning.directory / "llama-layer-trace.jsonl"
        self.trace_ledger = self.learning.directory / "inference-traces.jsonl"
        self.debug_trace_count = sum(1 for _ in self.trace_ledger.open(encoding="utf-8")) if self.trace_ledger.exists() else 0
        self.debug_status: dict[str, Any] = {
            "enabled": inference_debug,
            "state": "ready" if inference_debug else "disabled",
            "trace_count": self.debug_trace_count,
            "trace_file": str(self.trace_ledger),
            "last_trace_at": None,
            "last_trace_id": None,
            "last_error": None,
        }
        self.learning_status: dict[str, Any] = {
            "enabled": auto_learn,
            "examples": len(self.learning.rows),
            "personal_facts": self.learning.personal_fact_count,
            "feedback_count": self.learning.feedback_count,
            "bad_feedback_count": self.learning.bad_feedback_count,
            "corrected_bad_feedback_count": self.learning.corrected_bad_feedback_count,
            "batch_size": learn_batch_size,
            "last_attempt_count": self.learning.last_attempt_count,
            "last_attempt_status": self.learning.last_attempt_status,
            "state": "collecting" if auto_learn else "disabled",
            "note": "Completed text pairs are stored for training; explicitly stated names and preferences are stored separately. System prompts and tool payloads are omitted.",
        }
        self.backend: subprocess.Popen[str] | None = None
        self.backend_log = (ROOT / "onram-backend.log").open("a", encoding="utf-8")
        self.lock = threading.RLock()
        self.evolution_lock = threading.Lock()
        self.evolution: dict[str, Any] = {"state": "idle"}
        self.started_at = datetime.now(timezone.utc).isoformat()

    @property
    def backend_url(self) -> str:
        return f"http://127.0.0.1:{self.backend_port}"

    @property
    def model_name(self) -> str:
        stable_alias = getattr(self, "_stable_model_alias", None)
        if stable_alias:
            return stable_alias
        name = re.sub(r"-Q[^-]+$", "", self.model_path.stem)
        return f"{name}:latest"

    def start_backend(self) -> None:
        if self.backend_kind == "nram":
            return self._start_nram()
        if self.backend_kind == "strata":
            self._start_strata()
            return
        if not self.model_path.is_file():
            raise FileNotFoundError(f"GGUF not found: {self.model_path}")
        if not self.llama_server.is_file():
            raise FileNotFoundError(
                f"llama-server not found: {self.llama_server}. Build it with `./onram runtime-setup` "
                "or pass --llama-server /path/to/llama-server."
            )
        backend_env = os.environ.copy()
        if self.inference_debug:
            self.trace_scratch.parent.mkdir(parents=True, exist_ok=True)
            self.trace_scratch.write_text("", encoding="utf-8")
            backend_env["ONRAM_INFERENCE_TRACE_FILE"] = str(self.trace_scratch)
        else:
            backend_env.pop("ONRAM_INFERENCE_TRACE_FILE", None)
        self.backend = subprocess.Popen(
            [str(self.llama_server), "--model", str(self.model_path), "--host", "127.0.0.1",
             "--port", str(self.backend_port), "--ctx-size", str(self.ctx_size), "--parallel", "1",
             "--alias", self.model_name, "--jinja", *self.llama_args],
            cwd=ROOT,
            env=backend_env,
            stdout=self.backend_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.monotonic() + (900 if self.ctx_size >= 65536 else 90)
        while time.monotonic() < deadline:
            if self.backend.poll() is not None:
                raise RuntimeError(f"llama-server exited with code {self.backend.returncode}; see onram-backend.log")
            try:
                self._backend_request("GET", "/health", None, timeout=1)
                return
            except (OSError, urllib.error.URLError, RuntimeError):
                time.sleep(0.25)
        self.stop_backend()
        raise TimeoutError("Timed out waiting for llama-server health")

    def _start_nram(self) -> None:
        if not self.bundle.is_file():
            raise FileNotFoundError(f"NRAM bundle missing: {self.bundle}")
        self.backend = subprocess.Popen(
            [sys.executable, str(ROOT / "native_runtime.py"), "--bundle", str(self.bundle),
             "--port", str(self.backend_port), "--model-name", self.model_name,
             "--ctx-size", str(self.ctx_size)], cwd=ROOT,
            stdout=self.backend_log, stderr=subprocess.STDOUT, text=True)
        deadline = time.monotonic() + 600
        try:
            while time.monotonic() < deadline:
                if self.backend.poll() is not None:
                    raise RuntimeError("Direct NRAM runtime exited; see onram-backend.log")
                try:
                    if self._backend_request("GET", "/health", None, timeout=1).get("loaded"):
                        return
                except (OSError, urllib.error.URLError, RuntimeError):
                    time.sleep(.25)
            raise TimeoutError("Timed out loading direct NRAM runtime")
        except BaseException:
            self.stop_backend()
            raise

    def _start_strata(self) -> None:
        if not self.strata_config or not self.strata_config.is_file():
            raise FileNotFoundError("Strata requires --strata-config pointing to the JSON produced by its setup")
        if not (self.strata_dir / "serve/server.py").is_file():
            raise FileNotFoundError(f"Strata server missing in {self.strata_dir}")
        if not self.strata_python.is_file():
            raise FileNotFoundError(f"Strata Python missing: {self.strata_python}")
        self.backend = subprocess.Popen(
            [str(self.strata_python), "-m", "serve.server", "--engine", "strata",
             "--config", str(self.strata_config), "--host", "127.0.0.1",
             "--port", str(self.backend_port)],
            cwd=self.strata_dir, stdout=self.backend_log, stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.monotonic() + 1800
        try:
            while time.monotonic() < deadline:
                if self.backend.poll() is not None:
                    raise RuntimeError("Strata exited; see onram-backend.log")
                try:
                    health = self._backend_request("GET", "/health", None, timeout=1)
                    if health.get("loaded", False):
                        return
                except (OSError, urllib.error.URLError, RuntimeError):
                    time.sleep(0.25)
            raise TimeoutError("Timed out waiting for Strata health")
        except BaseException:
            self.stop_backend()
            raise

    def _completion_request(self, params: dict[str, Any]):
        if getattr(self, "backend_kind", "llama.cpp") not in {"strata", "nram"}:
            return "/completion", params
        body = {"model": self.model_name,
                "messages": params.get("messages") or [{"role": "user", "content": params["prompt"]}],
                "max_tokens": params["n_predict"], "stream": params["stream"],
                "reasoning_effort": "none",
                "temperature": params["temperature"], "top_p": params["top_p"],
                "top_k": params["top_k"], "repeat_penalty": params["repeat_penalty"]}
        if "stop" in params:
            body["stop"] = params["stop"]
        return "/v1/chat/completions", body

    @staticmethod
    def _strata_completion(item: dict[str, Any], streaming: bool = False):
        if "error" in item:
            raise RuntimeError(f"Strata inference failed: {item['error']}")
        choices = item.get("choices") or []
        choice = choices[0] if choices else {}
        message = choice.get("delta" if streaming else "message") or {}
        return {"content": message.get("content") or "",
                "stop": choice.get("finish_reason") is not None if streaming else True,
                "tokens_predicted": (item.get("usage") or {}).get("completion_tokens", 0)}

    def stop_backend(self) -> None:
        process = self.backend
        self.backend = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def close(self) -> None:
        self.stop_backend()
        self.backend_log.close()

    def _backend_request(self, method: str, path: str, body: dict[str, Any] | None,
                         timeout: float = 120) -> dict[str, Any]:
        translate = path == "/completion" and getattr(self, "backend_kind", "llama.cpp") in {"strata", "nram"}
        if translate:
            path, body = self._completion_request(body)
        raw = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.backend_url + path, data=raw, method=method,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read()) if response.status != 204 else {}
                return self._strata_completion(result) if translate else result
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"llama-server returned HTTP {exc.code}: {detail}") from exc

    def generate(self, prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        params = self._completion_options(prompt, options,
            (self.ctx_size or 131072) if self.backend_kind == "nram" else 512)
        params["stream"] = False
        with self.lock:
            self.begin_runtime_trace()
            try:
                result = self._backend_request("POST", "/completion", params)
                if self.inference_debug:
                    completion = result.get("content", result.get("completion", ""))
                    self.finish_runtime_trace_text(prompt, completion)
                return result
            except BaseException:
                self.clear_runtime_trace()
                raise

    @staticmethod
    def _completion_options(prompt: str, options: dict[str, Any], max_tokens: int = 512) -> dict[str, Any]:
        num_predict = int(options.get("num_predict", max_tokens if max_tokens != 512 else 128))
        temperature = float(options.get("temperature", 0.8))
        if not 1 <= num_predict <= max_tokens:
            raise ValueError(f"num_predict must be between 1 and {max_tokens}")
        if not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        params: dict[str, Any] = {
            "prompt": prompt,
            "n_predict": num_predict,
            "temperature": temperature,
            "top_k": int(options.get("top_k", 40)),
            "top_p": float(options.get("top_p", 0.95)),
            "repeat_penalty": float(options.get("repeat_penalty", 1.1)),
            "stream": False,
        }
        if options.get("_messages") is not None:
            params["messages"] = options["_messages"]
        if options.get("stop"):
            params["stop"] = options["stop"]
        return params

    def stream_generate(self, prompt: str, options: dict[str, Any]):
        params = self._completion_options(prompt, options,
            (self.ctx_size or 131072) if self.backend_kind == "nram" else 512)
        params["stream"] = True
        path, params = self._completion_request(params)
        raw = json.dumps(params).encode()
        request = urllib.request.Request(self.backend_url + path, data=raw, method="POST",
                                         headers={"Content-Type": "application/json"})
        with self.lock:
            self.begin_runtime_trace()
            trace_parts: list[str] = []
            trace_complete = False
            try:
                response = urllib.request.urlopen(request, timeout=3600)
                for raw_line in response:
                    line = raw_line.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        if getattr(self, "backend_kind", "llama.cpp") in {"strata", "nram"} and not trace_complete:
                            yield {"content": "", "stop": True}
                        break
                    item = json.loads(payload)
                    if getattr(self, "backend_kind", "llama.cpp") in {"strata", "nram"}:
                        item = self._strata_completion(item, streaming=True)
                    piece = item.get("content", item.get("completion", ""))
                    if self.inference_debug and isinstance(piece, str):
                        trace_parts.append(piece)
                    trace_complete = trace_complete or bool(item.get("stop", False))
                    yield item
                if self.inference_debug and trace_complete:
                    self.finish_runtime_trace_text(prompt, "".join(trace_parts))
                else:
                    self.clear_runtime_trace()
            except urllib.error.HTTPError as exc:
                self.clear_runtime_trace()
                detail = exc.read().decode("utf-8", "replace")
                raise RuntimeError(f"llama-server returned HTTP {exc.code}: {detail}") from exc
            except BaseException:
                self.clear_runtime_trace()
                raise

    def begin_evolution(self, body: dict[str, Any]) -> dict[str, Any]:
        if getattr(self, "backend_kind", "llama.cpp") == "nram":
            raise RuntimeError("Use /api/train with verified train, validation and guardrail arrays for direct NRAM updates")
        if getattr(self, "backend_kind", "llama.cpp") == "strata":
            raise RuntimeError("Evolution is unavailable with the Strata backend")
        if not self.evolution_lock.acquire(blocking=False):
            raise RuntimeError("An evolution run is already active")
        try:
            train = self._dataset(body.get("train", "nra_qa_train.jsonl"))
            validation = self._dataset(body.get("validation", "nra_qa_validation.jsonl"))
            guardrail = self._dataset(body.get("guardrail", "general_guardrail.jsonl"))
            epochs = int(body.get("epochs", 2))
            if not 1 <= epochs <= 100:
                raise ValueError("epochs must be between 1 and 100")
            learning_rate = float(body.get("learning_rate", 0.0005))
            if not 0 < learning_rate <= 0.01:
                raise ValueError("learning_rate must be > 0 and <= 0.01")
            self.evolution = {"state": "running", "started_at": datetime.now(timezone.utc).isoformat(),
                              "stage": "training", "accepted": None}
            threading.Thread(target=self._evolve_worker,
                             args=(train, validation, guardrail, epochs, learning_rate), daemon=True).start()
            return dict(self.evolution)
        except BaseException:
            self.evolution_lock.release()
            raise

    def augment_request(self, path: str, body: bytes | None) -> bytes | None:
        """Add recalled data to the last user text without changing tool blocks."""
        memory = getattr(self, "episodic", None)
        if memory is None or not body:
            return body
        route = urllib.parse.urlsplit(path).path
        if route not in {"/v1/messages", "/v1/chat/completions", "/v1/responses",
                         "/api/chat", "/api/generate"}:
            return body
        data = json.loads(body)
        query = extract_prompt(path, body)
        if not query:
            return body
        try:
            augmented = memory.augment(query)
            self.memory_error = None
        except Exception as exc:
            self.memory_error = str(exc)
            print(f"[onram] CHL retrieval failed: {exc}", flush=True)
            return body
        if augmented == query:
            return body
        # Only insert the context prefix; retain every original message/block.
        prefix = augmented[:-len(query)]
        if route == "/api/generate":
            data["prompt"] = prefix + data["prompt"]
        elif route == "/v1/responses" and isinstance(data.get("input"), str):
            data["input"] = prefix + data["input"]
        else:
            messages = data.get("input" if route == "/v1/responses" else "messages", [])
            for message in reversed(messages):
                if not isinstance(message, dict) or message.get("role") != "user":
                    continue
                content = message.get("content")
                if isinstance(content, str):
                    message["content"] = prefix + content
                    break
                if isinstance(content, list):
                    for block in content:
                        if (isinstance(block, dict) and block.get("type") in {"text", "input_text"}
                                and isinstance(block.get("text"), str)):
                            block["text"] = prefix + block["text"]
                            return json.dumps(data).encode()
        return json.dumps(data).encode()

    def record_interaction(self, path: str, request_body: bytes | None,
                           response_body: bytes, status: int = 200) -> None:
        memory = getattr(self, "episodic", None)
        if memory is not None:
            episode = extract_pair(path, request_body, response_body, status)
            if episode:
                try:
                    memory.remember(*episode, model=self.model_name)
                    self.memory_error = None
                except Exception as exc:
                    self.memory_error = str(exc)
                    print(f"[onram] CHL capture failed: {exc}", flush=True)
        if not self.auto_learn:
            return
        prompt = extract_prompt(path, request_body) if 200 <= status < 300 else ""
        pair = extract_pair(path, request_body, response_body, status)
        if pair is None and not prompt:
            return
        with self.learning_lock:
            facts_added = self.learning.capture_facts(prompt) if prompt else False
            if pair is not None:
                count, pair_added = self.learning.add(*pair)
            else:
                count, pair_added = len(self.learning.rows), False
            self.learning_status.update({"examples": count,
                                         "personal_facts": self.learning.personal_fact_count,
                                         "last_captured_at": datetime.now(timezone.utc).isoformat()})
        if facts_added or pair_added:
            self._schedule_auto_evolution()

    def record_feedback(self, body: dict[str, Any]) -> dict[str, Any]:
        trace_id = body.get("trace_id")
        rating = body.get("rating")
        corrected = body.get("corrected_completion")
        if not isinstance(trace_id, str) or not trace_id:
            raise ValueError("trace_id is required; get it from /api/debug/traces")
        if rating not in {"good", "bad"}:
            raise ValueError("rating must be 'good' or 'bad'")
        if corrected is not None and not isinstance(corrected, str):
            raise ValueError("corrected_completion must be a string")
        trace = None
        try:
            with self.trace_ledger.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        candidate = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(candidate, dict) and candidate.get("trace_id") == trace_id:
                        trace = candidate
        except OSError as exc:
            raise ValueError(f"inference trace ledger is unavailable: {exc}") from exc
        if trace is None:
            raise ValueError("trace_id not found; list recent traces at /api/debug/traces")
        prompt_hash = trace.get("prompt_sha256")
        completion_hash = trace.get("completion_sha256")
        if not prompt_hash or not completion_hash or not trace.get("callback_events"):
            raise ValueError("trace has no complete text pair or GGUF activation events")
        with self.learning_lock:
            pair = next((row for row in self.learning.rows
                         if hashlib.sha256(row["prompt"].encode("utf-8")).hexdigest() == prompt_hash
                         and hashlib.sha256(row["completion"].encode("utf-8")).hexdigest() == completion_hash), None)
            if pair is None:
                raise ValueError("matching interaction is not in the learning ledger; enable auto-learn and retry after the response finishes")
            feedback = self.learning.record_feedback(
                pair["prompt"], pair["completion"], trace_id, rating, corrected,
            )
            self.learning_status.update({
                "feedback_count": self.learning.feedback_count,
                "bad_feedback_count": self.learning.bad_feedback_count,
                "corrected_bad_feedback_count": self.learning.corrected_bad_feedback_count,
                "last_feedback_at": feedback["updated_at"],
            })
        if rating == "bad":
            self._schedule_auto_evolution()
        return {
            "accepted": True,
            "rating": rating,
            "has_correction": bool(feedback.get("corrected_completion")),
            "feedback_count": self.learning.feedback_count,
            "bad_feedback_count": self.learning.bad_feedback_count,
            "corrected_bad_feedback_count": self.learning.corrected_bad_feedback_count,
            "auto_learn": self.auto_learn,
        }

    def begin_runtime_trace(self) -> None:
        if not self.inference_debug:
            return
        try:
            self.trace_scratch.parent.mkdir(parents=True, exist_ok=True)
            self.trace_scratch.write_text("", encoding="utf-8")
            self.debug_status.update({"state": "capturing", "last_error": None})
        except OSError as exc:
            self.debug_status.update({"state": "failed", "last_error": str(exc)})

    def clear_runtime_trace(self) -> None:
        if not self.inference_debug:
            return
        try:
            self.trace_scratch.write_text("", encoding="utf-8")
        except OSError:
            pass

    def finish_runtime_trace_text(self, prompt: str, completion: str) -> None:
        if not self.inference_debug:
            return
        self.finish_runtime_trace(
            "/api/generate", json.dumps({"prompt": prompt}).encode("utf-8"),
            json.dumps({"response": completion, "done": True}).encode("utf-8"), 200,
        )

    def finish_runtime_trace(self, path: str, request_body: bytes | None,
                             response_body: bytes | None, status: int = 200) -> None:
        if not self.inference_debug:
            return
        prompt = extract_prompt(path, request_body)
        completion = extract_completion(path, response_body, status)
        events = []
        try:
            for line in self.trace_scratch.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict) and isinstance(item.get("layer"), int):
                    events.append(item)
        except OSError as exc:
            self.debug_status.update({"state": "failed", "last_error": str(exc)})
            return

        by_layer: dict[int, dict[str, Any]] = {}
        for item in events:
            layer = item["layer"]
            positions = max(1, int(item.get("positions", 1)))
            hidden = max(1, int(item.get("hidden_size", 1)))
            row = by_layer.setdefault(layer, {
                "layer": layer, "graph_calls": 0, "positions": 0,
                "hidden_size": hidden, "sum_sq": 0.0,
                "channel_abs_sum": {}, "channel_counts": {},
            })
            row["graph_calls"] += 1
            row["positions"] += positions
            row["sum_sq"] += float(item.get("output_rms", 0.0)) ** 2 * positions * hidden
            for channel in item.get("top_channels", []):
                if not isinstance(channel, dict) or not isinstance(channel.get("channel"), int):
                    continue
                index = channel["channel"]
                row["channel_abs_sum"][index] = row["channel_abs_sum"].get(index, 0.0) + float(channel.get("mean_abs", 0.0)) * positions
                row["channel_counts"][index] = row["channel_counts"].get(index, 0) + positions

        layers = []
        for layer, row in sorted(by_layer.items()):
            channels = [
                {"channel": channel, "mean_abs": total / row["channel_counts"][channel]}
                for channel, total in row["channel_abs_sum"].items()
            ]
            channels.sort(key=lambda channel: channel["mean_abs"], reverse=True)
            layers.append({
                "layer": layer,
                "graph_calls": row["graph_calls"],
                "positions": row["positions"],
                "hidden_size": row["hidden_size"],
                "output_rms": (row["sum_sq"] / max(row["positions"] * row["hidden_size"], 1)) ** 0.5,
                "top_mean_abs_channels": channels[:12],
            })

        report = {
            "format": "ONRAM_LLAMA_CPP_INFERENCE_TRACE_V1",
            "trace_id": str(uuid.uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "backend": "llama.cpp-gguf",
            "model_file": self.model_path.name,
            "api_route": urllib.parse.urlsplit(path).path,
            "http_status": status,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt else None,
            "completion_sha256": hashlib.sha256(completion.encode("utf-8")).hexdigest() if completion else None,
            "pair_sha256": hashlib.sha256((prompt + "\0" + completion).encode("utf-8")).hexdigest()
            if prompt and completion else None,
            "prompt_text_saved": False,
            "completion_text_saved": False,
            "callback_events": len(events),
            "layer_count": len(layers),
            "layers": layers,
            "limitations": [
                "Captures final residual-stream summaries from quantized GGUF inference; it does not expose a unique causal weight explanation.",
                "The ggml evaluation callback is experimental and may add latency while copying selected layer outputs to host memory.",
                "Per-layer channel rankings are descriptive activation magnitudes, not neuron semantics or gradient attribution.",
            ],
        }
        try:
            self.trace_ledger.parent.mkdir(parents=True, exist_ok=True)
            encoded = json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n"
            with self.trace_ledger.open("a", encoding="utf-8") as stream:
                stream.write(encoded)
            if self.trace_ledger.stat().st_size > 32 * 1024 * 1024:
                records = self.trace_ledger.read_text(encoding="utf-8").splitlines()
                self.trace_ledger.write_text("\n".join(records[-500:]) + "\n", encoding="utf-8")
            self.debug_trace_count += 1
            self.debug_status.update({
                "state": "ready" if events else "unsupported_backend",
                "trace_count": self.debug_trace_count,
                "last_trace_id": report["trace_id"],
                "last_trace_at": report["created_at"],
                "last_error": None if events else "llama-server emitted no l_out activation events; rebuild it with Onram's patched llama.cpp.",
            })
        except OSError as exc:
            self.debug_status.update({"state": "failed", "last_error": str(exc)})
        finally:
            try:
                self.trace_scratch.write_text("", encoding="utf-8")
            except OSError:
                pass

    def _schedule_auto_evolution(self, *, retry_pending: bool = False) -> None:
        if not self.auto_learn:
            return
        with self.learning_lock:
            count = len(self.learning.rows)
            pending_status = self.learning.last_attempt_status
            interrupted = (retry_pending and count >= self.learn_batch_size
                           and self.learning.last_attempt_count > 0
                           and pending_status != "completed")
            last_corrected_bad = int(self.learning.state.get(
                "last_attempt_corrected_bad_feedback_count", 0))
            feedback_due = self.learning.corrected_bad_feedback_count - last_corrected_bad >= 3
            due = (count >= self.learn_batch_size and
                   (count - self.learning.last_attempt_count >= self.learn_batch_size
                    or interrupted or feedback_due))
            if not due:
                return
            directory = self.learning.directory
            train = directory / "train.jsonl"
            validation = directory / "validation.jsonl"
            train_count, validation_count = self.learning.write_split(train, validation)
            personal_train = directory / "personal_train.jsonl"
            personal_validation = directory / "personal_validation.jsonl"
            new_personal_facts = (self.learning.personal_fact_count > 0
                                  and self.learning.personal_facts_changed_since_training)
            personal_train_count, personal_validation_count = self.learning.write_personal_split(
                personal_train, personal_validation)
            if train_count < 10 or validation_count < 3:
                self.learning_status.update({"state": "collecting", "train_examples": train_count,
                                             "validation_examples": validation_count})
                return
            if personal_train_count:
                if new_personal_facts:
                    # A new fact gets a focused micro-run. Replaying the model's
                    # old answers here can dilute or contradict the explicit fact.
                    train.write_text(personal_train.read_text(encoding="utf-8"),
                                     encoding="utf-8")
                else:
                    with train.open("a", encoding="utf-8") as stream:
                        stream.write(personal_train.read_text(encoding="utf-8"))
            if not self.evolution_lock.acquire(blocking=False):
                self.learning_status["state"] = "waiting_for_evolution"
                return
            self.learning.mark_attempt(count, self.learning.corrected_bad_feedback_count)
            self.learning_status.update({"state": "training", "examples": count,
                                         "train_examples": train_count + personal_train_count,
                                         "validation_examples": validation_count + personal_validation_count,
                                         "last_attempt_count": count,
                                         "last_attempt_status": "running"})
            self.evolution = {"state": "running", "started_at": datetime.now(timezone.utc).isoformat(),
                              "stage": "training", "accepted": None,
                              "source": "interactions", "personal_facts": self.learning.personal_fact_count}
            automatic_epochs = 50 if new_personal_facts else 8
        guardrail = ROOT / "data" / "general_guardrail.jsonl"
        threading.Thread(target=self._evolve_worker,
                         args=(train, validation, guardrail, automatic_epochs, 0.00001, 256, True,
                               personal_validation if personal_validation_count else None),
                         daemon=True).start()

    @staticmethod
    def _dataset(name: str) -> Path:
        if name not in ALLOWED_DATASETS:
            raise ValueError(f"dataset must be one of: {', '.join(sorted(ALLOWED_DATASETS))}")
        path = (ROOT / "data" / name).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"dataset not found: {path}")
        return path

    def _evolve_worker(self, train: Path, validation: Path, guardrail: Path,
                       epochs: int, learning_rate: float, max_length: int = 512,
                       automatic: bool = False,
                       personal_validation: Path | None = None) -> None:
        try:
            # Use the interpreter that is already running Onram unless the user
            # explicitly selects another environment. This keeps launcher-based
            # learning working even when this checkout has no local .venv.
            python = os.environ.get("ONRAM_PYTHON") or sys.executable
            from nram_container import load_bundle
            manifest, _ = load_bundle(self.bundle)
            generic = manifest.get("model_family") == "hf-causal-lm-dense-lora"
            if generic:
                command = [python, str(ROOT / "nram_evolve_generic.py"),
                           "--bundle", str(self.bundle), "--train", str(train),
                           "--validation", str(validation), "--guardrail", str(guardrail),
                           "--epochs", str(epochs), "--learning-rate", str(learning_rate),
                           "--max-length", str(max_length), "--batch-size", "2",
                           "--min-behavior-accuracy", "0.75", "--local-files-only"]
                if getattr(self, "episodic", None) is not None:
                    command.extend(("--chl-memory", str(self.episodic.memory)))
                analysis_host = "[::1]" if self.host == "::1" else "127.0.0.1"
                command.extend(("--self-analysis-url", f"http://{analysis_host}:{self.port}"))
                if self.trace_ledger.is_file():
                    command.extend(("--runtime-traces", str(self.trace_ledger)))
                if personal_validation:
                    command.extend(("--personal-validation", str(personal_validation)))
            else:
                command = [python, str(ROOT / "nram_evolve.py"),
                           "--train", str(train), "--validation", str(validation),
                           "--guardrail", str(guardrail), "--output", str(self.bundle),
                           "--epochs", str(epochs), "--learning-rate", str(learning_rate)]
            training_env = os.environ.copy()
            if self.api_key:
                training_env["ONRAM_API_KEY"] = self.api_key
            proc = subprocess.Popen(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, bufsize=1, env=training_env)
            output_lines: list[str] = []

            def collect_output() -> None:
                if proc.stdout is None:
                    return
                for line in proc.stdout:
                    output_lines.append(line)
                    if line.startswith("@onram-progress "):
                        try:
                            progress = json.loads(line[len("@onram-progress "):])
                        except json.JSONDecodeError:
                            continue
                        current = dict(self.evolution)
                        current.update(progress)
                        current["state"] = "running"
                        self.evolution = current

            reader = threading.Thread(target=collect_output, daemon=True)
            reader.start()
            try:
                proc.wait(timeout=6 * 60 * 60)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise TimeoutError("evolution exceeded the six-hour runtime limit")
            reader.join(timeout=5)
            output = "".join(output_lines)
            if proc.returncode:
                raise RuntimeError(output[-6000:] or f"evolver exited {proc.returncode}")
            match = re.search(r'"accepted"\s*:\s*(true|false)', output)
            if match is None:
                raise RuntimeError("evolver completed without a validation report: " + output[-3000:])
            accepted = match.group(1) == "true"
            report = {"state": "completed", "accepted": accepted, "stage": "validated",
                      "finished_at": datetime.now(timezone.utc).isoformat(), "log_tail": output[-3000:]}
            if accepted:
                report["stage"] = "exporting"
                version = self._bundle_version()
                if generic:
                    name = f"onram-{self.bundle.stem}-v{version}"
                    export = subprocess.run([python, str(ROOT / "nram_export_generic.py"),
                                             "--bundle", str(self.bundle), "--output-prefix",
                                             str(ROOT / "models" / name)], cwd=ROOT, text=True,
                                            capture_output=True, timeout=6 * 60 * 60)
                    q4_path = ROOT / "models" / f"{name}-Q4_K_M.gguf"
                    export_text = export.stdout
                else:
                    name = f"onram-nram-v{version}"
                    export = subprocess.run([str(ROOT / "export_evolved.sh"), str(self.bundle), name],
                                            cwd=ROOT, text=True, capture_output=True, timeout=6 * 60 * 60)
                    q4_path = ROOT / "models" / f"{name}-Q4_K_M.gguf"
                    export_text = export.stdout
                if export.returncode:
                    raise RuntimeError((export.stdout + "\n" + export.stderr)[-6000:])
                report["stage"] = "reloading"
                self._swap_model(q4_path)
                report["model_path"] = str(q4_path)
                report["export_log"] = export_text[-2000:]
                report["stage"] = "ready"
            self.evolution = report
            if automatic:
                self.learning_status.update({"state": "completed", "accepted": accepted,
                                             "finished_at": report["finished_at"],
                                             "last_attempt_status": "completed",
                                             "evolution": report})
                with self.learning_lock:
                    self.learning.finish_attempt("completed", accepted=accepted,
                                                 finished_at=report["finished_at"])
        except BaseException as exc:
            self.evolution = {"state": "failed", "stage": "error", "error": str(exc),
                              "finished_at": datetime.now(timezone.utc).isoformat()}
            if automatic:
                self.learning_status.update({"state": "failed", "error": str(exc),
                                             "finished_at": self.evolution["finished_at"],
                                             "last_attempt_status": "failed"})
                with self.learning_lock:
                    self.learning.finish_attempt("failed", error=str(exc),
                                                 finished_at=self.evolution["finished_at"])
        finally:
            self.evolution_lock.release()
            if automatic:
                self._schedule_auto_evolution()

    def _bundle_version(self) -> int:
        from nram_container import load_bundle
        manifest, _ = load_bundle(self.bundle)
        return int(manifest["version"])

    def _swap_model(self, candidate: Path) -> None:
        old = self.model_path
        pointer = self.model_pointer
        with self.lock:
            self.stop_backend()
            try:
                self.model_path = candidate.resolve()
                self.start_backend()
                temp_pointer = pointer.with_name(f".{pointer.name}.{os.getpid()}.tmp")
                temp_pointer.unlink(missing_ok=True)
                temp_pointer.symlink_to(self.model_path.name)
                os.replace(temp_pointer, pointer)
            except BaseException:
                self.model_path = old
                self.start_backend()
                raise

    def status(self) -> dict[str, Any]:
        return {"name": "onram", "version": "0.1.0", "model": self.model_name,
                "model_path": str(self.strata_config if getattr(self, "backend_kind", "llama.cpp") == "strata" else self.model_path), "backend": getattr(self, "backend_kind", "llama.cpp"),
                "backend_running": self.backend is not None and self.backend.poll() is None,
                "evolution": dict(self.evolution), "learning": dict(self.learning_status),
                "episodic_memory": {"path": str(self.episodic.memory) if getattr(self, "episodic", None) else None,
                                    "last_error": getattr(self, "memory_error", None)},
                "inference_debug": dict(self.debug_status),
                "started_at": self.started_at}


def handler_for(app: Onram):
    class Handler(BaseHTTPRequestHandler):
        server_version = "onram/0.1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            print("[onram] " + fmt % args, flush=True)

        def _json(self, value: Any, status: int = 200) -> None:
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 64_000_000:
                raise ValueError("request body exceeds 64 MB")
            value = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(value, dict):
                raise ValueError("request body must be a JSON object")
            return value

        def _read_proxy_body(self) -> bytes | None:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                return None
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise ValueError("invalid Content-Length") from exc
            if length < 0 or length > 64_000_000:
                raise ValueError("request body must be between 0 and 64 MB")
            return self.rfile.read(length)

        @staticmethod
        def _proxy_paths() -> set[str]:
            # Keep this list explicit: Onram exposes the inference APIs used by
            # coding agents, not llama.cpp's administrative/model-loading API.
            return {
                "/v1/chat/completions",
                "/v1/chat/completions/control",
                "/v1/chat/completions/input_tokens",
                "/v1/responses",
                "/v1/responses/input_tokens",
                "/v1/messages",
                "/v1/messages/count_tokens",
            }

        def _proxy_request(self, method: str, body: bytes | None = None) -> None:
            # Preserve protocol-specific headers (Anthropic version/beta,
            # content negotiation, bearer/API-key auth) while stripping
            # hop-by-hop headers that belong to the client connection.
            hop_by_hop = {
                "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
                "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
                "accept-encoding",
            }
            connection_tokens = {
                token.strip().lower()
                for value in self.headers.get_all("Connection", [])
                for token in value.split(",")
                if token.strip()
            }
            headers = {"Accept-Encoding": "identity"}
            for key, value in self.headers.items():
                if key.lower() not in hop_by_hop | connection_tokens:
                    headers[key] = value
            original_body = body
            if hasattr(app, "augment_request"):
                body = app.augment_request(self.path, body)
            request = urllib.request.Request(
                app.backend_url + self.path, data=body, headers=headers, method=method
            )
            captured = bytearray()
            inference_debug = getattr(app, "inference_debug", False)
            auto_learn = getattr(app, "auto_learn", False)
            capture_ok = (auto_learn or inference_debug or getattr(app, "episodic", None) is not None) and body is not None
            capture_complete = False
            upstream_status = 502
            with app.lock:
                if inference_debug:
                    app.begin_runtime_trace()
                try:
                    upstream = urllib.request.urlopen(request, timeout=24 * 60 * 60)
                except urllib.error.HTTPError as exc:
                    upstream = exc
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    if inference_debug:
                        app.clear_runtime_trace()
                    self._json({"error": f"llama-server unavailable: {exc}"}, 502)
                    return

                with upstream:
                    upstream_status = upstream.status
                    self.send_response(upstream.status)
                    has_content_length = False
                    for key, value in upstream.headers.items():
                        if key.lower() in {
                            "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
                            "te", "trailers", "transfer-encoding", "upgrade",
                        }:
                            continue
                        if key.lower() == "content-length":
                            has_content_length = True
                        self.send_header(key, value)
                    if not has_content_length:
                        # The backend's chunk framing has been removed by urllib.
                        # Close-delimited HTTP/1.0 responses preserve SSE incrementally.
                        self.send_header("Connection", "close")
                        self.close_connection = True
                    self.end_headers()
                    try:
                        while True:
                            read_chunk = getattr(upstream, "read1", upstream.read)
                            chunk = read_chunk(16_384)
                            if not chunk:
                                break
                            if capture_ok:
                                if len(captured) + len(chunk) <= 4_000_000:
                                    captured.extend(chunk)
                                else:
                                    capture_ok = False
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        capture_complete = True
                    except (BrokenPipeError, ConnectionResetError, http.client.HTTPException, OSError):
                        # A client cancelling a generation should stop consuming
                        # the local response without crashing the HTTP worker.
                        self.close_connection = True
                if inference_debug:
                    response_body = bytes(captured) if capture_complete and capture_ok else None
                    app.finish_runtime_trace(self.path, original_body, response_body, upstream_status)
            if capture_ok and capture_complete and (auto_learn or getattr(app, "episodic", None) is not None):
                app.record_interaction(self.path, original_body, bytes(captured), upstream_status)

        def _authorized(self) -> bool:
            if not app.api_key:
                return True
            authorization = self.headers.get("Authorization", "")
            bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
            api_key = self.headers.get("x-api-key", "")
            return bearer == app.api_key or api_key == app.api_key

        def do_GET(self) -> None:
            try:
                path = urllib.parse.urlsplit(self.path).path
                if not self._authorized():
                    return self._json({"error": "unauthorized"}, 401)
                if path == "/api/version":
                    return self._json({"version": "0.1.0"})
                if path == "/api/health":
                    return self._json(app.status())
                if path == "/api/runtime/status" and getattr(app, "backend_kind", "llama.cpp") == "nram":
                    return self._json(app._backend_request("GET", "/onram/status", None))
                if path == "/api/micro-training/status" and getattr(app, "backend_kind", "llama.cpp") == "nram":
                    runtime = app._backend_request("GET", "/onram/status", None)
                    return self._json(runtime.get("micro_training_schedule", {}))
                if path == "/api/evolve/status":
                    return self._json(app.status()["evolution"])
                if path == "/api/learning/status":
                    return self._json(dict(app.learning_status))
                if path == "/api/debug/status":
                    return self._json(dict(app.debug_status))
                if path == "/api/debug/traces":
                    traces = []
                    if app.trace_ledger.is_file():
                        for line in app.trace_ledger.read_text(encoding="utf-8").splitlines():
                            try:
                                item = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if isinstance(item, dict):
                                traces.append(item)
                    return self._json({"traces": traces[-20:]})
                if getattr(app, "backend_kind", "llama.cpp") == "strata" and path in {
                    "/api/tags", "/api/ps", "/v1/models", "/models"
                }:
                    if path in {"/v1/models", "/models"}:
                        return self._json({"object": "list", "data": [{"id": app.model_name,
                            "object": "model", "owned_by": "onram"}]})
                    return self._json({"models": [{"name": app.model_name, "model": app.model_name,
                        "size": 0, "digest": "strata-managed", "details": {"family": "qwen4_exp"}}]})
                if path == "/v1/models":
                    return self._json({"object": "list", "data": [{
                        "id": app.model_name,
                        "object": "model",
                        "created": int(datetime.fromtimestamp(app.model_path.stat().st_mtime, timezone.utc).timestamp()),
                        "owned_by": "onram",
                    }]})
                if path == "/models":
                    return self._json({"object": "list", "data": [{
                        "id": app.model_name, "object": "model", "owned_by": "onram",
                    }]})
                if path == "/api/ps" and getattr(app,"backend_kind","llama.cpp") == "nram":
                    status=app._backend_request("GET","/onram/status",None)
                    return self._json({"models":[{"name":app.model_name,"model":app.model_name,
                        "size":status['parameter_bytes'],"digest":"local-nram","expires_at":"",
                        "details":{"format":"nram","family":"gemma4","quantization_level":"BF16"}}]
                        if status.get('loaded') else []})
                if path == "/api/ps":
                    return self._json({"models": [{"name": app.model_name, "model": app.model_name,
                        "size": app.model_path.stat().st_size, "digest": "local-gguf",
                        "expires_at": ""}] if app.model_path.exists() else []})
                if path == "/api/tags" and getattr(app, "backend_kind", "llama.cpp") == "nram":
                    return self._json({"models": [{"name": app.model_name, "model": app.model_name,
                        "size": app.bundle.stat().st_size, "digest": "local-nram",
                        "details": {"format": "nram", "family": "gemma4", "quantization_level": "BF16"}}]})
                if path == "/api/tags":
                    info = {"name": app.model_name, "model": app.model_name,
                            "modified_at": datetime.fromtimestamp(app.model_path.stat().st_mtime, timezone.utc).isoformat(),
                            "size": app.model_path.stat().st_size, "digest": "local-gguf",
                            "details": {"format": "gguf", "family": "gpt2", "parameter_size": "82M", "quantization_level": "Q4_K_M"}}
                    return self._json({"models": [info]})
                if path == "/":
                    return self._json({"message": "onram is running", "docs": "/api/health"})
                return self._json({"error": "not found"}, 404)
            except Exception as exc:
                self._json({"error": str(exc)}, 500)

        def do_POST(self) -> None:
            try:
                if not self._authorized():
                    return self._json({"error": "unauthorized"}, 401)
                path = urllib.parse.urlsplit(self.path).path
                if path in self._proxy_paths():
                    return self._proxy_request("POST", self._read_proxy_body())
                body = self._read_json()
                if self.path in ("/api/generate", "/api/chat"):
                    if body.get("model") not in (None, "", app.model_name, "distilgpt2-nram"):
                        return self._json({"error": f"model not found: {body['model']}"}, 404)
                    original_body = json.dumps(body).encode()
                    if hasattr(app, "augment_request"):
                        body = json.loads(app.augment_request(self.path, original_body))
                    prompt = body.get("prompt", "")
                    if self.path == "/api/chat":
                        messages = body.get("messages", [])
                        if not isinstance(messages, list):
                            return self._json({"error": "messages must be an array"}, 400)
                        prompt = "".join(f"{m.get('role', 'user')}: {m.get('content', '')}\n" for m in messages)
                        prompt += "assistant:"
                    if not isinstance(prompt, str) or not prompt:
                        return self._json({"error": "prompt or messages are required"}, 400)
                    options = dict(body.get("options") or {})
                    if self.path == "/api/chat" and getattr(app, "backend_kind", "llama.cpp") in {"strata", "nram"}:
                        options["_messages"] = messages
                    started = time.monotonic()
                    if body.get("stream", True):
                        self.send_response(200)
                        self.send_header("Content-Type", "application/x-ndjson")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Transfer-Encoding", "chunked")
                        self.end_headers()
                        captured_text = []
                        completed = False
                        try:
                            for item in app.stream_generate(prompt, options):
                                piece = item.get("content", item.get("completion", ""))
                                if isinstance(piece, str):
                                    captured_text.append(piece)
                                done = bool(item.get("stop", False))
                                if self.path == "/api/chat":
                                    chunk = {"model": app.model_name,
                                        "created_at": datetime.now(timezone.utc).isoformat(),
                                        "message": {"role": "assistant", "content": piece}, "done": done}
                                else:
                                    chunk = {"model": app.model_name,
                                        "created_at": datetime.now(timezone.utc).isoformat(),
                                        "response": piece, "done": done}
                                if done:
                                    chunk["eval_count"] = item.get("tokens_predicted", 0)
                                    chunk["total_duration"] = int((time.monotonic() - started) * 1e9)
                                data = (json.dumps(chunk, ensure_ascii=False) + "\n").encode("utf-8")
                                self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
                                self.wfile.flush()
                                completed = completed or done
                            self.wfile.write(b"0\r\n\r\n")
                            if completed:
                                if self.path == "/api/chat":
                                    learned_response = {"message": {"content": "".join(captured_text)}, "done": True}
                                else:
                                    learned_response = {"response": "".join(captured_text), "done": True}
                                app.record_interaction(self.path, original_body,
                                                       json.dumps(learned_response).encode())
                        except Exception as exc:
                            print(f"[onram] streaming error: {exc}", flush=True)
                        return
                    result = app.generate(prompt, options)
                    text = result.get("content", result.get("completion", ""))
                    if self.path == "/api/chat":
                        response = {"model": app.model_name, "created_at": datetime.now(timezone.utc).isoformat(),
                                    "message": {"role": "assistant", "content": text}, "done": True,
                                    "total_duration": int((time.monotonic() - started) * 1e9),
                                    "eval_count": result.get("tokens_predicted", 0)}
                    else:
                        response = {"model": app.model_name, "created_at": datetime.now(timezone.utc).isoformat(),
                                    "response": text, "done": True,
                                    "total_duration": int((time.monotonic() - started) * 1e9),
                                    "eval_count": result.get("tokens_predicted", 0)}
                    app.record_interaction(self.path, original_body, json.dumps(response).encode())
                    return self._json(response)
                if self.path == "/api/train":
                    if getattr(app, "backend_kind", "llama.cpp") != "nram":
                        return self._json({"error": "Direct online training requires --backend nram"}, 400)
                    return self._json(app._backend_request("POST", "/onram/train", body, timeout=3600))
                if self.path == "/api/micro-training/train-topic":
                    if getattr(app, "backend_kind", "llama.cpp") != "nram":
                        return self._json({"error": "Topic micro-training requires --backend nram"}, 400)
                    return self._json(app._backend_request("POST", "/onram/train-topic", body, timeout=3600))
                if self.path == "/api/evolve":
                    return self._json(app.begin_evolution(body), 202)
                if self.path == "/api/learning/feedback":
                    return self._json(app.record_feedback(body), 202)
                if self.path == "/api/show" and getattr(app, "backend_kind", "llama.cpp") == "nram":
                    return self._json({"modelfile": str(app.bundle), "details": {"format": "nram", "family": "gemma4", "quantization_level": "BF16"}})
                if self.path == "/api/show" and getattr(app, "backend_kind", "llama.cpp") == "strata":
                    return self._json({"details": {"family": "qwen4_exp"},
                        "model_info": {"general.architecture": "qwen4_exp"},
                        "parameters": "Managed by Strata configuration", "license": ""})
                if self.path == "/api/show":
                    return self._json({"modelfile": f"FROM {app.model_path}", "parameters": "",
                        "template": "{{ .Prompt }}", "details": {"format": "gguf", "family": "gpt2",
                        "parameter_size": "82M", "quantization_level": "Q4_K_M"},
                        "model_info": {"general.architecture": "gpt2"}, "license": ""})
                if self.path == "/api/pull":
                    return self._json({"error": "onram prototype only manages local models; use /api/import to add a GGUF"}, 501)
                if self.path == "/api/import":
                    return self._json({"error": "import accepts local files through the CLI only in this version"}, 501)
                return self._json({"error": "not found"}, 404)
            except (ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, 400)
            except RuntimeError as exc:
                self._json({"error": str(exc)}, 409)
            except Exception as exc:
                self._json({"error": str(exc)}, 500)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["llama.cpp", "strata", "nram"], default="llama.cpp")
    parser.add_argument("--strata-dir", type=Path, default=DEFAULT_STRATA_DIR)
    parser.add_argument("--strata-config", type=Path, help="Existing Strata setup JSON; required for --backend strata")
    parser.add_argument("--strata-python", type=Path, help="Defaults to Strata's .venv/bin/python")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--chl-memory", type=Path, default=DEFAULT_MEMORY)
    parser.add_argument("--backend-arg", action="append", default=[],
                        help="Extra llama.cpp argument; use --backend-arg=--flag for flags")
    parser.add_argument("--llama-server", type=Path, default=DEFAULT_LLAMA_SERVER)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--backend-port", type=int, default=11436)
    parser.add_argument("--ctx-size", type=int, default=0,
                        help="llama.cpp context size; 0 uses the GGUF's model default")
    parser.add_argument("--api-key", default=os.environ.get("ONRAM_API_KEY"))
    parser.add_argument("--model-name", help="Stable model name exposed by /api/tags")
    auto_learn_default = os.environ.get("ONRAM_AUTO_LEARN", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }
    parser.add_argument("--auto-learn", action=argparse.BooleanOptionalAction,
                        default=auto_learn_default,
                        help="Capture completed text turns and train a validated candidate every batch (enabled by default; use --no-auto-learn to disable)")
    inference_debug_default = os.environ.get("ONRAM_INFERENCE_DEBUG", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }
    parser.add_argument("--inference-debug", action=argparse.BooleanOptionalAction,
                        default=inference_debug_default,
                        help="Capture per-layer GGUF inference activation summaries (enabled by default; use --no-inference-debug to disable)")
    parser.add_argument("--learn-batch-size", type=int,
                        default=int(os.environ.get("ONRAM_LEARN_BATCH_SIZE", "24")),
                        help="New unique turns required before an automatic training attempt")
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.api_key:
        parser.error("binding to a non-local address requires --api-key or ONRAM_API_KEY")
    if args.ctx_size < 0:
        parser.error("--ctx-size must be 0 or greater")
    if args.learn_batch_size < 16:
        parser.error("--learn-batch-size must be at least 16 to preserve a validation split")
    if args.backend == "strata" and not args.strata_config:
        parser.error("--backend strata requires --strata-config")
    model_name = args.model_name
    if model_name and ":" not in model_name:
        model_name += ":latest"
    app = Onram(args.model, args.llama_server, args.host, args.port, args.backend_port,
                args.bundle, args.api_key, model_name, args.ctx_size,
                args.auto_learn, args.learn_batch_size, args.inference_debug,
                args.backend, args.strata_dir, args.strata_config, args.strata_python, args.backend_arg, args.chl_memory)
    try:
        # Reserve the public port before loading any weights. Duplicate launches
        # fail immediately instead of starting another multi-GB model first.
        server = ThreadingHTTPServer((args.host, args.port), handler_for(app))
        app.start_backend()
    except BaseException:
        app.close()
        raise
    print(f"onram listening at http://{args.host}:{args.port} with {app.model_path.name}", flush=True)
    if app.auto_learn:
        app._schedule_auto_evolution(retry_pending=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        app.close()


if __name__ == "__main__":
    main()
