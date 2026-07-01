"""Derivation predicate for the `operational_fact` memory type.

Pure function of its inputs. Reads no storage, no config, no MCP, no
HTTP, no clock, no random. Given a stream of turn records and a
container reference, it emits a deterministic list of
:class:`OperationalFactCandidate` objects each of which has:

* one discovery event and one use event bound by argv-match within a
  window of :data:`DISCOVERY_TO_USE_WINDOW` turns in the same scope;
* every user-facing string passed through :func:`semantic.redaction.redact_sensitive`
  before emission;
* short (<10 char) artifacts matched via word-boundary regex to avoid
  Windows/POSIX substring false positives.

Wiring the predicate into storage, routing, and hooks is the job of
later PRs; this module deliberately imports nothing from
`storage.*`, `core.*`, `providers.*`, or `integrations.*`.

See ``docs/specs/2026-05-31-operational-fact-memory-design.md`` for the
governing design and
``.local/milestone-progress-2026-07/w4-phase0-spike-2026-07-01.md`` for
the Phase 0 evidence that shaped this predicate.
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

from semantic.redaction import redact_sensitive

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Constants (public — imported by wiring in PR 3)                             #
# --------------------------------------------------------------------------- #

DISCOVERY_TO_USE_WINDOW: Final[int] = 10
"""Maximum number of turns between a discovery event and its matching use."""

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
    """Split argv respecting simple single/double quoting.

    Not a full shell parser. Sufficient for extracting the command name
    and immediate subcommand for family + role classification.
    """
    if not cmd:
        return ()
    tokens: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in cmd:
        if quote:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
            continue
        if ch in ('"', "'"):
            quote = ch
            continue
        if ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
            continue
        buf.append(ch)
    if buf:
        tokens.append("".join(buf))
    return tuple(tokens)


def _strip_wrappers(argv: tuple[str, ...]) -> tuple[str, ...]:
    """Peel `env`, `sudo`, etc. off the front of an argv list."""
    while argv:
        head = argv[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        # Strip `env FOO=bar ...` including env-var assignments.
        if head == "env":
            argv = argv[1:]
            while argv and "=" in argv[0] and not argv[0].startswith(("-", "/", "\\", ".")):
                argv = argv[1:]
            continue
        if head in _WRAPPER_COMMANDS:
            argv = argv[1:]
            continue
        break
    return argv


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


def _normalize_argv(cmd: str) -> str:
    if not cmd:
        return ""
    # Case-fold drive letters and collapse backslashes to forward.
    s = cmd
    if len(s) >= 2 and s[1] == ":" and s[0].isalpha():
        s = s[0].upper() + s[1:]
    s = s.replace("\\", "/")
    # Collapse duplicate whitespace but preserve token boundaries.
    return re.sub(r"\s+", " ", s).strip()


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


def _artifact_matches_argv(artifact_normalized: str, argv_normalized: str) -> bool:
    if not artifact_normalized or not argv_normalized:
        return False
    if len(artifact_normalized) <= WORD_BOUNDARY_ARTIFACT_LEN_MAX:
        pattern = r"(?<!\w)" + re.escape(artifact_normalized) + r"(?!\w)"
        return re.search(pattern, argv_normalized, re.UNICODE) is not None
    return artifact_normalized in argv_normalized


# --------------------------------------------------------------------------- #
# Discovery + use extraction                                                  #
# --------------------------------------------------------------------------- #


def _extract_artifact_tokens(cmd: str, output_tail: str) -> list[str]:
    """Pull candidate artifact tokens from a discovery command.

    Returns the raw (pre-redaction) tokens; the caller normalizes and
    redacts. Order matters: paths first, then URLs, then versions.
    """
    tokens: list[str] = []
    seen: set[str] = set()

    def _push(tok: str) -> None:
        t = tok.strip().strip('"').strip("'")
        if not t:
            return
        if t in seen:
            return
        seen.add(t)
        tokens.append(t)

    # argv tokens after the command head are the primary candidates.
    argv = _strip_wrappers(_iter_argv_head(cmd))
    for tok in argv[1:]:
        if tok.startswith("-"):
            continue
        if "/" in tok or "\\" in tok or "." in tok:
            _push(tok)

    # Path / URL regexes run on output_tail only. Running them on `cmd`
    # would double-extract substrings of argv tokens already captured
    # above (e.g. argv `./target/a` + path regex `/target/a`), which
    # produces artifacts that land in different scope slots for the
    # same underlying reuse — silently over-emitting candidates.
    output_tail = output_tail or ""
    for m in _PATH_TOKEN_RE.finditer(output_tail):
        _push(m.group(0))
    for m in _URL_TOKEN_RE.finditer(cmd + " " + output_tail):
        _push(m.group(0))
    for m in _VERSION_TOKEN_RE.finditer(output_tail):
        _push(m.group(0))
    return tokens


def _make_discovery(
    tool: str,
    turn: TurnRecord,
    fragment_source: str,
    artifact_raw: str,
) -> DiscoveryEvent | None:
    normalized = _normalize_artifact(artifact_raw)
    if not normalized:
        return None
    # Reject trivial single-character or all-punctuation artifacts.
    if len(normalized) < 2:
        return None
    if not any(c.isalnum() for c in normalized):
        return None
    fragment = redact_sensitive(fragment_source)[:MAX_FRAGMENT_LEN]
    artifact_display = redact_sensitive(artifact_raw)[:MAX_ARTIFACT_LEN]
    return DiscoveryEvent(
        source_item_id=turn.source_item_id,
        tool=tool,
        turn_index=turn.turn_index,
        timestamp=turn.timestamp,
        fragment=fragment,
        artifact_raw=artifact_display,
        artifact_normalized=normalized,
    )


def _bash_discovery(turn: TurnRecord) -> list[DiscoveryEvent]:
    out: list[DiscoveryEvent] = []
    seen: set[str] = set()
    for cmd in turn.commands:
        if cmd.exit_code != 0 or not cmd.cmd:
            continue
        for token in _extract_artifact_tokens(cmd.cmd, cmd.output_tail):
            disc = _make_discovery("Bash", turn, cmd.cmd, token)
            if disc is None:
                continue
            if disc.artifact_normalized in seen:
                continue
            seen.add(disc.artifact_normalized)
            out.append(disc)
    return out


def _files_read_discovery(turn: TurnRecord) -> list[DiscoveryEvent]:
    out: list[DiscoveryEvent] = []
    seen: set[str] = set()
    for path in turn.files_read:
        if not path:
            continue
        disc = _make_discovery("Read", turn, path, path)
        if disc is None:
            continue
        if disc.artifact_normalized in seen:
            continue
        seen.add(disc.artifact_normalized)
        out.append(disc)
    return out


def _try_match_use(
    disc: DiscoveryEvent,
    turn: TurnRecord,
) -> UseEvent | None:
    if turn.turn_index == disc.turn_index:
        return None
    for cmd in turn.commands:
        if cmd.exit_code != 0 or not cmd.cmd:
            continue
        argv_norm = _normalize_argv(cmd.cmd)
        if _artifact_matches_argv(disc.artifact_normalized, argv_norm):
            return UseEvent(
                source_item_id=turn.source_item_id,
                tool="Bash",
                turn_index=turn.turn_index,
                timestamp=turn.timestamp,
                fragment=redact_sensitive(cmd.cmd)[:MAX_FRAGMENT_LEN],
            )
    return None


def _build_candidate(
    disc: DiscoveryEvent,
    use: UseEvent,
    container_ref: str,
    scope_resolver: ScopeResolver,
) -> OperationalFactCandidate | None:
    if not disc.artifact_normalized:
        return None
    scope_kind, scope_ref = scope_resolver(container_ref, disc.artifact_raw)
    family = _command_family(use.fragment, disc.artifact_normalized)
    if family == _FAMILY_FALLBACK:
        # Fall back to discovery-side family if the use argv is opaque.
        family_disc = _command_family(disc.fragment, disc.artifact_normalized)
        if family_disc != _FAMILY_FALLBACK:
            family = family_disc
    role = _derive_artifact_role(use.fragment, disc.artifact_normalized, family)
    subject = f"{family}: {disc.artifact_raw}"[:MAX_FRAGMENT_LEN]
    return OperationalFactCandidate(
        command_family=family,
        artifact_role=role,
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        subject=redact_sensitive(subject),
        artifact=disc.artifact_raw,
        artifact_normalized=disc.artifact_normalized,
        evidence=(disc, use),
    )


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
) -> list[OperationalFactCandidate]:
    """Emit operational-fact candidates from a stream of turn records.

    Pure. Same input → identical output. Ordering is deterministic by
    (discovery turn_index, artifact_normalized). Supersession, lifecycle,
    and cross-run reuse counters are the wiring layer's responsibility.
    """
    if not turn_stream:
        return []
    turns = sorted(turn_stream, key=lambda t: t.turn_index)
    open_discoveries: list[DiscoveryEvent] = []
    candidates: list[OperationalFactCandidate] = []

    for turn in turns:
        # 1. Retire discoveries older than the window.
        window_start = turn.turn_index - DISCOVERY_TO_USE_WINDOW
        open_discoveries = [d for d in open_discoveries if d.turn_index >= window_start]

        # 2. Close open discoveries against this turn's uses.
        remaining: list[DiscoveryEvent] = []
        for disc in open_discoveries:
            use = _try_match_use(disc, turn)
            if use is None:
                remaining.append(disc)
                continue
            cand = _build_candidate(disc, use, container_ref, scope_resolver)
            if cand is not None:
                candidates.append(cand)
            # Discovery closed; drop from open set.
        open_discoveries = remaining

        # 3. Emit new discoveries from this turn (bash primary + files_read secondary).
        new_bash = _bash_discovery(turn)
        new_reads = _files_read_discovery(turn)
        # Deduplicate against existing open discoveries on artifact_normalized
        already_open = {d.artifact_normalized for d in open_discoveries}
        for d in new_bash + new_reads:
            if d.artifact_normalized in already_open:
                continue
            already_open.add(d.artifact_normalized)
            open_discoveries.append(d)

    return _dedup_candidates(candidates)


__all__ = [
    "DISCOVERY_TO_USE_WINDOW",
    "WORD_BOUNDARY_ARTIFACT_LEN_MAX",
    "MAX_ARTIFACT_LEN",
    "MAX_FRAGMENT_LEN",
    "KNOWN_FAMILIES",
    "ScopeKind",
    "ScopeResolver",
    "CommandRecord",
    "TurnRecord",
    "DiscoveryEvent",
    "UseEvent",
    "OperationalFactCandidate",
    "resolve_scope",
    "build_default_scope_resolver",
    "derive_operational_facts",
]
