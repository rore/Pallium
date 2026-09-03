<!-- agent-workflow:start -->
**Outcome:**
Plan S1A: native peer text turn reaches Claude Stop; Stop performs one scoped Relay probe, renders and ACKs only deliverable messages, writes the attributed continuation block, and exits 2 once so Claude acts. Current review fixes rearm after every non-continuing probe, non-UTF-8 stderr emission, and exact storage/hook render templates.

**Target:**
Pallium Claude Code Relay availability.

**Scope:**
S1A changes the existing Claude Stop hook, `common.acknowledge_relay` return contract, and focused real-hook/HTTP E2E. Every Stop registers idle with existing exact session/container/actor derivation. If `stop_hook_active` is false, call scoped `/relay/turn`; route admission marks busy. Send `max_chars=2400` in every non-recursive `/relay/turn` POST; storage is the authoritative claim boundary and skips over-budget items while retaining later fitting items pending/claimable. Stop candidate-renders exactly the returned claimed set without a second formatter cap; ACK each candidate; reformat only the ACK-success subset for attributed stderr and exit 2 only when that subset is nonempty. If recursive, empty, failed, invalid, or render-empty, ingest and exit 0. Preserve unrelated `uv.lock` and `.agent-workflow/.hooks.log`; no PR.

**Constraints:**
Peer text -> Stop -> one scoped `/relay/turn` POST with authoritative `max_chars=2400` -> candidate render of the returned claimed set -> individual ACK -> reformat successful subset -> exit 2 -> continuation acts -> next Stop re-registers idle, ingests, exits 0. Native transport never changes delivery. Existing Stop scope is authoritative; no MCP or model scope/identity. One bounded non-recursive Stop probe is accepted; `stop_hook_active` prevents recursion. Empty/failure/render-empty/all-ACK-failure exits 0; unACKed claimed items stay lease-recoverable. `has_more` and `remaining_count` remain pending and are unqualified until S1B rearm/continuation; the S1A witness proves one bounded batch only. No pins, MCP, durable socket/token state, reconciler, TTL change, DPAPI, secret table, durable attempts, Uvicorn subclass, SessionEnd, StopFailure, batching beyond one bounded batch, or schema change. Session pin is out of scope.

**Completion criteria:**
1. Every Stop registers idle; only non-recursive Stop makes one exact scoped `/relay/turn` POST with `max_chars=2400`, which marks busy and claims no item outside that budget.
2. Storage `/relay/turn` `max_chars=2400` is the sole claim boundary; Stop calls `format_relay` without a competing cap on the returned claimed set, so a fitting delivery after a skipped over-budget item is rendered and considered for ACK. `common.acknowledge_relay` returns its successful items without changing existing callers; Stop ACKs candidates individually, reformats only successes, and exits 2 only for a nonempty successful subset. All-ACK failure exits 0; partial failure leaves only unACKed items lease-recoverable.
3. Continuation Stop re-registers idle, ingests result, exits 0, and does not re-probe; native wake never completes delivery.
4. Deterministic real-hook/HTTP E2E: pure-text zero-tool wake; none/one/max/over-budget/`has_more`; Unicode; missing/mismatch/failure; recursion guard; once-only, partial, and all-ACK failure; exit-2 success/failure boundary; duplicate empty; continuation ingest/rearm; lease recovery; fake clocks/events and no sleeps.
5. Installed Windows no-human text-only witness proves peer -> Stop -> continuation -> completion. S1B durability/reconciliation remains deferred.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
S1A changes normal end-of-turn Relay admission; bounded rendering, partial ACK, continuation, scope, and rearm require real caller-surface proof.

**Discovery:**
Claude 2.1.250 peer frames are internal `isMeta` text turns and bypass UserPromptSubmit, so S0/S0.5 were misqualified for peer admission. Claude reproduced a pure-peer-text Stop block/reason exit-2 continuation. Existing Stop derives exact scope and registers idle; existing `/relay/turn` callback marks matching registration busy. MCP/actor-pin is unnecessary.

**Material assumptions:**
- Claude supplies `stop_hook_active` on continuation Stop.
- Claude honors Stop exit 2 as one continuation for pure peer text.
- Existing Stop scope and route admission match or fail closed.
- Stderr is the proven attributed continuation surface.

**Plan:**
S0/S0.5 — MISQUALIFIED for causal peer admission.

S1A — Architect Codex re-review CLEAN: every non-continuing Stop re-registers idle after route admission; UTF-8 stderr buffer fallback emits before exit 2; storage budgets the exact hook template; and the boundary regression detects future storage/hook drift. Only the installed Windows no-human witness remains.

S1B — Deferred durable socket/token capability, cache rehydration, readiness and restart reconciliation.

S2 — Evidence-driven peer/lifecycle hardening. S3 — Codex MCP recovery remains fail-closed. S4 — cross-platform live qualification.

**Verification plan:**
- Stop lifecycle → real hook + HTTP exact probe, busy mark, stderr, exit 2, recursive exit 0, ingest/rearm.
- Claim/render/ACK → storage `/relay/turn` `max_chars=2400` is authoritative; an over-budget skipped item followed by a fitting claimed item proves the entire returned set renders; storage and hook use the exact same control lines for the authoritative budget, then successful-subset reformat, `has_more`/`remaining_count`/Unicode, partial/all failure, and exactly-once ACK.
- Failure/duplicate → scope mismatch, request/render failure, partial/all ACK failure and exit-2 boundary, recursion, duplicate, `has_more`/`remaining_count` pending, and lease recovery.
- Installed behavior → no-human Windows pure text peer witness.
- Repository → focused/full tests, workflow/redline/diff; no production claim before witness.

**Plan review:**
2026-09-03 — Prior S1 durability and MCP S1A proposals are superseded. Architect review found route-admission rearm, UTF-8 stderr, and storage-template gaps; all are corrected. Codex architect re-review is CLEAN: real boundary regression proves storage selection and Claude rendering stay within the same budget while preserving skipped-overbudget/later-fit `has_more`/`remaining_count`.

**Approvals:**
Approved by user 2026-09-03: "you have blanket approval for all tasks you get from the architect". Codex architect re-review CLEAN 2026-09-03; Claude is reserved only for the installed runtime witness.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

2026-09-03 — Implemented S1A: non-recursive Claude Stop probes scoped `/relay/turn` once with `max_chars=2400`, renders exactly the returned claimed set without a formatter cap, ACKs individually, re-renders only 2xx-confirmed items to stderr, and exits 2 only for that nonempty subset. Recursive Stop re-registers idle without a probe. `acknowledge_relay` now returns only confirmed deliveries while existing callers may ignore the return. Architect re-review fixed empty/request/render/all-ACK-failure rearm after route admission, non-UTF-8 stderr buffer emission, and exact storage/hook template budgeting. Focused caller-surface regressions and exact storage/Claude boundary regression pass. Module-form affected suite, relay E2E, and isolation counts are recorded by final verification. Workflow and diff checks clean. `ruff` is unavailable in the environment. Architect re-review is CLEAN; the only blocker is the installed no-human Windows witness before production qualification.