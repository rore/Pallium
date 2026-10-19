---
id: add-hermes-agent-integration
title: Add Hermes Agent integration
status: in-progress
priority: high
commitment: committed
milestone: pallium-relay
lane: integration
---

## Summary

Ship the full Pallium integration package for Hermes Agent, covering the bundled
skill and guidance, MCP tools, Relay, Session History capture/search/expansion,
optional derived memory, and setup/removal support as in the existing runtime
integrations. Deliver it in isolated slices alongside current reliability work.
The first deliverable proves Relay through the released native plugin API;
that proof alone does not complete this feature.

Initial source validation on **2026-10-17** supports investigating **Hermes
v0.22.2**, not waiting for unreleased gateway architecture. Slices 1 and 2 have
isolated native proofs and full non-slow regression passes. PR #321 is being
prepared for publication against merged reliability work; broader qualification
remains open. This is not general Hermes support.
Session History and optional derived-memory behavior remain required integration
scope, with discovery and E2E acceptance before claiming support. The supplied
research establishes neither. The user explicitly confirmed full-package scope
on 2026-10-19, including the skill, Session History and MCP.

## Why

Hermes has host-owned plugin injection and context hooks that could connect its
existing sessions to Pallium's durable Relay inbox. Reuse these native extension
points without spawning a competing Hermes process, owning an agent's workflow,
or building another message queue. The primary risks are conversation identity
drift after reset and duplicate actions or paid turns after ambiguous acceptance.

## Sequencing

- On 2026-10-19 the user approved isolated slice 1 in parallel: first prove a
  real released-host send → automatic idle wake → full payload → integration ACK
  → reply round trip, using disposable data and a local provider stub. Branch
  `feat/hermes-e2e-slice1` owns that experiment. No live setup is authorized.
  Broader rollout remains behind the release/rollout/real-delivery gates owned by
  `add-wake-first-relay-delivery`; this experiment does not satisfy those
  gates. Hermes precedes Copilot in runtime
  expansion without changing Copilot's existing prerequisites.
- The user subsequently approved slice 2 on 2026-10-19: installable skill and
  guidance, trusted MCP, Hermes-originated discovery/send/reply, setup/status and
  safe removal. `feat/hermes-package-slice2` is isolated from reliability and
  stacked on pushed slice-1 checkpoint `377327dd`. Its installed-package native
  journey and combined full-suite regression passed. The user approved preparing
  and merging PR #321 before slice 3; its final integration gates remain required.
  This does not imply live installation or broad qualification.
- Consume the shipped `add-relay-activation-capability-contract` and
  `add-relay-delivery-trace`. Reuse capability, fallback, fencing, and diagnostic
  contracts rather than introducing Hermes-only delivery authority.
- Recheck current Pallium and the actual Hermes release/build when picked up.
  v0.22.2 is the researched baseline, not a requirement to freeze, downgrade, or
  replace the user's installation. Its release notes explicitly distinguish the
  stable line from unreleased work and identify v0.22.1 as an accidental build.

## In Scope

### Agile delivery order

1. **Slice 1, implemented experimental proof:** one loaded Windows Hermes v0.22.2 gateway conversation,
   disposable profile/service data and local provider stub. Proved send → automatic
   idle marker wake → actual-turn claim → complete attributed provider request →
   integration ACK → host-bound reply → sender receipt. Common changes cover
   runtime recognition and the metadata-only pending read. The plugin is an
   explicitly enabled qualification adapter, not a general installation.
2. **Installable Relay package, implemented experimental proof:** bundled Pallium skill and references,
   runtime guidance, supported MCP configuration and trusted per-conversation
   identity propagation, plus setup/status/removal. The real-host journey proves
   Hermes discovers a recipient, initiates a message and receives its reply
   through the packaged tools. Disposable-profile installation, repeated setup
   and removal preserve unrelated configuration.
3. **Session History:** capture governed user and assistant turns with stable
   source identity and provenance. Prove a later Hermes session can search that
   history and expand the source through MCP; preserve visibility, redaction,
   forgetting, pagination and lookup lineage. This is required feature scope,
   not an unrelated follow-up.
