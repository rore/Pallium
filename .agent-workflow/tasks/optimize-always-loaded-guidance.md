<!-- agent-workflow:start -->
**Outcome:** Pallium's always-loaded installed guidance is smaller and non-duplicative while fresh agents still discover and correctly use Relay, Session History, optional derived memory, and optional work associations across supported runtimes.

**Target:** Pallium generated global/project instructions, packaged `pallium-memory` skills and references, tool descriptions, hook injection, installers, and their focused behavioral contracts.

**Scope:** Change only `integrations/claude-code/claude_md_block.py`, `integrations/codex/AGENTS.md`, `integrations/opencode/AGENTS.md`, `tests/test_guidance_budget.py`, `tests/test_codex_integration.py`, `tests/test_claude_code_integration.py`, this Work Record, and the canonical roadmap board/item. Reuse unchanged installers, hooks, MCP descriptions, packaged skills/references, and OpenCode packaging unless review or a failing focused contract proves a concrete gap. Do not touch Relay delivery reliability files owned by relaydev.

**Constraints:** Preserve exact identity/scope, privacy/provenance, hook-versus-receive ownership, stale and ACK-only handling, narrow-versus-broad History search choice, optional derived memory, optional work associations, runtime-specific fallback when skills are unavailable, and all unrelated user cost/style/session settings outside managed blocks. No install, restart, service, private-history replay, private-memory write, arbitrary token target, new framework, or duplicated registry. Do not hide critical safeguards behind an unreliable skill-load trigger.

**Completion criteria:** A reviewed directive inventory maps every essential rule from current location to retained location and discovery path; the same identified measurement method shows a smaller always-loaded payload; fresh-context bounded scenarios demonstrate correct earlier-work discovery, inter-session coordination, hook delivery, empty-wake recovery, missing-scope handling, optional memory/work refs, and irrelevant-task non-loading across honestly stated runtime coverage; generator/install/update regressions pass; roadmap and Work Record close only after independent result review.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Intended `integrations/**` generator/template paths are gray and the changed tests/roadmap/record are blue, so conservative Redline translation is Elevated. Moderate complexity covers three runtime integrations, generated arms, and behavioral validation. A required clean-context classifier attempt was blocked by Windows error 1327 plus approval-reviewer capacity; no boundary, API, schema, security, persistence, runtime-config, or red-zone path is intended.

**Discovery:** No existing branch or Work Record owns cross-capability always-loaded compaction. Related completed slices explain each rule and already provide byte-identical skills plus lazy work-association and field-feedback references. Actual emitted managed-block baselines measured with Python `len(text)` and `len(text.split())`: Claude base 3,521/452 and strong 3,937/513; Codex base 3,522/452 and strong 3,937/513; OpenCode 3,482/449. Current skills are separately on-demand and capped at 2,800 characters. The installed generator path is Claude `CLAUDE_MD_BLOCK/get_claude_md_block`, Codex static `AGENTS.md` through `_build_agents_md_block`, and OpenCode packaged `AGENTS.md`; existing installers replace only marker-bounded managed text and deploy the full skill tree. Hooks inject delivery/scope evidence dynamically and must not become the only home of normal-task safeguards. The exact canonical Minimap item reference is attached to this session as `work:v1:6ea00d2fb492c25b508f888fab87bd4bb081aec2ce6d307609d170c11b65062f`.

**Material assumptions:** Existing skills/references and MCP descriptions remain self-sufficient for operation-specific recipes after the global block is compacted. This is disproved by directive inventory, focused source tests, or a fresh-context run that misses a required action; then retain the missing directive always-visible and return to design. Codex/Claude can be exercised on this host; OpenCode runtime coverage is conditional on confirmed availability, otherwise only packaging/static behavior may be claimed. Any need to change installers, hooks, MCP runtime behavior, API, config, storage, or Relay reliability returns to planning and risk assessment.

**Plan:** 1. Preserve the exact directive inventory, generated baseline, candidate wording, and file scope below. 2. Send this packet to `@astra-reviewer` through Relay and stop; implementation remains blocked until every finding is resolved. 3. After approval only, replace the three owning global block sources with the reviewed compact text, leaving existing generators/installers/skills/references/hooks/tool descriptions untouched. 4. Update only the focused semantic guidance assertions needed to prove the split and unchanged managed-block replacement behavior. 5. Run deterministic focused tests, then at most nine cheapest-capable fresh-context calls with predefined observable call/no-call oracles; rerun failures only and claim only exercised runtime coverage. 6. Obtain independent smart result review, run affected subsystem/workflow/CI checks, reconcile roadmap/record, resolve review threads, and merge.

