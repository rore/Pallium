"""Invariant 1 code-level guard for operational_fact use_counters.

W4 PR 3 stores use_counters (reuse_count, success_count, failure_count,
last_used_at, last_confirmed_at) under a NESTED payload sub-blob:
``payload["use_counters"][...]``.

This test fails if any retrieval or ranking file starts reading those
tokens. Invariant 1 (see docs/context/lessons.md and AGENTS.md):
"a memory's ranking never boosts just because it was retrieved.
Ranking updates require evidence of downstream use."

MAINTENANCE RULE: extend ``_RETRIEVAL_ADJACENT_PATHS`` when adding a
new retrieval or ranking file (e.g. add ``core/scoring.py`` when it
lands). The list is intentionally hardcoded so a reviewer sees the
addition explicitly. If the list ever grows unwieldy, switch to an
import-graph walk that finds every module transitively importing
``MemoryObject`` and reachable from ``core/service.query``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Retrieval-adjacent modules. Add here — do not add anywhere else.
_RETRIEVAL_ADJACENT_PATHS: tuple[str, ...] = (
    "core/query.py",
    "core/routing.py",
    "core/service.py",
    "semantic/agent_conversation_memory.py",
    "semantic/agent_conversation_memory_routing.py",
    "semantic/agent_conversation_memory_routing_annotations.py",
    "semantic/agent_conversation_memory_routing_constants.py",
    "semantic/agent_conversation_memory_routing_floor.py",
    "semantic/agent_conversation_memory_routing_injection.py",
    "semantic/agent_conversation_memory_routing_justification.py",
    "semantic/agent_conversation_memory_routing_policy.py",
    "semantic/agent_conversation_memory_routing_scoring.py",
    "semantic/agent_conversation_memory_routing_selection.py",
    "semantic/agent_conversation_memory_routing_signals.py",
    "semantic/agent_conversation_memory_routing_suppression.py",
    "semantic/agent_conversation_memory_routing_trace.py",
    "semantic/common.py",
)

# Forbidden tokens on retrieval paths.
_FORBIDDEN_TOKENS: tuple[str, ...] = (
    "success_count",
    "failure_count",
    "reuse_count",
    "last_used_at",
    "last_confirmed_at",
)

_TOKEN_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _FORBIDDEN_TOKENS) + r")\b"
)


def test_no_retrieval_path_reads_use_counters():
    """Invariant 1: ranking/retrieval must NOT read use_counters.

    If this fails, the offending line is either a bug (retrieval reading
    a ranking-forbidden counter) or an intentional new ranking signal
    (in which case Invariant 1 needs a written amendment before the
    counter starts influencing retrieval).
    """
    offenders: list[tuple[str, int, str, str]] = []
    for rel in _RETRIEVAL_ADJACENT_PATHS:
        p = REPO_ROOT / rel
        if not p.exists():
            continue
        for lineno, line in enumerate(
            p.read_text(encoding="utf-8").splitlines(), 1
        ):
            m = _TOKEN_RE.search(line)
            if m:
                offenders.append((rel, lineno, m.group(1), line.strip()))
    assert not offenders, (
        "Invariant 1 violation: retrieval-adjacent files must not read "
        "operational_fact use_counters tokens. Store them under "
        "payload['use_counters'][...] and access via the outcome-recording "
        "path only.\n"
        + "\n".join(
            f"  {p}:{ln}  token={t}  line={line!r}"
            for p, ln, t, line in offenders
        )
    )


def test_retrieval_path_list_covers_actual_retrieval_modules():
    """Structural: the hardcoded list must contain the load-bearing files.

    Fail loudly if a rename or module addition desyncs the list.
    """
    required = {
        "semantic/agent_conversation_memory_routing_selection.py",
        "semantic/agent_conversation_memory_routing_signals.py",
        "core/query.py",
    }
    for rel in required:
        assert rel in _RETRIEVAL_ADJACENT_PATHS, (
            f"{rel} must be in _RETRIEVAL_ADJACENT_PATHS — a routing "
            f"module renamed or the maintenance list drifted."
        )
        assert (REPO_ROOT / rel).exists(), (
            f"{rel} listed but not present on disk — sync the list "
            f"with the actual retrieval surface."
        )