4. **Optional derived memory:** package the existing configured memory tools and
   guidance, and qualify any supported capture/query/injection hooks. Preserve
   opt-in behavior and private defaults; Relay and History work without enabling
   memory processing or provisioning a new inference provider.
5. **Normal-use and recovery qualification:** busy-session queueing, concurrent
   sessions, reset/close, restarts, ambiguous injection/ACK and stale routes.
   Extend real-host E2E coverage and coordinate generic fixes with the Relay
   reliability owner. Feature completion requires the complete package and its
   qualified lifecycle, not only the slice-1 round trip.

The frozen slice-1 topology must assert actual loaded plugin inventory before and
after, strict profile/provider configuration, clean pinned bundled source and
provider receipt before ACK. v0.22.2 exposes no public PluginContext middleware
count or callback enumeration; arbitrary middleware hotloads and general-provider
qualification remain blockers for broader release.

**Slice-1 evidence, 2026-10-19:** the real pinned Windows gateway and local provider
stub passed send → idle wake → full attributed request → integration ACK → native
reply tool → original sender receipt. The same run passed wrong-recipient and
closed-endpoint controls. This is an isolated experiment, not shipped support;
human result review and the later slices remain open.
The allocated full non-slow run stopped after 5,395 passes on an unchanged AnyIO
limiter test: the shared test environment has 4.12.1 while this branch requires
4.14.2 or newer. That exact test passes with locked 4.14.2 in a disposable overlay;
the shared environment was not changed. A compatible-environment full rerun still
needed a coordinated slot; the combined hosted validation below supersedes that request.

Two native requirements emerged from execution. The disposable profile disables
Tool Search with quoted `tools.tool_search.enabled: "off"` so the test can invoke
the reply function directly. Default Tool Search bridge behavior remains later
qualification. Registered handlers receive session ID but omit turn ID in this
release; public `tool_execution` middleware carries both. A context-local handoff
preserves normal host authorization and binds the reply to the admitted turn.

