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
| **Elevated** | Clean-context agent review required. Use operating-mode §Clean-context delegation; probe material uncertainty and record the result under Plan review in the Work Record. |
| **High** | Clean-context agent technical review **plus** separate human plan review and approval. Stop until both are complete; record human approval verbatim in Approvals. |

Record `Agent technical review: <source ref>` in Plan review for Elevated/High. The non-implementer agent assesses risk and verification-plan adequacy, citing revision, inspected evidence, findings, and disposition. Human approval alone proves neither review. Use the least costly capable reviewer; preserve human/specialist duties and user-selected settings. Reuse valid unchanged review.

**Predicates:**
- `approval.elevated_clean_context_review_present` / `approval.high_clean_context_review_present` — require a distinct agent technical review reference at Elevated / High.
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

- Begin after required reviews, recorded approval, and resolved blockers. Human consent to the presented plan is approval; no magic word. Preserve its exact quote and scope. Silence, elapsed time, tool results, and agent review are not approval.
- On approval, advance. Nonmaterial wording or revision bookkeeping preserves it. Repeat review/approval only when scope, assumptions, approach, or risk materially change; return to planning with a named `Blocked` reason. Before blocking for missing approval, identify the uncovered decision and ask one concrete question.

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
