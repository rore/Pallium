"""
Reporter core. Pure logic; no I/O at the top level except in main().
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml  # type: ignore
except ImportError:
    sys.stderr.write("error: PyYAML not installed. pip install pyyaml\n")
    sys.exit(1)


# --------------------------------------------------------------------------
# Data types
# --------------------------------------------------------------------------

@dataclass
class Diff:
    """A simplified diff: list of changed files plus line-count totals.

    `lines_by_file` (when present) maps each changed-file path to its
    insertion+deletion count, derived from `git diff --numstat`. With it,
    `_pr_size_status` can subtract excludes-matched files from the size
    budget; without it, the legacy scalar `lines_changed` is used as-is
    and `excludes` does not affect size accounting (PR-mode pre-v0.3
    behavior).

    `added_by_file` (when present) maps each post-image path to a list of
    `(line_no, content)` tuples for every added line, derived from
    `git diff --unified=0`. Populated by `parse_unified_diff()` when
    `--diff-unified` is supplied. Phase-4 suppression detection walks this
    structure; absent → suppression detection is a no-op.
    """
    changed_files: list[str]
    files_changed: int
    lines_changed: int
    lines_by_file: dict[str, int] | None = None
    added_by_file: dict[str, list[tuple[int, str]]] | None = None


@dataclass
class BoundaryViolation:
    rule: str
    detail: str
    severity: str = "error"
    source: str = "backend"


@dataclass
class CheckpointStatus:
    id: str
    reason: str
    satisfied: bool
    satisfy_by: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    verdict: str   # BLUE | RED | GRAY | BOUNDARY_VIOLATION | MIXED | API_CHANGE | SCHEMA_CHANGE | SECURITY_CHANGE | CONFIG_CHANGE
    summary: str
    zones: dict[str, list[str]]
    checkpoints: list[CheckpointStatus]
    boundary_violations: list[BoundaryViolation]
    api_changes: dict[str, Any]
    schema_changes: dict[str, Any]
    security_changes: dict[str, Any]
    runtime_config_changes: dict[str, Any]
    pr_size: dict[str, Any]
    exit_code: int
    recommended_action: str
    modes: dict[str, Any] = field(default_factory=dict)
    suppressions: list["SuppressionMatch"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "summary": self.summary,
            "zones": self.zones,
            "checkpoints": [asdict(c) for c in self.checkpoints],
            "boundaryViolations": [asdict(b) for b in self.boundary_violations],
            "apiChanges": self.api_changes,
            "schemaChanges": self.schema_changes,
            "securityChanges": self.security_changes,
            "runtimeConfigChanges": self.runtime_config_changes,
            "prSize": self.pr_size,
            "exitCode": self.exit_code,
            "recommendedAction": self.recommended_action,
            "modes": self.modes,
            "suppressions": [asdict(s) for s in self.suppressions],
        }


# --------------------------------------------------------------------------
# Glob matching
# --------------------------------------------------------------------------

def _glob_to_regex(pattern: str) -> re.Pattern:
    """
    Convert a shell-style glob into a regex.

    Differs from fnmatch in two important ways:
      - `**` matches zero or more path components (including empty)
      - `*` matches anything except `/`
    """
    i = 0
    out = ["^"]
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                # `**` — zero or more components.
                # Common forms we want to handle:
                #   "**/x"   → "x" or "any/path/x"  → matches "x" or "a/x" or "a/b/x"
                #   "x/**"   → "x" or "x/anything"
                #   "x/**/y" → "x/y" or "x/a/y" or "x/a/b/y"
                # Implementation: "**/" → "(.*/)?"; trailing "**" or middle "**" → ".*"
                if i + 2 < len(pattern) and pattern[i + 2] == "/":
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                else:
                    out.append(".*")
                    i += 2
                    continue
            else:
                out.append("[^/]*")
                i += 1
                continue
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            # Pass character class through. Find the matching ].
            j = i + 1
            # Allow leading `!` for negation (POSIX-style); also accept `^`.
            if j < len(pattern) and pattern[j] in "!^":
                j += 1
            # Allow `]` as the first character to be literal (POSIX rule).
            if j < len(pattern) and pattern[j] == "]":
                j += 1
            while j < len(pattern) and pattern[j] != "]":
                j += 1
            if j >= len(pattern):
                # Unmatched [: treat as literal
                out.append(r"\[")
            else:
                content = pattern[i + 1:j]
                # Translate `!` negation to regex `^`.
                if content.startswith("!"):
                    content = "^" + content[1:]
                out.append("[" + content + "]")
                i = j + 1
                continue
        elif c == ".":
            out.append(r"\.")
        elif c == "/":
            out.append("/")
        elif c in "()|+^$":
            out.append("\\" + c)
        else:
            out.append(re.escape(c))
        i += 1
    out.append("$")
    return re.compile("".join(out))


def matches(path: str, pattern: str) -> bool:
    return bool(_glob_to_regex(pattern).match(path))


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(matches(path, p) for p in patterns)


# --------------------------------------------------------------------------
# Zone classification
# --------------------------------------------------------------------------

def _zone_paths(zone_entries: list[dict[str, Any]] | None) -> list[str]:
    return [e["path"] for e in (zone_entries or [])]


def classify_files(
    files: list[str],
    policy: dict[str, Any],
) -> dict[str, list[str]]:
    """
    Classify each file as red / blue / gray / watch / excluded.

    Priority: excludes wins; then red; then blue; the rest fall through to
    gray. `watch` is *additive*: a file can be red+watch, blue+watch, or
    gray+watch. Watch never affects the verdict on its own — it only
    surfaces the path in the PR comment regardless of how the file is
    otherwise classified.
    """
    zones = policy.get("zones", {}) or {}
    red = _zone_paths(zones.get("red"))
    blue = _zone_paths(zones.get("blue"))
    watch = _zone_paths(zones.get("watch"))
    excludes = policy.get("excludes", []) or []

    classified: dict[str, list[str]] = {
        "red": [],
        "blue": [],
        "gray": [],
        "watch": [],
        "excluded": [],
    }

    for path in files:
        if matches_any(path, excludes):
            classified["excluded"].append(path)
            continue
        if matches_any(path, red):
            classified["red"].append(path)
        elif matches_any(path, blue):
            classified["blue"].append(path)
        else:
            classified["gray"].append(path)
        if matches_any(path, watch):
            classified["watch"].append(path)

    return classified


# --------------------------------------------------------------------------
# Signal detection (per-section policy fields)
# --------------------------------------------------------------------------

def _detect_signal(files: list[str], section: dict[str, Any] | None, key: str) -> bool:
    if not section:
        return False
    paths = section.get(key) or []
    return any(matches_any(f, paths) for f in files)


def detect_api_change(files: list[str], policy: dict[str, Any]) -> bool:
    api = policy.get("api") or {}
    api_type = api.get("type", "none")
    if api_type == "none":
        return False
    spec_path = api.get("specPath")
    if api_type in ("openapi-spec-file", "graphql", "proto") and spec_path:
        return any(matches(f, spec_path) for f in files)
    # openapi-from-controllers: file-level detection is not meaningful (the
    # spec is generated). The CI workflow runs the policy's generationCommand
    # at base and head and passes both specs to the reporter via
    # --api-spec-base / --api-spec-head; diff_openapi_specs() does the real
    # work. If neither spec was supplied (e.g. local pre-push), we fall back
    # to "no api signal" and rely on path classification (controllers in the
    # red zone) to trigger api-review.
    return False


# --------------------------------------------------------------------------
# OpenAPI structural diff
# --------------------------------------------------------------------------

# Methods we treat as path operations. OpenAPI's "parameters" and "summary"
# at the path level are intentionally excluded — operation changes are what
# move the contract, and parameters at the path level are uncommon enough
# that they'd produce more noise than signal.
_OPENAPI_METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")


def _openapi_paths(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the paths object as a dict, or {} if missing/malformed."""
    if not isinstance(spec, dict):
        return {}
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return {}
    # Only keep entries that are themselves mappings; OpenAPI allows $ref
    # at the path level, which we treat as opaque (modified if it changes).
    return {k: v for k, v in paths.items() if isinstance(v, dict)}


def _openapi_methods(path_item: dict[str, Any]) -> dict[str, Any]:
    """Return the operation entries on a path item (get/post/...), preserving order."""
    return {m: path_item[m] for m in _OPENAPI_METHODS if m in path_item}


