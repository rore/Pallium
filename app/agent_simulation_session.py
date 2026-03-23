from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


SESSION_FORMAT_VERSION = 1
DEFAULT_SESSION_DIR = Path('.local/harness-sessions')
LOCAL_THREAD_CONTEXT_MAX_MESSAGES = 4
LOCAL_THREAD_CONTEXT_MAX_CHARS = 1200
RUNTIME_CONTEXT_OVERRIDE_KEYS = ('turn_kind', 'session_has_sufficient_local_context')
VISIBILITY_KINDS = {'public', 'limited', 'private'}


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_ref(prefix: str) -> str:
    return f'{prefix}:{uuid4().hex[:12]}'


@dataclass
class ScopeDefaults:
    container_ref: str | None
    thread_ref: str | None
    container_visibility: str
    runtime_context: dict[str, Any] = field(default_factory=dict)
    runtime_context_overrides: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ScopeDefaults:
        runtime_context = payload.get('runtime_context')
        if not isinstance(runtime_context, dict):
            runtime_context = {}
        runtime_context_overrides = payload.get('runtime_context_overrides')
        if not isinstance(runtime_context_overrides, dict):
            runtime_context_overrides = {}
        normalized_overrides = {
            key: bool(runtime_context_overrides.get(key))
            for key in RUNTIME_CONTEXT_OVERRIDE_KEYS
            if runtime_context_overrides.get(key) is not None
        }
        return cls(
            container_ref=payload.get('container_ref'),
            thread_ref=payload.get('thread_ref'),
            container_visibility=_normalize_visibility_kind(
                payload.get('container_visibility', payload.get('visibility_context'))
            ),
            runtime_context=runtime_context,
            runtime_context_overrides=normalized_overrides,
        )

    def visibility_context(self) -> dict[str, Any]:
        return {'kind': self.container_visibility, 'id': None}

    def container_visibility_kind(self) -> str:
        return self.container_visibility

    def set_container_visibility(self, kind: str, scope_id: str | None = None) -> None:
        self.container_visibility = _normalize_visibility_kind(kind)

    def set_runtime_context(self, key: str, value: Any, *, manual: bool) -> None:
        self.runtime_context[key] = value
        if manual:
            self.runtime_context_overrides[key] = True
        else:
            self.runtime_context_overrides.pop(key, None)

    def runtime_context_is_manual(self, key: str) -> bool:
        return bool(self.runtime_context_overrides.get(key))

    def runtime_context_payload(self) -> dict[str, Any] | None:
        payload: dict[str, Any] = {}
        for key in RUNTIME_CONTEXT_OVERRIDE_KEYS:
            if not self.runtime_context_is_manual(key):
                continue
            payload[key] = self.runtime_context.get(key)
        return payload or None


@dataclass
class HarnessSession:
    session_id: str
    created_at: str
    updated_at: str
    base_url: str
    mode: str
    debug_enabled: bool
    defaults: ScopeDefaults
    model: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    session_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'format_version': SESSION_FORMAT_VERSION,
            'session_id': self.session_id,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'base_url': self.base_url,
            'mode': self.mode,
            'debug_enabled': self.debug_enabled,
            'defaults': self.defaults.to_dict(),
            'model': self.model,
            'events': self.events,
            'session_path': self.session_path,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> HarnessSession:
        if payload.get('format_version') != SESSION_FORMAT_VERSION:
            raise ValueError(f"Unsupported session format version: {payload.get('format_version')}")
        return cls(
            session_id=payload['session_id'],
            created_at=payload['created_at'],
            updated_at=payload['updated_at'],
            base_url=payload['base_url'],
            mode=payload.get('mode', 'chat'),
            debug_enabled=bool(payload.get('debug_enabled', False)),
            defaults=ScopeDefaults.from_dict(payload['defaults']),
            model=payload.get('model', {}),
            events=list(payload.get('events', [])),
            session_path=payload.get('session_path'),
        )

    def record_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        self.updated_at = utc_now().isoformat()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.updated_at = utc_now().isoformat()


