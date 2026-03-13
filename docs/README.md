# Docs Map

This repo uses four documentation surfaces on purpose. Each one owns a
different kind of truth.

## Recommended Reading Order

For a new developer evaluating the project:

1. `README.md`
2. `docs/problem-and-approach.md`
3. `docs/getting-started.md`
4. `docs/agent-integration.md`
5. `docs/privacy-and-visibility.md`
6. `docs/status.md`
7. `docs/overview.md`
8. `docs/context/architecture.md`

## Ownership

- docs/
  Developer-facing entry points and practical guides.
  Use this layer for evaluator flow, practical onboarding, integration, status,
  and concepts.

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
- If the question is "why this design and what were the alternatives?", update
  `docs/designs/`.

## Guardrails

- Keep front-door docs outside-in, not ontology-first.
- Do not duplicate planning state in docs/context/.
- Do not treat docs/designs/ as the canonical queue or status surface.
- When a design becomes accepted direction, summarize the outcome in
  docs/context/decisions.md and update the relevant context file.