def diff_openapi_specs(base_yaml: str, head_yaml: str) -> dict[str, Any]:
    """
    Structural diff between two OpenAPI YAML strings.

    Returns:
        {
            "pathsAdded":     [str, ...],
            "pathsRemoved":   [str, ...],
            "pathsModified":  [{"path": str,
                                "methodsAdded":    [str, ...],
                                "methodsRemoved":  [str, ...],
                                "methodsModified": [str, ...]}, ...],
        }

    "Modified" means the operation object differs by structural equality.
    We do not classify breaking vs additive — the goal is "the surface
    changed in these places," which is enough signal to drive a checkpoint.
    Reviewers (human or agent) judge severity.
    """
    try:
        base = yaml.safe_load(base_yaml) if base_yaml.strip() else {}
    except yaml.YAMLError:
        base = {}
    try:
        head = yaml.safe_load(head_yaml) if head_yaml.strip() else {}
    except yaml.YAMLError:
        head = {}

    base_paths = _openapi_paths(base)
    head_paths = _openapi_paths(head)

    added = sorted(set(head_paths) - set(base_paths))
    removed = sorted(set(base_paths) - set(head_paths))

    modified: list[dict[str, Any]] = []
    for path in sorted(set(base_paths) & set(head_paths)):
        b_methods = _openapi_methods(base_paths[path])
        h_methods = _openapi_methods(head_paths[path])
        m_added = sorted(set(h_methods) - set(b_methods))
        m_removed = sorted(set(b_methods) - set(h_methods))
        m_modified = sorted(
            m for m in set(b_methods) & set(h_methods)
            if b_methods[m] != h_methods[m]
        )
        if m_added or m_removed or m_modified:
            modified.append({
                "path": path,
                "methodsAdded": m_added,
                "methodsRemoved": m_removed,
                "methodsModified": m_modified,
            })

    return {
        "pathsAdded": added,
        "pathsRemoved": removed,
        "pathsModified": modified,
    }


def openapi_diff_is_empty(diff: dict[str, Any]) -> bool:
    """True if the OpenAPI diff has no surface change."""
    return not (diff.get("pathsAdded") or diff.get("pathsRemoved") or diff.get("pathsModified"))


def detect_schema_change(files: list[str], policy: dict[str, Any]) -> bool:
    return _detect_signal(files, policy.get("persistence"), "migrationPaths")


def detect_security_change(files: list[str], policy: dict[str, Any]) -> bool:
    return _detect_signal(files, policy.get("security"), "paths")


def detect_runtime_config_change(files: list[str], policy: dict[str, Any]) -> bool:
    return _detect_signal(files, policy.get("runtimeConfig"), "paths")


# --------------------------------------------------------------------------
# Boundary backend (JUnit XML) parsing
# --------------------------------------------------------------------------

def parse_archunit_junit_xml(xml_text: str) -> list[BoundaryViolation]:
    """
    Parse JUnit XML for ArchUnit-style violations.

    Looks for testcases whose <failure> message indicates an architecture
    rule violation. The match-class-name and match-test-name patterns from
    extension adapter.yaml would normally filter; for v0.1 we match by
    convention: testcases in classes containing "ArchitectureTest" with
    a <failure> element.
    """
    violations: list[BoundaryViolation] = []
    if not xml_text:
        return violations

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return violations

    # JUnit XML has either <testsuite> or <testsuites><testsuite>...
    suites = list(root.iter("testsuite"))
    for suite in suites:
        suite_name = suite.attrib.get("name", "")
        if "ArchitectureTest" not in suite_name and "Architecture" not in suite_name:
            continue
        for case in suite.iter("testcase"):
            failure = case.find("failure")
            if failure is None:
                continue
            test_name = case.attrib.get("name", "")
            detail = (failure.text or failure.attrib.get("message", "")).strip()
            violations.append(
                BoundaryViolation(
                    rule=test_name,
                    detail=_summarize_violation(detail),
                    severity="error",
                    source="archunit",
                )
            )
    return violations


def _first_line(text: str, max_len: int = 200) -> str:
    line = (text or "").strip().splitlines()[0] if text else ""
    return line[:max_len]


def parse_json_violations(text: str) -> list[BoundaryViolation]:
    """
    Parse a json-violations document (per core/schema/boundary-violations.schema.json).

    Lenient: any deviation from the schema causes the document to be ignored
    (returns []) with a clear stderr message. The reporter never crashes on
    malformed boundary-report input.

    The 'source' field on each BoundaryViolation comes from the document's
    top-level "source" (default: "backend").
    """
    violations: list[BoundaryViolation] = []
    if not text:
        return violations
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"warning: boundary report is not valid JSON: {e}\n")
        return violations
    if not isinstance(doc, dict):
        sys.stderr.write("warning: boundary report root must be an object\n")
        return violations
    raw_violations = doc.get("violations")
    if not isinstance(raw_violations, list):
        sys.stderr.write("warning: boundary report 'violations' must be an array\n")
        return violations
    source = doc.get("source") or "backend"
    if not isinstance(source, str):
        source = "backend"
    for entry in raw_violations:
        if not isinstance(entry, dict):
            continue
        rule = entry.get("rule")
        detail = entry.get("detail")
        if not isinstance(rule, str) or not rule:
            continue
        if not isinstance(detail, str) or not detail:
            continue
        severity = entry.get("severity", "error")
        if severity not in ("error", "warning"):
            severity = "error"
        violations.append(
            BoundaryViolation(
                rule=rule,
                detail=_summarize_violation(detail),
                severity=severity,
                source=source,
            )
        )
    return violations


def _summarize_violation(text: str, max_len: int = 400) -> str:
    """
    Summarize an ArchUnit failure message into a single readable line.

    The raw message looks like:
        Architecture Violation [Priority: MEDIUM] - Rule '<rule statement>'
        was violated (1 times):
        Class <com.example.X> depends on <com.example.Y>

    We want a one-line version that keeps the rule statement and the
    specific violation. Joins lines and truncates to max_len.
    """
    if not text:
        return ""
    # Collapse newlines / extra whitespace.
    one_line = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return one_line[:max_len] + ("…" if len(one_line) > max_len else "")


# --------------------------------------------------------------------------
# Unified-diff parsing (suppression-detection input)
# --------------------------------------------------------------------------

def parse_unified_diff(patch: str) -> dict[str, list[tuple[int, str]]]:
    """
    Parse a unified diff (produced by `git diff --unified=0`).

    Returns: {post_path: [(line_no, added_line_content), ...]}.

    Skips deleted files. For renames, the post-rename path is the key.
    Tracks the per-hunk new-file line counter so each added line carries
    its line number in the post-image. Hunk-boundary semantics are NOT
    used by callers; suppression detection (Phase 4) walks added lines
    per file regardless of hunk shape (spec §2.2 — naive algorithm).
    """
    out: dict[str, list[tuple[int, str]]] = {}
    current_path: str | None = None
    new_lineno = 0
    for raw in patch.splitlines():
        if raw.startswith("diff --git "):
            current_path = None  # reset; +++ line below sets it
            continue
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            if target == "/dev/null":
                current_path = None
            else:
                # `+++ b/path/to/file` → strip the `b/` prefix
                current_path = target[2:] if target.startswith(("a/", "b/")) else target
            continue
        if raw.startswith("@@"):
            # @@ -<old>[,<n>] +<new>[,<n>] @@
            # Extract `<new>` and seed the counter.
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
            if m and current_path is not None:
                new_lineno = int(m.group(1))
            continue
        if current_path is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            out.setdefault(current_path, []).append((new_lineno, raw[1:]))
            new_lineno += 1
        elif raw.startswith("-") or raw.startswith("---"):
            # deletion — does not advance new-file lineno
            pass
        else:
            # context line (only present with -U > 0; harmless either way)
            new_lineno += 1
    return out


# --------------------------------------------------------------------------
# Suppressions resolution (vendored-file contract)
# --------------------------------------------------------------------------

VENDORED_SUPPRESSIONS_PATH = ".agent-redline/suppressions.yaml"


@dataclass
class SuppressionsConfig:
    """Effective suppression marker list resolved from vendored defaults + policy overrides."""
    inline_comments: list[str] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)
    config_keys: list[str] = field(default_factory=list)
    exempt_paths: list[str] = field(default_factory=list)


def load_suppressions_defaults(repo_root: Path) -> dict[str, Any] | None:
    """Read `.agent-redline/suppressions.yaml` if present. Returns None if absent."""
    p = repo_root / VENDORED_SUPPRESSIONS_PATH
    if not p.exists():
        return None
    with p.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"error: vendored suppressions at {p} is not a mapping")
    return (data.get("suppressions") or {})


