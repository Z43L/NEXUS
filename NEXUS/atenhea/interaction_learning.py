"""Capture completed, text-only turns from Onram's local API clients."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

MAX_PROMPT_CHARS = 8_000
MAX_COMPLETION_CHARS = 8_000

_NAME_PATTERNS = (
    re.compile(r"\b(?:me llamo|mi nombre es)\s+([^.!?,;\n]+)", re.IGNORECASE),
    re.compile(r"\b(?:my name is|i am called)\s+([^.!?,;\n]+)", re.IGNORECASE),
)
_PREFERENCE_PATTERNS = (
    (re.compile(r"\bno me gusta(?:n)?\s+([^.!?,;\n]+)", re.IGNORECASE), "no_te_gusta"),
    (re.compile(r"(?<!no )\bme gusta(?:n)?\s+([^.!?,;\n]+)", re.IGNORECASE), "te_gusta"),
    (re.compile(r"\bprefiero\s+([^.!?,;\n]+)", re.IGNORECASE), "prefieres"),
    (re.compile(r"\bi don't like\s+([^.!?,;\n]+)", re.IGNORECASE), "no_te_gusta"),
    (re.compile(r"\bi like\s+([^.!?,;\n]+)", re.IGNORECASE), "te_gusta"),
    (re.compile(r"\bi prefer\s+([^.!?,;\n]+)", re.IGNORECASE), "prefieres"),
)


def _clean_fact_value(value: str) -> str:
    value = value.strip().strip(" \t\r\n\"'`“”‘’")
    value = re.split(r"\s+(?:y|pero|aunque|and|but)\s+", value, maxsplit=1, flags=re.IGNORECASE)[0]
    return value.strip(" \t\r\n.,;:!?\"'`“”‘’")[:120]


def _extract_explicit_facts(text: str) -> dict[str, Any]:
    """Extract only simple, explicitly stated name and preference facts."""
    facts: dict[str, Any] = {}
    for pattern in _NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            value = _clean_fact_value(match.group(1))
            if (value and len(value.split()) <= 5
                    and value.casefold() not in {"x", "alguien", "anonimo", "anonymous", "yo", "myself"}
                    and not value.casefold().startswith(("no sé", "no se", "not "))):
                facts["name"] = value
            break
    preferences = []
    for pattern, relation in _PREFERENCE_PATTERNS:
        for match in pattern.finditer(text):
            value = _clean_fact_value(match.group(1))
            if not value:
                continue
            if relation == "no_te_gusta":
                statement = f"No te gusta {value}."
            elif relation == "te_gusta":
                statement = f"Te gusta {value}."
            else:
                statement = f"Prefieres {value}."
            if statement.casefold() not in {item.casefold() for item in preferences}:
                preferences.append(statement)
    if preferences:
        facts["preferences"] = preferences
    return facts


def _personal_examples(facts: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Create supervised fact questions, with separate train and holdout prompts."""
    train: list[dict[str, str]] = []
    validation: list[dict[str, str]] = []

    def add(target: list[dict[str, str]], prompt: str, completion: str) -> None:
        target.append({"prompt": prompt, "completion": completion})

    name = facts.get("name")
    if isinstance(name, str) and name:
        display_name = name[:1].upper() + name[1:] if name.islower() else name
        for prompt, completion in (
            ("¿Cómo me llamo?", f"Te llamas {display_name}."),
            ("¿Cuál es mi nombre?", f"Tu nombre es {display_name}."),
            ("¿Recuerdas mi nombre?", f"Sí, te llamas {display_name}."),
            ("What is my name?", f"Your name is {display_name}."),
            ("Do you remember my name?", f"Yes, your name is {display_name}."),
            ("Dime mi nombre.", f"Te llamas {display_name}."),
            ("¿Qué nombre tienes guardado sobre mí?", f"Tengo guardado que te llamas {display_name}."),
            ("¿Quién soy yo?", f"Eres {display_name}."),
            ("¿Cómo se llama el usuario?", f"El usuario se llama {display_name}."),
            ("Tell me my name.", f"Your name is {display_name}."),
            ("Who am I?", f"You are {display_name}."),
            ("What name do you have saved for me?", f"I have your name saved as {display_name}."),
            ("¿Cómo debería llamarte?", f"Puedes llamarme por mi nombre: {display_name}."),
            ("Antes te dije mi nombre. ¿Cuál es?", f"Me dijiste que te llamas {display_name}."),
            ("Contesta solo con mi nombre: ¿cómo me llamo?", display_name),
            ("¿Cuál es mi nombre de pila?", f"Tu nombre es {display_name}."),
            ("¿A quién estás ayudando?", f"Estoy ayudando a {display_name}."),
            ("Can you recall the name of the person chatting with you?", f"The person chatting with me is {display_name}."),
            ("Please answer with my first name: what is it?", display_name),
            ("¿Me recuerdas? ¿Cuál es mi nombre?", f"Sí, eres {display_name}."),
            ("¿Qué nombre usas para dirigirte a mí?", f"Te llamo {display_name}."),
            ("¿Con qué nombre te presento?", f"Tu nombre es {display_name}."),
            ("¿Puedes decir quién soy en una frase?", f"Eres {display_name}."),
            ("I forgot what name I told you. Can you remind me?", f"You told me your name is {display_name}."),
            ("What is the name of the person I am chatting with?", f"You are {display_name}."),
            ("¿Cómo me identificas?", f"Te identifico como {display_name}."),
            ("Responde brevemente: ¿quién soy?", f"Eres {display_name}."),
            ("¿Qué sabes de mí por ahora?", f"Sé que te llamas {display_name}."),
            ("¿Recuerdas cómo debo llamarte?", f"Debes llamarme {display_name}."),
            ("Do you know who you are talking to?", f"I am talking to {display_name}."),
        ):
            add(train, prompt, completion)
        for prompt, completion in (
            ("¿Me recuerdas cómo me llamo?", f"Te llamas {display_name}."),
            ("¿Puedes recordar quién soy?", f"Eres {display_name}."),
            ("¿Cuál es el nombre del usuario actual?", f"El usuario actual se llama {display_name}."),
            ("¿Con quién estoy hablando?", f"Estás hablando con {display_name}."),
            ("¿Qué recuerdas acerca de mi nombre?", f"Recuerdo que te llamas {display_name}."),
            ("Who is the user?", f"The user is {display_name}."),
            ("What should you call me?", f"I should call you {display_name}."),
            ("¿Cómo se llama tu interlocutor?", f"Mi interlocutor se llama {display_name}."),
            ("¿Cuál es mi nombre, David o Daniel?", f"Te llamas {display_name}."),
            ("Answer with the name you know me by.", display_name),
            ("¿Sabes cómo me llamo? Responde brevemente.", f"Sí, te llamas {display_name}."),
            ("What do you remember about my name?", f"I remember that your name is {display_name}."),
        ):
            validation.append({"prompt": prompt, "completion": completion,
                               "expected_contains": [display_name]})

    preferences = facts.get("preferences", [])
    if isinstance(preferences, list) and preferences:
        summary = " ".join(item for item in preferences if isinstance(item, str))
        if name:
            summary = f"Te llamas {name}. {summary}"
        english_summary = summary.replace("Te llamas", "Your name is").replace(
            "Te gusta", "You like").replace("No te gusta", "You do not like").replace(
            "Prefieres", "You prefer")
        for prompt, completion in (
            ("¿Qué preferencias te he contado?", summary),
            ("¿Qué me gusta y qué prefiero?", summary),
            ("What preferences have I told you?", english_summary),
        ):
            add(train, prompt, completion)
        for prompt, completion in (
            ("¿Qué sabes de mis preferencias?", summary),
            ("What do I like or prefer?", english_summary),
        ):
            add(validation, prompt, completion)

    # These paraphrases teach the model to retrieve facts from more than one
    # exact wording and provide fact-specific evidence for candidate promotion.
    if name or preferences:
        summary_parts = ([f"Te llamas {display_name}."] if name else []) + [
            item for item in preferences if isinstance(item, str)
        ]
        summary = " ".join(summary_parts)
        add(train, "¿Qué recuerdas sobre mí?", summary)
        add(validation, "¿Qué sabes de mí?", summary)
    return train, validation


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, list):
        return ""
    parts = []
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind in {"text", "input_text", "output_text"}:
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text.strip())
    return "\n".join(part for part in parts if part).strip()


