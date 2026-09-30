# assess-risk

Fix two values in the Work Record's marker block before plan-and-review: **Risk** and **Complexity**.

Use the effective Redline policy or reporter on the complete intended path set, then apply the table. Classify directly when the rules and scope are clear; use a clean-context agent only for material uncertainty. This pre-edit result is provisional: CI checks the final diff.

## Allowed values

| Field | Values |
|---|---|
| **Risk** | `Routine`, `Elevated`, `High` (SPEC §8) |
| **Complexity** | `Simple`, `Moderate`, `Large` (SPEC §8) |

Boundary Violation stops the workflow before a Work Record is written. Don't record it as a Risk value; stop and escalate.

## Redline verdict → Risk

Inputs: the intended scope from Establish-Context + redline's pre-edit classification.

| Redline verdict on intended scope | Risk |
|---|---|
| All paths **blue** | `Routine` |
| Any **gray** path | `Elevated` (provisional unclassified floor, not proof of danger) |
| Any **red** zone touched | `Elevated` — or `High` when the red zone is a contract, security, persistence, or financial surface (use the repo's `agent-redline-policy.yaml` checkpoint metadata) |
| Any **boundary violation** | **Stop the workflow** — escalate; no Risk value |

Judgment may **raise** Risk; it may not lower the effective floor. A proposed policy relaxation does not change this task. For exact-path evidence and approved policy learning, follow Redline operating-mode.

## Complexity

Independent of redline. SPEC §8:

- **Simple** — one coherent change, likely one working session.
- **Moderate** — several affected components, meaningful uncertainty, or multi-session.
- **Large** — multiple repositories, services, delivery units, or independently verifiable outcomes.

## Shape consequence

`(Routine, Simple)` → compact. Anything else → expanded. The checker's `workrecord.shape_matches_classification` predicate blocks mismatches.

## Reason field

Required when classification is not `(Routine, Simple)`. One or two lines naming the redline finding or judgment that drove the decision:

> Redline reports red zone + persistence-review checkpoint required (Order aggregate touched). High because persistence is a contract surface. Moderate complexity — touches handler + repository + tests.

For `(Routine, Simple)`, Reason is optional. `—` is fine.

## CI re-classification

The harness re-classifies at PR time using the **final diff**:

- `risk.redline_findings_available` — is redline's verdict artifact present?
- `risk.boundary_violation_absent` — did redline flag a boundary violation?
- `risk.declared_not_below_detected` — is declared Risk at least the minimum detected?

A mismatch blocks. The skill's pre-edit classification is your input; CI's predicates are the gate.

## Reassessment triggers

Per SPEC §8.3, reassess when:

- Scope materially changes
- An important assumption fails
- New affected surfaces are discovered
- Before merge, against the actual final diff (CI handles this)

A Risk/Complexity change may trigger a shape migration; bump the fields, migrate if needed, commit before continuing.
