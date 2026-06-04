# Operational Fact Memory

**Date:** 2026-05-31 (revised 2026-06-04)
**Status:** Draft. Phase 0 spike must complete before any code lands.
**Scope:** New derived memory type owned by the `agent_work_trace` package.

---

## Problem

In session A an agent discovers how this repo or machine works — Python path, test command, package manager, local service port, repo wrapper script — then uses the discovery successfully. In session B a fresh agent repeats the reconnaissance from zero.

Pallium should preserve the discovered fact and surface it on demand, so future sessions start from known evidence instead of rediscovering basics.

The capture pipeline (Stop hook + `agent_work_trace_turn` metadata, [semantic/agent_work_trace.py](../../semantic/agent_work_trace.py)) is **structurally present but production-broken**: as of 2026-06-04, `read_turn()` mis-parses the on-disk Claude Code transcript shape and returns zero tool calls; the live DB has 0 `task_trace` memory objects across 773 processed items. T3 (`fix/t3-agent-work-trace-activation`) replaces the per-line aggregation with a turn-bracket pipeline and adds a Codex translator (OpenAI Responses → Anthropic shape). Once T3 lands, the metadata fields this spec depends on (`files_read`, `commands`, `grep_patterns`, `files_modified`, plus a new `patch_bodies` field for Codex `apply_patch` events) are populated. **Phase 0 of this spec assumes T3 is merged and the metadata is observable in the live DB.** What's still missing after T3 is derivation and surfacing.

This must be generic — not keyed to product names, ticket ids, tool names, or one-off phrasing.

---

## Position In The Type System

`operational_fact` is the first member of a **structurally-derived project-shape family**, distinct from conversation-derived types (`decision`, `investigation_outcome`, `note`).

Conversation-derived memory captures what was said. Project-shape memory captures what was demonstrated to work by structural evidence in the tool stream.

Future siblings (not v1, not committed): a project file index; a deterministic edit-pattern log. Each requires its own spec.

---

## Phase 0 — Verification spike (REQUIRED)

The spike answers four questions and produces a go/no-go.

**T3 prerequisite.** Q3 below cannot be evaluated until T3 (`fix/t3-agent-work-trace-activation`) is merged and at least one Claude Code session has run end-to-end so that `source_items.metadata_json` actually contains `agent_work_trace_turn` keys and `memory_objects.type='task_trace'` rows exist. Until then the answer to Q3 is forced: insufficient data.

1. Does Claude Code `PreToolUse` `additionalContext` reach the model, or only the runtime/user?
2. Can the routing-signals pipeline expose a structural operational-intent signal (verb-object on normalized tokens, language-agnostic), or is one cheap to add?
3. Is the existing `agent_work_trace_turn` metadata sufficient for the discovery + use predicate without further hook changes? (Post-T3 fields: `files_read`, `commands`, `grep_patterns`, `files_modified`, `patch_bodies`. The last covers Codex `apply_patch` and `apply_patch_call` items, where T3 preserves the freeform body or the structured `{operation: {type, path, diff}}` for predicate use.)
4. Could the goal be met by formatting `task_trace`'s `commands_succeeded` better and adding cross-thread retrieval, instead of a new memory type? (downscope)

### Outcome matrix

| Q1: PreToolUse model-visible? | Q2: intent signal available? | v1 surface |
|---|---|---|
| yes | — | **Surface A only** (PreToolUse, Claude Code) |
| no | yes | **Surface B only** (UserPromptSubmit, both integrations) |
| no | no | **Kill v1.** No on-demand path; storing facts is dead code. |

If the spike shows `task_trace` formatting alone covers the use case, downscope to that and skip Phases 1–4. The spec must be revisited, not extended past its scope, before adding code.

Known relevant code: [semantic/agent_work_trace.py](../../semantic/agent_work_trace.py), [integrations/claude-code/hooks/](../../integrations/claude-code/hooks/), [integrations/codex/hooks/](../../integrations/codex/hooks/), `semantic/agent_conversation_memory_routing_selection.py`, `api/schemas.py` `QueryRequest`. Verify active code paths; do not assume from roadmap status.

---

## Memory Type

Schema id: `agent_work_trace.operational_fact`. Owned by `agent_work_trace`.

