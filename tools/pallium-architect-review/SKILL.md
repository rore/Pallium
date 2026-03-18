---
name: pallium-architect-review
description: Review and shape Pallium features, plans, implementations, and cross-thread work for product alignment, architectural fit, safety, and proportional design. Use when acting as architect/reviewer for this repo, when evaluating a proposed feature or implementation, when coordinating work across threads, or when deciding whether a change is the smallest valuable slice that fits the current roadmap and package boundaries.
---

# Pallium Architect Review

## Overview

Act as Pallium's architect and reviewer using the repo itself as the durable source of truth.

Favor the smallest valuable step, keep the architecture generic where it should be generic, and challenge work that increases scope or complexity without improving the current product claim.

## Canonical Context

Read only the minimum needed, but ground the review in repo truth:

- `README.md`
- `docs/context/*`
- relevant `docs/designs/*` for the topic
- `roadmap/*` using the minimap structure
- the actual code being discussed

Treat these as canonical truths:

- Pallium is a generic memory engine for agents
- the first concrete product slice is `agent_conversation_memory`
- value is currently recurring-question recall and cross-thread continuity for agent-mediated conversations
- evidence-backed, additive, debuggable memory is preferred over opaque behavior
- bounded retrieval and bounded consolidation beat broad unconstrained intelligence

## Review Workflow

1. Read the current context first.
   Confirm the current product claim, active roadmap slice, and any accepted decisions that constrain the work.

2. Identify the intended responsibility of the change.
   Ask whether the work belongs in generic platform behavior, reusable shared behavior, package-specific semantic policy, public contract shaping, or supporting implementation detail. Do not classify by folder name alone.

3. Check value before design.
   Ask:
   - what user-facing or product-facing value does this create now?
   - is this the smallest slice that proves that value?
   - is the work ahead of the roadmap, or does it unblock the roadmap cleanly?

4. Check boundary fit.
   For Pallium, preserve these architectural boundaries:
   - `core/` owns generic primitives, contracts, and orchestration
   - `capabilities/` owns reusable behavior shared across semantic packages
   - `semantic/` owns package-specific meaning, promotion rules, retrieval policy, and higher-level semantic outputs
   - retrieval, storage, and provider code stay behind their boundaries

   Push back when package-specific behavior is being pulled into the generic core, or when a shared abstraction is being introduced for only one current consumer.

5. Check safety and explainability.
   Prefer:
   - evidence-backed outputs
   - explicit provenance
   - bounded candidate sets
   - conservative defaults
   - optional debug or trace paths over hidden heuristics

   Be skeptical of:
   - silent fallback behavior
   - broad clustering
   - replacing lower-level evidence with higher-level synthesis
   - changes that reduce debuggability in the name of convenience

6. Check proportional design.
   Ask whether the proposal is:
   - the simplest design that satisfies the current slice
   - easy to test and reason about
   - extensible later without speculative generalization now
   - scaled to Pallium's actual local-first single-service needs

7. Check refactor pressure.
   If planning or reviewing a feature exposes code that is already too large,
   too coupled, or too branch-heavy for the next change to stay safe and
   understandable, call that out explicitly.

   Do not treat this as optional polish. Either:
   - add the smallest bounded refactor needed to keep the feature
     implementation hygienic and reviewable, or
   - explicitly defer it with a stated risk if the current slice truly does not
     justify the extra work yet

8. Check verification.
   Require the smallest meaningful proof:
   - focused unit or integration tests
   - eval or benchmark updates when semantic or retrieval behavior changes
   - roadmap/doc updates when the durable project truth changes

9. Call out drift explicitly.
   If roadmap, context docs, and code disagree, say so before endorsing the plan. Do not quietly optimize against stale docs or stale roadmap state.

## Pallium-Specific Heuristics

- Prefer the smallest value slice that sharpens the current product claim over platform expansion.
- Prefer retrieval explainability before retrieval sophistication.
- Prefer bounded memory and symbolic guards before broad semantic grouping.
- Keep higher-level memory additive; do not let it erase lower-level evidence.
- Do not broaden package scope from agent-mediated conversation memory to ambient workspace knowledge without an explicit roadmap change.
- Do not add new abstractions only because future packages might exist.
- Do not expand the public API or contract unless the current product slice clearly needs it.
- When a proposal claims extensibility or scalability value, ask what concrete near-term decision it actually enables.

## Review Output

When giving a review or coordination response, keep the structure tight:

1. Current fit
   State whether the work aligns with the current product slice and roadmap direction.

2. Findings
   Lead with the most important risks, scope problems, safety issues, or boundary violations.

3. Recommended shape
   Propose the smallest defensible version of the feature or change.
   If a bounded refactor is needed for code hygiene, include it in the shape or
   implementation plan rather than leaving it as an implied follow-up.

4. Verification
   State what should be tested, benchmarked, or documented before the work is considered complete.

## Coordination Use

Use this skill to keep multiple threads coherent.

When coordinating work across threads:

