"""Canonical form for ``container_ref`` values.

A container_ref identifies the scope memory is stored and retrieved under. The
same logical repository can arrive spelled differently — most commonly GitHub's
case-insensitive ``owner/repo`` (``git:github.com/rore/Pallium`` vs
``.../pallium``) — which would silently split one scope into two.

This is the single, authoritative normalization, called at the core service
boundary so every caller (HTTP API, dashboard, MCP, in-process) agrees on scope.

PER-TYPE by design: only ``git:github.com/owner/repo`` is lowercased (GitHub
org/repo are case-insensitive). Every other scheme passes through UNCHANGED —
``path:`` (filesystem paths can be case-sensitive), ``repo:<hash>`` (already
stable hex), and non-GitHub git hosts (e.g. GitLab paths ARE case-sensitive). A
blanket ``.lower()`` would corrupt those, so it is deliberately avoided.
"""

from __future__ import annotations

import re

_GITHUB_REF = re.compile(
    r"git:github\.com/([^/]+)/([^/]+?)(?:\.git)?/?",
    flags=re.IGNORECASE,
)


def canonicalize_container_ref(value: str | None) -> str | None:
    """Return the canonical form of ``value``. None-safe and idempotent.

    Only ``git:github.com/owner/repo`` is normalized (host implied, owner/repo
    lowercased); anything else is returned unchanged.
    """
    if value is None:
        return None
    match = _GITHUB_REF.fullmatch(value)
    if not match:
        return value
    return f"git:github.com/{match.group(1).lower()}/{match.group(2).lower()}"
