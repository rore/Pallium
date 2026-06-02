# Operational Fact Memory — Reducing Agent Rediscovery Waste

**Date:** 2026-05-31
**Status:** Draft — spec request, not implementation request. Phase 0 verification spike must complete before any code lands.
**Scope:** New derived memory class for cross-session operational orientation, owned by the existing `agent_work_trace` semantic package.

---

## Motivation

Pallium should reduce repeated operational discovery across fresh agent sessions.

The recurring waste pattern is **not** mainly "an agent ran a failed command and should avoid it next time." The higher-value pattern is:

> In session A, an agent spends tool calls discovering how this repo or machine works: Python path, test command, package manager, local service port, wrapper script, shell behavior. It then uses the discovered result successfully. In session B, a new agent repeats the same reconnaissance from zero.

Pallium should preserve the discovered operational fact and surface it only when useful, so future sessions can start from known evidence instead of rediscovering basics.

### Empirical anchor

This is not a theoretical gap. Both shipped Claude Code memory plugins surveyed (`ClawMem`, `agentmemory`) ship `PreToolUse` hooks for `Edit|Write|Read|Glob|Grep` — but neither intercepts `Bash` based on prior session evidence. Claude Code's own auto-memory and Pallium's existing memory both fail in practice on the rediscovery case despite having most of the right primitives. The capture pipeline (Stop hook + `agent_work_trace_turn` metadata, [semantic/agent_work_trace.py](../../semantic/agent_work_trace.py)) is already in place; what is missing is the derivation that turns those traces into reusable operational facts and the surfacing that delivers them at the right moment without crowding existing memory.

This must be implemented as a generic memory-system capability, not as scenario-specific behavior keyed to product names, ticket ids, tool names, or one-off phrasing.

---

## Existing Context To Validate First (Phase 0)

Before designing details or implementing, inspect the current repo state and update this spec with direct file references.

Known relevant areas:

- [semantic/agent_work_trace.py](../../semantic/agent_work_trace.py) — existing parallel package that captures per-turn tool traces and creates `task_trace` memory objects.
- [integrations/claude-code/hooks/](../../integrations/claude-code/hooks/) — currently `SessionStart`, `UserPromptSubmit`, `Stop`, `PreCompact`. No `PreToolUse`.
- [integrations/codex/hooks/](../../integrations/codex/hooks/) — currently `SessionStart`, `UserPromptSubmit`, `Stop`. No pre-tool or pre-compact.
- `semantic/agent_conversation_memory_routing_selection.py` — formats and injects `task_trace` blocks; same surface should host `operational_fact` blocks.
- `docs/context/architecture.md`, `docs/codex-integration.md`, `docs/claude-code-integration.md`, `roadmap/*` — must be kept aligned if feature status changes.
- MCP tools/integration package — confirm whether `/query` plus a `type` filter is sufficient.

Do not assume current behavior from roadmap status. Verify active code paths.

### Phase 0 downscope clause

If the Phase 0 spike concludes that the existing `task_trace` payload plus a small extraction extension achieves the goal — for example by formatting `commands_succeeded` more usefully and adding cross-thread retrieval — **downscope to that and skip Phases 1–4.** A new memory type is justified only if Phase 0 shows that `task_trace`'s thread-superseded lifecycle and per-thread scope cannot deliver the cross-session reuse value. The spec must be revisited, not extended past its scope, before adding code.

---

## Product Goal

Add a derived operational memory capability that stores evidence-backed facts such as:

- "For this repo on this machine, Python was successfully run via `.venv/Scripts/python.exe`."
- "This repo's tests were successfully run with `./gradlew.bat test`."
- "This repo uses `uv` as the Python package manager."
- "The local Pallium API was observed on `localhost:19836`."
- "Use repo wrapper `gradlew.bat`, not global `gradle`, for this project."

The system should **store many operational facts but inject very few.**

---

## Non-Goals For V1