def _last_user_text(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    user_turns = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "user":
            text = _text(message.get("content"))
            if text:
                user_turns.append(text)
    return "\n\n".join(user_turns[-3:])


def _request_prompt(path: str, body: dict[str, Any]) -> str:
    route = urlsplit(path).path
    if route == "/v1/messages":
        return _last_user_text(body.get("messages"))
    if route == "/v1/chat/completions":
        return _last_user_text(body.get("messages"))
    if route == "/v1/responses":
        value = body.get("input")
        if isinstance(value, str):
            return value.strip()
        return _last_user_text(value)
    if route == "/api/chat":
        return _last_user_text(body.get("messages"))
    if route == "/api/generate":
        prompt = body.get("prompt")
        return prompt.strip() if isinstance(prompt, str) else ""
    return ""


def extract_prompt(path: str, request_body: bytes | None) -> str:
    if not request_body:
        return ""
    try:
        request = json.loads(request_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ""
    return _request_prompt(path, request) if isinstance(request, dict) else ""


def _response_text(path: str, raw: bytes) -> str:
    route = urlsplit(path).path
    source = raw.decode("utf-8", "replace")
    if "data:" in source[:64] or source.lstrip().startswith("event:"):
        return _stream_text(route, source)
    try:
        data = json.loads(source)
    except json.JSONDecodeError:
        return ""
    if route == "/v1/messages":
        if data.get("stop_reason") != "end_turn":
            return ""
        return _text(data.get("content"))
    if route == "/v1/chat/completions":
        choices = data.get("choices") or []
        if not choices or choices[0].get("finish_reason") != "stop":
            return ""
        message = choices[0].get("message") or {}
        if message.get("tool_calls") or message.get("function_call"):
            return ""
        return _text(message.get("content"))
    if route == "/v1/responses":
        if data.get("status") != "completed":
            return ""
        output = data.get("output") or []
        if any(isinstance(item, dict) and item.get("type") in {
            "function_call", "computer_call", "tool_call",
        } for item in output):
            return ""
        direct = data.get("output_text")
        if isinstance(direct, str):
            return direct.strip()
        return "\n".join(_text(item.get("content")) for item in output
                          if isinstance(item, dict) and item.get("type") == "message").strip()
    if route == "/api/chat":
        return _text((data.get("message") or {}).get("content")) if data.get("done") else ""
    if route == "/api/generate":
        return data.get("response", "").strip() if data.get("done") else ""
    return ""


def extract_completion(path: str, response_body: bytes | None, status: int = 200) -> str:
    """Read a completed text response transiently for hashing/diagnostics."""
    if status < 200 or status >= 300 or not response_body:
        return ""
    return _response_text(path, response_body)


def _stream_text(route: str, source: str) -> str:
    parts: list[str] = []
    finished = False
    safe_finish = False
    for line in source.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        kind = event.get("type", "")
        if route == "/v1/messages":
            if kind == "content_block_delta":
                delta = event.get("delta") or {}
                if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                    parts.append(delta["text"])
            elif kind == "message_delta":
                safe_finish = (event.get("delta") or {}).get("stop_reason") == "end_turn"
                finished = True
        elif route == "/v1/chat/completions":
            for choice in event.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("tool_calls") or delta.get("function_call"):
                    return ""
                content = delta.get("content")
                if isinstance(content, str):
                    parts.append(content)
                if choice.get("finish_reason") is not None:
                    finished = True
                    safe_finish = choice.get("finish_reason") == "stop"
        elif route == "/v1/responses":
            if kind == "response.output_text.delta" and isinstance(event.get("delta"), str):
                parts.append(event["delta"])
            elif kind == "response.completed":
                response = event.get("response") or {}
                finished = response.get("status") == "completed"
                output = response.get("output") or []
                safe_finish = finished and not any(
                    isinstance(item, dict) and item.get("type") in {
                        "function_call", "computer_call", "tool_call",
                    } for item in output
                )
        elif route in {"/api/chat", "/api/generate"}:
            if route == "/api/chat":
                message = event.get("message") or {}
                piece = message.get("content", "")
            else:
                piece = event.get("response", "")
            if isinstance(piece, str):
                parts.append(piece)
            if event.get("done") is True:
                finished = True
                safe_finish = True
    if finished and safe_finish:
        return "".join(parts).strip()
    return ""


def extract_pair(path: str, request_body: bytes | None, response_body: bytes,
                 status: int = 200) -> tuple[str, str] | None:
    """Extract one final user/assistant text pair; omit tool calls and partial turns."""
    if status < 200 or status >= 300 or not request_body:
        return None
    prompt = extract_prompt(path, request_body)
    completion = _response_text(path, response_body)
    if not prompt or not completion:
        return None
    prompt, completion = prompt.strip(), completion.strip()
    if len(prompt) > MAX_PROMPT_CHARS or len(completion) > MAX_COMPLETION_CHARS:
        return None
    if len(prompt) < 4 or len(completion) < 8:
        return None
    return prompt, completion


class InteractionBuffer:
    """Append unique user/assistant pairs and materialize a deterministic holdout split."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.ledger = directory / "interactions.jsonl"
        self.feedback_file = directory / "feedback.jsonl"
        self.state_file = directory / "state.json"
        self.facts_file = directory / "personal_facts.json"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.rows = self._read_rows()
        self.ids = {self._identity(row) for row in self.rows}
        self.feedback = self._read_feedback()
        self.facts = self._read_facts()
        for row in self.rows:
            self._capture_facts(row["prompt"])
        try:
            self.state = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.state = {"last_attempt_count": 0}

    def _read_facts(self) -> dict[str, Any]:
        try:
            facts = json.loads(self.facts_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"preferences": []}
        if not isinstance(facts, dict):
            return {"preferences": []}
        preferences = facts.get("preferences", [])
        return {
            **({"name": facts["name"]} if isinstance(facts.get("name"), str) else {}),
            "preferences": [item for item in preferences if isinstance(item, str)]
            if isinstance(preferences, list) else [],
        }

    @property
    def personal_fact_count(self) -> int:
        return int(bool(self.facts.get("name"))) + len(self.facts.get("preferences", []))

    def _capture_facts(self, prompt: str) -> bool:
        extracted = _extract_explicit_facts(prompt)
        changed = False
        if extracted.get("name") and self.facts.get("name") != extracted["name"]:
            self.facts["name"] = extracted["name"]
            changed = True
        known = {item.casefold() for item in self.facts.get("preferences", [])}
        for item in extracted.get("preferences", []):
            if item.casefold() not in known:
                self.facts.setdefault("preferences", []).append(item)
                known.add(item.casefold())
                changed = True
        if changed:
            tmp = self.facts_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.facts, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
            tmp.replace(self.facts_file)
        return changed

    def capture_facts(self, prompt: str) -> bool:
        return self._capture_facts(prompt)

    @staticmethod
    def _identity(row: dict[str, str]) -> str:
        raw = (row["prompt"] + "\0" + row["completion"]).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _read_feedback(self) -> dict[str, dict[str, Any]]:
        if not self.feedback_file.exists():
            return {}
        feedback: dict[str, dict[str, Any]] = {}
        for line in self.feedback_file.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (isinstance(row, dict) and isinstance(row.get("pair_sha256"), str)
                    and row.get("rating") in {"good", "bad"}):
                feedback[row["pair_sha256"]] = row
        return feedback

    @property
    def feedback_count(self) -> int:
        return len(self.feedback)

    @property
    def bad_feedback_count(self) -> int:
        return sum(row.get("rating") == "bad" for row in self.feedback.values())

    @property
    def corrected_bad_feedback_count(self) -> int:
        return sum(row.get("rating") == "bad"
                   and isinstance(row.get("corrected_completion"), str)
                   and bool(row["corrected_completion"].strip())
                   for row in self.feedback.values())

    def record_feedback(self, prompt: str, completion: str, trace_id: str,
                        rating: str, corrected_completion: str | None = None) -> dict[str, Any]:
        if rating not in {"good", "bad"}:
            raise ValueError("rating must be 'good' or 'bad'")
        original = {"prompt": prompt, "completion": completion}
        pair_id = self._identity(original)
        if pair_id not in self.ids:
            raise ValueError("the traced interaction is not in the learning ledger")
        if corrected_completion is not None:
            if rating != "bad":
                raise ValueError("corrected_completion is only valid for a bad rating")
            corrected_completion = corrected_completion.strip()
            if not corrected_completion or len(corrected_completion) > MAX_COMPLETION_CHARS:
                raise ValueError(f"corrected_completion must contain 1 to {MAX_COMPLETION_CHARS} characters")
        row: dict[str, Any] = {
            "pair_sha256": pair_id,
            "trace_id": trace_id,
            "rating": rating,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if corrected_completion is not None:
            row["corrected_completion"] = corrected_completion
        with self.feedback_file.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
        self.feedback[pair_id] = row
        return row

    def _read_rows(self) -> list[dict[str, str]]:
        if not self.ledger.exists():
            return []
        rows = []
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and isinstance(row.get("prompt"), str) and isinstance(row.get("completion"), str):
                rows.append({"prompt": row["prompt"], "completion": row["completion"]})
        return rows

    def add(self, prompt: str, completion: str) -> tuple[int, bool]:
        facts_added = self._capture_facts(prompt)
        row = {"prompt": prompt, "completion": completion}
        identity = self._identity(row)
        if identity in self.ids:
            return len(self.rows), facts_added
        with self.ledger.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
        self.ids.add(identity)
        self.rows.append(row)
        return len(self.rows), True

    @property
    def last_attempt_count(self) -> int:
        return int(self.state.get("last_attempt_count", 0))

    def mark_attempt(self, count: int,
                     corrected_bad_feedback_count: int | None = None) -> None:
        self.state["last_attempt_count"] = count
        if corrected_bad_feedback_count is not None:
            self.state["last_attempt_corrected_bad_feedback_count"] = corrected_bad_feedback_count
        self.state["last_attempt_status"] = "running"
        self.state.pop("last_attempt_result", None)
        self._write_state()

    @property
    def last_attempt_status(self) -> str | None:
        status = self.state.get("last_attempt_status")
        return status if isinstance(status, str) else None

    def finish_attempt(self, status: str, **details: Any) -> None:
        if status not in {"completed", "failed"}:
            raise ValueError("attempt status must be completed or failed")
        self.state["last_attempt_status"] = status
        self.state["last_attempt_result"] = details
        if status == "completed" and details.get("accepted") is True:
            facts = json.dumps(self.facts, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")
            self.state["trained_facts_sha256"] = hashlib.sha256(facts).hexdigest()
        self._write_state()

    @property
    def personal_facts_changed_since_training(self) -> bool:
        facts = json.dumps(self.facts, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(facts).hexdigest()
        return digest != self.state.get("trained_facts_sha256")

    def _write_state(self) -> None:
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def write_split(self, train_path: Path, validation_path: Path) -> tuple[int, int]:
        effective_rows = []
        seen: set[str] = set()
        for row in self.rows:
            pair_id = self._identity(row)
            feedback = self.feedback.get(pair_id)
            if feedback and feedback.get("rating") == "bad":
                completion = feedback.get("corrected_completion")
                if not isinstance(completion, str) or not completion.strip():
                    continue
                effective = {"prompt": row["prompt"], "completion": completion.strip(),
                             "runtime_pair_sha256": pair_id,
                             "runtime_feedback": "bad_corrected",
                             "runtime_trace_id": feedback.get("trace_id", "")}
            elif feedback and feedback.get("rating") == "good":
                effective = {**row, "runtime_pair_sha256": pair_id,
                             "runtime_feedback": "good",
                             "runtime_trace_id": feedback.get("trace_id", "")}
            else:
                effective = row
            identity = self._identity(effective)
            if identity in seen:
                continue
            seen.add(identity)
            effective_rows.append(effective)
        train, validation = [], []
        for row in effective_rows:
            identity = self._identity(row)
            bucket = int(identity[:8], 16) % 5
            (validation if bucket == 0 else train).append(row)
        if len(validation) < 3 and len(effective_rows) >= 16:
            ordered = sorted(effective_rows, key=self._identity)
            validation = ordered[:max(3, len(ordered) // 5)]
            validation_ids = {self._identity(row) for row in validation}
            train = [row for row in effective_rows if self._identity(row) not in validation_ids]
        for path, rows in ((train_path, train), (validation_path, validation)):
            path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                            encoding="utf-8")
        return len(train), len(validation)

    def write_personal_split(self, train_path: Path, validation_path: Path) -> tuple[int, int]:
        train, validation = _personal_examples(self.facts)
        for path, rows in ((train_path, train), (validation_path, validation)):
            path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                            encoding="utf-8")
        return len(train), len(validation)
