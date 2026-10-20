# establish-context

Write **Outcome**, **Target**, **Scope**, **Constraints**, and **Completion criteria** before reading code; keep routine fields to one line where possible.

If the task arrived from an authoritative source item, link it in surrounding prose and record only task-local context; do not copy it into a competing local specification.

## Relationships

At creation/pickup, copy supplied exact tuples; if an identified feature/issue lacks refs, resolve through its owning tool. Never guess/title-match or normalize identity. Write `(provider, scope_ref, local_ref)` tuples in the same record edit; preserve/correct on resume/handoff. Append the owning PR tool's returned URL in the PR-creation edit. Read back against expected refs; never rewrite the baseline. Unavailable/ambiguous resolution: keep `sources: null`/unverified, report the gap, continue safe independent work. `[]` means known no-source; missing stays legacy unknown. This discovery/edit/check is not automatic capture or proof no input was missed. No human backlink task. Rules: SPEC §13.1.

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

## Baseline and revision

Before discovery, copy Outcome, Scope, Constraints, and Completion criteria into the Requirement baseline JSON. See [behavioral-integrity.md](behavioral-integrity.md). Equivalent clarification uses a change entry; a material refinement blocks for task-owner approval. Never rewrite the baseline.

Planning and implementation cannot begin while context is unclear or the baseline is missing.
