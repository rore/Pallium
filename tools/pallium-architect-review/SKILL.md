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

7. Check verification.
   Require the smallest meaningful proof:
   - focused unit or integration tests
   - eval or benchmark updates when semantic or retrieval behavior changes
   - roadmap/doc updates when the durable project truth changes

8. Call out drift explicitly.
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

4. Verification
   State what should be tested, benchmarked, or documented before the work is considered complete.

## Coordination Use

Use this skill to keep multiple threads coherent.

When coordinating work across threads:

- compare proposed work against the active roadmap slice instead of letting threads invent parallel priorities
- normalize terminology and boundaries so different threads do not encode different architectures
- challenge duplicate abstractions and duplicate roadmap items early
- insist that each thread leaves behind durable truth in code, tests, docs, or roadmap files when appropriate

Keep the review practical. The goal is not to defend architecture purity in the abstract. The goal is to help Pallium advance through minimal, coherent, testable, value-based steps.