- No command blocking.
- No automatic command rewriting.
- No general mistake-prevention engine.
- No broad LLM summarization ("summarize useful operational facts").
- No injection of all operational facts at session start.
- No hard dependency on `PreToolUse` until hook behavior is empirically proven (Phase 0).
- No English-only or language-specific heuristics. Logic stays structural and multilingual-compatible.
- No background revalidation. Lazy only.

---

## Memory Type

Add a typed memory object: **`operational_fact`**.

Schema id: `agent_work_trace.operational_fact`.

Owned by the existing `agent_work_trace` semantic package, because the fact is derived from structural tool evidence already captured by that package.

(The alternative name `environment_discovery` was considered and rejected: the stored object is the *result* of a discovery, not the act. Existing Pallium memory types are noun-result-oriented — `decision`, `investigation_outcome`, `task_trace` — and `operational_fact` matches that convention.)

### Schema

```python
{
    "category": str,             # see taxonomy below
    "command_family": str | None, # python | node | gradle | npm | docker | service | git | shell | None
    "scope_kind": str,           # machine | machine_repo | repo | workspace | container
    "scope_ref": str,            # deterministic id appropriate to scope_kind
    "subject": str,              # short human-readable statement
    "artifact": str,             # discovered concrete value: path, command, port, URL, wrapper
    "artifact_normalized": str,  # posix-normalized form used for dedup and argv match
    "evidence": [                # follows existing evidence-list pattern
        {
            "kind": "discovery" | "use",
            "source_item_id": str,
            "tool": str,         # Bash | Read | Grep | Glob
            "turn_index": int,
            "timestamp": str,    # ISO8601 UTC
            "fragment": str,     # redacted, capped excerpt
        },
        ...
    ],
    "confidence": "high" | "medium",
    "reuse_count": int,          # incremented on each subsequent successful use of artifact within scope
    "first_observed_at": str,
    "last_success_at": str,
    "last_verified_at": str | None,
    "supersedes": str | None,    # id of older fact this supersedes, if any
}
```

### Taxonomy axis (committed)

**Domain-keyed**, with `command_family` as a separate field. v1 categories:

- `runtime` — interpreter/executable selection (Python, Node, Java)
- `package_manager` — repo's chosen package manager
- `test` — canonical test command
- `build` — canonical build command
- `service` — local service endpoint, port, startup command
- `path` — significant local path (venv, build output, config dir)

`command_family` disambiguates within a category (`runtime` + `python`, `runtime` + `node`). The taxonomy is the v1 limiter, **not a permanent shape**; new categories require an explicit decision, not silent extension.

---

## Extraction Predicate

A `operational_fact` is promotable to **`high` confidence** only when **all** of the following hold:

1. A known **discovery action** occurred — either a discovery command from the per-category table below, or a tool call matching a known discovery pattern (read of a manifest file, listing of a directory matching a known runtime convention).
2. The discovery action **produced a candidate artifact** — a path, command, version, port, or URL extractable from the tool result.
3. A **later successful action** (Bash with exit code 0) occurred within N=10 turns in the same thread.
4. The successful action's argv (full command string after redaction) **contains the candidate artifact** as a substring, OR contains a path-equivalent of the artifact (forward/back slash normalization, drive letter case-insensitive on Windows). **Same-command-family alone does not satisfy this requirement.**
5. Both events are within the same `scope_ref` for the chosen scope (see *Scope Rules* below).
6. Evidence links to both the discovery and use source items are retained.

A separate path produces **`medium` confidence**:

7. **Frequency-based fallback** — when no discovery event is observed but the same artifact appears in argv across N≥3 successful Bash calls within the same scope, with no contradicting evidence (no successful use of a *different* artifact in the same `(scope, category, command_family)` slot in that window). `medium` facts are stored but **never injected at SessionStart**; they are eligible for `UserPromptSubmit` injection and (if Phase 5 ships) `PreToolUse` advisory.