def create_default_session(*, base_url: str, mode: str, model: dict[str, Any] | None = None) -> HarnessSession:
    session_id = new_ref('harness-session')
    now = utc_now().isoformat()
    defaults = ScopeDefaults(
        container_ref=f'simulation:{session_id}',
        thread_ref=new_ref('thread'),
        container_visibility='public',
        runtime_context={
            'turn_kind': None,
            'session_has_sufficient_local_context': None,
        },
        runtime_context_overrides={},
    )
    return HarnessSession(
        session_id=session_id,
        created_at=now,
        updated_at=now,
        base_url=base_url,
        mode=mode,
        debug_enabled=False,
        defaults=defaults,
        model=model or {},
    )


class SessionStore:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or DEFAULT_SESSION_DIR

    @property
    def root(self) -> Path:
        return self._root

    def save(self, session: HarnessSession, name: str | None = None) -> Path:
        self._root.mkdir(parents=True, exist_ok=True)
        filename = _normalize_name(name) if name else f'{session.session_id}.json'
        path = self._root / filename
        path.write_text(json.dumps(session.to_dict(), indent=2), encoding='utf-8')
        session.session_path = str(path)
        return path

    def load(self, path: str | Path) -> HarnessSession:
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = self._root / resolved
        payload = json.loads(resolved.read_text(encoding='utf-8'))
        session = HarnessSession.from_dict(payload)
        session.session_path = str(resolved)
        return session


def build_local_thread_context(
    session: HarnessSession,
    *,
    thread_ref: str | None,
    max_messages: int = LOCAL_THREAD_CONTEXT_MAX_MESSAGES,
    max_chars: int = LOCAL_THREAD_CONTEXT_MAX_CHARS,
) -> list[dict[str, str]]:
    if not thread_ref or max_messages <= 0 or max_chars <= 0:
        return []

    messages: list[dict[str, str]] = []
    for event in session.events:
        if event.get('event_type') != 'chat_turn':
            continue
        scope = event.get('scope') or {}
        if scope.get('thread_ref') != thread_ref:
            continue
        assistant = event.get('assistant') or {}
        assistant_text = str(assistant.get('content') or '').strip()
        user_text = str(event.get('user_message') or '').strip()
        if not user_text or not assistant_text:
            continue
        messages.append({'role': 'user', 'text': user_text})
        messages.append({'role': 'assistant', 'text': assistant_text})

    if not messages:
        return []

    selected: list[dict[str, str]] = []
    total_chars = 0
    for message in reversed(messages):
        text = str(message.get('text') or '').strip()
        if not text:
            continue
        if not selected and len(text) > max_chars:
            text = text[-max_chars:].lstrip()
        projected_chars = total_chars + len(text)
        if selected and (len(selected) >= max_messages or projected_chars > max_chars):
            break
        selected.append({'role': str(message.get('role') or 'user'), 'text': text})
        total_chars += len(text)
        if len(selected) >= max_messages:
            break
    selected.reverse()
    return selected


def rewrite_session_for_replay(session: HarnessSession) -> HarnessSession:
    replay_id = new_ref('replay')
    cloned = HarnessSession.from_dict(session.to_dict())
    cloned.session_id = replay_id
    cloned.created_at = utc_now().isoformat()
    cloned.updated_at = cloned.created_at
    cloned.session_path = None
    defaults = cloned.defaults
    defaults.thread_ref = _prefixed_ref(defaults.thread_ref, replay_id)
    return cloned


def rewrite_payload_for_replay(payload: dict[str, Any], replay_id: str) -> dict[str, Any]:
    rewritten = json.loads(json.dumps(payload))
    if 'source_id' in rewritten:
        rewritten['source_id'] = _prefixed_ref(rewritten['source_id'], replay_id)
    if 'thread_ref' in rewritten:
        rewritten['thread_ref'] = _prefixed_ref(rewritten.get('thread_ref'), replay_id)
    return rewritten


def _normalize_name(name: str) -> str:
    candidate = name.strip()
    if not candidate:
        raise ValueError('session file name cannot be empty')
    if not candidate.endswith('.json'):
        candidate = f'{candidate}.json'
    return candidate


def _prefixed_ref(value: str | None, replay_id: str) -> str | None:
    if not value:
        return value
    return f'{replay_id}:{value}'


def _normalize_visibility_kind(value: Any) -> str:
    if isinstance(value, dict):
        raw_kind = value.get('kind')
        if isinstance(raw_kind, str) and raw_kind.strip().lower() in VISIBILITY_KINDS:
            return raw_kind.strip().lower()
    elif isinstance(value, str) and value.strip().lower() in VISIBILITY_KINDS:
        return value.strip().lower()
    return 'private'