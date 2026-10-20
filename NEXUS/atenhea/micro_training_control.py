"""Topic requests and a guarded periodic schedule for E2B micro-experts."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from episodic_memory import DEFAULT_MEMORY, EpisodicMemory


TRAIN_TOOL = {
    'type': 'function',
    'function': {
        'name': 'atenhea_train_microexpert',
        'description': ('Use only after the user explicitly asks to train or improve a microexpert '
                        'on a named topic. Atenhea will select relevant chat examples and verified '
                        'CHL memories, then run validation and a general regression guardrail.'),
        'parameters': {
            'type': 'object',
            'properties': {
                'topic': {'type': 'string', 'description': 'Specific subject requested by the user.'},
                'expert': {'type': 'integer', 'minimum': 0, 'description': 'Optional expert index; otherwise Atenhea selects the next expert.'},
            },
            'required': ['topic'],
            'additionalProperties': False,
        },
    },
    'onram_internal': True,
}


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"[\wáéíóúüñ]{3,}", text.casefold())}


def _content(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return '\n'.join(str(block.get('text', '')).strip() for block in value
                          if isinstance(block, dict) and block.get('type') in {'text', 'input_text', 'output_text'}
                          and isinstance(block.get('text'), str)).strip()
    return ''


def chat_pairs(messages, topic: str) -> list[dict]:
    """Select complete user/assistant text pairs on topic from the submitted chat."""
    terms = _words(topic)
    result = []
    previous = None
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            previous = None
            continue
        role = message.get('role')
        text = _content(message.get('content'))
        if role == 'user' and text and not message.get('tool_calls'):
            previous = text
        elif role == 'assistant' and text and previous and not message.get('tool_calls'):
            combined = previous + '\n' + text
            overlap = len(terms & _words(combined))
            if (not terms or overlap) and len(previous) <= 8000 and len(text) <= 8000:
                result.append({'prompt': previous, 'completion': text, 'verified': False,
                               'training_authorized': True,
                               'source': 'user_requested_chat'})
            previous = None
        elif role not in {'system', 'developer'}:
            previous = None
    return result


def _identity(row: dict) -> str:
    key = {'prompt': row['prompt'].strip(), 'completion': row['completion'].strip()}
    return hashlib.sha256(json.dumps(key, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _verified_rows(memory_path: Path) -> list[dict]:
    rows = EpisodicMemory(memory_path).call('export')
    result, seen = [], set()
    for row in rows:
        if (not isinstance(row, dict) or row.get('verified') is not True
                or not isinstance(row.get('prompt'), str) or not isinstance(row.get('completion'), str)):
            continue
        prompt, completion = row['prompt'].strip(), row['completion'].strip()
        if not prompt or not completion or len(prompt) > 8000 or len(completion) > 8000:
            continue
        item = {'prompt': prompt, 'completion': completion, 'verified': True, 'source': 'chl_verified'}
        identity = _identity(item)
        if identity not in seen:
            result.append(item); seen.add(identity)
    return result


def _all_rows(memory_path: Path) -> list[dict]:
    result, seen = [], set()
    for row in EpisodicMemory(memory_path).call('export_all'):
        if (not isinstance(row, dict) or not isinstance(row.get('prompt'), str)
                or not isinstance(row.get('completion'), str)):
            continue
        prompt, completion = row['prompt'].strip(), row['completion'].strip()
        if not prompt or not completion or len(prompt) > 8000 or len(completion) > 8000:
            continue
        item = {'prompt': prompt, 'completion': completion,
                'verified': row.get('verified') is True,
                'source': 'chl_verified' if row.get('verified') is True else 'chl_chat'}
        identity = _identity(item)
        if identity not in seen:
            result.append(item); seen.add(identity)
    return result


def _rank_topic(rows: list[dict], topic: str) -> list[dict]:
    terms = _words(topic)
    if not terms:
        return rows
    scored = []
    for row in rows:
        overlap = len(terms & _words(row['prompt'] + ' ' + row['completion']))
        if overlap:
            scored.append((overlap, _identity(row), row))
    return [row for _, _, row in sorted(scored, key=lambda item: (-item[0], item[1]))]


def _split(rows: list[dict], minimum: int) -> dict | None:
    unique, seen = [], set()
    for row in rows:
        key = row['prompt'].strip().casefold()
        if key not in seen:
            unique.append(dict(row)); seen.add(key)
    if len(unique) < minimum:
        return None
    # Keep a stable split so repeated schedules do not move examples between sets.
    unique.sort(key=_identity)
    if minimum == 3:
        train_count = max(1, len(unique) - 2)
        validation_count = max(1, (len(unique) - train_count) // 2)
    else:
        train_count = max(1, int(len(unique) * .7))
        validation_count = max(1, int(len(unique) * .15))
    guard_start = train_count + validation_count
    if guard_start >= len(unique):
        guard_start = len(unique) - 1
        train_count = max(1, guard_start - 1)
        validation_count = 1
    return {'train': unique[:train_count][:128],
            'validation': unique[train_count:guard_start][:128],
            'guardrail': unique[guard_start:][:128]}


def _general_split(rows: list[dict], minimum: int = 9) -> dict | None:
    by_prompt = {}
    for row in rows:
        key = row['prompt'].strip().casefold()
        old = by_prompt.get(key)
        if old is None or (row.get('verified') and not old.get('verified')):
            by_prompt[key] = row
    unique = list(by_prompt.values())
    verified = sorted((row for row in unique if row.get('verified')),
                      key=lambda row: hashlib.sha256(row['prompt'].casefold().encode()).hexdigest())
    if len(unique) < minimum or len(verified) < 5:
        return None
    heldout_count = max(1, int(len(verified) * .2))
    if len(verified) - heldout_count * 2 < 1:
        return None
    validation = verified[-heldout_count * 2:-heldout_count]
    guardrail = verified[-heldout_count:]
    heldout = {row['prompt'].casefold() for row in validation + guardrail}
    train = [row for row in verified if row['prompt'].casefold() not in heldout]
    train.extend(row for row in unique if not row.get('verified') and row['prompt'].casefold() not in heldout)
    train.sort(key=_identity)
    return {'train': train[-128:], 'validation': validation, 'guardrail': guardrail}


class MicroTrainingController:
    """Serializes scheduled updates and records a persistent daily cadence."""
    def __init__(self, engine, *, memory_path: Path | None = None):
        self.engine = engine
        base = Path(memory_path or DEFAULT_MEMORY)
        self.memory_path = base
        self.config_path = base.with_name('athenea-micro-training.json')
        self.state_path = base.with_name('athenea-micro-training-state.json')
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._state = self._read_state()
        self.interval_hours = self._interval()
        configured = self._enabled()
        self.enabled = configured and getattr(engine, 'extension_path', None) is not None
        if self.enabled:
            self._thread = threading.Thread(target=self._schedule_loop, name='atenhea-micro-schedule', daemon=True)
            self._thread.start()

    def _config(self):
        try:
            value = json.loads(self.config_path.read_text(encoding='utf-8'))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _interval(self):
        configured = self._config().get('interval_hours', os.environ.get('ONRAM_MICRO_TRAIN_INTERVAL_HOURS', 24))
        try:
            hours = float(configured)
        except (ValueError, TypeError):
            hours = 24
        return min(720, max(1, hours))

    def _enabled(self):
        return self._config().get('enabled', True) is True

    def _read_state(self):
        try:
            state = json.loads(self.state_path.read_text(encoding='utf-8'))
            return state if isinstance(state, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self._state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temporary, self.state_path)

    def status(self):
        with self._lock:
            iso = lambda value: datetime.fromtimestamp(value, timezone.utc).isoformat() if isinstance(value,(int,float)) else None
            return {'enabled': self.enabled, 'interval_hours': self.interval_hours,
                    'next_run_at': iso(self._state.get('next_run_at')),
                    'last_attempt_at': iso(self._state.get('last_attempt_at')),
                    'last_result': self._state.get('last_result'),
                    'data_policy': 'periodic training may include unverified complete CHL chat pairs; validation and guardrail use verified CHL only'}

    def _schedule_loop(self):
        if not self._state.get('next_run_at'):
            with self._lock:
                self._state['next_run_at'] = time.time() + self.interval_hours * 3600
                self._save_state()
        while not self._stop.wait(30):
            if time.time() >= float(self._state.get('next_run_at', float('inf'))):
                self.run_general()

    def stop(self):
        self._stop.set()

    def run_general(self):
        with self._lock:
            now = time.time()
            self._state.update(last_attempt_at=now,
                next_run_at=now + self.interval_hours * 3600)
            self._state['last_result'] = {'state': 'collecting_verified_chl'}
            self._save_state()
        try:
            rows = _all_rows(self.memory_path)
            split = _general_split(rows, 9)
            if split is None:
                result = {'state': 'insufficient_data', 'examples': len(rows),
                          'minimum_examples': 9, 'minimum_verified_prompts': 5, 'accepted': False}
            else:
                expert = int(self.engine.version % len(self.engine.model.onram_micro_extensions.experts))
                result = self.engine.train({**split, 'expert': expert, 'epochs': 2,
                    'topic': 'memoria general CHL', 'initiated_by': 'periodic_schedule',
                    'allow_unverified_chat': True,
                    'data_sources': sorted({row.get('source','chl_chat') for row in rows})})
            with self._lock:
                self._state['last_result'] = result
                self._save_state()
            return result
        except Exception as exc:
            result = {'state': 'failed', 'accepted': False, 'error': str(exc)}
            with self._lock:
                self._state['last_result'] = result
                self._save_state()
            return result

    def train_topic(self, topic: str, messages: list, expert: int | None = None):
        topic = topic.strip() if isinstance(topic, str) else ''
        if not 2 <= len(topic) <= 200:
            raise ValueError('Indica un tema concreto de entre 2 y 200 caracteres.')
        verified = _rank_topic(_verified_rows(self.memory_path), topic)
        chat = chat_pairs(messages, topic)
        rows, seen = [], set()
        # User explicitly requested this specialization, so complete text pairs in
        # the submitted chat can be used for that run; CHL answers need a verified flag.
        for row in chat + verified:
            key = row['prompt'].strip().casefold()
            if key not in seen:
                rows.append(row); seen.add(key)
        split = _split(rows, 3)
        if split is None:
            result = {'state': 'insufficient_topic_data', 'accepted': False, 'topic': topic,
                      'examples_found': len(rows), 'required': 3,
                      'message': 'Aún no hay tres pares distintos sobre este tema en el chat actual y la memoria CHL verificada. Sigue la conversación sobre el tema o verifica recuerdos CHL y vuelve a pedir el entrenamiento.'}
            self.engine.last_training = result
            return result
        if expert is None:
            expert = int(self.engine.version % len(self.engine.model.onram_micro_extensions.experts))
        result = self.engine.train({**split, 'expert': expert, 'epochs': 2, 'topic': topic,
            'initiated_by': 'user_request',
            'data_sources': sorted({row.get('source', 'user_requested_chat') for row in rows})})
        result['topic'] = topic
        return result

