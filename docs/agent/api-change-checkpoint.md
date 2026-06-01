# api-change-checkpoint

You're here because you're modifying API contract surface (controllers, OpenAPI files, GraphQL schemas, proto). The base checkpoint-note format is in `operating-mode.md`. This doc adds what to think about specifically for API changes.

## Classify the change shape

Before writing the checkpoint note, decide which kind of change this is:

- **Additive:** new endpoint, new optional field, new optional query parameter. Existing consumers continue to work unchanged.
- **Breaking:** removed endpoint, removed field, changed required field's type, renamed parameter, changed status code semantics. Existing consumers will fail.
- **Behavior-only:** signature unchanged but the response semantics shifted (e.g., field's value range changed, error conditions changed). Easy to miss; consumers may break without compile-time signal.

Each shape rolls out differently. State the shape explicitly in the checkpoint note.

## Backwards-compatibility checklist

For breaking and behavior-only changes:

- [ ] Is there a deprecation path? (Mark old surface deprecated before removing.)
- [ ] Is there a migration period? (Both old and new available simultaneously.)
- [ ] Are consumers identified? (Even within this repo: tests, internal callers.)
- [ ] Is the OpenAPI / schema diff in the PR? (The reporter shows it; reference it explicitly.)

If any answer is "no" or "I don't know," surface that in the checkpoint note. The reviewer needs to know what wasn't checked.

## Behavior-only changes need extra care

Behavior-only changes don't show up in OpenAPI/schema diffs. They look like blue-zone implementation changes but are actually contract changes. Examples:

- A field that returned `null` now returns `[]`.
- An endpoint that returned `200` for an empty result now returns `204`.
- Validation rules tightened (a previously-accepted input is now rejected).

If the change shifts what consumers can rely on, treat it as `api-change` even if no signature changed.

## Don't include in the checkpoint note

- The full schema or controller code (the reviewer reads the diff)
- Restated requirements ("we need to support X")
- A history of design alternatives (if alternatives matter, link to a design doc)
