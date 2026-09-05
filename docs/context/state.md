# Current State

> Updated 2026-09-05. Keep queue and sequencing in [roadmap/](../../roadmap/);
> this file is only a short implementation snapshot.

## Product shape

Pallium has two primary capabilities:

- Relay connects existing agent sessions.
- Session History records governed turns and lets later sessions search earlier
  work.

Derived-memory packages remain implemented but are an optional, experimentally
evaluated layer over history rather than the product definition.

## Shipped

### Relay

- persistent bounded messages
- runtime-wide, exact-session, and alias addressing
- replies and delivery status
- automatic hook delivery plus MCP recovery receive/ack tools
- durable next-natural-turn fallback for Claude Code, Codex, and OpenCode
- Windows Claude Code wake qualified
- Windows Codex loaded and unloaded exact-session wake proven

Codex lifecycle/dogfood gates, non-Windows qualification, and OpenCode active
wake remain open. There is no scheduled Relay feature.

### Session History

- source-only historical retrieval
- `pallium_search_history` for broad topic search
- `pallium_search_history_by_work_ref` for exact-reference search
- bounded `pallium_expand_source` context
- linked lookup/expansion telemetry
- search and expansion redaction
- per-neighbor visibility enforcement
- raw-turn forgetting and shared-raw revocation
- safeguards for superseded historical guidance

Supported integrations attach structural work references, and exact work-reference
search is shipped. Running raw Session History with zero semantic packages remains
ordered work, not shipped behavior.

### Derived memory

The existing packages support extraction, hybrid lexical/vector retrieval,
routing, explicit memory writes, lifecycle, evidence expansion, multilingual
text, and evaluation tooling. They still participate in the current runtime
configuration while the package-independence work is pending.

## Runtime and operations

- first implementation language: Python
- normal installed service port: `19836`
- local storage: SQLite, with separate Relay persistence where configured
- supported coding tools: Claude Code, Codex, OpenCode
- installed-service restart path for development:
  `scripts/restart-service.ps1`
- required post-restart checks: `/health`, `/status`, and
  `/debug/queue/health`

## References

- current queue: [roadmap/board.md](../../roadmap/board.md)
- product scope: [roadmap/scope.md](../../roadmap/scope.md)
- Session History direction: [strategy-vnext.md](strategy-vnext.md)
- architecture: [architecture.md](architecture.md)
- durable decisions: [decisions.md](decisions.md)
- operational rules: [operations.md](operations.md)
