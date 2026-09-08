# discover

Inspect what the system actually does before planning. Goal: enough material truth that the plan won't solve the wrong problem or break existing behaviour. Not exhaustive documentation.

SPEC §9.2 carries the normative shape.

## What to inspect

Focused — only what bears on the task:

- Affected code and tests
- Repository guidance (`AGENTS.md`, `CLAUDE.md`, READMEs near the change)
- Interfaces and schemas the change touches or relies on
- Recent related changes (`git log` on affected files)
- Design decisions (`docs/DECISIONS.md` or equivalent)
- Existing verification commands and CI checks
- Logs / incidents when the task is reactive to one

## What to record

Expanded shape's **Discovery** field carries material findings. Compact shape has no Discovery field — you still did discovery; nothing material needs preserving past the session.

**Material** = current behaviour and components involved, constraints and dependencies that bind the plan, verification capabilities and their gaps, unanswered questions or assumptions, references to the evidence you inspected.

**Non-material** = anything a reviewer would skim past. Don't pad.

## When sources disagree

Agents treat written context as authoritative even when it is stale. A disagreement is **material** when it would change scope, approach, completion criteria, or risk classification.

### Authoritative source by question

| Question | Authoritative source |
|---|---|
| What does the system actually do? | Code + tests + observed behaviour. |
| What should the system do? | Requirements / Jira / approved spec. |
| How is the system organised? Where do boundaries lie? | Architecture documents + redline policy. |
| How do we work in this repo? | `AGENTS.md` / `CLAUDE.md` / contribution docs. |
| What was decided, by whom, when, and why? | `DECISIONS.md` and equivalent ADRs. |

A document that contradicts its authoritative source is stale, not correct. Default to the authoritative source; the doc gets fixed.

### Three resolution paths — pick one explicitly

1. **Resolve in-task.** Small fix, inside the task's natural scope. Update the stale source; note in Discovery that you did.
2. **Record as assumption with validation condition.** Disagreement is real, resolving it is out of scope. Write the assumption into the expanded shape's **Material assumptions** field with what would prove it wrong and what you'd do. Discovery prose names the conflicting sources.
3. **Escalate.** Can't pick which source is authoritative without a human. Surface to the developer; State → `Blocked`; Work Record names the conflict. Do not pick a side silently.

Path 3 has to stay available. Without it, every conflict gets rationalised into the first two.

## Gate

Planning **MUST NOT** proceed while a material uncertainty is neither verified nor recorded as an assumption with a validation/invalidation condition. SPEC §9.2.