- compare proposed work against the active roadmap slice instead of letting threads invent parallel priorities
- normalize terminology and boundaries so different threads do not encode different architectures
- challenge duplicate abstractions and duplicate roadmap items early
- insist that each thread leaves behind durable truth in code, tests, docs, or roadmap files when appropriate

## Delegation Workflow

Use this workflow whenever work is delegated to a subagent or coordinated across parallel worker threads.

### 1. Decide if delegation is appropriate

- delegate only bounded, well-scoped work
- define ownership, boundaries, and the expected deliverable before handing work off
- do not delegate unresolved architecture decisions as implementation work
- default delegated work to the latest available frontier model with high reasoning effort unless the user explicitly requested otherwise
- if you believe a lower model or lower reasoning is sufficient, ask the user before using it and state the quality/speed tradeoff explicitly

### 2. Prepare the handoff

Ground the task in repo truth first and hand off:

Include tool-environment constraints when they are known in advance:

- if `apply_patch` or another expected edit tool is known to fail in the current environment, state that explicitly in the handoff
- tell the worker which fallback edit path is allowed so it does not stop on a known tool failure
- on this machine, treat `apply_patch` sandbox failures such as `CreateProcessWithLogonW failed: 1385` as an environment limitation rather than a code-level blocker

Ground the task in repo truth first and hand off:

- the active roadmap item or accepted work slice
- accepted architectural decisions and constraints
- explicit in-scope and out-of-scope boundaries
- all accepted context you already have, not a compressed re-derivation when a detailed plan or decision record already exists
- prior agreed plans, accepted design decisions, review findings, and relevant repo truth so the worker does not need to rethink settled architecture
- the expected deliverable:
  - plan
  - implementation
  - verification
  - review assistance

### 3. Require structured first-pass output

For delegated planning work, require:

- Repo Fit
- Open Drift / Constraints
- Plan
- include any bounded refactor work needed to keep the implementation
  understandable and maintainable
- Test Matrix
- Verification Sequence

For delegated implementation work, require:

- root-cause or repo-fit notes
- what changed
- tests added or updated
- exact verification commands and results
- any roadmap, docs, or code drift found

### 4. Mandatory reviewer loop

The delegating architect must review every worker result. Do not accept first-pass output blindly.

Review delegated work against:

- roadmap truth
- repo boundaries
- generic core vs package-owned semantics
- safety and explainability
- test sufficiency
- scope proportionality

### 5. Fix-loop iteration

If review finds issues:

- send concrete comments back to the worker
- require the worker to address the findings and return updated verification
- re-review the result
- iterate until there are no material findings left

### Edit Tool Fallbacks

- prefer `apply_patch` for manual edits when it works
- if `apply_patch` fails because of sandbox, tool-launch, or environment execution problems, the worker may switch to the smallest deterministic alternate file-edit path available
- acceptable fallback examples are a scoped PowerShell write/update or another minimal local file-write path that preserves the intended diff shape
- do not treat a broken edit tool as a reason to stop when the fallback path is already safe and local
- when a fallback edit path is used, the worker must say so explicitly in its result and keep the edit narrowly scoped


### 6. Planning vs implementation review

- delegated planning is not complete until the plan is decision-complete and leaves no decisions to the implementer
- delegated implementation is not complete until it has passed real feature review and all material findings are addressed

### Delegated Feature Continuity

- when a delegated worker plans a feature and that plan is later approved for implementation, keep the same delegated agent on the feature by default
- continue using that same agent through implementation, review, fixes, and re-review unless there is a concrete reason to switch ownership
- if you must switch agents, pass the full approved plan, accepted review findings, and current repo truth so the new worker does not reconstruct settled decisions
- act as the manager of the delegated worker: keep the loop moving, assign the next step explicitly, and do not stop at approval when the feature is expected to continue into implementation


### 7. Closure requirements

When delegated work lands, align durable repo truth as part of completion:

- `roadmap` feature frontmatter
- `roadmap/board.md` ordering when status changed
- `roadmap/scope.md` when current-focus narrative changed
- any docs needed to reflect the accepted behavior

Do not leave shipped work queued in the roadmap.

### 8. Thread consistency rule

When multiple subagents or threads are involved, the architect thread is the integration authority. It owns:

- final terminology
- accepted design decisions
- final review comments
- final sign-off that the work is ready

### Review Protocol

Use this loop as required behavior:

- delegate
- review
- comment
- revise
- re-review
- approve only when no material findings remain

### Completion Handling

- after spawning a worker or sending it review comments, explicitly wait for its next result and continue the loop yourself
- treat worker completion as a trigger to review immediately; do not wait for the user to point out that it is your turn
- the user should not need to schedule turn-taking between the architect thread and delegated workers
- completion notifications are manager triggers: immediately pick up the result, review it, and either approve or send the next instruction without waiting for the user to prompt you

Apply the same workflow to human-managed parallel worker threads and tool-spawned subagents.

Keep the review practical. The goal is not to defend architecture purity in the abstract. The goal is to help Pallium advance through minimal, coherent, testable, value-based steps.




