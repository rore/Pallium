# plan-and-review

Write the plan, then a reviewer (self / clean-context agent / human) signs off before implementation. Fields differ by shape; rules differ by Risk level.

## Fields

**Compact (routine) shape — two fields:**
- **Approach** — one or two lines naming the implementation strategy. Concrete enough that a reviewer can predict the diff.
- **Verification** — the test or CI job that proves the completion criterion. Name the test class or job, not "unit tests."

Self-review is sufficient; no Plan review field on compact.

**Expanded shape — four fields:**
- **Plan** — approach + sequence + deviations + stop conditions. For expanded tasks, also include:
  - *Key conventions:* naming patterns, existing utilities, or architectural rules this implementation must follow (surfaced during discovery).
  - *Target files or classes:* specific locations in scope, derived from the repository's conventions. Listing these before implementation starts makes scope drift visible.
- **Verification plan** — each completion criterion → check (one line per criterion). Use the same observable-outcome form as the criterion itself: *`When <trigger>, the <system> shall <outcome> → <method>`*. Example: `When concurrent retries arrive, the system shall produce one wallet → concurrency integration test`.
- **Plan review** — reference to the review that happened. Format depends on Risk; see below.
- **Approvals** — required at High Risk; "Not required at this risk level" otherwise.

## Plan review by Risk

| Risk | Review requirement |
|---|---|
| **Routine** | Self-review. No Plan review field on compact. |
| **Elevated** | **Clean-context agent review required.** Spawn a fresh subagent per the canonical mechanism in [`../../operating-mode.md`](../../operating-mode.md) §"Clean-context delegation" (Task/Agent tool with a read-only agent type, or a fresh session when the harness has no subagent primitive). Subagent reads only the Work Record + SPEC + relevant source files. Review prose lands under `## Plan review` in the same Work Record; the marker-block field references it. The reviewer SHOULD probe one assumption or decision at a time rather than producing a holistic summary — serial questioning surfaces weaknesses that a single-pass read glosses over. |
| **High** | Clean-context review **plus** human approval. Stop, present the plan + clean-context summary to the human, refuse to advance until approved. Record the approval **verbatim** in Approvals (see below). |

**Predicates:**
- `approval.elevated_clean_context_review_present` — blocks when the field is empty/`—`/`self` AND no `## Plan review` section exists.
- `approval.high_risk_approval_recorded` — matches the Approvals pattern case-insensitively.
- `approval.clean_context_does_not_satisfy_human` (non-waivable) — ensures the recorded approval is not the clean-context reference copied across.

## High-risk Approvals format

```
**Approvals:** Approved by user <timestamp>: "<verbatim quote of the human's response>"
```

## Hand-off readiness

Before `Ready to implement`:
- Compact: Approach and Verification both populated.
- Expanded: Plan, Verification plan, Plan review populated. Approvals populated when Risk is High.

Checker predicates: `workrecord.routine_fields_present` (compact) / `workrecord.expanded_fields_present` (expanded).

## Gates this checkpoint closes (SPEC §9.4)

- Implementation **MUST NOT** begin until required reviews complete, approvals recorded, blocking findings resolved.
- Plan review or approval **MUST** repeat only when scope, assumptions, approach, or risk materially change.

A reassessment that materially changes any of those returns the task to planning. State goes back from `Ready to implement` to `Blocked` (with reason); update the plan; reviewer signs off again.

## Exceptions (expanded shape only)

Optional per-task rule waivers per SPEC §11. Each entry:

```
**Exceptions:**
- rule: <named predicate>
  reason: <why the rule is being waived for this task>
  scope: <what the exception applies to>
  approver: <human identifier>
  expiry: 2026-12-31              # optional; ISO YYYY-MM-DD
  compensating_validation: <what was done in lieu of the waived rule>
```

When the checker sees a valid exception naming a blocking-failed predicate, it downgrades that predicate to advisory.

**Non-waivable.** Boundary-violation findings and structural-shape preconditions (`workrecord.exists`, `workrecord.markers_present`, `risk.declared`, `complexity.declared`, `workrecord.shape_matches_classification`) cannot be waived. An exception against any of these fails `exceptions.not_against_boundary` and blocks.

**Compact has no Exceptions field.** Waivers require expanded shape. To open an exception against `risk.declared_not_below_detected`, declare at the detected minimum (Elevated+) and waive from expanded — do **not** inflate Complexity to manufacture a waiver slot.

Use sparingly. Not every advisory needs an exception.
