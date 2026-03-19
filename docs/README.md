# Docs Map

Pallium's docs are split by job so the README does not have to do everything.

## Recommended Reading Order

For a developer evaluating the project for the first time:

1. `README.md`
2. `docs/problem-and-approach.md`
3. `docs/getting-started.md`
4. `docs/configuration.md`
5. `docs/agent-integration.md`
6. `docs/http-api.md`
7. `docs/privacy-and-visibility.md`
8. `docs/memory-model.md`
9. `docs/validation.md`
10. `docs/status.md`
11. `docs/overview.md`
12. `docs/context/architecture.md`

## Documentation Roles

- front door
  - `README.md`
  - what Pallium is, what it does today, and how to try it quickly

- tutorial
  - `docs/getting-started.md`
  - one short local walkthrough from setup to first query

- how-to
  - `docs/agent-integration.md`
  - how to fit Pallium into an agent runtime

- reference
  - `docs/http-api.md`
  - endpoint shapes, request fields, response fields, and operational endpoints
  - `docs/configuration.md`
  - config sources, precedence, provider blocks, package blocks, and runtime overrides

- explanations
  - `docs/problem-and-approach.md`
  - `docs/privacy-and-visibility.md`
  - `docs/memory-model.md`
  - `docs/validation.md`
  - `docs/status.md`
  - `docs/overview.md`

- stable architecture context
  - `docs/context/architecture.md`
  - `docs/context/state.md`

## Ownership

- docs/
  Developer-facing entry points and practical guides.
  Use this layer for evaluator flow, practical onboarding, integration,
  reference material, validation, memory model, and concepts.

- roadmap/
  Canonical planning workspace. Use it for queue, ordering, scope, milestones,
  phases, and feature status.

- docs/context/
  Stable project truth. Use it for vision, accepted architecture, durable
  decisions, and lightweight handoff state.

- docs/designs/
  Longer design threads. Use it for proposals, tradeoffs, analyses, examples,
  and designs that are still evolving or too detailed for docs/context/.

## Update Rules

- If the question is "how should a developer evaluate or use this repo?",
  update `docs/`.
- If the question is "what are we doing next?", update `roadmap/`.
- If the question is "what is Pallium and what have we accepted?", update
  `docs/context/`.
- If the question is "why this design and what were the alternatives?",
  update `docs/designs/`.

## Guardrails

- Keep front-door docs outside-in, not ontology-first.
- Keep public docs plain-language first and move deeper terms later.
- Separate tutorial, how-to, explanation, and reference material when a page is
  trying to do too many jobs.
- Do not duplicate planning state in docs/context/.
- Do not treat docs/designs/ as the canonical queue or status surface.
- When a design becomes accepted direction, summarize the outcome in
  docs/context/decisions.md and update the relevant context file.