def resolve_suppressions_config(
    policy: dict[str, Any],
    repo_root: Path,
) -> SuppressionsConfig | None:
    """
    Resolve the active suppression marker list.

    Spec §1.4 compatibility: absent `suppressions:` block in the policy →
    detection OFF (returns None). The missing-vendored-file error fires
    only when (1) the policy declares the block AND (2) useExtensionDefaults
    is true (default) AND (3) `.agent-redline/suppressions.yaml` is absent.
    """
    block = policy.get("suppressions")
    if block is None:
        return None  # detection OFF — non-negotiable per §1.4
    if not isinstance(block, dict):
        # A legacy list (`suppressions: []`) or any non-mapping would raise
        # AttributeError on the first `block.get(...)` below — and schema
        # validation doesn't always run (load_policy warns and continues
        # when jsonschema is absent or the schema can't be located). Treat
        # a non-mapping as a hard config error with a clean message rather
        # than a bare traceback. Removing the block is the way to disable
        # detection; a malformed block is not silently ignored.
        raise SystemExit(
            "error: policy 'suppressions' must be a mapping (block), got "
            f"{type(block).__name__}. Use a mapping with keys such as "
            "useExtensionDefaults / add / remove / exemptPaths, or remove "
            "the suppressions block entirely to disable detection."
        )

    use_defaults = block.get("useExtensionDefaults", True)
    # Coerce non-mapping add/remove to {} — a non-empty list/scalar here would
    # raise AttributeError in merge_list/merge_sub below, and schema validation
    # doesn't always run (load_policy warns and continues when jsonschema is
    # absent). An empty list is already falsy → {}; this covers the rest.
    add = block.get("add") or {}
    if not isinstance(add, dict):
        add = {}
    remove = block.get("remove") or {}
    if not isinstance(remove, dict):
        remove = {}
    exempt_paths = block.get("exemptPaths", []) or []

    defaults: dict[str, Any] = {}
    if use_defaults:
        loaded = load_suppressions_defaults(repo_root)
        if loaded is None:
            raise FileNotFoundError(
                f"policy declares a suppressions block with "
                f"useExtensionDefaults: true, but {VENDORED_SUPPRESSIONS_PATH} "
                f"is absent. Either re-run bootstrap (which vendors the file), "
                f"set useExtensionDefaults: false, or remove the suppressions "
                f"block to disable detection."
            )
        defaults = loaded

    def merge_list(category: str) -> list[str]:
        base = list(defaults.get(category, []) or [])
        added = list(add.get(category, []) or [])
        removed = set(remove.get(category, []) or [])
        return [m for m in base + added if m not in removed]

    def merge_sub(category: str, sub: str) -> list[str]:
        base = list((defaults.get(category, {}) or {}).get(sub, []) or [])
        added = list((add.get(category, {}) or {}).get(sub, []) or [])
        removed = set((remove.get(category, {}) or {}).get(sub, []) or [])
        return [m for m in base + added if m not in removed]

    return SuppressionsConfig(
        inline_comments=merge_list("inlineComments"),
        annotations=merge_list("annotations"),
        config_files=merge_sub("configEdits", "files"),
        config_keys=merge_sub("configEdits", "keys"),
        exempt_paths=list(exempt_paths),
    )


# --------------------------------------------------------------------------
# Suppression scanner (spec §2.2 — naive added-line scan)
# --------------------------------------------------------------------------

@dataclass
class SuppressionMatch:
    file: str
    line: int
    marker: str
    category: str         # "inlineComment" | "annotation" | "configEdit"
    zone: str             # "red" | "blue" | "gray"
    context: str          # the added-line content, truncated


_ANNOTATION_TOKEN_RE_CACHE: dict[str, re.Pattern] = {}


def _annotation_token_re(marker: str) -> re.Pattern:
    """Word-boundary regex for an annotation token (e.g. @SuppressWarnings).

    `@` is not a word character, so a leading boundary isn't useful; we
    anchor on the literal `@<Name>` and require a non-word character (or
    end-of-string) after the name to prevent `@SuppressWarningsExt` from
    matching `@SuppressWarnings`.
    """
    if marker not in _ANNOTATION_TOKEN_RE_CACHE:
        _ANNOTATION_TOKEN_RE_CACHE[marker] = re.compile(
            re.escape(marker) + r"(?![A-Za-z0-9_])"
        )
    return _ANNOTATION_TOKEN_RE_CACHE[marker]


