# Operational Fact Memory

**Date:** 2026-05-31 (revised 2026-06-04, 2026-07-01, 2026-07-02)
**Status:** Phase 0 resolved 2026-07-01 — see [`.local/milestone-progress-2026-07/w4-phase0-spike-2026-07-01.md`](../../.local/milestone-progress-2026-07/w4-phase0-spike-2026-07-01.md). **v1 surface: Surface B** (UserPromptSubmit, both integrations). Implementation sequenced under W4 of the [Shaped Memory Contract milestone](2026-07-01-milestone-shaped-memory-contract.md).
**Scope:** New derived memory type owned by the `agent_work_trace` package.

---

## Revision Notes

### 2026-07-02 — Reconnaissance-verb predicate + promotion (PRs 3, 4, 5)

Live-data analysis of the shipped v1 extractor showed the discovery+use pairing model in §Extraction Predicate was too permissive: any argv token repeated within the 10-turn window became a fact, and 86% of emitted rows landed in the `command_family="shell"` fallback slot (regex patterns, one-off script paths, argv fragments). The `command_family` open-set language read as "structural predicate fires the first time we see cargo" but in practice fired for arbitrary noise.

Two orthogonal, tool-agnostic signals replace the pairing model:

1. **Reconnaissance-verb signal** (see updated §Extraction Predicate below). A turn is a reconnaissance event if it uses a verb from a small closed set — `which`, `where`, `type`, `command -v`, `--version`, `--help`, `--list`, `ls`, `stat`, `test -f`, `cat` of a config-anchor file, port probes, or `Read` on a config anchor. This grammar is bounded and language-agnostic; a new ecosystem does not invent a new reconnaissance verb.
2. **Recurrence-based promotion** (see new §Promotion below). A reconnaissance event produces a `candidate` row invisible to retrieval/injection/dashboard. Only when the same conflict slot is answered in ≥2 distinct threads does it promote to `active`. One-off script paths never promote because they don't recur.

Together these replace the pre-PR-3 admission-gate machinery (`_RUNNER_SUBCOMMANDS`, `_OPERATIONAL_CONFIG_FILES`, `_INTERPRETER_ALLOWED_STEMS`, `_HIGH_VALUE_FAMILIES`-fallback channel). The `command_family` open-set language is retired; a candidate's family is derived from the reconnaissance verb's target and, for unknown targets, is the target's basename itself — the recurrence gate at promotion time is what filters one-off noise, not a per-family allow-list.

PR 3 (commit `3825537`) shipped the reconnaissance-verb predicate + candidate lifecycle. PR 4 (commit `59d8dfd`) shipped the promotion mechanism via `supported_by` relations and the cross-thread recurrence count. PR 5 (this revision) migrated 231 legacy pre-PR-3 active rows via a manifest-guarded soft-delete migration (`app/tools/operational_fact_migration_pr5.py`, reason tag `operational_fact_redesign_migration_2026_07`), removed the retired admission-gate code from `semantic/operational_fact.py`, and retired the tightening cleanup CLI at `app/tools/operational_fact_tightening_cleanup.py`.

---

## Problem

In session A an agent discovers how this repo or machine works — Python path, test command, package manager, local service port, repo wrapper script — then uses the discovery successfully. In session B a fresh agent repeats the reconnaissance from zero.

Pallium should preserve the discovered fact and surface it on demand, so future sessions start from known evidence instead of rediscovering basics.

The capture pipeline (Stop hook + `agent_work_trace_turn` metadata, [semantic/agent_work_trace.py](../../semantic/agent_work_trace.py)) has been active since T3 landed. **As of 2026-07-01 the live DB shows 1,251 source_items with `agent_work_trace_turn` metadata and 64 `task_trace` memory objects.** Discovery+use signals are captured; derivation and surfacing are what W4 adds.

This must be generic — not keyed to product names, ticket ids, tool names, or one-off phrasing.

---

## Position In The Type System

`operational_fact` is the first member of a **structurally-derived project-shape family**, distinct from conversation-derived types (`decision`, `investigation_outcome`, `note`).

Conversation-derived memory captures what was said. Project-shape memory captures what was demonstrated to work by structural evidence in the tool stream.

Future siblings (not v1, not committed): a project file index; a deterministic edit-pattern log. Each requires its own spec.

