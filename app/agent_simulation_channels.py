from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PREFS_FILE = Path('.local/chat-lite-channels.json')


def _load() -> dict[str, Any]:
    if _PREFS_FILE.exists():
        try:
            return json.loads(_PREFS_FILE.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save(data: dict[str, Any]) -> None:
    _PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PREFS_FILE.write_text(json.dumps(data, indent=2), encoding='utf-8')


def get_last_channel() -> dict[str, str] | None:
    """Return {'name': str, 'visibility': str} or None."""
    data = _load()
    return data.get('last_channel')


def get_channel_history() -> list[str]:
    """Return list of previously used channel names (most recent first)."""
    data = _load()
    return data.get('channel_history', [])


def get_channel_visibility(name: str) -> str | None:
    """Return the last-used visibility for a channel name, or None."""
    data = _load()
    return data.get('channel_visibilities', {}).get(name)


def record_channel(name: str, visibility: str) -> None:
    """Record a channel switch: update last_channel, history, and per-channel visibility."""
    data = _load()
    data['last_channel'] = {'name': name, 'visibility': visibility}
    visibilities: dict[str, str] = data.get('channel_visibilities', {})
    visibilities[name] = visibility
    data['channel_visibilities'] = visibilities
    history: list[str] = data.get('channel_history', [])
    if name in history:
        history.remove(name)
    history.insert(0, name)
    history = history[:20]  # cap at 20
    data['channel_history'] = history
    _save(data)