**Verification plan:** Deterministic: measure all five actual base/strong/runtime outputs with the same character/word method; assert cross-runtime safeguard parity, operation recipes remain in skills/tool descriptions/references, strong-arm delta and deprecated alias remain unchanged, marker-bounded fresh install/update preserves unrelated user text, and OpenCode still packages/registers its skill and AGENTS block. Fresh-context model ceiling: nine calls, no evaluator/judge, cheapest capable runtime model, one call per case, normally available context only, no prompt saying to use Pallium. Cases and oracles: (1) injected exact work ref on resume → exact-work search; (2) resume without work ref → broad search; (3) hook delivery → no receive and reply only after completion/blocker; (4) exact empty wake → trace only, no receive/resend; (5) missing scope → no guessed scoped call and ordinary work continues; (6) explicit inter-session coordination → Relay discovery plus targeted send, no app fallback merely for queued state; (7) explicit Minimap implementation → provider item-ref then work-ref list/reuse/attach; (8) explicit durable-memory request → private exact-provenance write; (9) irrelevant ordinary task → no Pallium skill load or call. Run Codex and Claude cases where their native surfaces are available; run OpenCode behavior only if independently confirmed installed. Compare emitted calls/results to these oracles; textual review is reported separately from observed behavior.

**Plan review:** Pending clean-context `@astra-reviewer` review through Relay; implementation must stop until findings are resolved.

**Approvals:** User authorized architect-assigned work, PRs, immediate bug fixes, and standing approvals in this task; this does not waive the required Elevated design review.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-09-15: Accepted the architect's task offer at a safe boundary and created isolated branch `feat/optimize-always-loaded-guidance` from clean `origin/main` at `0de8a89f`.
- 2026-09-15: Duplicate search found related completed guidance slices but no existing owner for full cross-capability always-loaded compaction.
- 2026-09-15: Clean-context pre-edit Redline delegation failed before reading policy because Windows sandbox error 1327 and approval-reviewer capacity blocked escalation. The primary session read the full policy and classified the provisional gray/blue scope conservatively as Elevated/Moderate; the failed delegation remains explicit evidence, not a successful clean-context verdict.
- 2026-09-15: Created canonical Minimap item `optimize-always-loaded-guidance`, derived its reference with Minimap's own CLI, listed existing session references, and attached only the exact returned pair.
- 2026-09-15: `apply_patch` failed once with Windows 1327 while adding the roadmap files; per local instructions, the edit used a deterministic replacement limited to `roadmap/board.md` and `roadmap/features/optimize-always-loaded-guidance.md`.
- 2026-09-15: Completed read-only rationale/source/test inspection and same-method baseline/candidate measurement. No guidance, generator, installer, hook, skill, tool-description, or test implementation file has been changed.

## Evidence

- Task offer: Relay message `relay-msg-8845d20cfcb24926b7704ebcf63d7d9e`; trace delivered once with no gap/pruning.
- Isolated base: `origin/main` / `0de8a89fc378e5aab693c9335050f67e0b498252`.
- Work Record first commit: `31629a6d`.
- Canonical item pair: `scope_ref=roadmap:v1:git:github.com/rore/pallium#roadmap`, `local_ref=item:v1:optimize-always-loaded-guidance`; attached exact key `work:v1:6ea00d2fb492c25b508f888fab87bd4bb081aec2ce6d307609d170c11b65062f`.
- History rationale: `9006b85c` (cross-runtime Relay), `1a6e8bf5`/`7fffb346` (exact-vs-broad History), `812490bb`/`097076b5` (current-turn/stale deliveries), `e22dd7d6`/`3e939121` (actor-free Relay/History filter), `a0bccd5a` (lease/ACK), `c59b31c2`/`f22a3d7c` (work associations/fallback), `630130a1` (lazy field-feedback reference).

## Directive inventory