---

## Phase 0 — Verification spike (RESOLVED 2026-07-01)

Full findings in [`.local/milestone-progress-2026-07/w4-phase0-spike-2026-07-01.md`](../../.local/milestone-progress-2026-07/w4-phase0-spike-2026-07-01.md). Summary of the four go/no-go answers:

1. **Q1 — PreToolUse `additionalContext` reaches the model?** YES on Claude Code (system-reminder injection). Codex has no PreToolUse equivalent.
2. **Q2 — Structural operational-intent signal available or cheap?** YES, cheap to add (<150 LOC in `semantic/agent_conversation_memory_routing_signals.py`).
3. **Q3 — `agent_work_trace_turn` metadata sufficient?** PARTIALLY. Bash-based discovery+use is fully covered (95% populated `commands`, 100% `exit_code` / `cmd` on each command). `files_read` populated on 22% of turns — usable secondary signal. `cwd` populated **0%** — the design's `cwd`-based scope derivation is not viable; scope resolution moves to service-level. `patch_bodies` populated **0%** in the surveyed Claude-Code DB — the `apply_patch` branch defers to a contingent PR pending Codex evidence.
4. **Q4 — Downscope to `task_trace` formatting?** NOT VIABLE. Rebuilding evidence-links, per-artifact granularity, conflict slot, and supersession on `task_trace` = rebuilding `operational_fact` in a different table.

### v1 surface decision

Q1 is YES but only for Claude Code (Codex asymmetry). Q2 is YES for both integrations. Choosing **Surface B** (UserPromptSubmit, both integrations) preserves cross-integration parity — the same posture W3 established with the explicit write tools. Surface A (PreToolUse) becomes a scoped follow-up if evals show the "surface before the tool call" moment is materially better than "surface at prompt submit."

### Predicate narrowing (evidence-driven)

Based on the Q3 field-presence data:

- **Discovery — primary:** `commands[i]` with `exit_code == 0` whose `cmd` contains a stable artifact token.
- **Discovery — secondary:** `files_read[i]` (path-only). Coverage ~22% — usable but not primary.
- **Discovery — deferred:** `apply_patch` (Codex `patch_bodies`). Ships in a contingent follow-up PR only if a Codex live DB shows populated `patch_bodies`.
- **Use:** `commands[j]` with `exit_code == 0` where `cmd` matches the discovery artifact via substring or word-boundary within N=10 subsequent turns in the same thread.
- **Scope:** `scope_kind='repo'` for repo-relative artifacts; `scope_kind='machine_repo'` otherwise. `scope_ref` computed at service level (not per turn), because `cwd` is not captured — see updated §Scope Rules below.

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

`command_family` is derived deterministically from the reconnaissance-verb target (see §Extraction Predicate). Known ecosystems (Python, Node, npm/pnpm/yarn, uv, pip, cargo, go, gradle, docker, git, make, service, shell) flow through `_FAMILY_KEYWORD_MAP`. Unknown targets — a fresh ecosystem's CLI — get the target's basename as their family. This is the ecosystem-agnostic branch; the recurrence gate at promotion time (see §Promotion) is what filters one-off noise, not a per-family allow-list. The pre-PR-3 "Values are not closed" language is superseded: the family space is open, but promotion is what confers durability, not the family value itself.

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

