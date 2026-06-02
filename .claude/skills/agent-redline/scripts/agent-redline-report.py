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
    """A simplified diff: list of changed files plus line-count totals."""
    changed_files: list[str]
    files_changed: int
    lines_changed: int


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
    verdict: str   # BLUE | RED | GRAY | BOUNDARY_VIOLATION | MIXED | API_CHANGE | SCHEMA_CHANGE | SECURITY_CHANGE
    summary: str
    zones: dict[str, list[str]]
    checkpoints: list[CheckpointStatus]
    boundary_violations: list[BoundaryViolation]
    api_changes: dict[str, Any]
    schema_changes: dict[str, Any]
    security_changes: dict[str, Any]
    pr_size: dict[str, Any]
    exit_code: int
    recommended_action: str

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
            "prSize": self.pr_size,
            "exitCode": self.exit_code,
            "recommendedAction": self.recommended_action,
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

    return required


def _is_satisfied(
    checkpoint_def: dict[str, Any],
    pr_labels: Iterable[str],
    codeowner_approvals: Iterable[str],
) -> tuple[bool, list[str]]:
    """OR-semantics over satisfiedBy entries. Returns (satisfied, satisfy_by_human)."""
    satisfied_by = checkpoint_def.get("satisfiedBy", []) or []
    labels = set(pr_labels)
    has_codeowner = bool(list(codeowner_approvals))

    satisfy_by_human: list[str] = []
    satisfied = False
    for sb in satisfied_by:
        if sb == "codeownerApproval":
            satisfy_by_human.append("CODEOWNER approval")
            if has_codeowner:
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
    # The standard glob the spring-archunit profile uses; agent-redline
    # treats architecture-test files as red regardless of policy.
    "src/test/java/**/architecture/**",
    # Common alternates for other ecosystems
    "**/architecture/**",
)


def _is_architecture_test_file(path: str) -> bool:
    return any(matches(path, g) for g in ARCHITECTURE_TEST_GLOBS)


def _pr_size_status(diff: Diff, policy: dict[str, Any]) -> dict[str, Any]:
    pr_rules = policy.get("prRules", {}) or {}
    files_rule = pr_rules.get("maxChangedFiles", {}) or {}
    lines_rule = pr_rules.get("maxLinesChanged", {}) or {}

    fail_files = files_rule.get("fail", 100)
    warn_files = files_rule.get("warn", 50)
    fail_lines = lines_rule.get("fail", 2000)
    warn_lines = lines_rule.get("warn", 1000)

    verdict = "ok"
    if diff.files_changed > fail_files or diff.lines_changed > fail_lines:
        verdict = "fail"
    elif diff.files_changed > warn_files or diff.lines_changed > warn_lines:
        verdict = "warn"

    return {
        "files": diff.files_changed,
        "lines": diff.lines_changed,
        "verdict": verdict,
    }


def _binding(modes: dict[str, Any], check_name: str) -> bool:
    """Whether a given check is binding under the policy's modes config."""
    default = (modes or {}).get("default", "shadow")
    per_check = (modes or {}).get("perCheck", {}) or {}
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
    )

    checkpoints_defs = policy.get("checkpoints", {}) or {}
    checkpoint_statuses: list[CheckpointStatus] = []
    for cp_id, reason in required.items():
        cp_def = checkpoints_defs.get(cp_id, {})
        satisfied, satisfy_by = _is_satisfied(cp_def, pr_labels, codeowner_approvals)
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
        pr_size=pr_size,
        exit_code=exit_code,
        recommended_action=recommended,
    )


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


def render_markdown(verdict: Verdict) -> str:
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

    # PR size
    sz = verdict.pr_size
    lines.append(f"**PR size:** {sz['files']} files / {sz['lines']} lines ({sz['verdict']})")

    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------

def load_policy(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"error: policy at {path} is not a mapping")
    return data


def load_diff_from_files(changed_files_path: Path, lines_changed: int = 0) -> Diff:
    files = [line.strip() for line in changed_files_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return Diff(changed_files=files, files_changed=len(files), lines_changed=lines_changed)


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

    Returns (report_text, format) or (None, None).
    """
    if explicit_path is not None:
        text = load_boundary_report(explicit_path)
        return text, (explicit_format or "junit-xml")
    if legacy_archunit_path is not None:
        text = load_archunit_xml(legacy_archunit_path)
        if text is not None:
            return text, "junit-xml"
    adapter = (policy.get("boundaryAdapter") or {}) if isinstance(policy, dict) else {}
    fmt = adapter.get("outputFormat")
    out_path = adapter.get("outputPath")
    if fmt and fmt != "none" and out_path:
        # Resolve glob first match (mirrors Spring's TEST-*ArchitectureTest.xml pattern).
        matches = sorted(Path(".").glob(out_path))
        if matches:
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
    p.add_argument("--policy", required=True, type=Path, help="Path to agent-policy.yaml")
    p.add_argument("--changed-files", type=Path,
                   help="Path to a newline-separated list of changed files (overrides --base/--head)")
    p.add_argument("--lines-changed", type=int, default=0,
                   help="Total lines changed (for PR-size check)")
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

    diff = load_diff_from_files(args.changed_files, args.lines_changed)

    if args.archunit_xml is not None:
        sys.stderr.write(
            "warning: --archunit-xml is deprecated; use --boundary-report "
            "with --boundary-format=junit-xml instead\n"
        )

    boundary_text, boundary_format = resolve_boundary_input(
        args.boundary_report, args.boundary_format,
        args.archunit_xml, policy,
    )
    api_spec_diff = _load_api_spec_diff(args.api_spec_base, args.api_spec_head)

    pr_labels = [s.strip() for s in args.pr_labels.split(",") if s.strip()]
    codeowner_approvals = [s.strip() for s in args.codeowner_approvals.split(",") if s.strip()]

    verdict = classify(
        policy, diff,
        boundary_report=boundary_text,
        boundary_format=boundary_format,
        api_spec_diff=api_spec_diff,
        pr_labels=pr_labels,
        codeowner_approvals=codeowner_approvals,
    )

    if args.json_out:
        args.json_out.write_text(json.dumps(verdict.to_dict(), indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps(verdict.to_dict(), indent=2))

    comment = render_markdown(verdict)
    if args.comment_out:
        args.comment_out.write_text(comment, encoding="utf-8")

    return verdict.exit_code


if __name__ == "__main__":
    sys.exit(main())
