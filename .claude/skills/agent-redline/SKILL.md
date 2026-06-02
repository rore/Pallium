---
name: agent-redline
description: Use when setting up agent governance for a repo, or when working in a repo that contains agent-policy.yaml. Classifies structural risk and routes human attention to red-zone changes.
---

# agent-redline

You classify changes before editing. Deterministic CI checks (a boundary-rule backend, the reporter) catch what you miss.

## Vocabulary

| Term | Meaning |
|---|---|
| **Red zone** | Changes are dangerous: contracts, modeling, architecture, security, persistence, shared behavior. |
| **Blue zone** | Autonomous work fine: isolated, replaceable, strongly testable, low blast-radius. |
| **Gray zone** | Unclassified. Cautious by default. |
| **Watch** | Additive tag (not a zone): paths surfaced in the PR comment regardless of red/blue/gray classification. No checkpoint, no gate — visibility only. |
| **Boundary rule** | Deterministic dependency rule (`X must not import Y`). Enforced by a backend (e.g., ArchUnit). |
| **Checkpoint** | Required human attention; satisfied by a label or CODEOWNER approval. Types: `architecture-review`, `api-review`, `persistence-review`, `security-review`, `ops-review`. |

## Pick a mode

1. **`agent-policy.yaml` exists in the repo root** → read [`operating-mode.md`](operating-mode.md). Everyday work.
2. **The user asked you to set up agent-redline** → read [`bootstrap-mode.md`](bootstrap-mode.md). One-time setup.
3. **Neither** → this skill is not relevant.

Read only the file for the mode that applies.

## Principles (non-negotiable)

1. **Classify before editing.** Decide blue / red / gray before you touch a file; note any `watch` paths to surface in the PR.
2. **Refuse boundary shortcuts.** If a change would create a forbidden dependency, fix the structure or escalate. Do not suppress, do not modify the architecture-test files, do not launder the import.
3. **Architecture-test files are red.** Any change to the boundary-rule backend's definition files (e.g., ArchUnit test classes) requires `architecture-review`, regardless of what the policy says.
4. **Never auto-commit CI changes.** Workflows, branch protection, CODEOWNERS — propose, don't commit.
5. **Default conservative on uncertainty.** Gray > blue, red > gray, boundary risk > everything.
6. **No slop.** Tight PR descriptions, tight code comments. What's not obvious from the code, and what it does.

## Decision priority

When ambiguous:

1. The repo's `agent-policy.yaml`
2. The repo's `AGENTS.md` / `CLAUDE.md` / `GEMINI.md`
3. The active language extension's `operating.md` (if present)
4. These principles
5. Ask the developer

Do not invent rules the policy doesn't state.

## Resources (load on demand)

- `operating-mode.md` — read when entering operating mode
- `bootstrap-mode.md` — read when entering bootstrap mode
- Active extension's files in `extensions/<name>/` — `profile.md` and `scaffold.md` during bootstrap; `operating.md` once per session in operating mode if present
- `docs/agent/` in the consuming repo — read a per-checkpoint doc only when escalating to that checkpoint
