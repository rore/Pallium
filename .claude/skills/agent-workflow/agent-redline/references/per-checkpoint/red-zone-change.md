# red-zone-change

You're here because you're modifying a red-zone file outside the API / persistence / security categories — typically domain models, application ports, or other architectural surface. The base rules are in `operating-mode.md`. This doc adds nuance specific to architectural red zones.

## "Red" doesn't mean "don't change"

Red means the change requires explicit human attention before merge. It is not a refusal. The discipline is:

- Recognize you're in red zone before editing
- Write a checkpoint note that gives the reviewer what they need
- Apply the label (or request a CODEOWNER does) once the note is reviewed
- Do not modify red files after the label is applied without re-applying the label

If you're forced to amend a labeled red change later, treat the amendment as a fresh red change.

## What architecture-review reviewers want

- The model concept that's changing (an invariant, an aggregate boundary, an interface contract)
- Why the existing model didn't fit
- What the change implies for downstream callers
- Whether the change introduces a new abstraction or modifies an existing one

A checkpoint note that doesn't address these forces the reviewer to reconstruct them from the diff.

## Refactor vs. behavior change

Two shapes get conflated and shouldn't be:

- **Refactor:** behavior unchanged, structure changes. Tests are the regression net. If a refactor changes red-zone surface, it's still red — but the checkpoint note should make explicit that observable behavior is identical.
- **Behavior change:** the model invariants or contracts shift. Existing tests may pass for reasons that no longer hold. Surface this; new tests likely needed.

## Don't bundle

A red-zone change should be the focus of its PR. Don't combine it with unrelated blue-zone work — the reviewer's attention is the scarce resource and bundling forces them to context-switch.
