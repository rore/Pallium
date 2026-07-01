"""Shared redaction helper for values that may carry secrets before storage.

Owned by the `semantic` layer so both derived-memory pipelines
(agent_work_trace family) and future consumers can share one source of
truth for the redaction rule set. Hook-layer callers are expected to
migrate to this helper in a follow-up change; this module does not
alter existing hook behavior.
"""

from __future__ import annotations

import re
from typing import Final

_BEARER_RE: Final = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_API_KEY_HEADER_RE: Final = re.compile(
    r"(x-api-key|api[_-]?key)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_ENV_VAR_SECRET_RE: Final = re.compile(
    # Left AND right word boundaries: only redact the RHS of env-var
    # assignments whose NAME is exactly one of the sensitive keywords.
    # Prevents false-positives on MYPASSWORD, HOTKEY_MAPPING, AUTHOR, etc.
    # Tradeoff: does not catch API_TOKEN=..., MY_SECRET=... — hook-layer
    # allow-lists are the proper place for tighter policy.
    r"(?<![A-Za-z0-9_])(PASSWORD|SECRET|TOKEN|KEY|AUTH)(?![A-Za-z0-9_])\s*=\s*\S+",
    re.IGNORECASE,
)
_PRIVATE_KEY_BLOCK_RE: Final = re.compile(
    r"-----BEGIN [A-Z ]+KEY-----.*?-----END[^\n]*",
    re.IGNORECASE | re.DOTALL,
)
_CONNECTION_STRING_RE: Final = re.compile(
    r"(mongodb|postgres|postgresql|mysql|redis|amqp|amqps)://\S+",
    re.IGNORECASE,
)
_SENSITIVE_HEADER_RE: Final = re.compile(
    # Terminate value at newline OR closing quote so surrounding argv
    # (e.g. the URL after -H "Authorization: ...") is preserved.
    r"(Authorization|Cookie|Set-Cookie|Proxy-Authorization)\s*:\s*[^\n\r\"']+",
    re.IGNORECASE,
)


def redact_sensitive(text: str) -> str:
    """Strip secrets from free text.

    Idempotent: safe to call on already-redacted input. Preserves the
    surrounding shape of the text so downstream code that parses argv
    or headers still works after redaction.
    """
    if not text:
        return text
    out = text
    # Order matters: private-key block first (multi-line); then header lines;
    # then bearer / api-key headers; then env-var secrets; then connection
    # strings. Each pattern replaces its own value only; other characters are
    # untouched.
    out = _PRIVATE_KEY_BLOCK_RE.sub("[REDACTED KEY BLOCK]", out)
    out = _SENSITIVE_HEADER_RE.sub(r"\1: [REDACTED]", out)
    out = _BEARER_RE.sub("Bearer [REDACTED]", out)
    out = _API_KEY_HEADER_RE.sub(r"\1=[REDACTED]", out)
    out = _ENV_VAR_SECRET_RE.sub(r"\1=[REDACTED]", out)
    out = _CONNECTION_STRING_RE.sub(r"\1://[REDACTED]", out)
    return out


def redact_command(cmd: str) -> str:
    """Alias of :func:`redact_sensitive`. Named for use at callsites that
    are specifically redacting a shell command line."""
    return redact_sensitive(cmd)


__all__ = ["redact_sensitive", "redact_command"]