`low` confidence is not produced. If neither the `high` nor the `medium` predicate is satisfied, no fact is created.

### Per-category extraction tables

#### `runtime.python`

| Discovery signal | Candidate artifact |
|---|---|
| `where python` / `which python` / `Get-Command python` | executable path from stdout |
| `py --version` / `python --version` | launcher command + version |
| Read of `.python-version` | version string |
| Read of `pyproject.toml` | version constraint, build-system |
| Listing of `.venv` or `.venv-wsl` | venv path |
| Stat of `.venv/Scripts/python.exe` or `.venv/bin/python` | venv executable path |

Successful use: any subsequent Bash with exit 0 whose argv contains the candidate path/launcher.

#### `test`

| Discovery signal | Candidate artifact |
|---|---|
| Read of `package.json` | scripts.test value |
| Read of `pyproject.toml` | tool config (pytest section) |
| Read of `Makefile` | test target |
| Read of `build.gradle` / `settings.gradle` | gradle test task |
| Bash of `<runner> --help` / `<runner> --list` | available test commands |

Successful use: any subsequent Bash with exit 0 whose argv contains the candidate command stem and produces no test-failure markers in stderr.

#### `service.local`

| Discovery signal | Candidate artifact |
|---|---|
| `docker ps` / `docker compose ps` | container name + ports |
| Read of `compose.yml` / `docker-compose.yml` / `.env` | service name, port |
| Bash check of known port (`curl localhost:NNNN/health`, `nc -z`) | port + endpoint path |

Successful use: subsequent Bash with exit 0 against the same host/port, OR subsequent successful command that depends on the service being up.

(Tables for `package_manager`, `build`, `path` follow the same shape; Phase 1 implementation defines them with the same precision.)

---

## Scope Rules

Scope is decided **per fact at promotion time**, not derived after the fact, and is part of the fact's identity (dedup key).

| `scope_kind` | When to use |
|---|---|
| `machine` | Absolute paths, installed tool versions, local OS-bound ports, shell quirks. |
| `machine_repo` | Repo-local venv path, local service port for this checkout, local config path that depends on machine layout. |
| `repo` | Package manager choice, repo wrapper script (`gradlew.bat`), canonical test command if not machine-specific. |
| `workspace` / `container` | Workspace-specific runtime conventions if Pallium container identity matters. |

Scope-resolution heuristics for v1:

- If the artifact is an absolute path or contains a drive letter → `machine` or `machine_repo` (latter if a repo-relative anchor is present).
- If the artifact is repo-relative (`./gradlew.bat`, `npm test`) → `repo`.
- If the artifact is a host:port → `machine` (port bindings are machine-local).
- If unsure → `machine_repo` (most conservative — won't leak across machines, won't false-share across repos).