```python
{
    "command_family": str,       # python | node | gradle | npm | docker | service | git | shell | ...
    "artifact_role": str,         # interpreter | venv | version | runner | task | endpoint | path | ...
    "scope_kind": str,           # repo | machine_repo
    "scope_ref": str,
    "subject": str,              # short human-readable statement
    "artifact": str,             # discovered concrete value: path, command, port, URL, wrapper
    "artifact_normalized": str,  # posix-normalized; dedup + argv match key
    "evidence": [                # one discovery + one use, both required
        {"kind": "discovery"|"use", "source_item_id": str, "tool": str,
         "turn_index": int, "timestamp": str, "fragment": str},
        ...
    ],
    "lifecycle": "active" | "superseded",
    "reuse_count": int,
    "last_used_at": str,
    "supersedes": str | None,
}
```

`command_family` is derived deterministically from artifact shape and argv. Values are not closed: any new ecosystem (cargo, Bun, hatch) gets a `command_family` value the first time the structural predicate fires on it — the derivation reads the argv head, not a hardcoded enum. Concrete reference set: `python | node | gradle | npm | pnpm | yarn | uv | pip | cargo | go | docker | service | git | shell`.

### Routing registration

`agent_work_trace` calls `register_routing_types` on init with a `TypeRegistration` (shape per [core/type_registry.py](../../core/type_registry.py); reference [semantic/agent_conversation_memory.py:173-218](../../semantic/agent_conversation_memory.py#L173)):

- `type_name="operational_fact"`, `layer_name="operational_fact"`
- `weight_by_intent` — same defaults as `decision` (`{"recall": 150, "structured_recall": 220, "work_resumption": 145, "evidence_trace": 180}`); revisit after Phase 4 evals.
- `default_weight=150`
- `block_title="Operational fact"`, `block_text_field="subject"` (renderer appends `artifact`)
- `high_value=True`

Consolidation exclusion lives outside `TypeRegistration` — wire through the same path that excludes `note` from consolidation; reference at extraction time.

### Retention

`durable_types = frozenset({OPERATIONAL_FACT_TYPE})` — extend `MemoryRetentionPolicy` if needed (existing policy on [semantic/agent_work_trace.py:110-113](../../semantic/agent_work_trace.py#L110) only declares `working_types`). Cleaner removes only `lifecycle == "superseded"` facts older than 90 days; `active` facts are kept indefinitely.

---

## Extraction Predicate

Operates on `agent_work_trace`'s per-turn capture surface ([integrations/claude-code/hooks/common.py:644-682](../../integrations/claude-code/hooks/common.py#L644)) — `{files_read, commands{cmd, exit_code, output_tail, failure_class}, grep_patterns, files_modified, patch_bodies}`. Structural and ecosystem-agnostic.

`patch_bodies` (added by T3) is a list of `{body?, operation?}` records. `body` is the freeform `apply_patch` DSL string for Codex `function_call.name == "apply_patch"` events; `operation` is the structured `{type: create_file|update_file|delete_file, path, diff}` shape for top-level `apply_patch_call` items. The predicate may treat `operation.path` as a discovery candidate (Read-equivalent) and `operation.diff` as a use-equivalent edit signal. T3 does NOT itself parse freeform `body` — that's this spec's job.

A fact is created when **all** hold:

1. **Discovery event** — any tool call whose result yields a candidate artifact:
   - `Read` of a project file producing extractable text containing a path, command, version, port, or URL
   - `Bash` exit 0 whose `output_tail` contains an extractable artifact
   - `Grep`/`Glob` whose result lists a candidate path
   - `apply_patch` `operation.path` (Codex structured form) — a path being touched is itself a discovery signal for that path's existence
2. **Later successful action** — `Bash` exit 0 within N=10 turns in the same thread, OR an `apply_patch` event with `operation.path` (structured form) within the same window.
3. **Argv contains the artifact** as a substring, OR contains a path-equivalent (slash normalization, drive-letter case-insensitive on Windows). Same `command_family` alone does not satisfy this.
4. Both events within the same `scope_ref`.
5. Evidence links to both source items retained.
6. `command_family` derived deterministically from artifact + argv, not used as an extraction filter.

If the predicate is not satisfied, no fact is created.

**Invariant:** the predicate must catch a discovery + use pair in a fresh ecosystem (Rust + cargo, Bun, hatch) without code or spec changes.

### Examples (illustrative, not closed)

`python` — discovery: `where python`, `python --version`, read of `.python-version` / `pyproject.toml`, listing of `.venv*`, stat of `.venv/Scripts/python.exe`. Use: any later Bash exit 0 whose argv contains the candidate.

`test` (any runner) — discovery: read of `package.json`, `pyproject.toml`, `Makefile`, `build.gradle`; `<runner> --help`/`--list`. Use: later Bash exit 0 whose argv contains the candidate command stem and produces no test-failure markers.

`service` — discovery: `docker ps`, read of `compose.yml`/`docker-compose.yml`, port health check. Use: later Bash exit 0 against the same host:port, or a command depending on the service.

---

## Scope Rules

Two scopes, chosen at promotion time:

| `scope_kind` | When |
|---|---|
| `repo` | Repo-relative artifact (`./gradlew.bat`, `npm test`, `uv run pytest`). |
| `machine_repo` | Artifact depends on machine layout: absolute paths, repo-local venv, local service port. Default when uncertain. |

Heuristic: repo-relative (no drive letter, no absolute path) → `repo`. Otherwise → `machine_repo`.

`scope_ref` follows existing container_ref conventions ([integrations/claude-code/hooks/common.py:40-69](../../integrations/claude-code/hooks/common.py#L40)). For `machine_repo`: `<container_ref>@machine:<sha256-prefix-of(socket.gethostname() + platform.system() + platform.machine())>` — stdlib-only, cross-platform (no `os.uname()` which doesn't exist on Windows), no PII.

---

## Deduplication And Conflict

- **Conflict slot** = `(command_family, artifact_role, scope_kind, scope_ref)`. At most one `active` fact per slot.
- **Exact-dedup key** = `(command_family, artifact_role, scope_kind, scope_ref, artifact_normalized)`. Same-key events extend evidence and bump `reuse_count`; never duplicate.

`artifact_role` distinguishes facts that share a `command_family` but represent different things (e.g. `interpreter` vs `venv` vs `version` for `python`; `runner` vs `task` for `gradle`). Derived deterministically from the discovery shape, like `command_family`. Set is open.

When a new fact's exact-dedup key matches: merge, update `last_used_at`. When the conflict slot matches but `artifact_normalized` differs: newer supersedes older. Older lifecycle moves to `superseded`, gets `supersedes` link, stays queryable for audit, ineligible for injection. Conflict logged in `query_audit_log`.

Conflicting facts are never injected together.

Cases this handles: Python interpreter path moves `.venv` → `.venv-wsl` (same `command_family=python`, same `artifact_role=interpreter`); test command `pytest` → `uv run pytest`; service port changes.

---

## Surfacing

Store many facts. Inject few.

v1 ships **exactly one surface**, picked by Phase 0.

### Surface A — PreToolUse Bash (Claude Code only)

Active iff Phase 0 confirms `additionalContext` reaches the model.

When the agent is about to run argv, surface the active fact for the derived `command_family` in the current container's scope:

```
Operational fact: previous sessions used .venv/Scripts/python.exe for Python in this repo.
```

- Advisory only. No blocking, no rewriting, no suppression of the Bash call.
- Lookup keyed by `(command_family, artifact_role*, container_scope)` — `artifact_role` optional; the hook may not know it from argv alone, in which case it returns the most-recently-used active fact in the family.
- Latency budget < 100 ms. The MCP/`pallium_query` path is too coarse (text-similarity scoring over the full memory store); Surface A needs a direct lookup endpoint on the Pallium HTTP service. Phase 2 adds it: `GET /operational_fact/lookup?command_family=...&scope_ref=...` returning the active fact (or null) with a small in-process cache. The new MCP-tool work is still cut from v1; this endpoint is internal to the integration hook, not exposed via MCP.
- `superseded` facts not surfaced. Conflicting active facts not surfaced (already a `query_audit_log` entry).

### Surface B — UserPromptSubmit (cross-integration fallback)

Active iff Surface A is not viable AND a structural intent signal exists.

The intent signal must be structural, not phrase matching. Acceptable shapes:

1. A verb-object extractor on normalized tokens (Phase 0 scopes if absent).
2. The cue-free routing infrastructure exposing `intent.operational`.

Phrase matching is rejected (English-biased, structurally unsound). If neither shape is available after Phase 0, kill v1.

When the intent signal fires, operational facts compete with normal injection at lower priority than `constraint_memory`. Cap: 3 facts per UserPromptSubmit, one per `command_family`.

### Ranking

Sort by `last_used_at` descending. Take top N (1 for Surface A, 3 for Surface B).

### Do-not-inject

- Never `superseded`.
- Never conflicting active facts together.
- Never across container scope (`machine_repo` only renders in same machine_repo; `repo` only in same repo).
- Never crowd `constraint_memory`.
- Never exceed budget (300 chars per fact, surface caps above).

---

## Hooks

### If Surface A active

| Hook | Change |
|---|---|
| `pre_tool_use.py` (NEW, Claude Code only) | `command_family`-keyed lookup, < 100 ms, advisory. |
| `pre_compact.py` (Claude only) | **Preservation only.** Re-inject an operational fact if and only if it was already surfaced in the active conversation window before compaction. Not an independent injection path; never introduces a fact the model hasn't seen. |
| `session_start.py`, `user_prompt_submit.py` | No change. |
| Codex | No operational-fact integration in v1 (no PreToolUse equivalent). |

### If Surface B active

| Hook | Change |
|---|---|
| `user_prompt_submit.py` | Route through structural intent signal; inject only on operational intent. Same in Claude and Codex. |
| `pre_compact.py` (Claude only) | **Preservation only.** Re-inject an operational fact if and only if it was already surfaced in the active conversation window before compaction. Never an independent injection. |
| `common.py` (both) | Mirror extraction/redaction additions; parity test. |
| `session_start.py`, `stop.py` | No change. |

Existing constraints in either case: hooks stdlib-only; Pallium-unreachable must not break the agent; redaction before storage; container pinning and visibility unchanged.

---

## MCP

v1 uses existing `pallium_query` text retrieval for any `pallium_*` tool consumer (Surface B path goes through it). No new typed filters, no new MCP tool.

If Surface A is active, the integration hook calls a new internal HTTP endpoint `GET /operational_fact/lookup` on the Pallium service (added in Phase 2) — not via MCP, because PreToolUse needs sub-100 ms and the MCP path adds a tool-call hop. The endpoint is internal to the integration hook surface and is not promoted to MCP in v1.

`pallium_expand` returns the discovery and use evidence source items via the existing path.

---

## Security

Reuse redaction in [agent_work_trace](../../semantic/agent_work_trace.py): API keys, bearer tokens, private keys; env vars containing `PASSWORD`/`SECRET`/`TOKEN`/`KEY`/`AUTH`; connection strings (`mongodb://`, `postgres://`, `mysql://`, `redis://`); `Authorization:` and `Cookie:` header values.

Operational facts respect existing container scope, visibility, and actor access. Storage is posix-normalized; rendering may use platform separators.

---

## Test Plan

### 1. Hook extraction parity
Bash exit codes, discovery tools captured, Edit/Write excluded, secret redaction, Windows + POSIX path normalization, output capping, malformed-transcript safety, missing-exit-code conservatism. Claude/Codex `common.py` parity (Surface B only).

### 2. Derivation
Discovery + matching use → fact. Discovery alone → no fact. Discovery + use of *different* artifact in same family → no fact (argv-match regression guard). Use without discovery → no fact. Test/gradle/docker examples per the predicate. Failed command → no fact. Conflicting newer fact supersedes older with `supersedes` link. Absolute path → `machine_repo`; repo-relative → `repo`. Secret-like artifact rejected/redacted. Evidence links to both items. `last_used_at` and `reuse_count` update on subsequent matching use.

### 3. Retrieval / injection
Surface A: about-to-run Bash returns active fact for that container's scope; `superseded` not surfaced. Surface B: operational-intent prompt injects relevant facts; non-operational prompt does not. Conflicting facts never together. Never crowds `constraint_memory`. Within 300-char budget. `pallium_expand` returns discovery + use evidence. Cross-session orientation not wrongly suppressed.

### 4. End-to-end
Session A (discover + use) → Session B (fact surfaces). Variants for the active surface only. Windows PowerShell + POSIX. Pallium unreachable does not break agent. Empty DB. Existing `task_trace` without operational fact. Multi-repo isolation. Same repo cross-machine: `machine_repo` does not leak; `repo` does follow correctly. Visibility filtering. Public context does not leak machine-local fact.

---

## Evals

Retrieval and injection only (redaction/extraction safety are unit tests).

- `operational_fact_runtime_python_reuse`
- `operational_fact_test_command_reuse`
- `operational_fact_wrong_repo_suppression`
- `operational_fact_machine_scope_boundary`
- `operational_fact_no_value_prompt_no_injection` (Surface B)
- `operational_fact_conflict_prefers_fresh_success`
- `operational_fact_artifact_match_required`

Multilingual prompt variants for Surface B confirm structural-only intent.

---

## Invariants

- No fact without evidence links (one discovery + one use).
- No fact without artifact-in-argv match.
- No injection of `superseded`.
- At most one active fact per `command_family` × scope.
- No cross-container leakage.
- No public visibility for machine-local facts.
- No command rewrite, no blocking.
- No unredacted secrets.
- Within 300 chars per fact, 1 fact at Surface A, 3 at Surface B.
- Hook failures non-blocking.
- Claude/Codex parity (Surface B only).
- No `task_trace` regression.

---

## Documentation Updates

- `docs/context/architecture.md` — add `operational_fact` and name the project-shape family.
- `docs/claude-code-integration.md` — hook behavior for the active surface.
- `docs/codex-integration.md` — Codex hook asymmetry; Claude-only operational facts if Surface A wins.
- `docs/agent-integration.md` — if agent-facing instructions change.
- `roadmap/*` — only when implementation status changes. If Phase 0 finds drift, surface in spike note.

---

## Rollout

- **Phase 0.** Spike. Fill in outcome matrix. Commit to: Surface A, Surface B, downscope, or kill.
- **Phase 1.** Schema + storage; structural derivation; unit tests (§Test Plan 2).
- **Phase 2.** Implement the picked surface; debug audit-log entries; retrieval/injection tests (§3).
- **Phase 3.** Hook integration (Claude, Codex if Surface B); parity test (Surface B); integration docs.
- **Phase 4.** Evals + invariants; regression suite; e2e.

### Phase 5+ (not v1; revive only on measured trigger)

| Item | Revive when |
|---|---|
| The other surface | Single surface insufficient |
| `medium`-confidence frequency-based facts | Recall too low |
| `category` axis grouping families | Cross-family ranking matters |
| Typed `/query` filters | Text retrieval misses operational facts |
| Lazy revalidation + softener | Stale facts dominate FP rate |
| `machine`, `workspace`, `container` scopes | Real cases show repo/machine_repo wrong |
| Active-fact decay / TTL | Stale active facts dominate FP rate |
| LLM extraction proposals (with structural argv-match still gating) | Structural recall insufficient |
| Markdown materialization (`pallium operational dump`) | Debugging needs human-readable dump |
| Local-deployment subscription credentials shell-out (strip `ANTHROPIC_API_KEY`, use `claude -p`) | LLM extraction added in Phase 5 |

---

## Acceptance

**Capability**

- Fact derived from discovery + argv-match use; correct scope and evidence.
- Single active surface injects on the right trigger; not otherwise.
- Surface A: Claude-only. Surface B: both integrations.
- Tests cover extraction, derivation, routing, injection, integration, redaction, scope, conflicts, failures.
- Evals/invariants updated, or judged unnecessary with rationale.
- Docs and roadmap aligned.
- No regression in `task_trace`, routing, privacy.

**Empirical (kill criterion)**

Across 15+ real sessions in 2+ repos over 3 weeks: ≥70% of repeated operational reconnaissance commands (cases where a previous session in same scope had the answer) preempted by an injected `operational_fact`, with <5% false-positive injection rate.

If FP rate exceeds 10% after 3 weeks, suppress injection and revisit derivation. Mirrors the [agent_work_trace spec](2026-05-05-agent-work-trace-design.md) precedent: measured reduction across 15+ sessions, not a binary capability check.

---

## Open Architect Questions

1. Is this truly a derived fact, or a `task_trace` formatting improvement? (Phase 0 downscope clause; reviewer to validate.)
2. Are `repo` and `machine_repo` sufficient to prevent leaks across containers and visibility, or is there a concrete case requiring `machine`-only scope?
3. Does this duplicate query-routing responsibilities, or cleanly extend `agent_work_trace`?
4. Enough observability (`query_audit_log`, supersession links) to debug wrong/missing injections?
5. Are tests proving end-to-end behavior — particularly artifact-match-required and machine-scope-boundary?
6. Is the Phase 0 → single-surface decision tight enough to prevent "ship both, see what happens" creep?