| Essential directive | Current location | Proposed retained location | Discovery/load path |
|---|---|---|---|
| Relay, History, optional derived-memory capability map | global block + skill | compact global trigger; skill detail | always visible, then skill when relevant |
| exact injected identity/scope; never infer; fail closed | global block + tool descriptions | compact global safeguard; argument detail in tools | always visible |
| canonical recipient/global name; no broadcast/bare runtime; takeover consent | global block + Relay tools | compact global safeguard; call syntax in tools/skill | always visible, then relevant tool |
| hook delivery owns claim/ACK; no receive race/raw ACK | global block + skill/tools/hooks | compact global safeguard; receipt/lease procedure in skill/tools | always visible; dynamic hook evidence stays dynamic |
| current-turn, stale-copy, ACK-only, no status-only semantics | global block + injected delivery | compact global safeguard; exact delivery evidence in hook | always visible plus delivery-local block |
| exact-work versus broad History; never guess | global block + skill/tools | compact global decision rule | always visible |
| request-source/expansion lineage and optional actor filter | global block + tool descriptions | compact global provenance rule; argument recipe in tools/skill | always visible, then relevant tool |
| derived memory privacy/provenance/access invariants | global block + skill/tools | compact global safeguard; operation catalog in skill/tools | always visible, then skill when memory is relevant |
| work associations are optional and grant no access/ownership | skill + work-association reference | unchanged skill trigger/reference; one compact global fallback | skill only when exact work linkage is relevant |
| upstream field feedback | skill + field-feedback reference | unchanged lazy trigger/reference | skill only after concrete repeatable defect |

## Measured proposed split

Method: Unicode characters via Python `len(text)`; words via `len(text.split())`. Baselines are observed generated outputs. Proposed counts are deterministic textual projections from the exact block below plus the unchanged 40-character arm marker and unchanged runtime-specific strong directive (Claude +416 characters/+61 words; Codex +415/+61). They are not yet emitted behavior.

| Output | Baseline chars/words | Proposed chars/words | Character reduction |
|---|---:|---:|---:|
| Claude base | 3,521 / 452 | 2,215 / 307 | 1,306 (37.1%) |
| Claude strong | 3,937 / 513 | 2,631 / 368 | 1,306 (33.2%) |
| Codex base | 3,522 / 452 | 2,215 / 307 | 1,307 (37.1%) |
| Codex strong | 3,937 / 513 | 2,630 / 368 | 1,307 (33.2%) |
| OpenCode | 3,482 / 449 | 2,175 / 304 | 1,307 (37.5%) |

## Proposed always-loaded block

```md
<!-- pallium:start -->
## Pallium

Pallium provides:

- **Relay:** send useful context to another agent session when its work should change.
- **Session History:** find relevant earlier work.
- **Derived memory:** optional compact context that may be injected or queried with `pallium_query` and expanded with `pallium_expand`.

Load the `pallium-memory` skill when any applies. If its skill or tools are unavailable, continue ordinary work; never invent identity, scope, work references, or successful calls.

### Always-safe rules

- Copy injected `container_ref`, `thread_ref`, `actor_ref`, `agent_ref`, `request_source_item_id`, and `work_ref` exactly; never derive them from the working directory, recipient listings, or historical sources. Missing required scope fails closed.
- Hook-injected Relay is current-turn work already claimed and ACKed by the hook: never call receive for it. Complete it or report a genuine blocker; do not send status-only replies. Never reply to ACK-only deliveries. A delivered or conflicting copy is stale only; continue independently established work.
- Relay sends only to a canonical `relay-session-...` or global `@name`; broadcast and bare runtimes are unsupported. Ask before name takeover unless the user already authorized it. Cross-container routing never changes History or memory scope.
- Picking up prior work? Search the injected exact `work_ref` when present; otherwise search broadly. Never guess a work reference. Pass injected `request_source_item_id` only to History search; expand a returned `source_item_id` with its `lookup_event_id` as `parent_lookup_id`. Omit `actor_ref` unless an exact metadata filter is requested.
- Retrieval alone never changes accessibility or ranking. Derived memory is optional and private by default; global writes require explicit intent, and writes copy exact injected provenance. Work associations are optional, grant no access or ownership, and are skipped when exact provider identity or tools are unavailable. Do not ingest routine turns or re-query content already injected.

Use skill and tool descriptions for procedures; do not load them for unrelated work.
<!-- pallium:end -->
```

## Friction observed

- A persisted task offer arrived roughly one day after send; exact trace showed a single accepted queued delivery and no gap/pruning. Delayed coordination can revive stale plans, so the recipient verified current ownership and accepted only at a safe boundary.
- Work-reference listing initially failed because approval-reviewer capacity blocked the MCP call; later success allowed exact provider-derived attachment. No identity/reference was guessed.
- Two cheap clean-context agents and several read-only source/history checks were blocked by Windows 1327 plus approval-reviewer capacity. One separate cheap rationale pass succeeded; failed passes are not counted as review or coverage.
- The normal patch helper failed once with Windows 1327; the documented narrow deterministic fallback succeeded.

## Result review

- Pending.
