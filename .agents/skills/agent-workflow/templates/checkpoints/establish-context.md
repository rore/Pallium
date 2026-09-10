# establish-context

Routine path. Five fields, each one line where possible: **Outcome**, **Target**, **Scope**, **Constraints**, **Completion criteria**. Write all five before you read code.

The point of this checkpoint is to write down what you would otherwise *infer*. Agents fill gaps confidently and silently; the marker block makes the gap-filling visible to a reviewer.

## Field-by-field

### Outcome

What is true when the task is done, from the user's point of view. Not "add a method"; not "refactor X". Concrete enough that you could turn it into a one-line PR title.

> Concurrent retries against the wallet creation endpoint produce a single wallet, not multiple.

If you cannot write this without saying "and also X" or "and refactor Y", the scope is wrong or the task is not routine. Stop and discuss.

### Target

The system, service, or repository this affects. One name, no list. A task that touches more than one target is not routine.

> wallet-service.

### Scope

What may change. List the surfaces or files; "and tests" is fine as shorthand.

> Wallet creation flow and its tests.

### Constraints

What must NOT change, even if it would be convenient. Use this to name things that are tempting to break — public API, schema, tenant isolation, performance — and lock them down up front. Use `—` only when nothing meaningful applies.

> Public API unchanged. Tenant isolation unchanged.

### Completion criteria

Observable outcome — a thing a reviewer could check from the diff or from CI. Not "the change works"; that is unfalsifiable. Not "add a test" — that describes implementation, not the outcome.

State the observable result directly. EARS form works well: *`When <trigger>, the <system> shall <observable outcome>`.*

> When concurrent retries arrive, the system shall produce exactly one wallet — verified by the CI concurrency test.

If you cannot name an observable outcome, you do not yet know what success looks like. Stop and discuss with the developer before continuing.

## What this checkpoint is not

- It is not a design exercise. Approach goes under **Approach**, not here.
- It is not an exhaustive context dump. Five lines (one per field) is the typical shape.
- It is not a place to record reasoning. The reasoning lives in surrounding prose, not in the marker block.

## When to revise

The Task Context can be refined during discovery — the spec allows this. If you revise it after starting implementation, ask whether the change is material. A material change (different outcome, different scope, different completion criteria) means re-planning, not in-place editing.
