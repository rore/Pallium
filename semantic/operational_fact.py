"""Derivation predicate for the `operational_fact` memory type.

Pure function of its inputs. Reads no storage, no config, no MCP, no
HTTP, no clock, no random. Given a stream of turn records and a
container reference, it emits a deterministic list of
:class:`OperationalFactCandidate` objects.

PR 3 of the operational_fact redesign (2026-07-02) replaced the
discovery+use pairing model with a **reconnaissance-verb** predicate:
each candidate is emitted from a single reconnaissance event
(``which python``, ``python --version``, ``cat pyproject.toml`` etc.)
detected by :mod:`semantic.reconnaissance`. Every user-facing string
still passes through :func:`semantic.redaction.redact_sensitive` before
emission. Cross-thread recurrence — not intra-thread use-pairing — is
the durability signal (PR 4).

PR 5 (2026-07-02) removed the pre-PR-3 admission-gate machinery
(``_is_admissible_candidate``, ``_looks_like_noise``,
``_is_operational_shape_artifact``, ``_RUNNER_SUBCOMMANDS``,
``_OPERATIONAL_CONFIG_FILES``, ``_INTERPRETER_ALLOWED_STEMS``, the
argv discovery+use helpers) once callers moved fully to the
reconnaissance predicate.

Wiring the predicate into storage, routing, and hooks is the job of
later PRs; this module deliberately imports nothing from
`storage.*`, `core.*`, `providers.*`, or `integrations.*`.

See ``docs/specs/2026-05-31-operational-fact-memory-design.md`` for the
governing design.
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import re
import secrets
import socket
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Final, Literal, Sequence

from semantic.argv import (
    argv_basename as _argv_basename,
    iter_argv_head as _iter_argv_head_shared,
    shell_word_head as _shell_word_head_shared,
    strip_wrappers as _strip_wrappers_shared,
)
from semantic.redaction import is_sensitive_artifact, redact_sensitive

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Constants (public — imported by wiring in PR 3)                             #
# --------------------------------------------------------------------------- #

OPERATIONAL_FACT_TYPE: Final[str] = "operational_fact"
"""Canonical memory-type name. Single source of truth for the routing gate,
the wiring layer, and the type registry."""

WORD_BOUNDARY_ARTIFACT_LEN_MAX: Final[int] = 9
"""Artifacts with length <= this trigger a word-boundary argv match."""

MAX_ARTIFACT_LEN: Final[int] = 256
MAX_FRAGMENT_LEN: Final[int] = 300


ScopeKind = Literal["repo", "machine_repo"]
EventKind = Literal["discovery", "use"]


_FAMILY_KEYWORD_MAP: Final[dict[str, str]] = {
    "python": "python", "python3": "python", "python.exe": "python", "py": "python",
    "python3.exe": "python",
    "uv": "uv",
    "pip": "pip", "pipx": "pip",
    "node": "node", "node.exe": "node", "npx": "node", "bun": "node",
    "npm": "npm", "npm.cmd": "npm",
    "pnpm": "pnpm", "pnpm.cmd": "pnpm",
    "yarn": "yarn", "yarn.cmd": "yarn",
    "cargo": "cargo",
    "go": "go",
    "gradle": "gradle", "gradlew": "gradle", "gradlew.bat": "gradle",
    "docker": "docker", "docker-compose": "docker", "podman": "docker",
    "git": "git", "git.exe": "git",
    "make": "make",
    "curl": "service", "wget": "service", "httpie": "service",
    "psql": "service", "mongo": "service", "redis-cli": "service",
    "systemctl": "service", "sc": "service", "sc.exe": "service",
    "pytest": "python", "poetry": "python", "hatch": "python",
}

KNOWN_FAMILIES: Final[frozenset[str]] = frozenset({
    "python", "node", "npm", "pnpm", "yarn", "uv", "pip",
    "cargo", "go", "gradle", "docker", "git", "make", "service", "shell",
})

_FAMILY_FALLBACK: Final[str] = "shell"

_WRAPPER_COMMANDS: Final[frozenset[str]] = frozenset({
    "env", "sudo", "time", "xargs", "nice", "nohup", "exec",
})
# NOTE: the shell-tokenizer primitives (_iter_argv_head, _shell_word_head,
# _strip_wrappers) were extracted to ``semantic/argv.py`` in PR 3 of the
# operational_fact redesign (2026-07-02) so ``semantic/reconnaissance.py``
# uses the SAME logic. The local names below preserve backward
# compatibility for tests and downstream callers; they are thin wrappers.

# Argv-shape → artifact-role heuristics (see design doc §Deduplication)
_INTERPRETER_SUFFIXES: Final[tuple[str, ...]] = (
    "python", "python.exe", "python3", "python3.exe", "node", "node.exe",
)


# --------------------------------------------------------------------------- #
# Regexes for artifact-token extraction (NOT for redaction — see semantic/redaction.py)
# --------------------------------------------------------------------------- #

_PATH_TOKEN_RE: Final = re.compile(r"(?:[A-Za-z]:)?[/\\][\w./\\-]+")
_VERSION_TOKEN_RE: Final = re.compile(r"\b\d+\.\d+(?:\.\d+)?(?:[-+][\w.]+)?\b")
_URL_TOKEN_RE: Final = re.compile(r"https?://[^\s\"']+")
_PORT_TOKEN_RE: Final = re.compile(r"^:?\d{2,5}$")


# --------------------------------------------------------------------------- #
# Public dataclasses                                                          #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CommandRecord:
    """One command extracted from ``agent_work_trace_turn.commands``."""

    cmd: str
    exit_code: int | None = None
    output_tail: str = ""
    failure_class: str = ""


@dataclass(frozen=True)
class TurnRecord:
    """A single turn's structural evidence.

    The predicate reads nothing else: no LLM output, no thread text, no
    routing context.
    """

    turn_index: int
    source_item_id: str
    timestamp: str = ""
    commands: tuple[CommandRecord, ...] = ()
    files_read: tuple[str, ...] = ()
    files_modified: tuple[str, ...] = ()
    grep_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiscoveryEvent:
    source_item_id: str
    tool: str
    turn_index: int
    timestamp: str
    fragment: str
    artifact_raw: str
    artifact_normalized: str
    kind: Literal["discovery"] = "discovery"


@dataclass(frozen=True)
class UseEvent:
    source_item_id: str
    tool: str
    turn_index: int
    timestamp: str
    fragment: str
    kind: Literal["use"] = "use"


@dataclass(frozen=True)
class OperationalFactCandidate:
    """A derived candidate. Lifecycle / reuse_count / supersedes are
    populated by the wiring layer (PR 3), not by the predicate.
    """

    command_family: str
    artifact_role: str
    scope_kind: ScopeKind
    scope_ref: str
    subject: str
    artifact: str
    artifact_normalized: str
    evidence: tuple[DiscoveryEvent | UseEvent, ...]


ScopeResolver = Callable[[str, str | None], tuple[ScopeKind, str]]


# --------------------------------------------------------------------------- #
# Scope resolver — salted machine hash, cached at first call                  #
# --------------------------------------------------------------------------- #


# Module-level ephemeral fallback salt. Computed once at import time so
# the salt survives lru_cache.cache_clear() during tests and honors the
# design's "cached at service start" determinism guarantee for the
# OSError-fallback branch.
_EPHEMERAL_FALLBACK_SALT: Final[str] = secrets.token_hex(16)


@lru_cache(maxsize=1)
def _load_machine_hash_salt() -> str:
    """Load the per-installation salt.

    Precedence:
    1. ``PALLIUM_MACHINE_HASH_SALT`` environment variable (non-empty).
    2. ``~/.pallium/machine_salt`` (auto-generated on first read; never
       overwritten if the file exists).
    3. Module-level ephemeral salt (fallback if home is not writable).
    """
    env = os.environ.get("PALLIUM_MACHINE_HASH_SALT")
    if env is not None:
        if env == "":
            logger.warning(
                "operational_fact: PALLIUM_MACHINE_HASH_SALT is set but empty; "
                "falling back to on-disk salt"
            )
        else:
            return env
    salt_path = Path.home() / ".pallium" / "machine_salt"
    try:
        if salt_path.exists():
            # Never overwrite an existing salt file, even if it's
            # currently blank — an unexpected rewrite would silently
            # break scope determinism for prior derived facts. Fall
            # through to ephemeral instead.
            content = salt_path.read_text(encoding="utf-8").strip()
            if content:
                return content
            logger.warning(
                "operational_fact: %s exists but is empty; using ephemeral salt",
                salt_path,
            )
            return _EPHEMERAL_FALLBACK_SALT
        salt_path.parent.mkdir(parents=True, exist_ok=True)
        new_salt = secrets.token_hex(16)
        salt_path.write_text(new_salt, encoding="utf-8")
        return new_salt
    except OSError:
        logger.warning(
            "operational_fact: could not read/write %s; using ephemeral salt",
            salt_path,
        )
        # Stable within this process. Predicate purity holds even if
        # tests call cache_clear() and re-enter this branch.
        return _EPHEMERAL_FALLBACK_SALT


def _safe_hostname() -> str:
    try:
        name = socket.gethostname()
        if name:
            return name
    except OSError:
        pass
    try:
        node = platform.node()
        if node:
            return node
    except OSError:
        pass
    logger.warning("operational_fact: hostname resolution failed; using 'unknown-host'")
    return "unknown-host"


@lru_cache(maxsize=1)
def _default_machine_hash_provider() -> str:
    """Compute salted SHA-256 of hostname + platform. Cached once per process."""
    salt = _load_machine_hash_salt()
    material = f"{salt}|{_safe_hostname()}|{platform.system()}|{platform.machine()}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _is_repo_relative(path: str | None) -> bool:
    if not path:
        return False
    s = path.strip()
    if not s:
        return False
    # Windows drive letter
    if len(s) >= 2 and s[1] == ":" and s[0].isalpha():
        return False
    # POSIX absolute
    if s.startswith("/") or s.startswith("~"):
        return False
    # Common absolute markers in argv text
    lowered = s.lower()
    absolute_markers = ("/.venv/", "\\.venv\\", "/home/", "\\users\\", "/root/")
    if any(m in lowered for m in absolute_markers):
        return False
    return True


def resolve_scope(
    container_ref: str,
    artifact_path: str | None,
    machine_hash_provider: Callable[[], str],
) -> tuple[ScopeKind, str]:
    """Resolve ``(scope_kind, scope_ref)`` for a candidate artifact.

    Repo-relative artifacts → ``("repo", container_ref)``.
    Everything else → ``("machine_repo", "<container_ref>@machine:<hash>")``.
    """
    if _is_repo_relative(artifact_path):
        return ("repo", container_ref)
    return ("machine_repo", f"{container_ref}@machine:{machine_hash_provider()}")


def build_default_scope_resolver(
    machine_hash_provider: Callable[[], str] | None = None,
) -> ScopeResolver:
    """Return a :data:`ScopeResolver` bound to a machine-hash provider.

    The default provider hashes the salted hostname + platform tuple
    exactly once per process.
    """
    provider = machine_hash_provider or _default_machine_hash_provider

    def _resolver(container_ref: str, artifact_path: str | None) -> tuple[ScopeKind, str]:
        return resolve_scope(container_ref, artifact_path, provider)

    return _resolver


# --------------------------------------------------------------------------- #
# Argv / artifact helpers                                                     #
# --------------------------------------------------------------------------- #


def _iter_argv_head(cmd: str) -> tuple[str, ...]:
    """Thin wrapper around :func:`semantic.argv.iter_argv_head`.

    Preserved as a private name for backward compatibility with tests
    and downstream callers that imported the internal API before the
    PR 3 extraction to :mod:`semantic.argv`.
    """
    return _iter_argv_head_shared(cmd)


def _shell_word_head(cmd: str) -> str:
    """Thin wrapper around :func:`semantic.argv.shell_word_head`."""
    return _shell_word_head_shared(cmd)


def _strip_wrappers(argv: tuple[str, ...]) -> tuple[str, ...]:
    """Thin wrapper around :func:`semantic.argv.strip_wrappers`."""
    return _strip_wrappers_shared(argv)


def _command_family(cmd: str, artifact: str) -> str:
    argv = _strip_wrappers(_iter_argv_head(cmd))
    if not argv:
        return _FAMILY_FALLBACK
    head = argv[0]
    base = head.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    return _FAMILY_KEYWORD_MAP.get(base, _FAMILY_FALLBACK)


def _derive_artifact_role(cmd: str, artifact: str, family: str) -> str:
    lowered = artifact.lower()
    if any(lowered.endswith(sfx) or lowered.endswith(sfx + ".exe") for sfx in _INTERPRETER_SUFFIXES):
        return "interpreter"
    if ".venv" in lowered and not lowered.endswith((".exe", ".py")):
        return "venv"
    if _VERSION_TOKEN_RE.fullmatch(artifact):
        return "version"
    if _URL_TOKEN_RE.match(artifact) or _PORT_TOKEN_RE.fullmatch(artifact):
        return "endpoint"
    argv = _strip_wrappers(_iter_argv_head(cmd))
    if len(argv) >= 2 and family in {"npm", "pnpm", "yarn"} and argv[1].lower() == "run":
        return "task"
    if family in {"python", "uv", "node", "cargo", "go", "gradle", "make", "pip", "npm", "pnpm", "yarn"}:
        return "runner"
    return "path"


def _normalize_artifact(raw: str) -> str:
    if not raw:
        return ""
    redacted = redact_sensitive(raw)
    s = redacted.strip()
    if not s:
        return ""
    # POSIX-normalize slashes; case-fold drive letters.
    if len(s) >= 2 and s[1] == ":" and s[0].isalpha():
        s = s[0].upper() + s[1:]
    s = s.replace("\\", "/")
    # Strip a leading `./` so `./gradlew` and `gradlew` match.
    if s.startswith("./"):
        s = s[2:]
    if len(s) > MAX_ARTIFACT_LEN:
        s = s[:MAX_ARTIFACT_LEN]
    return s


# --------------------------------------------------------------------------- #
# Candidate ranking / dedup / cap                                             #
# --------------------------------------------------------------------------- #


MAX_CANDIDATES_PER_REBUILD: Final[int] = 5


@dataclass(frozen=True)
class AdmissionDiagnostics:
    """Counters describing candidate flow through the predicate.

    Semantics:

    - ``admitted`` — number of candidates in the returned list AFTER
      dedup and per-thread cap. This is the count callers see.
    - ``capped`` — number of admitted-and-deduped candidates dropped
      by the per-thread cap.

    PR 5 (2026-07-02) removed the pre-PR-3 shape/family fallback
    counters (``fallback_family``, ``non_operational_shape``): the
    reconnaissance predicate does not have those rejection channels,
    so the counters were always zero from PR 3 onward.
    """

    admitted: int = 0
    capped: int = 0


_HIGH_VALUE_FAMILIES: Final[frozenset[str]] = frozenset({
    "python", "uv", "node", "npm", "pnpm", "yarn",
    "cargo", "go", "gradle", "docker", "make",
})


_ROLE_SPECIFICITY: Final[dict[str, int]] = {
    "interpreter": 0,
    "runner": 1,
    "endpoint": 2,
    "version": 3,
    "task": 4,
    "path": 5,
    "venv": 6,
}


def _rank_candidates_for_cap(
    cands: list[OperationalFactCandidate],
) -> list[OperationalFactCandidate]:
    """Deterministic ranking for the per-thread cap.

    Preference order:
      1. Known high-value family (python/uv/npm/... over service/shell).
      2. Specific role (interpreter > runner > endpoint > version > path).
      3. Earlier discovery turn (stable within a run).
      4. Artifact-normalized string (final tiebreak, deterministic).
    """
    def _key(c: OperationalFactCandidate) -> tuple:
        family_rank = 0 if c.command_family in _HIGH_VALUE_FAMILIES else 1
        role_rank = _ROLE_SPECIFICITY.get(c.artifact_role, 99)
        turn_rank = c.evidence[0].turn_index if c.evidence else 0
        return (family_rank, role_rank, turn_rank, c.artifact_normalized)

    return sorted(cands, key=_key)


def _dedup_candidates(
    candidates: list[OperationalFactCandidate],
) -> list[OperationalFactCandidate]:
    """Collapse candidates with identical (family, role, scope, artifact_norm).

    Different ``artifact_normalized`` values in the same conflict slot are
    kept side-by-side; supersession is the wiring layer's responsibility
    (PR 3) because it needs cross-run DB state to decide precedence.
    """
    seen: dict[tuple[str, str, str, str, str], OperationalFactCandidate] = {}
    for cand in candidates:
        key = (
            cand.command_family,
            cand.artifact_role,
            cand.scope_kind,
            cand.scope_ref,
            cand.artifact_normalized,
        )
        if key not in seen:
            seen[key] = cand
    result = list(seen.values())
    result.sort(
        key=lambda c: (
            c.evidence[0].turn_index if c.evidence else 0,
            c.artifact_normalized,
        )
    )
    return result


# --------------------------------------------------------------------------- #
# Public entry point                                                          #
# --------------------------------------------------------------------------- #


def derive_operational_facts(
    turn_stream: Sequence[TurnRecord],
    container_ref: str,
    scope_resolver: ScopeResolver,
    *,
    return_diagnostics: bool = False,
) -> list[OperationalFactCandidate] | tuple[list[OperationalFactCandidate], AdmissionDiagnostics]:
    """Emit operational-fact candidates from a stream of turn records.

    Pure. Same input → identical output. Ordering is deterministic by
    (turn_index, artifact_normalized). Lifecycle promotion (candidate →
    active) is the wiring layer's responsibility (PR 4).

    PR 3 of the operational_fact redesign (2026-07-02) replaced the
    discovery+use pairing model with a **reconnaissance-verb** model:
    each candidate is emitted directly from a reconnaissance event
    (``which python``, ``python --version``, ``cat pyproject.toml``,
    ``ls src/``, etc.) via the closed verb set in
    :mod:`semantic.reconnaissance`. Cross-thread recurrence — not
    intra-thread use-pairing — is the durability signal (see PR 4).

    ``return_diagnostics`` — opt-in. When True, returns
    ``(candidates, AdmissionDiagnostics)``.
    """
    # Local import to keep the module import cycle acyclic — the
    # reconnaissance module depends on this one for CommandRecord/
    # TurnRecord types.
    from semantic.reconnaissance import (
        ReconnaissanceEvent,
        detect_reconnaissance,
    )

    if not turn_stream:
        if return_diagnostics:
            return [], AdmissionDiagnostics()
        return []
    turns = sorted(turn_stream, key=lambda t: t.turn_index)
    raw_candidates: list[OperationalFactCandidate] = []

    for turn in turns:
        for event in detect_reconnaissance(turn):
            cand = _recon_event_to_candidate(event, container_ref, scope_resolver)
            if cand is not None:
                raw_candidates.append(cand)

    # Dedup on the conflict slot. Two reconnaissance events for the
    # same slot in the same thread collapse — the recurrence gate at
    # promotion time (PR 4) counts distinct THREADS, not distinct
    # events, so intra-thread duplication doesn't help.
    deduped = _dedup_candidates(raw_candidates)

    # Per-thread cap. Same ranking heuristic as before; preserves
    # deterministic tie-breaks.
    capped_count = 0
    if len(deduped) > MAX_CANDIDATES_PER_REBUILD:
        ranked = _rank_candidates_for_cap(deduped)
        kept = set(id(c) for c in ranked[:MAX_CANDIDATES_PER_REBUILD])
        capped_count = len(deduped) - MAX_CANDIDATES_PER_REBUILD
        deduped = [c for c in deduped if id(c) in kept]

    if return_diagnostics:
        return deduped, AdmissionDiagnostics(
            admitted=len(deduped),
            capped=capped_count,
        )
    return deduped


def _recon_event_to_candidate(
    event: "ReconnaissanceEvent",  # noqa: F821 — imported lazily above
    container_ref: str,
    scope_resolver: ScopeResolver,
) -> OperationalFactCandidate | None:
    """Map a :class:`ReconnaissanceEvent` to an
    :class:`OperationalFactCandidate`.

    Sourced from PR 3 of the operational_fact redesign. Replaces
    ``_build_candidate`` which paired a discovery with a use event —
    the new model emits directly from a single reconnaissance verb.
    """
    # The "answer" the recon event captured (interpreter path, semver,
    # config-anchor basename, host:port) is the durable artifact when
    # available; else fall back to the target.
    artifact_raw = event.discovered_value or event.target
    if not artifact_raw:
        return None
    artifact_normalized = _normalize_artifact(artifact_raw)
    if not artifact_normalized:
        return None
    # Sensitive-artifact skip — belt-and-braces with the reconnaissance
    # module's own SENSITIVE_ANCHOR_BASENAMES filter and PR 0's
    # redaction pipeline. If any of these three layers miss, we still
    # want the artifact rejected before it lands in storage.
    if is_sensitive_artifact(artifact_normalized, context=event.fragment):
        return None
    if is_sensitive_artifact(artifact_raw, context=event.fragment):
        return None
    # Reject trivial single-character or all-punctuation artifacts.
    if len(artifact_normalized) < 2:
        return None
    if not any(c.isalnum() for c in artifact_normalized):
        return None

    scope_kind, scope_ref = scope_resolver(container_ref, artifact_raw)
    family = _family_for_verb(event, artifact_normalized)
    role = _role_for_verb(event, artifact_normalized, family)
    subject = f"{family}: {artifact_raw}"[:MAX_FRAGMENT_LEN]

    # Build a DiscoveryEvent as evidence so downstream serializers that
    # inspect ``cand.evidence[i].kind == "discovery"`` continue to
    # work. The evidence carries the reconnaissance verb via the
    # fragment prefix in the memory payload dict — see
    # ``_candidate_to_memory_object`` in ``semantic/agent_work_trace.py``.
    disc = DiscoveryEvent(
        source_item_id=event.source_item_id,
        tool=event.tool,
        turn_index=event.turn_index,
        timestamp=event.timestamp,
        fragment=event.fragment,
        artifact_raw=artifact_raw[:MAX_ARTIFACT_LEN],
        artifact_normalized=artifact_normalized,
    )
    return OperationalFactCandidate(
        command_family=family,
        artifact_role=role,
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        subject=redact_sensitive(subject),
        artifact=artifact_raw[:MAX_ARTIFACT_LEN],
        artifact_normalized=artifact_normalized,
        evidence=(disc,),
    )


def _family_for_verb(event: "ReconnaissanceEvent", artifact_norm: str) -> str:  # noqa: F821
    """Best-effort command_family classification for a recon event.

    The verb determines the general shape; ``_FAMILY_KEYWORD_MAP``
    handles known ecosystems. Unknown targets get their basename as
    the family — that's the ecosystem-agnostic path (Test 4a).
    """
    verb = event.verb
    if verb in ("port_probe",):
        return "service"
    if verb in ("file_read_recon", "cat_config_recon"):
        # Family drives from the anchor basename category so recall
        # queries like "how do I run tests" still hit the right slot.
        base = event.target.lower()
        for prefix in ("pyproject", "requirements", "poetry", "pipfile", ".python", "uv."):
            if base.startswith(prefix):
                return "python"
        for prefix in ("package.json", "package-lock", "pnpm-lock", "yarn", ".nvmrc", ".node", "tsconfig", "jsconfig"):
            if base.startswith(prefix):
                return "node"
        if base.startswith("cargo"):
            return "cargo"
        if base.startswith("go."):
            return "go"
        if base in {"makefile", "gnumakefile", "justfile"}:
            return "make"
        if base.startswith(("docker", "compose", "container")):
            return "docker"
        if base.startswith(("build.gradle", "gradlew", "settings.gradle")):
            return "gradle"
        return _FAMILY_FALLBACK
    # command_lookup / version_query / help_query — target IS the tool
    # basename. Consult the family-keyword map first.
    target = event.target.lower()
    if target in _FAMILY_KEYWORD_MAP:
        return _FAMILY_KEYWORD_MAP[target]
    # Also check with .exe stripped.
    if target.endswith(".exe") and target[:-4] in _FAMILY_KEYWORD_MAP:
        return _FAMILY_KEYWORD_MAP[target[:-4]]
    if verb == "directory_probe":
        return _FAMILY_FALLBACK
    # Unknown tool — use its own name as the family. Ecosystem-agnostic
    # admission: xyzlang → family="xyzlang". The recurrence gate in
    # PR 4 filters out one-off / noise families by requiring cross-
    # thread recurrence for promotion. Strip .exe unconditionally on
    # this branch so ``which xyzlang`` and ``which xyzlang.exe``
    # collapse to the same family — otherwise mixed POSIX/Windows
    # fleets silently break the recurrence counter.
    if target.endswith(".exe"):
        target = target[:-4]
    return target or _FAMILY_FALLBACK


def _role_for_verb(event: "ReconnaissanceEvent", artifact_norm: str, family: str) -> str:  # noqa: F821
    """Best-effort artifact_role classification for a recon event."""
    verb = event.verb
    if verb == "version_query":
        return "version"
    if verb == "port_probe":
        return "endpoint"
    if verb == "command_lookup":
        # If the discovered_value looks like an interpreter path,
        # role=interpreter; else role=runner.
        low = artifact_norm.lower()
        for sfx in _INTERPRETER_SUFFIXES:
            if low.endswith(sfx) or low.endswith(sfx + ".exe"):
                return "interpreter"
        return "runner"
    if verb in ("file_read_recon", "cat_config_recon"):
        return "config"
    if verb == "help_query":
        return "help"
    if verb == "directory_probe":
        return "path"
    return "path"


__all__ = [
    "OPERATIONAL_FACT_TYPE",
    "WORD_BOUNDARY_ARTIFACT_LEN_MAX",
    "MAX_ARTIFACT_LEN",
    "MAX_FRAGMENT_LEN",
    "MAX_CANDIDATES_PER_REBUILD",
    "KNOWN_FAMILIES",
    "ScopeKind",
    "ScopeResolver",
    "CommandRecord",
    "TurnRecord",
    "DiscoveryEvent",
    "UseEvent",
    "OperationalFactCandidate",
    "AdmissionDiagnostics",
    "resolve_scope",
    "build_default_scope_resolver",
    "derive_operational_facts",
]