def _annotation_marker_in_code(line: str, marker: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("@") and _annotation_token_re(marker).search(stripped) is not None


def _is_config_key_assignment(line: str, key: str) -> bool:
    """Structural key match for configEdits.

    `ignore_imports = [...]`           → True
    `[ignore_imports]`                 → True (TOML/INI section header)
    `"ignore_imports": [...]`          → True (JSON-ish)
    `# ignore_imports stuff`           → False (comment)
    `// ignore_imports`                → False (comment)

    Note: nested TOML table headers like `[tool.x.ignore_imports]` do NOT
    match by this rule — the leading `.` is not in the boundary character
    class. Such lines land in a config file because someone declared a
    nested TOML table; if an extension wants to flag them, register the
    fully-qualified key (e.g. `tool.x.ignore_imports`) in `markerLists`.
    """
    stripped = line.lstrip()
    if not stripped or stripped[0] == "#" or stripped.startswith("//"):
        return False
    pattern = re.compile(
        r"(?:^|[\s\[\"'])"
        + re.escape(key)
        + r"\s*[=:\[\]]"
    )
    return bool(pattern.search(line))


def scan_suppressions(
    added_by_file: dict[str, list[tuple[int, str]]] | None,
    config: SuppressionsConfig | None,
    classification: dict[str, list[str]],
) -> list[SuppressionMatch]:
    """
    Naive added-line scanner. Spec §2.2 — deliberately no hunk parsing,
    no removed-line tracking, no equivalence by marker family. Reformat
    false positives are visible-and-cheap by design (see spec §6).
    """
    if config is None or added_by_file is None:
        return []

    file_zone: dict[str, str] = {}
    for f in classification.get("red", []):
        file_zone[f] = "red"
    for f in classification.get("gray", []):
        file_zone.setdefault(f, "gray")
    for f in classification.get("blue", []):
        file_zone.setdefault(f, "blue")

    matches: list[SuppressionMatch] = []
    for path, lines in added_by_file.items():
        if path == VENDORED_SUPPRESSIONS_PATH:
            continue
        if config.exempt_paths and matches_any(path, config.exempt_paths):
            continue
        zone = file_zone.get(path, "gray")
        is_config_file = (
            bool(config.config_files)
            and matches_any(path, config.config_files)
        )

        for line_no, content in lines:
            stripped = content.lstrip()
            for marker in config.inline_comments:
                if marker in content:
                    matches.append(SuppressionMatch(
                        file=path, line=line_no, marker=marker,
                        category="inlineComment", zone=zone,
                        context=content[:200],
                    ))
            for marker in config.annotations:
                if _annotation_marker_in_code(content, marker):
                    matches.append(SuppressionMatch(
                        file=path, line=line_no, marker=marker,
                        category="annotation", zone=zone,
                        context=content[:200],
                    ))
            if is_config_file:
                for key in config.config_keys:
                    if _is_config_key_assignment(content, key):
                        matches.append(SuppressionMatch(
                            file=path, line=line_no, marker=key,
                            category="configEdit", zone=zone,
                            context=content[:200],
                        ))
    return matches


# --------------------------------------------------------------------------
# Checkpoint satisfaction
# --------------------------------------------------------------------------

def _build_api_changes(detected: bool, spec_diff: dict[str, Any] | None) -> dict[str, Any]:
    """Compose the apiChanges field. Carries the structural diff when present."""
    out: dict[str, Any] = {"detected": detected}
    if spec_diff is not None:
        out["specDiff"] = spec_diff
    return out


def _required_checkpoints(
    classification: dict[str, list[str]],
    policy: dict[str, Any],
    api_changed: bool,
    schema_changed: bool,
    security_changed: bool,
    runtime_config_changed: bool,
    architecture_test_modified: bool,
    suppression_matches: list["SuppressionMatch"] | None = None,
) -> dict[str, str]:
    """Return {checkpoint_id: reason} for each required checkpoint."""
    required: dict[str, str] = {}

    # Red-zone files map to their declared checkpoints (default architecture-review).
    zones = policy.get("zones", {}) or {}
    red_entries = zones.get("red", []) or []
    for entry in red_entries:
        path = entry["path"]
        cp = entry.get("checkpoint", "architecture-review")
        for f in classification["red"]:
            if matches(f, path):
                required.setdefault(cp, f"red-zone change: {f}")
                break

    if api_changed:
        cp = (policy.get("api") or {}).get("checkpoint", "api-review")
        required.setdefault(cp, "API contract changed")
    if schema_changed:
        cp = (policy.get("persistence") or {}).get("checkpoint", "persistence-review")
        required.setdefault(cp, "Persistence migration changed")
    if security_changed:
        cp = (policy.get("security") or {}).get("checkpoint", "security-review")
        required.setdefault(cp, "Security path changed")
    if runtime_config_changed:
        cp = (policy.get("runtimeConfig") or {}).get("checkpoint", "ops-review")
        required.setdefault(cp, "Runtime configuration changed")
    if architecture_test_modified:
        required.setdefault(
            "architecture-review",
            "Architecture-test files modified",
        )

    # Spec §2.3 (cmt_000010): a suppression match on a non-exempt path always
    # contributes architecture-review, INDEPENDENT of the headline verdict.
    # `setdefault` is critical — when a higher-priority reason (e.g. a red-zone
    # path or arch-test edit) already required architecture-review, that reason
    # wins for the comment, but the requirement stays put either way. The
    # exempt-paths filter has already been applied by scan_suppressions(), so
    # a non-empty list here means at least one non-exempt match exists.
    if suppression_matches:
        first = suppression_matches[0]
        extra = (
            f" (+{len(suppression_matches) - 1} more)"
            if len(suppression_matches) > 1
            else ""
        )
        required.setdefault(
            "architecture-review",
            f"Suppression marker on guarded surface: {first.marker} "
            f"at {first.file}:{first.line}{extra}",
        )

    return required


# ---------------------------------------------------------------------------
# CODEOWNERS parsing + path intersection (F2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CodeOwnersRule:
    """One pattern → owners rule from a CODEOWNERS file.

    Owners are the literal tokens GitHub recognises: ``@user`` for a
    user, ``@org/team`` for a team. We don't resolve teams to members
    locally — that requires the GitHub API and we're a pure function.
    Branch protection's "Require Code Owner review" handles team
    resolution on the server side; this predicate does best-effort
    user-login intersection plus surfaces team-only rules as
    "verification incomplete" so reviewers know what they're getting.
    """

    pattern: str
    owners: tuple[str, ...]


_CODEOWNERS_SEARCH_PATHS: tuple[str, ...] = (
    ".github/CODEOWNERS",
    "CODEOWNERS",
    "docs/CODEOWNERS",
)


def load_codeowners(repo_root: Path) -> list[_CodeOwnersRule]:
    """Read and parse the first CODEOWNERS file found at the standard locations.

    Returns an empty list when no CODEOWNERS file exists (the
    'codeownerApproval' satisfaction path then degrades to "any
    approval" — caller decides whether that's tolerable).

    Lines starting with '#' and blank lines are skipped. Each remaining
    line is split on whitespace; the first token is the path pattern,
    the rest are owner tokens. Malformed lines (no owners) are skipped
    silently — CODEOWNERS is GitHub's authoritative parser, ours is
    best-effort and conservative.
    """
    for rel in _CODEOWNERS_SEARCH_PATHS:
        p = repo_root / rel
        if p.is_file():
            return _parse_codeowners_text(p.read_text(encoding="utf-8"))
    return []


def _parse_codeowners_text(text: str) -> list[_CodeOwnersRule]:
    rules: list[_CodeOwnersRule] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            # Pattern with no owners; CODEOWNERS treats this as
            # "no required reviewer." Skip — we can't intersect.
            continue
        pattern, *owners = parts
        rules.append(_CodeOwnersRule(pattern=pattern, owners=tuple(owners)))
    return rules


def owners_for_paths(
    rules: list[_CodeOwnersRule],
    paths: Iterable[str],
) -> set[str]:
    """Return the union of owner tokens whose pattern matches any path.

    GitHub's CODEOWNERS pattern semantics are gitignore-shaped: later
    rules override earlier ones. For the satisfaction check we want
    "who could approve this," so we take the union — a more
    conservative interpretation than GitHub's last-match-wins. The
    cost: if the team intends a narrow override to limit who counts,
    we'd over-attribute. The benefit: missing approvers never sneak
    past us due to ordering surprises.
    """
    matched: set[str] = set()
    for path in paths:
        for rule in rules:
            if _codeowners_match(rule.pattern, path):
                matched.update(rule.owners)
    return matched


def _codeowners_glob_to_regex(pattern: str) -> str:
    """Translate a CODEOWNERS-style glob into an un-anchored regex body.

    `**` matches ZERO OR MORE full path segments (crossing `/`) ONLY when it
    forms a WHOLE segment — bounded by a segment separator on both sides:
    it starts the pattern or follows `/` (left boundary) AND is followed by
    `/` or ends the pattern (right boundary). A `**` glued to a literal on
    either side (`foo**/bar`, `foo/**bar`) is not a whole segment; per
    gitignore the asterisks act as a within-segment `*` and must not cross
    `/` — otherwise an unrelated path could match and let an unrelated
    approver satisfy a CODEOWNER checkpoint. `*` matches within a single
    segment (no `/`); every other character is escaped literally. Unlike the
    previous ``fnmatch.translate`` hack, the zero-segment case of a middle
    `**` is handled — ``foo/**/bar`` matches ``foo/bar`` as well as
    ``foo/x/bar`` and ``foo/x/y/bar``.

    Returns the body only (no `^`/`\\Z`); the caller anchors it to
    preserve the anchored-vs-unanchored (re.match vs re.search)
    semantics of :func:`_codeowners_match`.
    """
    i = 0
    n = len(pattern)
    out: list[str] = []
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                # Whole-segment globstar requires a LEFT boundary (start of
                # pattern or preceding `/`). Without it (`foo**`), the stars
                # are glued to a literal and stay within one segment.
                left_boundary = (i == 0) or (pattern[i - 1] == "/")
                if left_boundary and i + 2 < n and pattern[i + 2] == "/":
                    # `**/` → an optional run of whole segments (incl. zero),
                    # which is what makes `foo/**/bar` match `foo/bar`.
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                if left_boundary and i + 2 >= n:
                    # Trailing whole-segment `**` → match anything to the end,
                    # crossing segment boundaries (e.g. `core/schema/**`).
                    out.append(".*")
                    i += 2
                    continue
                # Glued to a literal on the left (`foo**/`) or right
                # (`foo/**bar`): NOT a whole segment; gitignore treats the
                # asterisks as a within-segment `*`, so it must not cross `/`.
                # (The old fnmatch hack turned these into `.*`, over-matching
                # across slashes.)
                out.append("[^/]*")
                i += 2
                continue
            # Single `*` — anything except a slash (stays within a segment).
            out.append("[^/]*")
            i += 1
            continue
        out.append(re.escape(c))
        i += 1
    return "".join(out)


def _codeowners_match(pattern: str, path: str) -> bool:
    """gitignore-style glob match for one CODEOWNERS pattern against one path.

    Supported:
    - Leading '/': anchor to repo root.
    - Trailing '/': directory match (anything beneath).
    - '**' matches any number of path segments (including zero).
    - '*' matches any single segment substring (no slash).
    - Bare patterns match anywhere in the tree.

    Not supported (rare in real CODEOWNERS): negation '!', character
    classes '[...]'. Patterns using those fall through to fnmatch's
    plain semantics, which is conservative — over-matches rather than
    under-matches.
    """
    pat = pattern
    # Trailing slash → directory; anything below matches.
    if pat.endswith("/"):
        pat = pat + "**"
    # Leading slash → anchored to root. Strip it for fnmatch.
    if pat.startswith("/"):
        pat = pat[1:]
        anchored = True
    else:
        anchored = False

    if "**" in pat:
        # fnmatch handles '*' but not '**'; translate via an explicit
        # converter so '**' can cross slash boundaries AND collapse to
        # zero segments (`foo/**/bar` ⊇ `foo/bar`). Terminate with \Z so
        # a match runs to the end of the path; re.match anchors the
        # start for anchored patterns, re.search leaves it free for bare
        # ones — same split the fnmatch path below preserves.
        regex_pat = _codeowners_glob_to_regex(pat) + r"\Z"
        if anchored:
            return re.match(regex_pat, path) is not None
        return re.search(regex_pat, path) is not None

    if anchored:
        return fnmatch.fnmatchcase(path, pat)
    # Bare patterns match anywhere — try matching against the path
    # and every trailing segment.
    return fnmatch.fnmatchcase(path, pat) or any(
        fnmatch.fnmatchcase(path[i:], pat)
        for i in range(len(path))
        if path[i - 1:i] == "/"
    )


def _codeowner_satisfaction(
    effective_owners: set[str],
    approver_logins: set[str],
) -> tuple[bool, bool]:
    """Decide whether codeownerApproval is satisfied for the changed paths.

    Returns ``(satisfied, verification_complete)``.

    - ``satisfied=True`` when at least one approver matches at least
      one ``@user`` owner. Team tokens (``@org/team``) can't be resolved
      locally — they don't contribute to the user-level match.
    - ``verification_complete=False`` when the effective_owners contains
      team tokens we couldn't resolve. Reviewers should know that
      branch protection's "Require Code Owner review" is the only
      remaining enforcement layer in that case.
    """
    user_owners = {
        o.lstrip("@") for o in effective_owners
        if o.startswith("@") and "/" not in o
    }
    team_owners = {
        o for o in effective_owners
        if o.startswith("@") and "/" in o
    }
    # Approvers come in as bare logins (no @ prefix).
    if user_owners & approver_logins:
        return True, True
    # No user-level match. If only teams were configured, mark
    # verification incomplete; otherwise the user owners were present
    # but didn't approve.
    return False, len(team_owners) == 0


def _is_satisfied(
    checkpoint_def: dict[str, Any],
    pr_labels: Iterable[str],
    codeowner_approvals: Iterable[str],
    *,
    effective_owners: set[str] | None = None,
) -> tuple[bool, list[str]]:
    """OR-semantics over satisfiedBy entries. Returns (satisfied, satisfy_by_human).

    For ``codeownerApproval``:
    - When ``effective_owners`` is provided (the path-aware path):
      satisfied only when at least one approver intersects with the
      user-level owners of the changed paths (F2 fix).
    - When ``effective_owners`` is ``None`` (legacy callers that
      don't pass paths): falls back to "any non-empty approver list"
      with a note in ``satisfy_by_human`` so reviewers see the path
      check wasn't performed.
    """
    satisfied_by = checkpoint_def.get("satisfiedBy", []) or []
    labels = set(pr_labels)
    approver_set = {a.lstrip("@") for a in codeowner_approvals if a}

    satisfy_by_human: list[str] = []
    satisfied = False
    for sb in satisfied_by:
        if sb == "codeownerApproval":
            if effective_owners is None:
                # Legacy / no-paths path: degrade to "any approval".
                # Plain text preserves the pre-F2 satisfy_by wording so
                # callers that don't supply paths see the historic
                # surface. CLI invocations always supply (possibly
                # empty) effective_owners and route through the
                # path-aware branch below.
                satisfy_by_human.append("CODEOWNER approval")
                if approver_set:
                    satisfied = True
            else:
                ok, complete = _codeowner_satisfaction(
                    effective_owners, approver_set
                )
                if complete:
                    satisfy_by_human.append("CODEOWNER approval")
                else:
                    satisfy_by_human.append(
                        "CODEOWNER approval "
                        "(team membership verified by branch protection)"
                    )
                if ok:
                    satisfied = True
        elif isinstance(sb, dict):
            if "label" in sb:
                satisfy_by_human.append(f"label `{sb['label']}`")
                if sb["label"] in labels:
                    satisfied = True
    return satisfied, satisfy_by_human


# --------------------------------------------------------------------------
# Verdict computation
# --------------------------------------------------------------------------

ARCHITECTURE_TEST_GLOBS = (
    # The standard glob the jvm-archunit profile uses; agent-redline
    # treats architecture-test files as red regardless of policy.
    "src/test/java/**/architecture/**",
    # Common alternates for other ecosystems
    "**/architecture/**",
)


def _is_architecture_test_file(path: str) -> bool:
    return any(matches(path, g) for g in ARCHITECTURE_TEST_GLOBS)


def _pr_size_status(diff: Diff, policy: dict[str, Any]) -> dict[str, Any]:
    """Compute size verdict.

    When `diff.lines_by_file` is available AND `policy.excludes` is set,
    files matching any excludes glob are excluded from both the file
    count and the line count. Without per-file line counts the reporter
    falls back to the scalar `diff.lines_changed` (which already
    represents the full unfiltered diff) and the file count is filtered
    only on the changed-files list (file count IS excludes-aware in the
    fallback path; line count is not, because per-file lines aren't
    known).

    The returned dict surfaces `excludedFiles` and `excludedLines` so
    the comment can show "(N files / M lines excluded)" — a
    transparency line that prevents users from re-discovering this
    bug class by being surprised at numbers that don't match
    git-shortstat.
    """
    pr_rules = policy.get("prRules", {}) or {}
    files_rule = pr_rules.get("maxChangedFiles", {}) or {}
    lines_rule = pr_rules.get("maxLinesChanged", {}) or {}

    fail_files = files_rule.get("fail", 100)
    warn_files = files_rule.get("warn", 50)
    fail_lines = lines_rule.get("fail", 2000)
    warn_lines = lines_rule.get("warn", 1000)

    excludes = policy.get("excludes", []) or []
    excluded_paths = [f for f in diff.changed_files if matches_any(f, excludes)]
    included_paths = [f for f in diff.changed_files if f not in excluded_paths]

    files = len(included_paths)
    excluded_files = len(excluded_paths)

    if diff.lines_by_file is not None:
        lines = sum(diff.lines_by_file.get(p, 0) for p in included_paths)
        excluded_lines = sum(diff.lines_by_file.get(p, 0) for p in excluded_paths)
    else:
        # No per-file breakdown available. The scalar represents the
        # unfiltered diff; we can't subtract the excluded portion.
        lines = diff.lines_changed
        excluded_lines = 0

    verdict = "ok"
    if files > fail_files or lines > fail_lines:
        verdict = "fail"
    elif files > warn_files or lines > warn_lines:
        verdict = "warn"

    return {
        "files": files,
        "lines": lines,
        "excludedFiles": excluded_files,
        "excludedLines": excluded_lines,
        "verdict": verdict,
    }


# Spec §2.4: checks in this set default to `binding` regardless of
# `modes.default`. Only an explicit `modes.perCheck.<name>: shadow` flips it.
# Only `suppression` is hardcoded — `boundary_violation` still respects
# `modes.default` so existing fixtures/tests remain valid.
_HARDCODED_BINDING_DEFAULTS = {"suppression"}


def _binding(modes: dict[str, Any], check_name: str) -> bool:
    """Whether a given check is binding under the policy's modes config."""
    per_check = (modes or {}).get("perCheck", {}) or {}
    if check_name in _HARDCODED_BINDING_DEFAULTS:
        # Hardcoded default is `binding`; modes.default has no effect.
        # Explicit perCheck override (e.g. shadow) still applies.
        return per_check.get(check_name, "binding") == "binding"
    default = (modes or {}).get("default", "shadow")
    return per_check.get(check_name, default) == "binding"


def classify(
    policy: dict[str, Any],
    diff: Diff,
    *,
    archunit_xml: str | None = None,
    boundary_report: str | None = None,
    boundary_format: str | None = None,
    api_spec_diff: dict[str, Any] | None = None,
    pr_labels: Iterable[str] = (),
    codeowner_approvals: Iterable[str] = (),
    codeowners_rules: list[_CodeOwnersRule] | None = None,
    suppressions_config: SuppressionsConfig | None = None,
) -> Verdict:
    """The single entry point. Pure function.

    Boundary-rule input is delivered in one of three ways:

    - boundary_report + boundary_format (canonical, since v0.2): the caller
      passes the raw report text and its format ('junit-xml' or
      'json-violations'). The reporter dispatches on format.
    - archunit_xml (deprecated alias): kept working for back-compat with v0.1
      callers; equivalent to boundary_report with boundary_format='junit-xml'.
    - neither: the policy may carry a `boundaryAdapter:` block with
      outputFormat='none', in which case no boundary parsing happens.

    api_spec_diff (when supplied) is the result of diff_openapi_specs() against
    base and head specs the caller produced. When non-empty, it forces
    api_changed=True regardless of what file globs say. When None, api change
    is decided by detect_api_change() (path-glob detection on specPath).
    """
    files = diff.changed_files
    classification = classify_files(files, policy)

    suppression_matches = scan_suppressions(
        diff.added_by_file, suppressions_config, classification,
    )

    arch_test_modified = any(_is_architecture_test_file(f) for f in files)

    api_changed = detect_api_change(files, policy)
    if api_spec_diff is not None and not openapi_diff_is_empty(api_spec_diff):
        api_changed = True
    schema_changed = detect_schema_change(files, policy)
    security_changed = detect_security_change(files, policy)
    runtime_changed = detect_runtime_config_change(files, policy)

    boundary_violations: list[BoundaryViolation] = []
    # Resolve which boundary report to parse, and in which format.
    # Precedence: explicit boundary_report > legacy archunit_xml > nothing.
    if boundary_report is not None:
        fmt = boundary_format or "junit-xml"
        if fmt == "junit-xml":
            boundary_violations = parse_archunit_junit_xml(boundary_report)
        elif fmt == "json-violations":
            boundary_violations = parse_json_violations(boundary_report)
        elif fmt == "none":
            boundary_violations = []
        else:
            sys.stderr.write(f"warning: unknown boundary format '{fmt}'; ignoring report\n")
    elif archunit_xml:
        boundary_violations = parse_archunit_junit_xml(archunit_xml)

    required = _required_checkpoints(
        classification, policy,
        api_changed, schema_changed, security_changed, runtime_changed,
        arch_test_modified,
        suppression_matches=suppression_matches,
    )

    checkpoints_defs = policy.get("checkpoints", {}) or {}
    # Pre-compute the effective-owner set from CODEOWNERS rules over
    # all changed files. Per-checkpoint owner narrowing (using only
    # the paths that triggered THIS checkpoint) is a future
    # refinement; today's set is "owners of anything in this PR's
    # diff," which is the right conservative cut for the satisfaction
    # test.
    effective_owners: set[str] | None = None
    if codeowners_rules:
        effective_owners = owners_for_paths(codeowners_rules, files)
    checkpoint_statuses: list[CheckpointStatus] = []
    for cp_id, reason in required.items():
        cp_def = checkpoints_defs.get(cp_id, {})
        satisfied, satisfy_by = _is_satisfied(
            cp_def, pr_labels, codeowner_approvals,
            effective_owners=effective_owners,
        )
        checkpoint_statuses.append(
            CheckpointStatus(
                id=cp_id, reason=reason, satisfied=satisfied,
                satisfy_by=satisfy_by,
            )
        )

    pr_size = _pr_size_status(diff, policy)

    # Top-level verdict.
    if not files:
        verdict = "BLUE"
        summary = "No files changed."
    elif boundary_violations:
        verdict = "BOUNDARY_VIOLATION"
        summary = f"{len(boundary_violations)} boundary violation(s) detected."
    elif arch_test_modified:
        verdict = "RED"
        summary = "Architecture-test files modified; architecture-review required."
    elif api_changed:
        verdict = "API_CHANGE"
        summary = "Public API contract changed."
    elif schema_changed:
        verdict = "SCHEMA_CHANGE"
        summary = "Persistence schema changed."
    elif security_changed:
        verdict = "SECURITY_CHANGE"
        summary = "Security-sensitive code changed."
    elif runtime_changed:
        verdict = "CONFIG_CHANGE"
        summary = "Runtime configuration changed."
    elif suppression_matches:
        # Spec §2.4: a pure-suppression diff (no higher signal) headlines as RED
        # with a suppression-flavored summary. Combined cases (e.g. + red zone)
        # already hit the higher arm above; the suppressions still surface in
        # Verdict.suppressions and the architecture-review checkpoint.
        verdict = "RED"
        n = len(suppression_matches)
        summary = f"{n} suppression marker(s) added on guarded surfaces."
    elif classification["red"]:
        verdict = "RED"
        summary = "Red-zone files changed."
    elif classification["gray"]:
        verdict = "GRAY"
        summary = "Gray-zone files changed; cautious review."
    else:
        verdict = "BLUE"
        summary = "All changes in blue zones."

    # Exit code under the modes policy.
    modes = policy.get("modes", {}) or {}
    exit_code = 0
    recommended = "none"

    has_unmet_required = any(not c.satisfied for c in checkpoint_statuses)
    pr_size_fail = pr_size["verdict"] == "fail"
    pr_size_warn = pr_size["verdict"] == "warn"

    if boundary_violations and _binding(modes, "boundary_violation"):
        exit_code = 2
        recommended = "fix-boundary-violation"
    elif has_unmet_required and _binding(modes, "report"):
        # In default config, the report comment is informational; only fail
        # when the policy makes the report binding.
        exit_code = 2
        recommended = "satisfy-checkpoints"
    elif pr_size_fail and _binding(modes, "pr_size"):
        exit_code = 2
        recommended = "split-pr"
    elif boundary_violations or has_unmet_required or pr_size_fail:
        # Issues exist but checks are in shadow.
        exit_code = 1
        recommended = "review-shadow-warnings"
    elif classification["gray"] or classification["watch"] or pr_size_warn:
        exit_code = 1
        recommended = "review-warnings"

    # Spec §2.4: a binding suppression match with an unmet architecture-review
    # checkpoint lifts the exit code to 2 (never lowers an already-elevated
    # code). Applied AFTER the chain so it overrides shadow/warn arms when
    # binding, but does not downgrade a 2 from boundary/report/pr_size.
    suppression_unmet = bool(suppression_matches) and any(
        c.id == "architecture-review" and not c.satisfied
        for c in checkpoint_statuses
    )
    if suppression_unmet and _binding(modes, "suppression"):
        exit_code = max(exit_code, 2)
        if recommended == "none" or recommended in (
            "review-shadow-warnings", "review-warnings",
        ):
            recommended = "satisfy-suppression-checkpoint"

    return Verdict(
        verdict=verdict,
        summary=summary,
        zones={
            "red": classification["red"],
            "blue": classification["blue"],
            "gray": classification["gray"],
            "watch": classification["watch"],
        },
        checkpoints=checkpoint_statuses,
        boundary_violations=boundary_violations,
        api_changes=_build_api_changes(api_changed, api_spec_diff),
        schema_changes={"detected": schema_changed},
        security_changes={"detected": security_changed},
        runtime_config_changes={"detected": runtime_changed},
        pr_size=pr_size,
        exit_code=exit_code,
        recommended_action=recommended,
        modes=_normalise_modes(modes),
        suppressions=suppression_matches,
    )


def _normalise_modes(modes: dict[str, Any]) -> dict[str, Any]:
    """Echo the policy's modes block so consumers can read disposition.

    The reporter already uses this internally to drive exit code and
    recommended action (see :func:`_binding`). Echoing it on the
    verdict lets downstream consumers — notably the agent-workflow
    checker's ``review.checkpoints_satisfied`` predicate — surface the
    correct disposition without re-reading the policy file or
    reverse-engineering the exit code.

    The shape matches the policy's ``modes`` block one-for-one:
    ``{"default": "shadow"|"binding", "perCheck": {<name>: "shadow"|"binding"}}``.
    Missing keys default to ``shadow`` (the bootstrap default).
    Boundary-violation disposition is reported as it is in the policy;
    callers that care should consult ``perCheck.boundary_violation``,
    which the bootstrap pins to ``binding``.
    """
    if not isinstance(modes, dict):
        return {"default": "shadow", "perCheck": {}}
    default = modes.get("default") or "shadow"
    per_check = modes.get("perCheck") or {}
    if not isinstance(per_check, dict):
        per_check = {}
    return {
        "default": default,
        "perCheck": dict(per_check),
    }


# --------------------------------------------------------------------------
# Markdown PR comment
# --------------------------------------------------------------------------

def _render_api_spec_diff(spec_diff: dict[str, Any]) -> list[str]:
    """Render the OpenAPI structural-diff block. Caller has already decided to render."""
    added = spec_diff.get("pathsAdded") or []
    removed = spec_diff.get("pathsRemoved") or []
    modified = spec_diff.get("pathsModified") or []
    out: list[str] = ["**API check:** structural changes detected"]
    if added:
        out.append("")
        out.append("Added:")
        out.extend(f"- `{p}`" for p in added)
    if removed:
        out.append("")
        out.append("Removed:")
        out.extend(f"- `{p}`" for p in removed)
    if modified:
        out.append("")
        out.append("Modified:")
        for entry in modified:
            parts: list[str] = []
            if entry.get("methodsAdded"):
                parts.append("+" + ",".join(entry["methodsAdded"]).upper())
            if entry.get("methodsRemoved"):
                parts.append("-" + ",".join(entry["methodsRemoved"]).upper())
            if entry.get("methodsModified"):
                parts.append("~" + ",".join(entry["methodsModified"]).upper())
            suffix = f" ({' '.join(parts)})" if parts else ""
            out.append(f"- `{entry['path']}`{suffix}")
    out.append("")  # trailing blank to separate from the next section
    return out


def render_markdown(verdict: Verdict, flow_mode: str = "pr") -> str:
    lines: list[str] = []
    lines.append(f"## agent-redline: {verdict.verdict}")
    lines.append("")
    lines.append(f"**{verdict.summary}**")
    lines.append("")

    # Zones table — only show non-empty rows.
    rows = []
    for label, key in (("Red", "red"), ("Blue", "blue"), ("Gray", "gray"), ("Watch", "watch")):
        files = verdict.zones.get(key, [])
        if files:
            shown = ", ".join(f"`{p}`" for p in files[:5])
            if len(files) > 5:
                shown += f" (+{len(files) - 5} more)"
            rows.append(f"| {label} | {shown} |")
    if rows:
        lines.append("| Zone | Files |")
        lines.append("|---|---|")
        lines.extend(rows)
        lines.append("")

    # Checkpoints
    if verdict.checkpoints:
        lines.append("**Required checkpoints:**")
        for cp in verdict.checkpoints:
            box = "[x]" if cp.satisfied else "[ ]"
            if flow_mode == "push":
                # Push-mode: the change has already landed. Satisfier text
                # frames the checkpoint as a review obligation on the commit
                # that already exists, not a gate to be satisfied before
                # merge. CODEOWNER approval / PR labels don't apply (no PR).
                lines.append(
                    f"- {box} `{cp.id}` — {cp.reason}. "
                    f"Action: review the commit; revert if unintended, otherwise the red CI run on this commit is the audit record."
                )
            else:
                satisfy = " or ".join(cp.satisfy_by) if cp.satisfy_by else "(see policy)"
                lines.append(f"- {box} `{cp.id}` — {cp.reason}. Satisfy by: {satisfy}")
        lines.append("")

    # Boundary violations
    if verdict.boundary_violations:
        lines.append("**Boundary violations:**")
        for bv in verdict.boundary_violations:
            lines.append(f"- `{bv.rule}` ({bv.severity}): {bv.detail}")
        lines.append("")
    else:
        lines.append("**Boundary check:** passed")

    # Suppressions added (spec §2.5). Silent when the list is empty —
    # absent suppressions block, no policy detection, or no markers found
    # all funnel through Verdict.suppressions == [] and must not surface
    # the section.
    if verdict.suppressions:
        n = len(verdict.suppressions)
        lines.append("")
        lines.append(f"**Suppressions added ({n}):**")
        lines.append("")
        lines.append("| File | Line | Marker | Zone |")
        lines.append("|---|---|---|---|")
        shown = verdict.suppressions[:5]
        for s in shown:
            lines.append(f"| `{s.file}` | {s.line} | `{s.marker}` | {s.zone} |")
        if n > 5:
            lines.append(f"| (+{n - 5} more) | | | |")
        lines.append("")
        lines.append(
            "Suppressions on guarded surfaces require `architecture-review`."
        )
        lines.append("")
        lines.append(
            "[Why this matters](docs/agent/boundary-violation.md#suppressions)"
        )
        lines.append("")

    # Other signals
    if verdict.api_changes.get("detected"):
        spec_diff = verdict.api_changes.get("specDiff")
        if spec_diff:
            lines.extend(_render_api_spec_diff(spec_diff))
        else:
            lines.append("**API check:** changes detected")
    else:
        lines.append("**API check:** no changes")
    if verdict.schema_changes.get("detected"):
        lines.append("**Schema check:** changes detected")
    if verdict.security_changes.get("detected"):
        lines.append("**Security check:** changes detected")
    if verdict.runtime_config_changes.get("detected"):
        lines.append("**Runtime config check:** changes detected")

    # Change-size line. PR-mode calls it "PR size" (matches the surface
    # the reviewer sees — a pull request); push-mode calls it "Change
    # size" (no PR exists; the unit is the push diff). When the policy's
    # excludes filtered out files from the size budget, surface the
    # subtracted totals so the math is visible (prevents users from
    # being surprised that the verdict's lines/files don't match
    # `git diff --shortstat`).
    sz = verdict.pr_size
    size_label = "Change size" if flow_mode == "push" else "PR size"
    suffix = ""
    excluded_files = sz.get("excludedFiles", 0) or 0
    excluded_lines = sz.get("excludedLines", 0) or 0
    if excluded_files or excluded_lines:
        suffix = f" — {excluded_files} files / {excluded_lines} lines excluded by policy"
    lines.append(f"**{size_label}:** {sz['files']} files / {sz['lines']} lines ({sz['verdict']}){suffix}")

    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------

def _find_policy_schema() -> Path | None:
    """Locate agent-policy.schema.json.

    Resolution order:
      1. Vendored repo-root copy `.agent-redline/agent-policy.schema.json`
         — how a consuming repo carries it (mirrors the vendored
         suppressions.yaml pattern; the reporter runs with CWD = repo root).
      2. dev repo:  core/reporter/reporter.py → ../schema/agent-policy.schema.json
      3. vendored skill layout: agent-redline/scripts/agent-redline-report.py
                                → ../assets/schema/agent-policy.schema.json
    First existing candidate wins. Returns None if none are found — the
    caller degrades to no validation.
    """
    here = Path(__file__).resolve().parent
    candidates = [
        Path(".") / ".agent-redline" / "agent-policy.schema.json",       # vendored, repo-root
        here / ".." / "schema" / "agent-policy.schema.json",              # dev layout
        here / ".." / "assets" / "schema" / "agent-policy.schema.json",   # vendored skill layout
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    return None


def load_policy(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"error: policy at {path} is not a mapping")

    # Validate against agent-policy.schema.json. A schema-invalid policy is
    # the class of bug that silently disabled codeowner-approval satisfaction,
    # PR-size excludes, and boundary declarations on real installs — the
    # reporter reads the keys it knows and ignores the rest, so a malformed
    # policy passes every gate green. Hard-fail here turns those into a loud
    # error the moment the reporter runs.
    #
    # Degrades gracefully when the pieces aren't present: no jsonschema
    # installed (some pre-push machines) or schema file not locatable → warn
    # to stderr and continue. CI installs jsonschema explicitly, so the gate
    # is real where it counts.
    try:
        import jsonschema  # type: ignore
    except ImportError:
        sys.stderr.write(
            "warning: jsonschema not installed; skipping policy schema "
            "validation. Install jsonschema to validate agent-redline-policy.yaml.\n"
        )
        return data

    schema_path = _find_policy_schema()
    if schema_path is None:
        sys.stderr.write(
            "warning: could not locate agent-policy.schema.json next to the "
            "reporter; skipping policy schema validation.\n"
        )
        return data

    with schema_path.open(encoding="utf-8") as f:
        schema = json.load(f)
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        loc = "/".join(str(p) for p in e.absolute_path) or "(root)"
        raise SystemExit(
            f"error: policy at {path} is invalid against agent-policy.schema.json\n"
            f"  at: {loc}\n"
            f"  {e.message}"
        )
    return data



def load_diff_from_files(
    changed_files_path: Path,
    lines_changed: int = 0,
    lines_per_file_path: Path | None = None,
    diff_unified_path: Path | None = None,
) -> Diff:
    files = [line.strip() for line in changed_files_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    lines_by_file: dict[str, int] | None = None
    if lines_per_file_path is not None and lines_per_file_path.exists():
        # `git diff --numstat` rows: <added>\t<deleted>\t<path>. Either
        # numeric column may be "-" for binary files; treat those as 0.
        lines_by_file = {}
        for raw in lines_per_file_path.read_text(encoding="utf-8").splitlines():
            row = raw.rstrip("\n")
            if not row.strip():
                continue
            parts = row.split("\t")
            if len(parts) < 3:
                continue
            added_s, deleted_s, path = parts[0], parts[1], "\t".join(parts[2:])
            added = int(added_s) if added_s.isdigit() else 0
            deleted = int(deleted_s) if deleted_s.isdigit() else 0
            lines_by_file[path] = added + deleted
        # When numstat is given, derive the scalar from it for consistency.
        # (The workflow's `git diff --shortstat` and `git diff --numstat`
        # see the same diff, so the totals should match; we recompute
        # locally to avoid silent disagreement.)
        if lines_by_file:
            lines_changed = sum(lines_by_file.values())

    added_by_file: dict[str, list[tuple[int, str]]] | None = None
    if diff_unified_path is not None and diff_unified_path.exists():
        added_by_file = parse_unified_diff(
            diff_unified_path.read_text(encoding="utf-8")
        )

    return Diff(
        changed_files=files,
        files_changed=len(files),
        lines_changed=lines_changed,
        lines_by_file=lines_by_file,
        added_by_file=added_by_file,
    )


def load_archunit_xml(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def load_boundary_report(path: Path | None) -> str | None:
    """Load a boundary report file. Format-agnostic — caller decides how to parse."""
    if path is None or not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def resolve_boundary_input(
    explicit_path: Path | None,
    explicit_format: str | None,
    legacy_archunit_path: Path | None,
    policy: dict[str, Any],
) -> tuple[str | None, str | None]:
    """
    Resolve which boundary report and format to use, given CLI flags + policy.

    Precedence:
      1. --boundary-report + --boundary-format on the CLI (canonical).
      2. --archunit-xml on the CLI (deprecated alias for junit-xml).
      3. policy.boundaryAdapter (when present and outputFormat != 'none').
      4. Nothing — boundary parsing is skipped.

    Raises FileNotFoundError when a boundary report is configured but absent.
    Silent fallthrough would let a misconfigured CI run produce a clean
    BLUE verdict despite policy declaring a backend — that hides the
    deterministic boundary check the policy promised. Set
    boundaryAdapter.outputFormat: none to opt out explicitly.

    Returns (report_text, format) or (None, None) only when no source is
    configured at all.
    """
    if explicit_path is not None:
        text = load_boundary_report(explicit_path)
        if text is None:
            raise FileNotFoundError(
                f"--boundary-report path does not exist: {explicit_path}. "
                f"The boundary backend must produce this file before the reporter runs."
            )
        return text, (explicit_format or "junit-xml")
    if legacy_archunit_path is not None:
        text = load_archunit_xml(legacy_archunit_path)
        if text is None:
            raise FileNotFoundError(
                f"--archunit-xml path does not exist: {legacy_archunit_path}. "
                f"The boundary backend must produce this file before the reporter runs."
            )
        return text, "junit-xml"
    adapter = (policy.get("boundaryAdapter") or {}) if isinstance(policy, dict) else {}
    fmt = adapter.get("outputFormat")
    out_path = adapter.get("outputPath")
    if fmt and fmt != "none" and out_path:
        # Resolve glob first match (mirrors Spring's TEST-*ArchitectureTest.xml pattern).
        matches = sorted(Path(".").glob(out_path))
        if not matches:
            raise FileNotFoundError(
                f"policy.boundaryAdapter.outputPath matched no file: {out_path!r}. "
                f"The boundary backend ({fmt}) must produce a report at this path "
                f"before the reporter runs. Set boundaryAdapter.outputFormat: none "
                f"to opt out of boundary enforcement explicitly."
            )
        return matches[0].read_text(encoding="utf-8"), fmt
    return None, None


def _load_api_spec_diff(base: Path | None, head: Path | None) -> dict[str, Any] | None:
    """
    Load both OpenAPI specs and compute the structural diff.

    Returns None when neither path is provided (api_spec_diff has no signal).
    Returns the diff dict when both are provided. If only one is provided,
    treat the other as empty (an added or removed contract).
    """
    if base is None and head is None:
        return None
    base_text = base.read_text(encoding="utf-8") if base and base.exists() else ""
    head_text = head.read_text(encoding="utf-8") if head and head.exists() else ""
    return diff_openapi_specs(base_text, head_text)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="agent-redline reporter")
    p.add_argument("--policy", required=True, type=Path, help="Path to agent-redline-policy.yaml")
    p.add_argument("--changed-files", type=Path,
                   help="Path to a newline-separated list of changed files (overrides --base/--head)")
    p.add_argument("--lines-changed", type=int, default=0,
                   help="Total lines changed (size check). Used as the fallback "
                        "when --lines-per-file is not given. The scalar is "
                        "NOT excludes-aware on its own — pass --lines-per-file "
                        "to make excludes apply to size accounting.")
    p.add_argument("--lines-per-file", type=Path,
                   help="Path to a `git diff --numstat` output file (one row "
                        "per changed file: added<TAB>deleted<TAB>path). When "
                        "provided, `policy.excludes` is applied to the size "
                        "check: files matching any excludes glob are subtracted "
                        "from both file and line counts. Without this flag, "
                        "excludes affects only zone classification, not size.")
    p.add_argument("--diff-unified", type=Path,
                   help="Path to a unified diff with -U0 (produced by "
                        "`git diff --unified=0 <base> <head>`). Used by "
                        "Phase-4 suppression detection to read added-line "
                        "content. Optional; absent -> suppression detection "
                        "falls back to no-op (compatible with policies that "
                        "lack a suppressions block).")
    p.add_argument("--archunit-xml", type=Path,
                   help="(Deprecated) Path to an ArchUnit JUnit XML report. Use "
                        "--boundary-report with --boundary-format=junit-xml instead.")
    p.add_argument("--boundary-report", type=Path,
                   help="Path to the boundary-rule backend's report file. Format "
                        "is given by --boundary-format (or inferred from "
                        "policy.boundaryAdapter when this flag is omitted).")
    p.add_argument("--boundary-format",
                   choices=["junit-xml", "json-violations", "none"],
                   help="Format of the file passed to --boundary-report. Defaults to "
                        "policy.boundaryAdapter.outputFormat, then to junit-xml.")
    p.add_argument("--api-spec-base", type=Path,
                   help="Path to the OpenAPI spec generated at the base SHA "
                        "(for api.type=openapi-from-controllers; the workflow generates this)")
    p.add_argument("--api-spec-head", type=Path,
                   help="Path to the OpenAPI spec generated at the head SHA")
    p.add_argument("--pr-labels", default="", help="Comma-separated PR labels")
    p.add_argument("--codeowner-approvals", default="",
                   help="Comma-separated CODEOWNER approver logins")
    p.add_argument("--flow-mode", default="pr", choices=["pr", "push"],
                   help="Flow shape of the surrounding CI workflow. 'pr' (default) "
                        "renders checkpoint satisfier text as 'Satisfy by: CODEOWNER "
                        "approval or label X' (PR-mode mechanics). 'push' renders "
                        "it as a review obligation on the commit that already "
                        "landed, since CODEOWNER approval / labels don't apply on a "
                        "direct push.")
    p.add_argument("--default-mode", default="shadow", choices=["shadow", "binding"],
                   help="Fallback for modes.default when the policy does not set it. The policy always wins if it pins modes.default; this flag only fills in a missing value.")
    p.add_argument("--mode", dest="default_mode_legacy", default=None,
                   choices=["shadow", "binding"],
                   help=argparse.SUPPRESS)  # Deprecated alias for --default-mode; kept for back-compat.
    p.add_argument("--json-out", type=Path, help="Write JSON verdict to this file")
    p.add_argument("--comment-out", type=Path, help="Write markdown PR comment to this file")
    args = p.parse_args(argv)

    policy = load_policy(args.policy)

    # Resolve --default-mode (canonical) vs the deprecated --mode alias.
    default_mode = args.default_mode_legacy if args.default_mode_legacy is not None else args.default_mode

    # Apply --default-mode as a fallback for modes.default if the policy doesn't pin it.
    if "modes" not in policy:
        policy["modes"] = {}
    policy["modes"].setdefault("default", default_mode)

    if args.changed_files is None:
        sys.stderr.write("error: --changed-files required in v0.1 (git-driven mode is roadmap)\n")
        return 1

    diff = load_diff_from_files(
        args.changed_files,
        args.lines_changed,
        lines_per_file_path=args.lines_per_file,
        diff_unified_path=args.diff_unified,
    )

    if args.archunit_xml is not None:
        sys.stderr.write(
            "warning: --archunit-xml is deprecated; use --boundary-report "
            "with --boundary-format=junit-xml instead\n"
        )

    try:
        boundary_text, boundary_format = resolve_boundary_input(
            args.boundary_report, args.boundary_format,
            args.archunit_xml, policy,
        )
    except FileNotFoundError as e:
        # Mirror the resolve_suppressions_config handler below: a
        # configured-but-missing boundary report is a config error, not a
        # crash. Bare traceback + exit 1 gets silently downgraded to a
        # shadow warning by CI, hiding the misconfiguration.
        sys.stderr.write(f"error: {e}\n")
        return 1
    api_spec_diff = _load_api_spec_diff(args.api_spec_base, args.api_spec_head)

    # Phase 4b.4: resolve the suppression marker list once per CLI invocation.
    # repo_root is the CWD because that's where `--changed-files` paths are
    # anchored AND where `.agent-redline/suppressions.yaml` lives in the
    # consuming repo. Returns None when the policy has no `suppressions:`
    # block — detection stays OFF and end-to-end behavior is unchanged for
    # policies that haven't opted in (spec §1.4).
    try:
        suppressions_cfg = resolve_suppressions_config(policy, repo_root=Path("."))
    except FileNotFoundError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1

    pr_labels = [s.strip() for s in args.pr_labels.split(",") if s.strip()]
    codeowner_approvals = [s.strip() for s in args.codeowner_approvals.split(",") if s.strip()]

    # Load CODEOWNERS (F2). Empty list when no file exists — the
    # checkpoint then degrades to "any approver satisfies," with a
    # note in satisfy_by_human so reviewers see the path check
    # wasn't performed.
    codeowners_rules = load_codeowners(Path("."))

    verdict = classify(
        policy, diff,
        boundary_report=boundary_text,
        boundary_format=boundary_format,
        api_spec_diff=api_spec_diff,
        pr_labels=pr_labels,
        codeowner_approvals=codeowner_approvals,
        codeowners_rules=codeowners_rules,
        suppressions_config=suppressions_cfg,
    )

    if args.json_out:
        args.json_out.write_text(json.dumps(verdict.to_dict(), indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps(verdict.to_dict(), indent=2))

    comment = render_markdown(verdict, flow_mode=args.flow_mode)
    if args.comment_out:
        args.comment_out.write_text(comment, encoding="utf-8")

    return verdict.exit_code


if __name__ == "__main__":
    sys.exit(main())
