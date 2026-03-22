# Documentation

## For Users

Start here if you're evaluating or using Pallium.

| Doc | What it covers |
|-----|---------------|
| [Getting Started](getting-started.md) | Local setup to first query in ~10 minutes |
| [How It Works](how-it-works.md) | Design rationale, memory model, retrieval architecture |
| [HTTP API](http-api.md) | Endpoints, request/response shapes, examples |
| [Configuration](configuration.md) | Providers, packages, prompt roles, tuning knobs |
| [Agent Integration](agent-integration.md) | Wiring Pallium into an agent runtime |
| [Integration Example](integration-example.md) | Concrete Slack agent walkthrough with code |
| [Privacy and Visibility](privacy-and-visibility.md) | Scoped memory boundaries and enforcement |

Recommended order for a first read: Getting Started → How It Works → HTTP API.

## For Contributors

Project internals, architecture decisions, and planning.

| Doc | What it covers |
|-----|---------------|
| [context/architecture.md](context/architecture.md) | Stable architecture truths |
| [context/decisions.md](context/decisions.md) | Accepted design decisions |
| [context/state.md](context/state.md) | Current repo state and handoff snapshot |
| [context/validation.md](context/validation.md) | Benchmark architecture and acceptance gates |
| [context/lessons.md](context/lessons.md) | Problem-solution pairs worth remembering |
| [context/prompt-improvement.md](context/prompt-improvement.md) | Prompt variant workflow |
| [context/vision.md](context/vision.md) | Project identity and principles |
| [designs/](designs/) | Design threads, proposals, and analyses |

## Ownership

- `docs/` — user-facing guides and references
- `docs/context/` — stable project truth for contributors
- `docs/designs/` — longer design threads and tradeoff analyses
- `roadmap/` — planning, queue, milestones, feature status
