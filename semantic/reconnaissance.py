"""Reconnaissance-verb predicates for the operational_fact redesign.

Design (from PR 3 of the plan
``C:\\Users\\I347041\\.claude\\plans\\noble-brewing-squid.md``):

The operational_fact type answers reconnaissance questions a fresh
agent asks when arriving in a repo/machine — interpreter, test runner,
service port, wrapper script, config anchor, etc. This module defines
the closed set of reconnaissance verbs a fresh session executes to
discover those answers.

Seven predicates:

1. ``command_lookup`` — ``which``, ``where``, ``type``, ``command -v``.
2. ``version_query`` — ``--version`` / ``-V`` / ``--ver`` invocation.
3. ``help_query`` — ``--help`` / ``-h`` / ``-?`` invocation.
4. ``port_probe`` — ``curl -sI``, ``wget --spider``, ``nc -z``.
5. ``file_read_recon`` — ``Read`` tool events against config anchors.
6. ``cat_config_recon`` — ``cat <path>`` where path basename is a
   config anchor.
7. ``directory_probe`` — ``ls``, ``stat``, ``find``, ``test -f/-e/…``.

The verb set is ecosystem-agnostic: a new interpreter, package manager,
or service tool doesn't invent new reconnaissance verbs, so this module
doesn't need per-tool changes when a new ecosystem shows up. That is
the load-bearing property the redesign turns on.

Every predicate is pure: no clock, no random, no state. Given a
``CommandRecord`` (or a ``TurnRecord`` for file-read events) it either
returns a :class:`ReconnaissanceEvent` or ``None``. Callers dispatch
via :func:`detect_reconnaissance`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Final, Literal

from semantic.argv import (
    argv_basename,
    iter_argv_head,
    shell_word_head,
    strip_wrappers,
)
from semantic.operational_fact import CommandRecord, TurnRecord
from semantic.redaction import redact_sensitive


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


ReconVerb = Literal[
    "command_lookup",
    "version_query",
    "help_query",
    "port_probe",
    "file_read_recon",
    "cat_config_recon",
    "directory_probe",
]


@dataclass(frozen=True)
class ReconnaissanceEvent:
    """A single reconnaissance action a session took.

    Emitted by the verb predicates in this module. Downstream code in
    :mod:`semantic.operational_fact` maps these to
    :class:`OperationalFactCandidate` rows with ``lifecycle="candidate"``.

    Fields:

    - ``verb`` — which predicate fired.
    - ``tool`` — the surface (``Bash`` or ``Read``) the event was
      observed on. Auxiliary; downstream logic keys on ``verb``.
    - ``turn_index`` / ``source_item_id`` / ``timestamp`` — provenance,
      passed through from the source :class:`TurnRecord`.
    - ``target`` — the argv/file target the agent looked up. Pre-
      normalization but redaction-safe (redacted before store).
    - ``discovered_value`` — the answer captured from ``output_tail``
      when the predicate was able to extract one (e.g. interpreter
      path for ``command_lookup``, semver for ``version_query``).
      Empty string when unavailable.
    - ``fragment`` — the raw command/file text used as evidence,
      truncated and redacted before store.
    """

    verb: ReconVerb
    tool: Literal["Bash", "Read"]
    turn_index: int
    source_item_id: str
    timestamp: str
    target: str
    discovered_value: str
    fragment: str


# ---------------------------------------------------------------------------
# Config-anchor allowlist (public API)
# ---------------------------------------------------------------------------

# Basenames a fresh agent would typically look at to answer
# "how does this repo work?" — the reconnaissance surface for
# file_read_recon and cat_config_recon. All entries are lowercased at
# module-load time so callers can pass raw basenames without .lower()
# guards. See :func:`is_config_anchor`.
_RAW_CONFIG_ANCHORS: Final[frozenset[str]] = frozenset({
    # Python
    "pyproject.toml",
    "requirements.txt", "requirements-dev.txt", "poetry.lock", "uv.lock",
    "Pipfile", "Pipfile.lock",
    ".python-version",
    # JavaScript / Node
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    ".nvmrc", ".node-version",
    "tsconfig.json", "jsconfig.json",
    # Rust
    "Cargo.toml", "Cargo.lock",
    # Go
    "go.mod", "go.sum",
    # JVM
    "gradlew", "gradlew.bat",
    "build.gradle", "build.gradle.kts", "settings.gradle",
    "pom.xml",
    # Docker / containers
    "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
    "Dockerfile", "Containerfile",
    # Make / task runners
    "Makefile", "makefile", "GNUmakefile",
    "justfile", "Justfile",
    # Multi-tool / meta
    ".tool-versions",
    # Env examples (never .env — those are sensitive; see below)
    ".env.example", ".env.sample",
    # Documentation anchors — fresh agents read READMEs and agent
    # instruction files first.
    "README.md", "README.rst", "README", "README.txt",
    "AGENTS.md", "CLAUDE.md",
})

CONFIG_ANCHOR_BASENAMES: Final[frozenset[str]] = frozenset(
    name.lower() for name in _RAW_CONFIG_ANCHORS
)

# Basenames that are structurally config-shaped but hold secrets. A
# reconnaissance predicate must NEVER emit an event referencing one of
# these — belt-and-braces with the redaction layer in PR 0. If a
# future contributor adds a .env-adjacent file to the allowlist above,
# adding the same basename here suppresses reconnaissance emission
# without touching downstream logic.
SENSITIVE_ANCHOR_BASENAMES: Final[frozenset[str]] = frozenset({
    ".env", ".env.local", ".env.production", ".env.development",
    ".env.staging", ".env.test",
    ".envrc",  # direnv
    ".netrc", "_netrc",
    ".pgpass",
    "credentials", "credentials.json",
    "id_rsa", "id_ed25519", "id_ecdsa",
    "secrets.yaml", "secrets.yml", "secrets.json",
})


def is_config_anchor(basename: str) -> bool:
    """Return True if ``basename`` is a config-anchor a fresh agent
    would typically read for reconnaissance.

    Case-insensitive. Returns False for sensitive files even if their
    basename would otherwise match — see
    :data:`SENSITIVE_ANCHOR_BASENAMES`.
    """
    if not basename:
        return False
    low = basename.lower()
    if low in SENSITIVE_ANCHOR_BASENAMES:
        return False
    return low in CONFIG_ANCHOR_BASENAMES


def _is_sensitive_anchor(basename: str) -> bool:
    if not basename:
        return False
    return basename.lower() in SENSITIVE_ANCHOR_BASENAMES


# ---------------------------------------------------------------------------
# Fragment / target helpers
# ---------------------------------------------------------------------------

_MAX_FRAGMENT_LEN: Final[int] = 300
_MAX_TARGET_LEN: Final[int] = 256


def _make_fragment(text: str) -> str:
    return redact_sensitive(text or "")[:_MAX_FRAGMENT_LEN]


def _make_target(text: str) -> str:
    return redact_sensitive(text or "")[:_MAX_TARGET_LEN]


def _basename(path: str) -> str:
    if not path:
        return ""
    # Strip surrounding quotes if present.
    p = path.strip().strip('"').strip("'")
    # Handle POSIX and Windows separators uniformly.
    return p.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


# ---------------------------------------------------------------------------
# 1. command_lookup — which / where / type / command -v
# ---------------------------------------------------------------------------


_LOOKUP_HEADS: Final[frozenset[str]] = frozenset({
    "which", "where", "type",
})


def match_command_lookup(
    command: CommandRecord, turn: TurnRecord,
) -> ReconnaissanceEvent | None:
    argv = strip_wrappers(iter_argv_head(command.cmd))
    if not argv:
        return None
    head_base = argv_basename(argv[0])
    # ``command -v <target>`` requires the -v flag (POSIX). Bare
    # ``command`` alone is used to bypass shell functions; not lookup.
    if head_base == "command":
        if len(argv) < 3 or argv[1] != "-v":
            return None
        target_raw = argv[2]
    elif head_base in _LOOKUP_HEADS:
        if len(argv) < 2:
            return None
        target_raw = argv[1]
    else:
        return None
    # Skip flag targets (``which -a``); those are meta, not queries.
    if target_raw.startswith("-"):
        return None
    target = _make_target(target_raw)
    if not target:
        return None
    # Discovered value = first non-empty output line if it looks like
    # a filesystem path (which/where output). For ``type``, the output
    # is "prog is /path/to/prog" — pick the last token on the line.
    discovered = _extract_lookup_answer(command.output_tail, head_base, target)
    return ReconnaissanceEvent(
        verb="command_lookup",
        tool="Bash",
        turn_index=turn.turn_index,
        source_item_id=turn.source_item_id,
        timestamp=turn.timestamp,
        target=target,
        discovered_value=_make_target(discovered),
        fragment=_make_fragment(command.cmd),
    )


def _extract_lookup_answer(output_tail: str, head_base: str, target: str) -> str:
    if not output_tail:
        return ""
    for line in output_tail.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if head_base == "type":
            # "prog is /path/to/prog" or "prog is aliased to ..."
            tokens = stripped.split()
            if tokens and (tokens[-1].startswith("/") or _looks_windows_path(tokens[-1])):
                return tokens[-1]
            continue
        # which/where/command -v: first line is the path
        if stripped.startswith("/") or _looks_windows_path(stripped):
            return stripped
    return ""


def _looks_windows_path(s: str) -> bool:
    return len(s) >= 3 and s[1] == ":" and s[2] in ("/", "\\") and s[0].isalpha()


# ---------------------------------------------------------------------------
# 2. version_query — --version / -V / --ver
# ---------------------------------------------------------------------------


_VERSION_FLAGS: Final[frozenset[str]] = frozenset({
    "--version", "-V", "--ver",
})

# Strict 3-part semver-like regex. Bounded major (<100) rules out
# stray IPv4 octets in prose, though the IPv4 disqualifier below is
# the actual guard. `[-+][\w.]+` accepts pre-release/build metadata.
_SEMVER_RE: Final = re.compile(r"\b\d{1,2}\.\d+\.\d+(?:[-+][\w.]+)?\b")
_IPV4_RE: Final = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def match_version_query(
    command: CommandRecord, turn: TurnRecord,
) -> ReconnaissanceEvent | None:
    argv = strip_wrappers(iter_argv_head(command.cmd))
    if not argv:
        return None
    # A version flag must appear in argv (excluding argv[0] which is
    # the program name). Order-independent.
    has_flag = any(tok in _VERSION_FLAGS for tok in argv[1:])
    if not has_flag:
        return None
    target = argv_basename(argv[0])
    # Strip trailing .exe for the target (family classification key).
    if target.endswith(".exe"):
        target = target[:-4]
    if not target:
        return None
    discovered = _extract_semver(command.output_tail, target)
    return ReconnaissanceEvent(
        verb="version_query",
        tool="Bash",
        turn_index=turn.turn_index,
        source_item_id=turn.source_item_id,
        timestamp=turn.timestamp,
        target=_make_target(target),
        discovered_value=_make_target(discovered),
        fragment=_make_fragment(command.cmd),
    )


def _extract_semver(output_tail: str, cmd_basename: str) -> str:
    """Pull a 3-part semver from ``output_tail``.

    Line-scoped: only consider lines that mention the word "version"
    or the command basename. This rejects unrelated 3-part numbers
    elsewhere (timestamps, sizes, unrelated log noise).

    IPv4-guarded: rejects the 3-part suffix of a 4-octet address
    (e.g. ``0.0.1`` matched from ``127.0.0.1``) by checking that the
    candidate isn't preceded by a leading digit-dot octet in the line.
    """
    if not output_tail:
        return ""
    cmd_lc = cmd_basename.lower()
    for line in output_tail.splitlines():
        lc = line.lower()
        if "version" not in lc and cmd_lc and cmd_lc not in lc:
            continue
        for m in _SEMVER_RE.finditer(line):
            candidate = m.group(0)
            # IPv4 disqualifier: reject 4-octet shapes like 127.0.0.1
            # that the 3-part regex would otherwise match a prefix of.
            if _IPV4_RE.match(candidate):
                continue
            # Reject if the candidate is a 3-octet SUFFIX of a 4-octet
            # IPv4 elsewhere in the line — e.g. "0.0.1" matched from
            # "127.0.0.1". Look for `\d{1,3}\.<candidate>` immediately
            # preceding it.
            start = m.start()
            prefix = line[max(0, start - 6):start]
            if re.search(r"\b\d{1,3}\.$", prefix):
                continue
            # Reject if the candidate is a 3-octet PREFIX of a 4-octet
            # IPv4: <candidate>.<octet>.
            if re.search(rf"\b{re.escape(candidate)}\.\d{{1,3}}\b", line):
                continue
            return candidate
    return ""


# ---------------------------------------------------------------------------
# 3. help_query — --help / -h / -?
# ---------------------------------------------------------------------------


_HELP_FLAGS: Final[frozenset[str]] = frozenset({
    "--help", "-h", "-?",
})


def match_help_query(
    command: CommandRecord, turn: TurnRecord,
) -> ReconnaissanceEvent | None:
    argv = strip_wrappers(iter_argv_head(command.cmd))
    if not argv:
        return None
    has_flag = any(tok in _HELP_FLAGS for tok in argv[1:])
    if not has_flag:
        return None
    target = argv_basename(argv[0])
    if target.endswith(".exe"):
        target = target[:-4]
    if not target:
        return None
    return ReconnaissanceEvent(
        verb="help_query",
        tool="Bash",
        turn_index=turn.turn_index,
        source_item_id=turn.source_item_id,
        timestamp=turn.timestamp,
        target=_make_target(target),
        discovered_value="",
        fragment=_make_fragment(command.cmd),
    )


# ---------------------------------------------------------------------------
# 4. port_probe — curl -sI / wget --spider / nc -z
# ---------------------------------------------------------------------------


_PROBE_HEADS: Final[frozenset[str]] = frozenset({
    "curl", "wget", "nc", "netcat",
})

_PROBE_FLAG_MAP: Final[dict[str, frozenset[str]]] = {
    # curl HEAD probe: -sI, -I, -s -I; --head; -s -I combined
    "curl": frozenset({"-sI", "-Is", "-I", "--head"}),
    "wget": frozenset({"--spider"}),
    "nc": frozenset({"-z"}),
    "netcat": frozenset({"-z"}),
}

# Match host:port in a URL or a bare host+port pair.
_URL_HOST_PORT_RE: Final = re.compile(r"://([^/\s:]+)(?::(\d{2,5}))?")


def match_port_probe(
    command: CommandRecord, turn: TurnRecord,
) -> ReconnaissanceEvent | None:
    argv = strip_wrappers(iter_argv_head(command.cmd))
    if not argv:
        return None
    head_base = argv_basename(argv[0])
    if head_base not in _PROBE_HEADS:
        return None
    allowed_flags = _PROBE_FLAG_MAP.get(head_base, frozenset())
    tail = argv[1:]
    # curl accepts combined short flags like `-sI` OR split `-s -I`.
    matched = any(tok in allowed_flags for tok in tail)
    if not matched and head_base == "curl":
        # Accept the split form too: contains both -s and -I.
        matched = "-s" in tail and "-I" in tail
    if not matched:
        return None
    # Extract host:port target from argv URL / positional args.
    target = _extract_host_port(tail, head_base)
    if not target:
        return None
    return ReconnaissanceEvent(
        verb="port_probe",
        tool="Bash",
        turn_index=turn.turn_index,
        source_item_id=turn.source_item_id,
        timestamp=turn.timestamp,
        target=_make_target(target),
        discovered_value="",
        fragment=_make_fragment(command.cmd),
    )


def _extract_host_port(tail: tuple[str, ...], head_base: str) -> str:
    # First check for URL-style targets.
    for tok in tail:
        m = _URL_HOST_PORT_RE.search(tok)
        if m:
            host = m.group(1)
            port = m.group(2) or ""
            return f"{host}:{port}" if port else host
    # ``nc -z host port`` form: two consecutive non-flag positional args.
    if head_base in ("nc", "netcat"):
        positional = [t for t in tail if not t.startswith("-")]
        if len(positional) >= 2 and positional[1].isdigit():
            return f"{positional[0]}:{positional[1]}"
    return ""


# ---------------------------------------------------------------------------
# 5. file_read_recon — Read tool events (per-turn)
# ---------------------------------------------------------------------------


def match_file_read_recon(turn: TurnRecord) -> list[ReconnaissanceEvent]:
    """Emit one ReconnaissanceEvent per config-anchor in ``turn.files_read``.

    Called per-turn (not per-command) because ``files_read`` is a
    turn-level accumulator from the Read tool.
    """
    events: list[ReconnaissanceEvent] = []
    seen: set[str] = set()
    for raw_path in turn.files_read:
        if not raw_path:
            continue
        base = _basename(raw_path)
        if not is_config_anchor(base):
            # Sensitive anchors (.env etc.) fall through here too
            # because is_config_anchor already excludes them.
            continue
        # Deduplicate per turn on the canonical (lowercased) basename.
        key = base.lower()
        if key in seen:
            continue
        seen.add(key)
        events.append(ReconnaissanceEvent(
            verb="file_read_recon",
            tool="Read",
            turn_index=turn.turn_index,
            source_item_id=turn.source_item_id,
            timestamp=turn.timestamp,
            target=_make_target(base),
            discovered_value="",
            fragment=_make_fragment(raw_path),
        ))
    return events


# ---------------------------------------------------------------------------
# 6. cat_config_recon — cat of a config-anchor file
# ---------------------------------------------------------------------------


def match_cat_config_recon(
    command: CommandRecord, turn: TurnRecord,
) -> ReconnaissanceEvent | None:
    argv = strip_wrappers(iter_argv_head(command.cmd))
    if not argv:
        return None
    head_base = argv_basename(argv[0])
    if head_base != "cat":
        return None
    if len(argv) < 2:
        return None
    # Skip flag arg (``cat -n``); pick the first non-flag positional.
    target_raw = ""
    for tok in argv[1:]:
        if tok.startswith("-"):
            continue
        target_raw = tok
        break
    if not target_raw:
        return None
    base = _basename(target_raw)
    if not is_config_anchor(base):
        return None
    return ReconnaissanceEvent(
        verb="cat_config_recon",
        tool="Bash",
        turn_index=turn.turn_index,
        source_item_id=turn.source_item_id,
        timestamp=turn.timestamp,
        target=_make_target(base),
        discovered_value="",
        fragment=_make_fragment(command.cmd),
    )


# ---------------------------------------------------------------------------
# 7. directory_probe — ls / stat / find / test -f/-e/-d/…
# ---------------------------------------------------------------------------


_DIR_PROBE_HEADS: Final[frozenset[str]] = frozenset({
    "ls", "stat", "find",
})

# ``test`` restricted to file-check forms only. Other uses of ``test``
# (``test $? -eq 0``, ``test "$var" = foo``) are shell conditionals,
# not reconnaissance, and produce garbage targets.
_TEST_FILE_FLAGS: Final[frozenset[str]] = frozenset({
    "-f", "-e", "-d", "-r", "-w", "-x", "-s", "-h", "-L",
})


def match_directory_probe(
    command: CommandRecord, turn: TurnRecord,
) -> ReconnaissanceEvent | None:
    argv = strip_wrappers(iter_argv_head(command.cmd))
    if not argv:
        return None
    head_base = argv_basename(argv[0])
    if head_base in _DIR_PROBE_HEADS:
        # First non-flag positional is the target (path or pattern).
        target_raw = ""
        for tok in argv[1:]:
            if tok.startswith("-"):
                continue
            # Skip shell-var references — these are not durable targets.
            if tok.startswith("$"):
                continue
            target_raw = tok
            break
        if not target_raw:
            # ``ls`` alone (with no positional) still counts as
            # reconnaissance of the current directory.
            if head_base == "ls":
                target_raw = "."
            else:
                return None
        return ReconnaissanceEvent(
            verb="directory_probe",
            tool="Bash",
            turn_index=turn.turn_index,
            source_item_id=turn.source_item_id,
            timestamp=turn.timestamp,
            target=_make_target(target_raw),
            discovered_value="",
            fragment=_make_fragment(command.cmd),
        )
    if head_base == "test":
        if len(argv) < 3:
            return None
        flag = argv[1]
        if flag not in _TEST_FILE_FLAGS:
            return None
        target_raw = argv[2]
        # Reject shell-var expansions and empty targets.
        if not target_raw or target_raw.startswith("$"):
            return None
        return ReconnaissanceEvent(
            verb="directory_probe",
            tool="Bash",
            turn_index=turn.turn_index,
            source_item_id=turn.source_item_id,
            timestamp=turn.timestamp,
            target=_make_target(target_raw),
            discovered_value="",
            fragment=_make_fragment(command.cmd),
        )
    return None


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------


# Order matters: first-match-wins per command. ``command_lookup`` before
# ``version_query`` before ``help_query`` handles the ``prog --version
# --help`` collision case deterministically. Each predicate is
# self-contained; ordering only affects the tie-break for argvs that
# would match more than one verb.
COMMAND_PREDICATES: Final[tuple[
    Callable[[CommandRecord, TurnRecord], ReconnaissanceEvent | None], ...
]] = (
    match_command_lookup,
    match_version_query,
    match_help_query,
    match_port_probe,
    match_cat_config_recon,
    match_directory_probe,
)


def detect_reconnaissance(turn: TurnRecord) -> list[ReconnaissanceEvent]:
    """Emit one :class:`ReconnaissanceEvent` per matching predicate hit.

    - Command predicates run first-match-wins per command. A single
      argv line produces at most one event; predicate order is fixed
      by :data:`COMMAND_PREDICATES` and locked by tests.
    - Failed commands (``exit_code != 0``) are skipped — a failed
      reconnaissance verb isn't evidence.
    - :func:`match_file_read_recon` runs once per turn and can emit
      multiple events (one per anchor read).

    Deterministic: same input yields identical output, in the same
    order. No clock, no random.
    """
    events: list[ReconnaissanceEvent] = []
    for cmd in turn.commands:
        if cmd.exit_code is not None and cmd.exit_code != 0:
            continue
        if not cmd.cmd:
            continue
        for predicate in COMMAND_PREDICATES:
            ev = predicate(cmd, turn)
            if ev is not None:
                events.append(ev)
                break
    events.extend(match_file_read_recon(turn))
    return events


__all__ = [
    "ReconVerb",
    "ReconnaissanceEvent",
    "CONFIG_ANCHOR_BASENAMES",
    "SENSITIVE_ANCHOR_BASENAMES",
    "COMMAND_PREDICATES",
    "is_config_anchor",
    "match_command_lookup",
    "match_version_query",
    "match_help_query",
    "match_port_probe",
    "match_file_read_recon",
    "match_cat_config_recon",
    "match_directory_probe",
    "detect_reconnaissance",
]
