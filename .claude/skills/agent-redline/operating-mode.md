# operating-mode

Active when `agent-policy.yaml` exists in the repo root.

## The loop

```
1. Read agent-policy.yaml.
2. Classify the change BEFORE editing.
3. Branch by classification.
4. Edit (or escalate).
5. Run the local check.
6. Write a PR description that exposes the classification.
```

## Step 1 — Read the policy

Form a working model of:
- Red / blue / gray / watch path globs
- Boundary rules
- API / persistence / security / runtime-config paths
- Checkpoints (label names, CODEOWNER teams)

If `project.extension` is set and the extension has an `operating.md`, read it once.

If the policy is inconsistent with the repo (paths reference packages that don't exist, boundary rules point at moved packages), flag it. Do not silently update the policy mid-task — policy changes are red-zone.

## Step 2 — Classify

Answer:
- Which files would I change?
- What zone do they fall in?
- Do any boundary rules apply to dependencies I'd add?
- Am I touching API, schema, security, or runtime-config paths?

Priority:
1. **Red wins.** One red file → the change is RED (or higher: API_CHANGE, SCHEMA_CHANGE, SECURITY_CHANGE).
2. **Boundary risk wins** over zone classification.
3. **Blue + gray** → GRAY.
4. **All blue** → BLUE.

| Classification | Meaning |
|---|---|
| `BLUE` | All files in blue zones. Proceed. |
| `RED` | At least one red-zone file. Stop. Plan a checkpoint. |
| `GRAY` | At least one gray file (none red). Proceed cautiously. |
| `BOUNDARY_RISK` | Intended change would create a forbidden dependency. Do not proceed. |
| `API_CHANGE` / `SCHEMA_CHANGE` / `SECURITY_CHANGE` | Touched the corresponding contract surface. |
| `MIXED` | Combination — resolve to the most-restrictive. |

## Step 3 — Branch

### BLUE
Proceed.

### RED / API_CHANGE / SCHEMA_CHANGE / SECURITY_CHANGE
Stop. Produce a checkpoint note:

```
## Checkpoint: <id>
What is changing: <1–2 sentences>
Why: <reason>
Affected contract / model / boundary: <which>
Compatibility / migration risk: <low|medium|high — one-line reason>
Verification plan: <tests, checks, manual validation>
```

If the developer has already authorized the change (e.g., the task says "extend the OrderRepository port"), proceed and include the note in the PR description; apply the checkpoint label or request a CODEOWNER does.

If the request is ambiguous, ask before editing.

### GRAY
Proceed cautiously. Surface in the PR description that gray-zone code was touched. Suggest those paths be classified explicitly.

### BOUNDARY_RISK
Do not work around the rule.

Forbidden:
- `@SuppressWarnings`, lint exclusions, or any other suppression
- Modifying the boundary-rule backend's definition files
- Adding a transitive layer to launder the import
- Moving offending code to a different package just to satisfy globs

Two legitimate responses:
1. **Fix the structure** (open the port, extend the interface, route through the right layer). May itself need `architecture-review`.
2. **Escalate.** Tell the developer the change requires an explicit modeling decision.

## Step 4 — Edit

- Don't expand into other zones during implementation. If you need to, re-classify.
- No unrelated cleanup. Small PRs.
- Do not split a coherent change into multiple PRs to evade size limits.

### Do not silently modify governance — refuse, don't proceed

Refuse to edit these as a side-effect of another task. The only legitimate edit is one the developer asks for explicitly and in isolation; that edit is itself red-zone (architecture-review).

- **Architecture-test files** (matching the policy's architecture-test red entries).
- **`agent-policy.yaml`** — including widening a threshold, dropping a red entry, relaxing a checkpoint.
- **Already-shipped migrations** (any `V*.sql` / Flyway / Liquibase file already on `main`). To change V1, write V2 that compensates.

If the task asks for any of these as a side-effect, stop and escalate.

## Step 5 — Local check

Run `scripts/agent-redline-check.sh`. Same logic as CI, on your local diff. Reports:
- Classification verdict
- Boundary violations
- Required checkpoints (and whether satisfied)
- PR size

Fix what it surfaces before pushing.

## Step 6 — PR description

Use the repo's PR template. Tick the classification and checkpoint boxes.

- **What changed:** short, factual. One paragraph. Not a history; not a restated requirement.
- **Why:** one or two sentences.
- **Verification:** commands actually run.

## When the policy disagrees with reality

Generated source files classified as red, new top-level packages the policy doesn't mention, paths that no longer exist after a refactor:

- Treat affected paths as gray for *this* PR.
- Surface the inconsistency in the PR description.
- Suggest a separate PR to update the policy.

Do not silently fix the policy as part of unrelated work.

## Do not load during operating mode

`bootstrap-mode.md`, the extension's `scaffold.md`, the extension's `profile.md`. Their work was captured in the policy and committed artifacts during bootstrap.
