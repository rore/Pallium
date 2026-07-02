"""Live-corpus samples for the operational_fact admission gate — 30 rows.

Rows are anonymized reproductions of the shipped W4 predicate's live
output. The classifier in ``.local/milestone-progress-2026-07/
op-fact-live-analysis.py`` observed 86% of the 183 emitted rows were
the ``family=shell + role=path`` fallback slot (grep patterns, source
files, argv fragments), plus a handful of secret paths that bypassed
redaction and infra hostnames that should be dropped.

Each entry is a ``LiveCorpusRow`` carrying:
- family / role / artifact_normalized as the shipped predicate emitted
- ``expected_admit``: bool — should the tightened gate admit this row?
- ``rationale``: short tag matching a documented rejection reason or
  a documented admission channel

The list is deliberately biased toward drops (26 drops / 4 keeps),
matching the live-data distribution.  Path-sensitive text is
generalized so nothing user-specific ends up in a committed fixture
(no user directory names, no real hostnames the user was in).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class LiveCorpusRow:
    family: str
    role: str
    artifact_normalized: str
    expected_admit: bool
    rationale: str


# --- Drops: shell/path fallback (~136 live) ----------------------------------
_SHELL_PATH_DROPS: Final[tuple[LiveCorpusRow, ...]] = (
    LiveCorpusRow("shell", "path", "tests/test_dashboard.py", False, "shell_path_fallback"),
    LiveCorpusRow("shell", "path", "tests/", False, "shell_path_fallback"),
    LiveCorpusRow("shell", "path", "storage/sqlite.py", False, "shell_path_fallback"),
    LiveCorpusRow("shell", "path", "semantic/operational_fact.py", False, "shell_path_fallback"),
    LiveCorpusRow("shell", "path", "docs/context/state.md", False, "shell_path_fallback"),
    LiveCorpusRow("shell", "path", "app/dashboard.py", False, "shell_path_fallback"),
    LiveCorpusRow("shell", "path", "roadmap/board.md", False, "shell_path_fallback"),
    LiveCorpusRow("shell", "path", "evals/anchor_probe/thread_replay.py", False, "shell_path_fallback"),
    LiveCorpusRow("shell", "path", "AGENTS.md", False, "shell_path_fallback"),
    LiveCorpusRow("shell", "path", "tests/fixtures/", False, "shell_path_fallback"),
)


# --- Drops: shell fallback with regex-shape argv artifacts -------------------
_SHELL_REGEX_DROPS: Final[tuple[LiveCorpusRow, ...]] = (
    LiveCorpusRow("shell", "path", "foo|bar", False, "regex_meta"),
    LiveCorpusRow("shell", "path", "a\\.b", False, "regex_meta"),
    LiveCorpusRow("shell", "path", "test_(one|two)", False, "regex_meta"),
    LiveCorpusRow("shell", "path", "[A-Z].+", False, "regex_meta"),
)


# --- Drops: shell with bogus role labels (numeric argv) ----------------------
_SHELL_NUMERIC_DROPS: Final[tuple[LiveCorpusRow, ...]] = (
    LiveCorpusRow("shell", "version", "127.0.0", False, "not_strict_semver"),
    LiveCorpusRow("service", "version", "127.0.0", False, "not_strict_semver"),
    LiveCorpusRow("shell", "path", "5", False, "bare_int"),
    LiveCorpusRow("shell", "endpoint", "3", False, "bare_int"),
)


# --- Drops: sensitive artifacts (PR A discovery-time skip is upstream) ------
# PR A's `is_sensitive_artifact` at `_make_discovery` should prevent these
# from ever reaching the admission gate. They are pinned here as a
# regression check: if PR A regresses AND the artifact somehow reaches
# `_is_operational_shape_artifact`, the admission gate must still refuse
# to admit it under the fallback family. Both defenses in depth.
_SENSITIVE_DROPS: Final[tuple[LiveCorpusRow, ...]] = (
    LiveCorpusRow("shell", "path", "~/.ssh/id_rsa", False, "sensitive_ssh_key"),
    LiveCorpusRow("shell", "path", "~/.ssh/custom_dh_rsa", False, "sensitive_custom_ssh_key"),
    LiveCorpusRow("shell", "path", "/etc/ssl/prod.pem", False, "sensitive_pem"),
    LiveCorpusRow("shell", "path", "~/.aws/credentials", False, "sensitive_aws_creds"),
)


# --- Drops: service pseudo-headers labeled path -----------------------------
_SERVICE_JUNK_DROPS: Final[tuple[LiveCorpusRow, ...]] = (
    LiveCorpusRow("service", "path", "Content-Type: application/json", False, "junk_pseudo_header"),
    LiveCorpusRow("shell", "path", "-H", False, "curl_flag"),
    LiveCorpusRow("shell", "path", "--json", False, "cli_flag"),
    LiveCorpusRow("shell", "endpoint", "80", False, "bare_port_without_context"),
)


# --- Keeps: real operational memory the gate must preserve -------------------
_ADMIT_KEEPS: Final[tuple[LiveCorpusRow, ...]] = (
    LiveCorpusRow(
        "python", "interpreter",
        "C:/Users/x/AppData/Roaming/uv/python/cpython-3.13/python.exe",
        True, "interpreter_stem_python.exe",
    ),
    LiveCorpusRow(
        "service", "endpoint",
        "http://127.0.0.1:19836/dashboard",
        True, "known_family_endpoint_url",
    ),
    LiveCorpusRow(
        "python", "runner",
        "scripts/run.py",
        True, "known_family_non_noise",
    ),
    LiveCorpusRow(
        "python", "version",
        "3.13.14",
        True, "strict_semver",
    ),
)


LIVE_CORPUS_ROWS: Final[tuple[LiveCorpusRow, ...]] = (
    _SHELL_PATH_DROPS
    + _SHELL_REGEX_DROPS
    + _SHELL_NUMERIC_DROPS
    + _SENSITIVE_DROPS
    + _SERVICE_JUNK_DROPS
    + _ADMIT_KEEPS
)


__all__ = ["LiveCorpusRow", "LIVE_CORPUS_ROWS"]