**Slice-2 evidence, 2026-10-19:** production setup installed the skill and trusted
12-tool MCP package into a disposable profile. The pinned released host loaded
the skill and ran two conversations with overlapping discovery calls and distinct
sender identities. Both sent through MCP, received peer replies by automatic
wake, forwarded full attributed Unicode context to the local provider, ACKed
after provider completion and replied through MCP to the peer. Wrong-recipient
and closed-session controls retained pending messages without claims or ACKs.
Repeated offline setup, status and removal preserved unrelated config, comments,
credentials and data. Native E2E: **1 passed in 71.22s**; focused plugin/MCP/setup
and default Relay MCP regressions also passed. Independent review accepts the
frozen experiment. Combined hosted non-slow regression passed on Python 3.12 and
3.13 (each **7,190 passed, 92 skipped, 2 xfailed**), plus Windows smoke; evidence
is [draft PR #321](https://github.com/rore/Pallium/pull/321), application revision
`882546cf`. An initial 3.12 common Relay setup timeout passed one focused test
and one hosted job recheck without code/test changes. Human review remains open.
Setup requires exclusive offline profile access: the native writer has no
atomic conflict check for overlapping writers. Live setup, ordinary providers,
default Tool Search, History, optional memory and recovery remain unqualified.
Detailed revision, source hashes and disposable artifacts are recorded in
`.agent-workflow/tasks/hermes-package-slice2.md`.

**Publication integration:** merged main `cf4e8ece` (PR #314) was incorporated
without conflict at `ad30f944`. The native package journey passed again in
104.00s, and affected MCP/plugin/setup/app-run/Relay files passed 273 tests with
one platform-permission skip. Independent review accepts the four-file code
composition. Final hosted checks and review are authoritative on PR #321. The
full feature remains in progress; slice 3 is Session History, and live rollout
requires separate environment approval.

### Complete integration scope

- Bundle the `pallium-memory` skill, its applicable reference procedures and
  Hermes-native orientation guidance. Cover Relay, Session History, optional
  derived memory and work associations without inventing a second policy.
- Expose the existing applicable Pallium MCP tool surface using supported Hermes
  configuration and trusted live session/container identity. Qualify both normal
  and Relay-woken tool use, concurrent conversations and permission refusal;
  a static profile-wide MCP identity is not proof of the requesting conversation.
  Reuse shared tools and contracts rather than building Hermes-specific copies.
- Capture governed user and assistant turns for Session History, with stable
  upstream event identities, idempotence, exact scope and provenance. Support
  broad/exact-work search and source expansion through MCP, including bounded
  replay and the existing visibility/redaction/forgetting contracts.
- Support the existing optional derived-memory capabilities through the package,
  with explicit configuration, private defaults and source provenance. Retrieval
  alone never changes accessibility/ranking. Discover host hook support before
  advertising automatic memory injection; do not require memory processing for
  Relay or History.
- A Hermes-native plugin, distributed through supported plugin mechanisms, with
  explicit setup, permission checks, compatibility detection, removal, and bounded
  lifecycle cleanup. Keep Hermes-specific behavior inside its integration.
- Exact conversation registration, discovery/address, common send/reply/status,
  and session-bound wrappers for self-addressed Relay operations. Derive identity
  from trusted host turn context; never let the model select its own identity or
  use a static profile MCP connection as proof of the current conversation.
- Natural-turn delivery through `pre_llm_call`, with payload admission/ACK
  verification at the effective `llm_execution` request and successful downstream
  execution in the explicit single-plugin/provider topology. The real local
  provider stub must independently observe the complete attributed content;
  `pre_api_request` alone is insufficient. Preserve attribution, scope, claim leases,
  `claim_attempt`, and `possible_redelivery`.
- A small outbound pending-work poller in the owning Hermes host, using
  `ctx.inject_message("Pallium Relay wake: <delivery-id>", role="user",
  session_key=...)` only on qualified hosts. The notification contains a stable
  marker; the actionable payload stays in Pallium until claimed.
- Reuse `RelayService.pending_candidate()` and
  `SQLiteRelayMixin.relay_pending_candidate()`'s exact-scope read-only
  semantics. Slice 1 adds the scoped metadata-only HTTP wrapper; it remains
  experimental on the isolated branch until validation/review and merge.
- Integrate runtime validation, HTTP/MCP schemas, registration/activation,
  diagnostics/dashboard, setup and user guidance, and E2E coverage wherever the
  existing supported-runtime contract requires it. Audit these callers together;
  adding a plugin alone does not make Hermes a supported runtime.

## Proposed Delivery Contract

1. Register the exact container, profile/host, conversation identity, and native
   routing key. Advertise capabilities per live integration/session, not globally
   for all Hermes modes.
2. Poll a bounded, read-only pending check. It must neither claim nor ACK nor
   expose message bodies. Retain existing scope and authorization boundaries.
3. Before native submission, persist an integration-owned metadata-only wake fence
   in supported profile state, tied to the exact
   target and delivery. Submit at most one uncertain/accepted wake for that fence.
   A proven pre-submit refusal can permit retry; timeout or lost response cannot
   be treated as refusal. Coalesce safely without starving other pending messages.
4. On the actual turn, verify trusted current conversation identity against the
   registered recipient before claiming. A delayed stale wake may produce an
   empty notification turn; it must never reveal an old recipient's payload to a
   successor using the same route.
5. Claim and append attributed Relay content from `pre_llm_call`. Correlate by
   session and turn, not a process-global current-session variable. Verify exact
   attributed content in the effective request observation before ACK; make ACK
   idempotent across repeated API attempts. Hook failure, absent payload, failed
   identity checks, or lost ACK retain normal recoverable lease semantics.
6. Report native acceptance, payload admission, ACK, turn completion, and action
   completion separately. Neither a successful injection nor an ACK proves that
   the model performed the requested work. Do not ask the model to establish
   transport correctness by voluntarily acknowledging.

### Qualification limits and corrections to the initial research

- **Classic standalone CLI active wake is excluded.** Its plugin injection uses
  the CLI instance and can interrupt a busy turn; the supplied destination key
  does not provide the TUI host's exact-session routing. A separately qualified
  natural-turn path may still be useful. No `hermes --resume` cold-wake fallback.
- **Routing key is not sufficient identity.** TUI injection matches a loaded
  session's reported `session_key`, not its ephemeral UI map key. Gateway routing
  can outlive a conversation reset. Verify the underlying conversation/session ID
  at claim time and test rotations, reloads, and delayed callbacks.
- **Permission is configuration, not just an API capability name.** Authorized
  gateway/TUI injection requires
  `plugins.entries.<plugin-id>.allow_gateway_injection: true`. Check effective
  plugin/profile permission and messaging authorization; fail closed when absent.
- **Hook output can spill.** Released code can replace oversized context with a
  preview and file reference (documented default: 10,000 characters per hook).
  Bound claims to what can be admitted, including attribution overhead and Unicode.
  A marker, preview, saved file, or original pre-hook text alone cannot justify
  ACK. Cover oversized messages without silently changing global Hermes settings.
- **The observer is not an unconditional final-wire guarantee.** Tagged code runs
  `pre_api_request` after request assembly and `llm_request` middleware, but
  `llm_execution` middleware runs afterward and can wrap/short-circuit the provider
  call. Hooks are fail-open observers. Qualify the supported middleware/provider
  configuration and actual request payload with a model stub; if exact admission
  cannot be established, do not claim that this observer proves it. This remains
  a design gate, not a solved two-hook implementation.
- **Acceptance is not durable execution.** Tagged tests show that accepted queued
  text is written to the session DB, but a never-drained prompt is retired on cold
  reopen after the in-memory queue is lost. A persisted row is not a replayable
  turn. Keep the message in Pallium and the integration-owned uncertain-attempt
  fence in supported profile state; a restarted host
  must not trigger blind reinjection. Active-turn gateway resume is a separate
  recovery path; qualify it independently from busy-queue prompt replay.
- **MCP identity still needs discovery.** The source review does not establish a
  public per-tool current-conversation API for plugin wrappers. Prove trusted
  session propagation under concurrency; if unavailable, report the gap rather
  than guessing from cwd, titles, profile configuration, or model arguments.

## Initial Validation and Evidence

Evidence below is **tagged source/documentation inspection**, not execution of
Hermes tests or a Pallium integration. The supplied investigation's stronger
test/qualification claims are not inherited without inspecting their evidence.

| Finding | Initial validation | Primary evidence |
|---|---|---|
| v0.22.2 is a released baseline | Confirmed; released October 15, 2026. Main-only gateway work is not a dependency. | [Release notes](https://github.com/NousResearch/hermes-agent/releases/tag/v0.22.2) |
| Public injection and permission | Confirmed in tagged API and host-specific plugin guidance. | [PluginContext.inject_message](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/hermes_cli/plugins.py#L3197-L3244), [plugin guide](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/website/docs/user-guide/features/plugins.md#L698-L757) |
| Loaded TUI/Desktop exact route, busy queue, idle drain, missing target | Confirmed in implementation and inspected test assertions; tests were not run. `test_reported_session_key_is_queued_not_the_ui_session_id`, `test_idle_session_key_drains_onto_that_prompt_queue`, and `test_missing_session_is_not_rerouted_to_another_tui_session` are useful anchors. | [TUI injector](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/tui_gateway/plugin_inject.py), [host tests](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/tests/tui_gateway/test_plugin_inject_host.py) |
| Classic CLI bypasses TUI routing | Confirmed by tagged documentation and `test_cli_injection_still_bypasses_the_tui_host`; busy CLI injection can interrupt. | [Same host tests](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/tests/tui_gateway/test_plugin_inject_host.py), [host-specific guidance](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/website/docs/user-guide/features/plugins.md#L698-L757) |
| Reset reuses the gateway route but replaces conversation identity | Confirmed in `reset_session(session_key)`: new `session_id`, same routing key. This establishes the need for claim-time identity validation, not a proven Pallium implementation. | [Reset implementation](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/gateway/session.py#L1134-L1177), [reset/stale-writer regression](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/tests/gateway/test_session.py#L1536) |
| Queued text persists but never-started intent is retired after restart | Confirmed by inspected `test_queued_prompt_survives_a_backend_restart`, `test_restart_retires_the_never_drained_accept_row`, and `test_restart_between_drains_retires_only_the_later_prompt`. These are not automatic queued-turn replay tests. | [Accept-time persistence](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/tests/tui_gateway/test_queued_prompt_persistence.py#L128), [restart retirement](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/tests/tui_gateway/test_queued_prompt_restart_retire.py#L51-L145) |
| Context injection and shared turn identity | Confirmed: `pre_llm_call` receives session/task/turn IDs and its returned context is appended at API time; oversized output can spill. | [Turn context](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/agent/turn_context.py#L798-L852) |
| Request observation after request middleware | Confirmed, with subsequent execution-middleware caveat; not provider receipt or action completion. | [Request assembly](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/agent/turn_api_request.py#L43-L88), [ordering](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/agent/turn_api_request.py#L142-L164), [execution wrapper](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/agent/turn_api_call.py#L121-L139) |
| Pending candidate reuse in Pallium | Confirmed locally: `core/relay.py` and `storage/sqlite_relay.py` query exact registered scope without claiming/ACKing; no generic HTTP wrapper was found. | Existing methods and their callers in `app/claude_wake.py`, `app/codex_wake.py`, and `app/dependencies.py` |
| Bot Chat live-owner handoff and run idempotency | Confirmed source primitives; optional, not part of generic session wake. Store exposes `durable` and can fall back to memory. Tests include `test_restart_durability_and_terminal_semantics` and `test_dead_owner_nonterminal_status_becomes_interrupted`. | [Run dispatch](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/gateway/platforms/api_server_runs.py#L735-L751), [idempotency store](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/gateway/platforms/api_server_run_idempotency.py#L53-L84), [run tests](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/tests/gateway/test_api_server_runs.py) |
| End-to-end Pallium delivery, reset isolation, and crash recovery | Slice-1 idle wake/payload/ACK/reply passed in the isolated Windows gateway/local-stub topology, including wrong-recipient and closed-endpoint controls. Reset/crash recovery and queued-prompt replay remain unproven. | `tests/test_hermes_relay_native_e2e.py`; [gateway active-turn recovery tests](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/tests/gateway/test_restart_resume_pending.py), remaining qualification below |

## Alternatives and Deferred Options

- **`hermes peer run` / `/v1/runs`:** optional canonical Bot Chat transport.
  Preserve stable wake/idempotency key, native run ID, status, authenticated scope,
  and actual durability capability. Live-owner handoff avoids a second writer;
  persisted status does not promise crash-resumed execution. Do not use it as a
  generic fallback for an arbitrary existing conversation.
- **`message_agent` / Bot Mode:** the supplied investigation describes canonical
  Bot Chat messaging and envelopes. Recheck exact release behavior if selected;
  it is not evidence that arbitrary CLI/Desktop chats can be woken.
- **A2A:** the supplied investigation describes task/context-owned conversations,
  not arbitrary pre-existing chat addressing. Not selected for the first slice.
- **Webhooks:** the supplied investigation distinguishes a new webhook run from
  `mirror_to_session` history mirroring. Mirroring alone must not be advertised as
  a wake. Exact tagged behavior was not independently revalidated here.
- **hermes-teammates and NeMo Relay:** retain as research leads only. The supplied
  descriptions concern subagent orchestration and runtime telemetry respectively;
  the paste contains no usable primary links for its author-intent or historical
  failure claims. Do not repeat those claims as verified evidence or add either
  dependency without new primary-source validation.

## Out of Scope

- Active wake of classic/unloaded standalone CLI sessions; process spawning,
  arbitrary process discovery, UI automation, private session mutation, or an
  unreleased gateway dependency.
- A Hermes-side HTTP listener, second durable delivery queue, general orchestration
  engine, automatic takeover, or automatic host upgrade/migration.
- Native Bot Chat transport in the first deliverable unless separately justified.
  No new inference provider or mandatory derived-memory processing dependency.
  Session History capture and access, skill packaging and MCP are required parts
  of this feature even though they were not part of the first Relay experiment.

## Done When

- [ ] A supported installable Hermes package includes the Pallium skill and
  references, runtime guidance, MCP connection and trusted identity plumbing,
  plugin hooks, setup/status/removal documentation and compatibility reporting.
  Disposable-profile E2E proves install → use → repeated setup → remove and
  preserves unrelated configuration, credentials and user data.
- [ ] Real Hermes tool calls exercise the applicable common MCP capabilities,
  including Relay initiation/reply, broad and exact-work History search, source
  expansion, work associations and configured optional memory operations.
  Concurrent sessions cannot impersonate one another, and missing trusted
  identity or permission fails closed. Normal and Relay-woken turns are covered.
- [ ] History E2E captures user and assistant turns in Hermes, finds them from a
  later session and expands the original source, with stable provenance,
  duplicate suppression, bounded paging and lookup lineage. Visibility,
  redaction, forgetting and service failure retain their existing contracts.
- [ ] Optional derived-memory support is documented and tested in its supported
  modes; disabled mode leaves Relay and History usable. Private defaults,
  correction/forget provenance and the retrieval accessibility invariant hold.
- [ ] Exact released build, supported host/OS/provider modes, permissions,
  trustworthy identity propagation, lifecycle hooks, and middleware admission
  boundary are documented with a tested capability/fallback matrix.
- [ ] Existing Hermes sessions can register, discover/address, send, receive, and
  reply through Relay; self-addressed tools cannot impersonate another session.
  Unsupported modes are reported honestly and preserve natural-turn fallback
  where qualified. Existing runtimes retain their contracts.
- [ ] Idle delivery starts the intended session; busy delivery queues a distinct
  later turn without interruption/steering. Missing/unloaded/closed sessions,
  permission denial, reset, route reuse, profile change, and concurrent sessions
  never leak or misroute payloads.
- [ ] Claim/append/verify/ACK is proven through the plugin and model-stub request
  surface, including empty/max/over-max payloads, Unicode, spill, request rewriting,
  multiple API attempts, hook errors, unavailable service, missing entities,
  invalid enum/scope, and state conflicts. ACK requires full attributed inclusion.
- [ ] Crash before execution, lost native response, restart after acceptance,
  claim lease expiry, lost ACK, and duplicate pollers retain messages and fences
  correctly. A possibly accepted attempt never causes blind duplicate wake;
  redelivery exposes correct metadata and does not promise exactly-once action.
- [ ] E2E coverage drives the real caller surface and reads state through normal
  Relay status/list/trace surfaces. Include create → deliver/reply → reset/close →
  dispose, repeated operations, more than two chained turns, and multiple
  concurrent sessions/profiles/containers. Do not substitute internal unit tests
  for the observable contract.
- [ ] Isolated Windows qualification uses the actual Hermes distribution with a
  model stub and disposable profile/data, including Hermes/gateway and Pallium
  restarts. Verify poller shutdown, disable/remove/reload, no orphan workers, and
  no profile crossover. User installations/services change only with separate
  explicit approval of exact impact and rollback.
- [ ] Setup/removal docs and common capability/trace projections reflect only
  proven behavior; record any remaining blocker rather than declaring broad
  Hermes support from successful native submission.

## Notes

Source: user-supplied investigation, “Research update: a working path exists in
released Hermes,” captured and corrected on 2026-10-17. Primary links above replace
the paste's unresolved “GitHub” citation placeholders. No Hermes installation,
paid model request, service restart, or live delivery test was performed during
this initial validation. Revalidate version-sensitive claims at implementation.
