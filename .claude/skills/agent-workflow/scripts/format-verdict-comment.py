#!/usr/bin/env python3
"""Format a checker verdict JSON file as a developer-friendly Markdown comment.

The sticky PR comment is the harness's developer-facing surface. The
renderer translates the verdict JSON (structural, harness-internal)
into prose a developer reading a PR can act on without learning
harness vocabulary.

Three render shapes:

- **Clean** — workflow checks passed. Headline + scope + collapsed
  audit detail. 2-3 visible lines.
- **Action required** — at least one blocking predicate failed.
  Headline names how many records need action; per-record action
  blocks tell the developer what to do, why, and how. Audit detail
  collapsed below.
- **No Work Records** — the PR didn't touch any task file under
  ``.agent-workflow/tasks/``. One-line note.

Multi-record consolidation: when ≥2 records fail the same blocking
predicate with the same fix, the action block appears once with the
affected-records list. Different fixes stay per-record.

Skip-summarisation: within a group, when ALL checks are
``passed=True`` and ``detail`` starts with ``skipped —`` (i.e. the
whole group was short-circuited by an upstream blocker), the group
renders as one summary line instead of one row per check.

Jargon translation: harness terms (``predicate``, ``marker block``,
``Verification Record``, ``satisfy by:``, ``red zone``) are
translated to plain prose at render time. The audit ``<details>`` is
the only place dotted predicate names appear, and even there they are
grouped under plain-English headings.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Predicate → group mapping (plain-English names)
# ---------------------------------------------------------------------------

# First segment of the dotted predicate name → group display name.
# An unknown segment falls back to "Other checks." Adding a predicate
# whose first segment is new is fine — it'll just land in "Other."
_GROUPS: dict[str, str] = {
    "workrecord": "Work Record structure",
    "risk": "Risk classification",
    "complexity": "Risk classification",  # paired with risk in the dev's mental model
    "exceptions": "Exceptions",
    "approval": "Plan approvals",
    "evidence": "Verification plan",
    "review": "Required reviews",
}


def _group_for(predicate_name: str) -> str:
    head = predicate_name.split(".", 1)[0]
    return _GROUPS.get(head, "Other checks")


# ---------------------------------------------------------------------------
# Jargon translation
# ---------------------------------------------------------------------------
#
# Two-stage: (1) word-level substitutions that always apply; (2) a
# best-effort prose-clean for predicate detail strings (strip leading
# "predicate: ", normalise "satisfy by:" → "to fix this:", etc).

_WORD_SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    ("Verification Record", "verification plan"),
    ("verification_plan field", "verification plan"),
    ("marker block", "the structured block in the task file"),
    ("Work Record block", "task file"),
    ("red zone", "an architecture-protected area"),
    ("Routine-path", "routine-shape"),
    ("Routine path", "routine shape"),
    ("expanded-path", "expanded-shape"),
    ("expanded path", "expanded shape"),
)


def _translate_jargon(text: str) -> str:
    """Apply jargon substitutions to a detail string for human reading.

    Word-level only — we don't try to rewrite full sentences. Predicate
    dotted names are left as-is in the audit ``<details>`` (where
    they're useful for greppability); the headline/action blocks never
    surface them.
    """
    out = text
    for needle, replacement in _WORD_SUBSTITUTIONS:
        out = out.replace(needle, replacement)
    # ``satisfy by:`` (case-insensitive, optional leading punctuation)
    # is the most common phrase the dev sees. Replace globally.
    out = re.sub(
        r"(?i)\bsatisfy\s+by\s*:\s*", "To fix this: ", out
    )
    return out


# ---------------------------------------------------------------------------
# Action templates
# ---------------------------------------------------------------------------
#
# Each entry returns (action_headline, why, how) given the predicate
# detail and the record slug. Headlines never reveal predicate dotted
# names; they describe what the developer does. ``how`` is the
# concrete fix in one sentence. ``why`` is one sentence about the
# trigger that made the check fail.
#
# Predicates without an entry fall back to a generic block that
# reproduces the (translated) detail string.

_FIELDS_RE = re.compile(r"missing required (?:routine|expanded)-path field\(s\):\s*([\w, ]+)", re.IGNORECASE)
_CHECKPOINT_ID_RE = re.compile(r"unsatisfied checkpoint '([^']+)'", re.IGNORECASE)
_SATISFY_RE = re.compile(r"satisfy by:\s*([^.\n]+)", re.IGNORECASE)
_CHECKPOINT_FILE_RE = re.compile(
    r"red-zone change:\s*([^;]+);", re.IGNORECASE
)
_NON_WAIVABLE_RE = re.compile(
    r"non-waivable predicate\(s\):\s*'([^']+)'", re.IGNORECASE
)


def _missing_fields(detail: str) -> list[str]:
    """Extract the list of missing field names from a fields-present detail."""
    m = _FIELDS_RE.search(detail)
    if not m:
        return []
    return [s.strip() for s in m.group(1).split(",") if s.strip()]


def _checkpoint_info(detail: str) -> tuple[str, str, str]:
    """Pull (checkpoint id, file path, satisfy-by) out of a checkpoint detail.

    Detail shape:
        unsatisfied checkpoint '<id>' — red-zone change: <path>; satisfy by: <opts>
    """
    cid = _CHECKPOINT_ID_RE.search(detail)
    fp = _CHECKPOINT_FILE_RE.search(detail)
    sby = _SATISFY_RE.search(detail)
    return (
        cid.group(1) if cid else "<unknown>",
        fp.group(1).strip() if fp else "",
        sby.group(1).strip() if sby else "",
    )


# Plain-English summaries of what each named review checkpoint is for.
# Keeps the "why" copy honest about what the reviewer is actually
# protecting against, instead of citing checkpoint names a developer
# may never have seen before. Unknown checkpoint ids fall back to a
# generic "the repo's policy requires a review."
_CHECKPOINT_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    # (what-it-protects, what-the-reviewer-is-checking)
    "architecture-review": (
        "the repo's architectural rules",
        "the change keeps the layering and boundary rules intact",
    ),
    "api-review": (
        "the public API contract",
        "the change is backwards-compatible (or breakage is intentional and documented)",
    ),
    "persistence-review": (
        "the database schema and migrations",
        "the migration is forward-only, multi-tenant-safe, and rolls out cleanly",
    ),
    "security-review": (
        "security-sensitive code",
        "the change doesn't introduce vulnerabilities, weaken auth, or expose secrets",
    ),
    "ops-review": (
        "runtime configuration",
        "the change behaves correctly across environments and won't break deploys",
    ),
}


def _explain_satisfy(satisfy_by_raw: str, checkpoint_id: str) -> str:
    """Turn the comma-separated satisfy-by list into a developer-readable list.

    Input shape (from redline): ``CODEOWNER approval, label `<name>``` or
    individual entries separated by commas. Output: two bullet-list
    options the developer can follow without prior context.
    """
    opts = [o.strip() for o in satisfy_by_raw.split(",") if o.strip()]
    rendered: list[str] = []
    label_name: str | None = None
    has_codeowner = False
    for opt in opts:
        if "label" in opt.lower():
            # Pull the backticked label name if present.
            m = re.search(r"`([^`]+)`", opt)
            if m:
                label_name = m.group(1)
        elif "codeowner" in opt.lower():
            has_codeowner = True
    if has_codeowner:
        rendered.append(
            "Get an approving review from someone listed in `.github/CODEOWNERS` "
            "for this path (GitHub auto-requests them when the PR opens)."
        )
    if label_name:
        rendered.append(
            f"Or ask a maintainer with write access to add the `{label_name}` "
            f"label to this PR (Labels sidebar on the right → search → click)."
        )
    if not rendered:
        # Unknown satisfy shape — fall back to the raw text.
        rendered.append(f"Satisfy via: {satisfy_by_raw}")
    return "\n".join(f"- {r}" for r in rendered)


def _a_or_an(word: str) -> str:
    """English a/an article for a following word, vowel-sound heuristic.

    Imperfect but good enough for our small vocabulary ("architecture
    review" → "an", "persistence review" → "a", etc.).
    """
    if not word:
        return "a"
    return "an" if word[0].lower() in "aeiou" else "a"


def _action_for(predicate: dict, slug: str) -> tuple[str, str, str, str] | None:
    """Return (headline, why, how, signature) for a blocking failed predicate.

    Copy is written for a cold reader — a developer who's never seen
    the harness internals and won't read the harness documentation.
    Each block must answer: what changed, why a reviewer cares, what
    to click or type to fix it.

    ``signature`` is the consolidation key — predicates+detail combos
    that yield the same signature consolidate into one action block
    across records. Returns None when the predicate has no bespoke
    template (caller renders a fallback action block).
    """
    name = predicate["name"]
    detail = predicate["detail"]

    if name == "review.checkpoints_satisfied":
        cid, file_path, sby = _checkpoint_info(detail)
        desc = _CHECKPOINT_DESCRIPTIONS.get(cid)
        if desc:
            protects, reviewer_checks = desc
        else:
            protects = "code in this area"
            reviewer_checks = "the change is safe to merge"
        file_clause = (
            f"`{file_path}`" if file_path else "a path in a protected area"
        )
        # Use plain prose for the human-readable name rather than the
        # bare checkpoint id (which reads awkwardly with "a" / "an").
        readable_name = cid.replace("-", " ")
        article = _a_or_an(readable_name)
        why = (
            f"This PR modified {file_clause}, which the repo's policy "
            f"protects with {article} {readable_name}. Reviewers check that "
            f"{reviewer_checks}, before code touching {protects} ships."
        )
        how = _explain_satisfy(sby, cid)
        return (
            f"Get {article} {readable_name} on this PR",
            why,
            how,
            f"review:{cid}:{sby}",
        )

    if name == "risk.declared_not_below_detected":
        m = re.search(r"declared '(\w+)' is below detected '(\w+)'", detail)
        declared, detected = (m.group(1), m.group(2)) if m else ("?", "?")
        why = (
            f"The task file declares Risk `{declared}`, but the PR's diff "
            f"touches files the repo's policy classifies as `{detected}` — "
            f"higher than what was declared. Risk drives which approvals and "
            f"reviews are required, so it has to match the diff before merge."
        )
        how_lines = [
            f"Open the task file `.agent-workflow/tasks/{slug}.md` and find the "
            f"line `**Risk:** {declared}` inside the `<!-- agent-workflow:start "
            f"--> ... <!-- agent-workflow:end -->` block.",
            f"Change it to `**Risk:** {detected}`.",
        ]
        if detected != "Routine":
            how_lines.append(
                "If the task file currently uses the compact (routine) layout, "
                "you'll also need to migrate it to the expanded layout. The "
                "expanded layout adds fields like Discovery, Material assumptions, "
                "Plan, Verification plan, Plan review, and Approvals. The agent "
                "running this task can do the migration for you."
            )
        return (
            f"Bump Risk in the task file from `{declared}` to `{detected}`",
            why,
            "\n\n".join(how_lines),
            f"risk_too_low:{declared}->{detected}",
        )

    if name == "risk.boundary_violation_absent":
        why = (
            "The PR violates an architecture rule that the repo treats as "
            "non-negotiable (typically a layering rule, like 'controllers "
            "may not import database classes directly'). These rules are "
            "non-waivable in place — the harness can't let the change merge "
            "without either fixing the violation in this PR or amending the "
            "rule itself in a separate PR."
        )
        how = (
            "Look at the `## agent-redline` sticky comment on this PR — it "
            "names the specific rule and the offending files. Then either:\n\n"
            "- Restructure this PR so the rule isn't violated (usually the "
            "right answer), **or**\n"
            "- Open a separate PR that changes the architecture rule itself "
            "(in `agent-redline-policy.yaml` or the architecture-test "
            "file the policy points at). Get that PR reviewed and merged "
            "first, then rebase this one."
        )
        return (
            "Fix the architecture violation flagged by agent-redline",
            why,
            how,
            f"boundary:{slug}",
        )

    if name == "risk.redline_findings_available":
        return (
            "agent-redline didn't produce a verdict for this PR",
            (
                "agent-redline is the CI job that classifies which files in "
                "the PR are architecturally sensitive. It didn't produce a "
                "verdict file this run, so the workflow check can't tell "
                "what the PR touches. This is a CI configuration problem, "
                "not a code problem."
            ),
            (
                "Check the `redline` job's logs in the PR's Checks tab. If "
                "the job failed, fix that first. If the job didn't run at "
                "all, the workflow file may be misconfigured — see "
                "`.github/workflows/agent-workflow.yml` and confirm the "
                "redline job is present and wired correctly."
            ),
            "redline_missing",
        )

    if name in ("workrecord.routine_fields_present", "workrecord.expanded_fields_present"):
        fields = _missing_fields(detail)
        if fields:
            field_list = ", ".join(f"`{f}`" for f in fields)
            why = (
                f"The task file at `.agent-workflow/tasks/{slug}.md` is "
                f"missing required fields: {field_list}. Each engineering "
                f"task records its scope, plan, and risk classification in "
                f"this file so reviewers (and future readers) can see what "
                f"the change was about. Empty fields block merge — they "
                f"indicate the planning step was incomplete."
            )
            how = (
                f"Open `.agent-workflow/tasks/{slug}.md` and fill in the "
                f"missing fields ({field_list}) inside the "
                f"`<!-- agent-workflow:start --> ... <!-- agent-workflow:end "
                f"-->` block. Each field is a single line or short "
                f"paragraph; the agent driving the task can fill them in "
                f"based on the PR's purpose."
            )
            return (
                f"Fill missing fields in the task file: {field_list}",
                why,
                how,
                f"missing_fields:{','.join(sorted(fields))}",
            )
        # Detail didn't expose missing-field list — fall through.

    if name == "workrecord.shape_matches_classification":
        return (
            "The task file's layout doesn't match its risk classification",
            (
                "Task files come in two layouts. The compact layout is "
                "allowed only when the task is Routine + Simple — small, "
                "reversible changes. Anything riskier needs the expanded "
                "layout, which records additional fields (Discovery, "
                "Material assumptions, Plan, Verification plan, Plan "
                "review, Approvals). This task's declared Risk and "
                "Complexity don't match the layout it actually uses."
            ),
            (
                "Two options:\n\n"
                "- If the classification is correct, migrate the task file "
                f"`.agent-workflow/tasks/{slug}.md` to the expanded layout. "
                "The agent driving this task can do this for you.\n"
                "- If the classification was wrong (the task is actually "
                "Routine + Simple), correct the Risk and Complexity fields "
                "in the task file instead."
            ),
            "shape_mismatch",
        )

    if name == "approval.high_risk_approval_recorded":
        return (
            "Record a human approval for this high-risk task",
            (
                "This task is classified High risk — typically because the "
                "change is destructive, breaks compatibility, or affects "
                "tenant isolation / financial integrity / production state. "
                "High-risk tasks require a recorded human approval (someone "
                "looking at the plan and saying it's safe to proceed) before "
                "implementation merges."
            ),
            (
                "Before pushing more code, get someone with authority to "
                "approve the plan. Once they say ok, open the task file "
                f"`.agent-workflow/tasks/{slug}.md` and set the `Approvals` "
                "field to:\n\n"
                "```\n"
                "Approved by user <ISO-8601 timestamp>: \"<verbatim quote of "
                "what they said>\"\n"
                "```\n\n"
                "Example: `Approved by user 2026-06-24T15:30:00Z: \"ok, "
                "looks safe — proceed\"`."
            ),
            "high_approval_missing",
        )

    if name == "approval.elevated_clean_context_review_present":
        return (
            "Add a clean-context plan review to the task file",
            (
                "This task is classified Elevated risk. Elevated tasks "
                "require a *clean-context* plan review — a separate agent "
                "(or human) looking at just the plan, without the bias of "
                "having implemented it. This catches plan-level mistakes "
                "before code is written."
            ),
            (
                f"Open `.agent-workflow/tasks/{slug}.md`. Have a fresh "
                f"agent session (or a human reviewer) read just the marker "
                f"block and write a short review. Save the review under a "
                f"`## Plan review` heading in the file. Then set the "
                f"`Plan review` field inside the marker block to point at "
                f"that section (or a session id / artifact path)."
            ),
            "clean_context_missing",
        )

    if name == "approval.clean_context_does_not_satisfy_human":
        return (
            "Separate the plan review from the human approval",
            (
                "The task file records the same reference as both the "
                "clean-context plan review AND the human approval. These "
                "have to stay separate: the plan review is a second pair of "
                "eyes on the plan, the approval is a person with authority "
                "saying the work can ship. They can't be the same artifact."
            ),
            (
                f"Open `.agent-workflow/tasks/{slug}.md`. Make sure the "
                f"`Plan review` field references a review (the prose under "
                f"`## Plan review` or a session id), and the `Approvals` "
                f"field separately records the human's ok in the form "
                f"`Approved by user <timestamp>: \"<verbatim quote>\"`."
            ),
            "approval_collapsed",
        )

    if name.startswith("exceptions."):
        # Special-case the boundary-violation waiver — that's the most
        # common exception failure and the most confusing one in the
        # original copy.
        nw_match = _NON_WAIVABLE_RE.search(detail)
        if nw_match:
            rule = nw_match.group(1)
            return (
                "Remove this exception — the rule it waives can't be waived",
                (
                    f"The task file records an exception that waives the "
                    f"`{rule}` check. That check protects the integrity of "
                    f"every other check — waiving it would let the rest of "
                    f"the verdict become meaningless. The harness refuses "
                    f"exceptions against this kind of structural rule."
                ),
                (
                    f"Open `.agent-workflow/tasks/{slug}.md` and remove the "
                    f"exception entry that names `{rule}`. Address the "
                    f"underlying problem instead — either change the PR so "
                    f"it doesn't trigger `{rule}`, or open a separate PR to "
                    f"update the rule itself if the rule is wrong."
                ),
                f"exception_non_waivable:{rule}",
            )
        return (
            "Fix the exception entry in the task file",
            _translate_jargon(detail),
            (
                f"Open `.agent-workflow/tasks/{slug}.md` and correct the "
                f"`Exceptions` list. Each exception entry needs a `rule` "
                f"(the check being waived), `reason` (why), `scope` (where "
                f"the exception applies), `approver` (who agreed), `expiry` "
                f"(when the exception stops being valid), and "
                f"`compensating_validation` (what stand-in check protects "
                f"the same risk)."
            ),
            f"exception:{name}",
        )

    return None


# ---------------------------------------------------------------------------
# Headline + scope
# ---------------------------------------------------------------------------


def _status_icon(status: str) -> str:
    return {"clean": "✅", "advisory": "⚠️", "blocking": "⛔"}.get(status, "❔")


def _human_age(seconds: float) -> str:
    """Render an age in seconds as 'N hours/days ago'."""
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        h = int(seconds // 3600)
        return f"{h} hour{'s' if h != 1 else ''} ago"
    days = int(seconds // 86400)
    return f"{days} day{'s' if days != 1 else ''} ago"


def _record_age(repo_root: Path, slug: str) -> str | None:
    """File-mtime → human-friendly 'last updated' string.

    Returns None when we can't resolve the path (e.g. running against a
    fixture verdict whose file doesn't exist in this checkout). The
    headline simply omits the timestamp in that case.
    """
    path = repo_root / ".agent-workflow" / "tasks" / f"{slug}.md"
    if not path.exists():
        return None
    try:
        # We deliberately don't import time; calling Path.stat() and
        # comparing to current time via os.path.getmtime + a stub for
        # "now" keeps this testable. Pull current time from env when
        # provided (tests override) else use os.times for monotonic.
        now = float(os.environ.get("AGENT_WORKFLOW_TEST_NOW", _now_seconds()))
        mtime = path.stat().st_mtime
        return _human_age(now - mtime)
    except OSError:
        return None


def _now_seconds() -> float:
    """Wrap time.time so it can be substituted in tests via env var."""
    import time
    return time.time()


def _record_link(slug: str) -> str:
    """Markdown link to the record's task file."""
    return f"[`{slug}`](.agent-workflow/tasks/{slug}.md)"


def _record_state(record: dict) -> str:
    """Extract the State field value from a record's predicates.

    The verdict JSON doesn't surface State directly — but the
    ``workrecord.state_valid`` predicate's detail carries it. Extract
    when we can; fall back to "unknown" gracefully.
    """
    for p in record.get("predicates", []):
        if p["name"] == "workrecord.state_valid":
            m = re.search(r"state '([^']+)'", p["detail"])
            if m:
                return m.group(1)
    return "unknown"


def _record_risk(record: dict) -> str:
    """Extract the declared Risk from a record's predicates."""
    for p in record.get("predicates", []):
        if p["name"] == "risk.declared":
            m = re.search(r"Risk = '([^']+)'", p["detail"])
            if m:
                return m.group(1)
    return "unknown"


def _record_headline_line(record: dict, repo_root: Path) -> str:
    """One-line summary for a single record in the headline area."""
    icon = _status_icon(record["status"])
    slug = record["slug"]
    risk = _record_risk(record)
    state = _record_state(record)
    age = _record_age(repo_root, slug)
    parts = [f"{icon} {_record_link(slug)}", f"Risk: {risk}", f"State: {state}"]
    if age:
        parts.append(f"Last updated: {age}")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Action consolidation
# ---------------------------------------------------------------------------


def _collect_actions(records: list[dict], repo_root: Path) -> list[dict]:
    """Walk all records; bucket blocking failures by signature.

    Returns a list of action buckets in stable order. Each bucket:

        {
            "signature": str,
            "headline": str,
            "why": str,
            "how": str,
            "records": [slug, ...],  # at least one entry
            "is_fallback": bool,     # True when no bespoke template matched
            "predicate_name": str,
        }
    """
    buckets: dict[str, dict] = {}
    order: list[str] = []
    for rec in records:
        slug = rec["slug"]
        for p in rec.get("predicates", []):
            if p["passed"] or not p["blocking"]:
                continue
            mapped = _action_for(p, slug)
            if mapped is None:
                signature = f"fallback:{p['name']}:{p['detail']}"
                bucket = {
                    "signature": signature,
                    "headline": f"Resolve `{p['name'].split('.', 1)[-1].replace('_', ' ')}` check",
                    "why": _translate_jargon(p["detail"]),
                    "how": "See the audit detail below.",
                    "is_fallback": True,
                    "predicate_name": p["name"],
                }
            else:
                headline, why, how, sig_tail = mapped
                signature = f"{p['name']}:{sig_tail}"
                bucket = {
                    "signature": signature,
                    "headline": headline,
                    "why": why,
                    "how": how,
                    "is_fallback": False,
                    "predicate_name": p["name"],
                }
            existing = buckets.get(signature)
            if existing is None:
                bucket["records"] = [slug]
                buckets[signature] = bucket
                order.append(signature)
            else:
                if slug not in existing["records"]:
                    existing["records"].append(slug)
    return [buckets[s] for s in order]


# ---------------------------------------------------------------------------
# Audit `<details>` block — grouped, skip-summarised
# ---------------------------------------------------------------------------


def _is_irrelevant_skip(p: dict) -> bool:
    """A predicate that passed because it didn't apply to this record.

    Skip-summarisation collapses a group when all its predicates are
    ``passed=True`` and their detail starts with ``skipped —``. Some
    predicates skip because they're irrelevant to this record (e.g.
    ``approval.high_risk_approval_recorded`` on a Routine record); we
    want those collapsed too, since the dev doesn't care.
    """
    return bool(p["passed"]) and p["detail"].lstrip().startswith("skipped —")


def _group_predicates(predicates: list[dict]) -> dict[str, list[dict]]:
    """Group predicates by their plain-English group name, preserving order."""
    out: dict[str, list[dict]] = {}
    for p in predicates:
        group = _group_for(p["name"])
        out.setdefault(group, []).append(p)
    return out


def _group_summary_line(group: str, preds: list[dict]) -> str:
    """Render one group as a single summary line for the audit block."""
    total = len(preds)
    failed_blocking = [p for p in preds if not p["passed"] and p["blocking"]]
    failed_advisory = [p for p in preds if not p["passed"] and not p["blocking"]]
    all_skipped = total > 0 and all(_is_irrelevant_skip(p) for p in preds)

    if all_skipped:
        # Use the first predicate's "skipped — <reason>" reason for the
        # group summary. They almost always share a reason; if not, the
        # first is representative enough for the one-line collapse.
        first_reason = preds[0]["detail"].split("—", 1)[-1].strip()
        return f"- ✅ **{group}** — skipped ({first_reason})"
    if not failed_blocking and not failed_advisory:
        return f"- ✅ **{group}** — {total} check{'s' if total != 1 else ''}, all passed"

    bits = []
    if failed_blocking:
        bits.append(f"{len(failed_blocking)} failing")
    if failed_advisory:
        bits.append(f"{len(failed_advisory)} advisory")
    summary = ", ".join(bits)
    # Use ⛔ only when there's a blocking failure; advisory-only groups
    # get ⚠️ so the icon matches the severity.
    icon = "⛔" if failed_blocking else "⚠️"
    return f"- {icon} **{group}** — {total} checks, {summary}"


def _expanded_group_block(group: str, preds: list[dict]) -> list[str]:
    """Render a group with mixed pass/fail — show only the failing rows."""
    lines: list[str] = [_group_summary_line(group, preds)]
    for p in preds:
        if p["passed"]:
            continue
        icon = "⛔" if p["blocking"] else "⚠️"
        translated = _translate_jargon(p["detail"])
        lines.append(f"  - {icon} `{p['name']}` — {translated}")
    return lines


def _audit_block_for_record(record: dict) -> list[str]:
    """Render one record's audit `<details>` content."""
    groups = _group_predicates(record["predicates"])
    lines: list[str] = []
    for group_name, preds in groups.items():
        # Render expanded when ANY non-skipped failure exists; otherwise
        # one summary line. Failing groups always expand; clean and
        # all-skipped groups collapse to one line.
        has_real_failure = any(not p["passed"] for p in preds)
        if has_real_failure:
            lines.extend(_expanded_group_block(group_name, preds))
        else:
            lines.append(_group_summary_line(group_name, preds))
    return lines


# ---------------------------------------------------------------------------
# Top-level format_comment
# ---------------------------------------------------------------------------


def _scope_line(records: list[dict]) -> str:
    """One-line scope: counts + risk-level breakdown."""
    if not records:
        return ""
    by_risk: dict[str, int] = {}
    for r in records:
        risk = _record_risk(r)
        by_risk[risk] = by_risk.get(risk, 0) + 1
    risk_summary = ", ".join(
        f"{n} {risk}" for risk, n in sorted(by_risk.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    n = len(records)
    return f"**Scope:** {n} task file{'s' if n != 1 else ''} ({risk_summary})"


def _footer(verdict: dict) -> str:
    """Render a footer line — commit SHA + run reference."""
    sha = (
        os.environ.get("AGENT_WORKFLOW_COMMIT_SHA")
        or os.environ.get("GITHUB_SHA")
        or ""
    )
    if not sha:
        return ""
    short = sha[:8]
    return f"<sub>Updated against commit `{short}`.</sub>"


def format_comment(verdict: dict, *, repo_root: Path | None = None) -> str:
    """Render a verdict JSON as a developer-friendly Markdown comment.

    ``repo_root`` is used to read task-file mtime for the
    "Last updated" cue. Defaults to ``.`` when omitted; the CI workflow
    invokes with the repo's checkout root.
    """
    if repo_root is None:
        repo_root = Path(".")
    status = verdict.get("status", "unknown")
    records = verdict.get("records", []) or []

    out: list[str] = []

    if not records:
        # PR didn't touch any task file. One-line advisory.
        out.append("## ⚠️ No task file changed in this PR")
        out.append("")
        out.append(
            "This PR didn't modify any file under `.agent-workflow/tasks/`. "
            "If this PR is part of an engineering task with a Work Record, ensure "
            "the Work Record reflects the work done. Otherwise dismiss this advisory."
        )
        foot = _footer(verdict)
        if foot:
            out.append("")
            out.append(foot)
        return "\n".join(out) + "\n"

    # Collect actions across all records BEFORE deciding the headline —
    # the headline needs the action count.
    actions = _collect_actions(records, repo_root) if status != "clean" else []
    blocking_record_count = sum(1 for r in records if r["status"] == "blocking")

    if status == "clean":
        n = len(records)
        word = "task file" if n == 1 else "task files"
        out.append(f"## ✅ Workflow checks passed — {n} {word}")
    elif status == "advisory":
        out.append("## ⚠️ Advisory: workflow checks have non-blocking findings")
    else:
        # blocking
        if blocking_record_count == 1 and len(actions) == 1:
            out.append(f"## ⛔ Action required: {actions[0]['headline']}")
        else:
            out.append(
                f"## ⛔ Action required on {blocking_record_count} of {len(records)} task file{'s' if len(records) != 1 else ''}"
            )

    out.append("")

    # Scope line + per-record headlines.
    scope = _scope_line(records)
    if scope:
        out.append(scope)
        out.append("")
    for rec in records:
        out.append(f"- {_record_headline_line(rec, repo_root)}")
    out.append("")

    # Action blocks (consolidated when applicable).
    if actions:
        out.append("---")
        out.append("")
        for action in actions:
            slug_part = ""
            if len(action["records"]) == 1:
                slug_part = f" — `{action['records'][0]}`"
            out.append(f"### ⛔ {action['headline']}{slug_part}")
            out.append("")
            out.append(f"**Why:** {action['why']}")
            out.append("")
            # When `how` starts with a bullet/list, the **How:** label
            # goes on its own line so the markdown list renders.
            how_text = action["how"]
            if how_text.lstrip().startswith("-"):
                out.append("**How:**")
                out.append("")
                out.append(how_text)
            else:
                out.append(f"**How:** {how_text}")
            if len(action["records"]) > 1:
                affects = ", ".join(f"`{s}`" for s in action["records"])
                out.append("")
                out.append(f"**Affects:** {affects}")
            out.append("")

    # Audit detail — collapsed `<details>` per record.
    out.append("<details>")
    label = (
        "Audit detail — per-record checks"
        if len(records) > 1
        else "Audit detail — all checks"
    )
    out.append(f"<summary>{label}</summary>")
    out.append("")
    for rec in records:
        if len(records) > 1:
            out.append(f"#### `{rec['slug']}`")
            out.append("")
        out.extend(_audit_block_for_record(rec))
        out.append("")
        # Effective-rules block stays inside the audit `<details>` —
        # nested details are valid markdown but make the comment too
        # noisy; flatten to a small table per record instead.
        rules = rec.get("effective_rules") or []
        if rules:
            out.append("<details>")
            out.append(f"<summary>Effective rules ({len(rules)})</summary>")
            out.append("")
            out.append("| Rule | Source |")
            out.append("|---|---|")
            for r in rules:
                out.append(f"| `{r['name']}` | `{r['source']}` |")
            out.append("")
            out.append("</details>")
            out.append("")
    out.append("</details>")

    foot = _footer(verdict)
    if foot:
        out.append("")
        out.append(foot)

    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: format-verdict-comment.py <verdict.json>\n")
        return 2
    verdict = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    text = format_comment(verdict)
    # Force UTF-8 on stdout regardless of platform default — emoji
    # icons (✅ ⚠️ ⛔) and unicode separators don't survive cp1252
    # encoding. CI on Linux works fine; this keeps local invocations
    # on Windows working too.
    sys.stdout.buffer.write(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