`scope_ref` follows existing container_ref conventions ([integrations/claude-code/hooks/common.py:40-69](../../integrations/claude-code/hooks/common.py#L40)). For `machine` scope, a stable machine fingerprint is required: `machine:<sha256-prefix-of(hostname + os.uname() platform)>` — no user PII.

---

## Deduplication And Conflict Handling

Fact identity = `(category, command_family, scope_kind, scope_ref, artifact_normalized)`.

When a new fact would conflict with an existing one (same identity but different `artifact_normalized`):

- Newer high-confidence evidence supersedes older.
- The older fact is marked `supersedes` from the new one and lifecycle moved to `superseded`. It remains queryable (audit) but is not eligible for injection.
- Conflicting facts are **never injected together** in the same hook call.
- The conflict is surfaced in `query_audit_log` so debug paths can show why the previous fact was suppressed.

Examples that this must handle correctly:

- Python path moves from `.venv` to `.venv-wsl` after dev environment switch.
- Test command changes from `pytest` to `uv run pytest` after `uv` adoption.
- Service moves from port 19836 to a configured alternate.

---

## Retrieval And Injection Behavior

Store many facts. **Inject few.**

### Tier 1 — SessionStart

Inject a tiny orientation card only when facts are `high` confidence and scope-match the current container/machine.

Hard cap: **5 facts per card.** One fact per category. Freshest-with-confidence-floor first (see ranking below). Compact wording.

```
Known operational setup:
- Python: .venv/Scripts/python.exe (last used 2 days ago)
- Tests: ./gradlew.bat test (last used 2 days ago)
- Local API: localhost:19836 (last seen 5 hours ago)
```

`medium` confidence facts are **not** injected at SessionStart.

### Tier 2 — UserPromptSubmit

Operational facts surface only when the prompt structurally implies operational intent. **Mechanism:** reuse the existing routing signal extraction ([semantic/agent_conversation_memory_routing_signals.py](../../semantic/agent_conversation_memory_routing_signals.py)) to extract verb-object pairs from the prompt; operational facts compete in retrieval **only if** at least one extracted verb falls inside a small `OPERATIONAL_VERBS` set.

`OPERATIONAL_VERBS` v1 (structural, multilingual-compatible — verbs are matched on extracted tokens, not raw prompt text):

```
{run, execute, start, stop, build, test, install, debug, launch,
 deploy, configure, connect, query}
```

This set is bounded and reviewed; it is not a phrase-cue list. If the cue-free routing infrastructure exposes a more structural intent signal, that should be used in preference. **If Phase 0 verification finds that no reliable structural mechanism exists**, drop Tier 2 from v1 and rely on Tier 1 + Tier 3 only — do not paper over the gap with phrase matching.

When operational intent is detected, operational facts compete with normal memory injection at lower priority than `constraint_memory` (constraints are mandatory) and never crowd them out.

### Tier 3 — PreToolUse Bash (Phase 5, conditional)

Treated as a spike. **Required Phase 0 verification:**

- Can Claude Code `PreToolUse` make context model-visible (does `additionalContext` reach the model, or only the runtime/user)?
- Can it rewrite Bash input via `updatedInput`, and is that path stable?
- Does Codex have any equivalent? If not, **v1 does not design around it**; PreToolUse remains Claude-only and optional.

If proven viable, v1 PreToolUse behavior is **advisory only**:

```
Operational fact: previous sessions used .venv/Scripts/python.exe for Python in this repo.
```

No blocking. No rewriting. Lookup is keyed by `command_family` derived from the about-to-run argv; latency budget < 100 ms; backed by a small in-memory cache on the Pallium service so the call does not traverse the full `/query` path.

If PreToolUse cannot deliver model-visible context, **the value proposition collapses to Tiers 1 + 2.** Both are still useful. Tier 2 becomes more important in that world; the spec must explicitly say that's what happened, not silently degrade.

---

## Ranking

SessionStart ranking (in order of precedence):

1. `confidence == high`
2. `scope_kind` matches current container/machine
3. Category priority order: `test` → `runtime` → `package_manager` → `service` → `build` → `path`
4. Higher `reuse_count`
5. Freshest `last_success_at`
6. One per category — drop later same-category candidates

UserPromptSubmit ranking weights category match against extracted verb-object pairs higher than recency.

---

## Lazy Revalidation (Concrete Mechanics)

Cheap probe runs **in the hook process** (stdlib only — no Pallium server round-trip), with a hard timeout. v1 probes are limited to:

- Path existence (`os.path.exists` on `artifact` for `path.*` and `runtime.*` categories).
- Environment variable presence (no value inspection).

**Constraints:**

- 50 ms per probe, hard timeout. On timeout: skip probe, inject the fact with a softener.
- No subprocess spawns. No network calls. No disk writes.
- Probe runs only when a fact is *about to be injected*, not eagerly.
- Probe failure does **not** suppress injection; it *softens* the wording (`previously observed` instead of `currently used`) and triggers a `last_verified_at = null` reset.
- Categories not eligible for cheap probe (`test`, `build`, `package_manager`, `service`) are injected as previously-observed without revalidation.

Background revalidation is explicitly **out of scope** for v1.

---

## Hook Integration

### Claude Code

| Hook | Change |
|---|---|
| `session_start.py` | Add operational-fact orientation card alongside existing injection. Hard cap 5 facts. |
| `user_prompt_submit.py` | Route through routing-signals verb extraction; inject operational facts only on operational-verb match. |
| `stop.py` | No change required for v1 — `agent_work_trace_turn` metadata already carries the necessary signal. |
| `pre_compact.py` | Re-inject the top-3 operational facts before compaction so they survive context compression. |
| `pre_tool_use.py` (NEW, Phase 5 only) | Advisory-only, command_family-keyed lookup, < 100 ms budget. Conditional on Phase 0 verification. |

Preserve existing constraints: hooks are stdlib-only; Pallium-unreachable must not break the agent workflow; redaction runs before any storage; container pinning and visibility rules are unchanged.

### Codex

| Hook | Change |
|---|---|
| `session_start.py` | Same as Claude Code. |
| `user_prompt_submit.py` | Same as Claude Code. |
| `stop.py` | No change required for v1. |
| `common.py` | Mirror any extraction/redaction additions; parity test enforces alignment. |

Codex does **not** get `PreToolUse` or `PreCompact` in v1. `docs/codex-integration.md` records this asymmetry.

---

## MCP Impact (Committed)

**v1 reuses `pallium_query` and `/query`.** A new `pallium_operational_lookup` MCP tool is not introduced in v1.

Required `/query` extensions:

- Accept `type=operational_fact` filter (already general — verify it works without code changes).
- Accept `command_family` and `category` parameters for typed lookup; if these are not already structurally supported, add as optional filter dimensions.

`pallium_expand` for an `operational_fact` returns the discovery and use evidence source items.

A dedicated `pallium_operational_lookup` MCP tool is reconsidered only in Phase 5, **only if** PreToolUse advisory ships and benefits from a narrower contract than `/query` provides.

---

## Security And Privacy

Never store secrets from command output.

Redact (reuse existing redaction in [agent_work_trace](../../semantic/agent_work_trace.py)):

- API keys, bearer tokens, private keys.
- Environment variable assignments containing `PASSWORD`, `SECRET`, `TOKEN`, `KEY`, `AUTH`.
- Connection strings (`mongodb://`, `postgres://`, `mysql://`, `redis://`).
- `Authorization:` and `Cookie:` header values.

Operational facts respect:

- Container scope (no cross-container leakage).
- Visibility (machine-local facts never promote to public/shared visibility).
- Actor access.
- Existing privacy model (no new dimensions).

Path normalization is posix-internal: stored paths use forward slashes; rendering to the agent uses platform-style separators if helpful but storage stays normalized for dedup.

---

## Test Plan

### 1. Hook extraction parity

- Bash exit 0 captured; Bash non-zero captured as failed.
- Discovery tools (Read/Grep/Glob) captured.
- Edit/Write excluded from discovery (already enforced).
- Secret redaction in commands and output.
- Windows path normalization to posix-internal.
- POSIX path normalization.
- PowerShell command patterns.
- Long output capped.
- Missing/malformed transcript does not crash hook.
- Tool result with no explicit exit code handled conservatively.
- Claude/Codex `common.py` parity test.

### 2. Derivation unit tests

- Python discovery + venv invocation → `high` `runtime.python` fact.
- Python discovery without successful use → no fact.
- Discovery + successful use of *different* artifact (same command_family) → no `high` fact (regression guard for the artifact-must-appear-in-argv predicate).
- Successful command without discovery, observed once → no fact.
- Successful command without discovery, observed N=3 times in scope → `medium` fact, not SessionStart-eligible.
- Test command discovered from `package.json` and used → `test` fact.
- Gradle wrapper discovered and used → `repo.gradle.wrapper` fact.
- Docker service discovered + health check passes → `service.local` fact.
- Failed command does not create success fact.
- Multiple candidates discovered, only successful one promoted.
- Conflicting newer fact supersedes older; `supersedes` link populated.
- Absolute path → `machine` or `machine_repo` scope.
- Repo-relative wrapper → `repo` scope.
- Secret-like artifact rejected or redacted.
- Evidence links to both discovery and use source items.

### 3. Retrieval / injection tests

- SessionStart injects ≤5 facts, one per category.
- SessionStart never injects `medium` facts.
- UserPromptSubmit on operational verb match injects category-relevant facts.
- UserPromptSubmit on non-operational prompt injects no operational facts.
- Conflicting facts are not injected together.
- Stale fact (probe failure) injected with softener wording, not suppressed.
- Operational facts never crowd out `constraint_memory`.
- Long facts are formatted compactly within token budget.
- `pallium_expand` returns discovery + use evidence.
- Same-thread suppression rules do not wrongly suppress cross-session orientation.

### 4. End-to-end tests

Simulate session A (discover + use) → session B (orientation card surfaces fact). Variants:

- Claude Code hook path.
- Codex hook path.
- Windows PowerShell.
- POSIX shell.
- Pallium service unreachable (must not break agent).
- Empty DB.
- Existing `task_trace` but no derived operational fact.
- Multiple repos on same machine — facts don't cross-leak.
- Same repo on different machine — `machine_repo`-scoped facts don't leak.
- Same machine path but different repo — `machine`-scoped facts ARE shared correctly; `machine_repo` facts are not.
- Private visibility filtering.
- Public/shared context must not leak machine-local fact.

---

## Eval Updates

(Redaction and extraction safety are unit-test concerns, not eval — evals here are about **retrieval and injection behavior**.)

Suggested scenario names:

- `operational_fact_runtime_python_reuse` — discovered + reused, surfaces in next session
- `operational_fact_test_command_reuse` — same for tests
- `operational_fact_wrong_repo_suppression` — `repo`-scoped fact does not surface in different repo
- `operational_fact_machine_scope_boundary` — `machine_repo` fact does not cross machines
- `operational_fact_no_value_prompt_no_injection` — non-operational prompt gets no operational facts
- `operational_fact_conflict_prefers_fresh_success` — superseded fact is suppressed
- `operational_fact_codex_sessionstart`
- `operational_fact_claude_userpromptsubmit`
- `operational_fact_artifact_match_required` — same-family-but-different-artifact use does NOT promote a fact (regression guard)

Multilingual prompt variants for operational verbs (where supported) confirm structural matching is not English-only.

---

## Invariants

- No operational fact without evidence links (one discovery + one use for `high`; ≥3 use evidence items for `medium`).
- No `high`-confidence fact without artifact-in-argv match.
- No injection of `medium` facts at SessionStart.
- No cross-container leakage.
- No public visibility for machine-local facts unless explicitly safe.
- No command rewrite in v1.
- No blocking in v1.
- No unredacted secrets in payload, index, or injection.
- No more than one injected fact per category at SessionStart.
- Injection remains under hard token/character budget (300 chars per fact, 5 facts at SessionStart).
- Hook failures are non-blocking.
- Claude/Codex shared extraction stays in parity.
- Existing `task_trace` behavior continues to work without regression.

---

## Documentation Updates

- `docs/context/architecture.md` — add `operational_fact` as a derived memory type owned by `agent_work_trace`.
- `docs/claude-code-integration.md` — document hook behavior, including any Phase 5 PreToolUse capability.
- `docs/codex-integration.md` — document Codex's hook asymmetry (no PreToolUse, no PreCompact).
- `docs/http-api.md` — if `/query` extends with category/command_family filters, document them.
- `docs/agent-integration.md` — if agent-facing instructions change.
- `roadmap/*` — only updated when implementation status actually changes.

If during Phase 0 the implementer finds drift between roadmap claims and actual code, surface it in the spike note explicitly. Do not silently align.

---

## Rollout Plan

### Phase 0 — Verification spike (REQUIRED before Phase 1)

- Verify Claude Code `PreToolUse` contract: model visibility of `additionalContext`, behavior of `updatedInput`, current Claude Code version reliability.
- Verify Codex hook surface — confirm absence of `PreToolUse`/`PreCompact` equivalents.
- Verify existing `agent_work_trace` `agent_work_trace_turn` metadata is sufficient for the discovery + use predicate without hook changes. If not, scope a hook-side extension.
- Verify routing-signals verb extraction is reusable for the operational-intent gate, or determine that Tier 2 must be cut.
- Verify whether `task_trace` formatting alone could cover the use case (downscope clause).
- Produce a short spike note with direct file references and a go/no-go for each tier.

### Phase 1 — Data model + derivation

- Add `operational_fact` schema and storage path.
- Implement `high` and `medium` derivation in `semantic/agent_work_trace.py` (or sibling module).
- Unit tests per *Test Plan §2*.

### Phase 2 — Tier 1 + Tier 2 injection

- Add SessionStart compact orientation.
- Add UserPromptSubmit verb-gated lookup.
- Formatting + debug audit-log entries.
- Retrieval/injection tests per *Test Plan §3*.

### Phase 3 — Integration parity

- Update Claude hooks.
- Update Codex hooks.
- Add parity tests.
- Update integration docs.

### Phase 4 — Evals + invariants

- Add eval scenarios.
- Add invariant checks.
- Run regression suite.
- Run targeted new e2e suite.

### Phase 5 — Optional PreToolUse advisory (Claude only)

Only after Phase 0 says PreToolUse is viable AND Phases 1–4 are stable.

- Implement advisory-only PreToolUse for Claude.
- Add small in-memory cache for command_family lookup.
- No blocking, no rewriting.
- Codex remains without this path.

---

## Acceptance Criteria

The feature is complete when:

**Capability:**

- An `operational_fact` can be derived from discovery + successful artifact-match use evidence.
- The fact has correct scope and evidence links.
- SessionStart injects a compact ≤5-fact card per the rules above.
- UserPromptSubmit injects category-relevant facts only on operational verb match.
- Non-operational prompts receive no operational facts.
- Claude and Codex integrations are both covered to their hook capabilities.
- MCP impact is checked and documented.
- Tests cover extraction, derivation, routing, injection, integration, redaction, scope, conflicts, stale facts, and failure modes.
- Evals/invariants are updated, or explicitly judged unnecessary with rationale.
- Docs and roadmap are aligned.
- No existing `task_trace`, memory routing, or privacy behavior regresses.

**Empirical (kill criterion):**

- Across **15+ real sessions in 2+ repos over 3 weeks of normal use**, ≥70% of repeated operational reconnaissance commands (cases where a previous session in the same scope had the answer) are preempted by an injected `operational_fact`, with **<5% false-positive injection rate** (facts that are stale, wrong-scope, or contradicted by current state).
- If after 3 weeks the false-positive rate exceeds 10%, **suppress injection and revisit derivation.** This mirrors the precedent set by the [agent_work_trace spec](2026-05-05-agent-work-trace-design.md) of measurable reduction across 15+ sessions, not binary capability check.

---

## Architect Review Questions Before Implementation

(Reduced from the original list — questions already answered by the spec are removed.)

1. Is this truly a derived fact requiring a new memory type, or should it remain a `task_trace` formatting improvement? *(Answered by Phase 0 downscope clause; reviewer to validate.)*
2. Are the scope rules precise enough to prevent leaking machine-local facts across containers and visibility boundaries?
3. Does this duplicate query-routing responsibilities, or does it cleanly extend `agent_work_trace`?
4. Are we adding enough observability (`query_audit_log` entries, supersession links) to debug wrong or missing injections?
5. Are the test cases proving behavior end-to-end rather than just unit-level plausibility — particularly the artifact-match-required and machine-scope-boundary cases?