**Superseded by the reconnaissance-verb model in PR 3 (2026-07-02).** The historic §Extraction Predicate — a discovery+use pair bound by argv-match within 10 turns — is retained for historical context in the [pre-PR-3 draft](https://github.com/rore/Pallium/blame/main/docs/specs/2026-05-31-operational-fact-memory-design.md). The current predicate is:

Operates on `agent_work_trace`'s per-turn capture surface — `{files_read, commands{cmd, exit_code, output_tail, failure_class}, grep_patterns, files_modified, patch_bodies}` — via the closed reconnaissance-verb set in [`semantic/reconnaissance.py`](../../semantic/reconnaissance.py).

**Reconnaissance verbs (closed set).** A turn contributes a candidate iff it contains at least one of:

- `command_lookup` — argv head ∈ `{which, where, type, command}` (also `command -v` recognized by argv[0..1]). Target = argv[N]. Discovered value = the path in `output_tail`.
- `version_query` — any argv containing `--version` / `-V` / `--ver`. Target = argv[0]. Discovered value = the version token extracted from `output_tail` via a bounded semver regex.
- `help_query` — any argv containing `--help` / `-h` / `-?`. Target = argv[0].
- `port_probe` — argv head ∈ `{curl, wget, nc}` with `-sI` / `--spider` / `-z`. Target = host:port extracted from the argv URL.
- `file_read_recon` — `Read` tool events (via `TurnRecord.files_read`) whose basename is in a small closed allow-list of config anchors (`pyproject.toml`, `package.json`, `Makefile`, `docker-compose.yml`, `go.mod`, `Cargo.toml`, …).
- `cat_config_recon` — argv head `cat` with argv[1] basename in the same allow-list.
- `directory_probe` — argv head ∈ `{ls, stat, find, test}`. Target = the argv path token. Not gated on "under container root"; promotion via recurrence carries the durability signal.

Each predicate emits at most one `ReconnaissanceEvent`. The event maps directly to an `OperationalFactCandidate` (see `_recon_event_to_candidate` in [`semantic/operational_fact.py`](../../semantic/operational_fact.py)). Every user-facing string is passed through `semantic.redaction.redact_sensitive` before candidate emission; sensitive artifacts (SSH keys, `.pem`/`.key`, AWS/kube creds, SSH targets) are skipped entirely rather than redacted.

**Family and role derivation.** The candidate's `command_family` is derived from the recon verb's target: known ecosystems flow through the `_FAMILY_KEYWORD_MAP` (Python, Node, npm, cargo, gradle, docker, git, make, service, shell); for unknown targets (`xyzlang`, an unfamiliar CLI), the family is the target's basename itself. This is the ecosystem-agnostic branch: a fresh tool admits without a code change; the recurrence gate at promotion time (see §Promotion) decides durability.

**Role derivation.** `artifact_role` is derived from the verb (see `_role_for_verb`): `version_query` → `version`; `port_probe` → `endpoint`; `command_lookup` on an interpreter-shaped basename → `interpreter`, else `runner`; `file_read_recon` / `cat_config_recon` → `config`; `help_query` → `help`; `directory_probe` → `path`.

**Ecosystem-agnostic invariant.** The predicate must catch a reconnaissance-answer pair in a fresh ecosystem (Rust + cargo, Bun, hatch, `xyzlang`) without code or spec changes. Locked by `tests/test_operational_fact_e2e.py::test_unknown_ecosystem_*`.

If the predicate is not satisfied, no candidate is created.

### Examples (illustrative, not closed)

`python` — `where python`, `python --version`, `cat pyproject.toml`, `Read .python-version`.
`test` (any runner) — `Read package.json`, `Read pyproject.toml`, `Read Makefile`, `<runner> --help`.
`service` — `curl -sI http://localhost:8000/health`, `Read docker-compose.yml`, `nc -z localhost 5432`.
`xyzlang` (fresh ecosystem) — `where xyzlang`, `xyzlang --version`. Family = `xyzlang`. Recurrence gate decides whether it promotes to `active`.

---

## Promotion

**New in PR 4 (2026-07-02).** Candidates emitted by the reconnaissance predicate ship as `lifecycle="candidate"` and are invisible to `service.query`, `_storage.list_memory_objects` (at default filters), the dashboard `/api/memories` endpoint, and MCP `pallium_query`. Only after cross-thread recurrence does a candidate promote to `active`.

**Recurrence signal — `supported_by` relations.** When `_candidate_to_memory_object` at [`semantic/agent_work_trace.py`](../../semantic/agent_work_trace.py) constructs an operational_fact `MemoryObject`, it also constructs a `Relation(from_kind="memory_object", from_id=<memory_id>, relation_type="supported_by", to_kind="source_item", to_id=<discovery.source_item_id>)` for each evidence entry. This creates a graph from operational_fact → discovery source items → thread_ref.

**Promotion query — `count_distinct_threads_for_conflict_slot`.** A helper on `SqliteStorage` joins `memory_objects` (filtered by container_ref + type + slot fields + lifecycle in `{candidate, active}`) to `relations` (`from_id = memory_object.id AND relation_type = "supported_by"`) to `source_items` (`id = relations.to_id`) and returns `COUNT(DISTINCT source_items.thread_ref)`. A candidate promoted by one thread pointing at ten source items counts as one thread — the anti-inflation invariant.

**Promotion transaction — `promotion_hints` on `ProcessResult`.** The reconcile hook at `semantic/agent_work_trace.py` returns hints describing "for each candidate slot, promote if the distinct-thread count ≥ threshold." `_persist_process_result` in [`core/service.py`](../../core/service.py) inserts candidate rows + `supported_by` relations, then evaluates the hints inside the SAME transaction (candidate rows are visible to the query at that point), then performs the `UPDATE ... SET lifecycle='active'` promotions. Atomic: either everything commits or nothing does.

**Threshold.** `PROMOTION_THREAD_THRESHOLD = 2` by default. Configurable via `pallium.local.toml` under `[operational_fact] promotion_threads`. Recurrence in ≥ N distinct threads is the durability signal that replaces the pre-PR-3 admission-gate allow-lists.

**Slot supersession.** If promotion produces a second active row in the same conflict slot with a different `artifact_normalized`, the older row is marked `superseded` and the newer row's `supersedes` link is set. See §Deduplication.

**Promotion log — `operational_fact_promotion_log` table.** Every lifecycle transition writes a row to this table (`from_lifecycle`, `to_lifecycle`, `reason`, `distinct_threads_count`, `promoted_at`). Not queried by retrieval or ranking; strictly for post-hoc debugging and metrics.

**Locks.** Tests 1 (two-session recurrence promotes), 4b (unknown ecosystem promotes after recurrence), 7 (UserPromptSubmit injects on operational intent) in `tests/test_operational_fact_e2e.py`.

---


## Scope Rules

Two scopes, chosen at promotion time:

| `scope_kind` | When |
|---|---|
| `repo` | Repo-relative artifact (`./gradlew.bat`, `npm test`, `uv run pytest`). |
| `machine_repo` | Artifact depends on machine layout: absolute paths, repo-local venv, local service port. Default when uncertain. |

Heuristic: repo-relative (no drive letter, no absolute path) → `repo`. Otherwise → `machine_repo`.

`scope_ref` follows existing container_ref conventions ([integrations/claude-code/hooks/common.py:40-69](../../integrations/claude-code/hooks/common.py#L40)). For `machine_repo`: `<container_ref>@machine:<sha256-prefix-of(salt + socket.gethostname() + platform.system() + platform.machine())>` — stdlib-only, cross-platform (no `os.uname()` which doesn't exist on Windows), no PII. **The hostname is salted** with a stable per-installation salt so raw hostnames never enter `scope_ref` and the DB doesn't become an implicit machine inventory. **The machine hash is computed once at service start** and cached; it is not re-computed per candidate.

**Note on `cwd`:** the design originally derived `scope_ref` from per-turn `cwd`. Live-DB evidence (2026-07-01) shows `cwd` is not populated in `agent_work_trace_turn` metadata (0% across a 200-turn sweep). Scope derivation therefore happens at the service level from `container_ref` + machine hash, not from turn metadata.

---

## Deduplication And Conflict

- **Conflict slot** = `(command_family, artifact_role, scope_kind, scope_ref)`. At most one `active` fact per slot.
- **Exact-dedup key** = `(command_family, artifact_role, scope_kind, scope_ref, artifact_normalized)`. Same-key events extend evidence and bump `reuse_count`; never duplicate.

`artifact_role` distinguishes facts that share a `command_family` but represent different things (e.g. `interpreter` vs `venv` vs `version` for `python`; `runner` vs `task` for `gradle`). Derived deterministically from the discovery shape, like `command_family`. Set is open.

When a new fact's exact-dedup key matches: merge, update `last_used_at`. When the conflict slot matches but `artifact_normalized` differs: newer supersedes older. Older lifecycle moves to `superseded`, gets `supersedes` link, stays queryable for audit, ineligible for injection. Conflict logged in `query_audit_log`.

Conflicting facts are never injected together.

Cases this handles: Python interpreter path moves `.venv` → `.venv-wsl` (same `command_family=python`, same `artifact_role=interpreter`); test command `pytest` → `uv run pytest`; service port changes.

**Cross-origin rule:** derivation never supersedes a fact with `origin='agent_explicit'`. An explicit fact written via `pallium_remember(type='operational_fact', ...)` (W3) always wins its conflict slot against a derived fact. Colliding derived candidates are either skipped or written with `lifecycle='superseded'` linked to the explicit fact.

---

## Redaction

Every candidate emitted by the predicate passes through a shared redaction helper before being written. Values redacted (case-insensitive):

- **Bearer tokens** — `Authorization: Bearer <redacted>`.
- **API keys** — `X-API-Key: <redacted>`, `x-api-key=<redacted>`.
- **Private-key material** — `-----BEGIN [A-Z ]+PRIVATE KEY-----...`.
- **Environment-variable secrets** — env vars whose name contains `PASSWORD|SECRET|TOKEN|KEY|AUTH` are redacted at the value.
- **Connection strings** — `mongodb://`, `postgres://`, `mysql://`, `redis://` with embedded credentials.
- **HTTP header values** — `Authorization:` and `Cookie:` header values.

The helper is a single shared function (factored from or into `semantic/agent_work_trace.py` — see PR 1). Redaction happens before the payload is built; the raw pre-redaction values never enter the SQLite row.

---

## Surfacing

Store many facts. Inject few.

**v1 ships Surface B** (UserPromptSubmit, both integrations). See Phase 0 resolution above.

### Surface B — UserPromptSubmit (both integrations)

The `operational_intent` signal is a token-based verb-object detector in `semantic/agent_conversation_memory_routing_signals.py`, added under W4 PR 2. It is structural (not phrase matching) and English-first — non-English fall-through is a documented limitation for v1, revisit if evals show impact.

When the operational_intent signal fires, or when `trigger_origin` is one of the Phase 4 event triggers (`post_tool_failure`, `retry_threshold`, `session_start_checkpoint`, `user_explicit`), operational facts compete with normal injection **at lower priority than `constraint_memory`**. Cap: 3 facts per UserPromptSubmit, one per `command_family`.

Config default: `[injection.policy.types.operational_fact] mode = "on_demand"`. `mode="suspended"` hides on both read and inject paths.

### Surface A — PreToolUse (deferred to a follow-up milestone)

Surface A remains architecturally viable on Claude Code (Phase 0 Q1 answered YES) but is deferred out of v1 to preserve Claude/Codex parity. Revisit if Surface B evals show the "surface before the tool call" moment is materially better than "surface at prompt submit."

If Surface A ships later, it adds:
- `pre_tool_use.py` (NEW, Claude Code only) — `command_family`-keyed lookup, < 100 ms, advisory only.
- `GET /operational_fact/lookup?command_family=...&scope_ref=...` internal HTTP endpoint (bypasses MCP for latency).

### Ranking

Sort by `last_used_at` descending. Take top 3.

**Invariant 1 preservation:** `success_count` / `failure_count` / `reuse_count` / `last_used_at` / `last_confirmed_at` are stored under a nested `use_counters` sub-blob in the payload and are NOT read by any ranking or retrieval path in v1. This is enforced by a code-level diff-grep test in W4 PR 3 that fails if any ranking file reads them.

### Do-not-inject

- Never `superseded`.
- Never conflicting active facts together.
- Never across container scope (`machine_repo` only renders in same machine_repo; `repo` only in same repo).
- Never crowd `constraint_memory`.
- Never exceed budget (300 chars per fact, surface caps above).

---

## Hooks

**v1 wires Surface B in both integrations.** Surface A hooks are deferred; the row is kept for future reference.

### Surface B (v1)

| Hook | Change |
|---|---|
| `user_prompt_submit.py` | Route through structural intent signal; inject only on operational intent. Same in Claude and Codex. |
| `pre_compact.py` (Claude only) | **Preservation only.** Re-inject an operational fact if and only if it was already surfaced in the active conversation window before compaction. Never an independent injection. |
| `common.py` (both) | Reuse the shared redaction helper; parity test in W4 PR 4 (scenario 8). |
| `session_start.py`, `stop.py` | No change. |

### Surface A (deferred, not v1)

| Hook | Change |
|---|---|
| `pre_tool_use.py` (NEW, Claude Code only) | `command_family`-keyed lookup, < 100 ms, advisory. |
| `pre_compact.py` (Claude only) | Preservation only, as above. |
| `session_start.py`, `user_prompt_submit.py` | No change. |
| Codex | No operational-fact integration on this surface (no PreToolUse equivalent). |

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
