<!-- agent-workflow:start -->
**Outcome:**
Compact, match-centred MCP historical search output with honest bounded expansion and guidance aligned across GitHub/Codex surfaces.

**Target:**
Pallium MCP historical search, source-context expansion, GitHub/Codex integration guidance, docs, roadmap, and end-to-end tests.

**Scope:**
MCP client/server response shaping; bounded match-centred excerpts including the anchor; GitHub container-ref canonicalization; integration guidance and tool descriptions; named docs/roadmap files; full public-surface E2E coverage.

**Constraints:**
Preserve retrieval/ranking semantics, visibility and lifecycle invariants, source-context authorization, existing MCP compatibility, and generic package boundaries. No new dependency or schema migration.

**Completion criteria:**
Historical search returns a complete FastMCP JSON payload of <=2000 characters (<=300 for zero results), with only compact source hits (source_item_id and excerpt required; role/occurred_at omitted when absent, never null) plus top-level lookup_event_id; expansion returns a complete JSON payload of <=4000 characters by default (before=1, after=1, max_chars=4000), always represents the anchor, clips deterministically with content_truncated=true, preserves parent_lookup_id, and uses a fixed minimum accepted max_chars for compact validation errors when metadata cannot fit. GitHub container references canonicalize only for GitHub; guidance/tool descriptions meet a measured reduction ceiling; public MCP/HTTP E2E covers the full edge and lifecycle matrix.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Pre-edit redline is GRAY with watch-tagged `app/mcp/client.py` and `app/mcp/server.py`; no boundary violations or red-zone checkpoints. Moderate complexity because the change spans MCP runtime behavior, integrations, docs/roadmap, and full E2E.

**Discovery:**
Pre-edit redline evidence is `build/preedit-redline-verdict.json`: GRAY, gray/watch MCP runtime files, blue tests/docs/roadmap, no boundary violations, no API/schema/security detections. The intended surfaces are compact MCP output, source-context expansion, GitHub canonicalization, integration guidance, docs/roadmap, and tests.

**Material assumptions:**
The existing MCP client/server contracts can project compact JSON without changing HTTP schemas; disprove by a required caller-visible schema break, then return to planning. Existing visibility/lifecycle and telemetry helpers remain canonical: retrieval must not mutate accessibility state, lookup events remain unconditional, and lookup_event_id/parent_lookup_id linkage must survive projection; disprove with E2E, then narrow the change. Claude and Codex each have _normalize_remote_url; preserve both seams, changing only GitHub forms and leaving unknown/non-Git refs case-preserving. Measured baselines are Claude base 5336 chars, Claude strong 5659, Codex/AGENTS 5171, Claude SKILL 3016, Codex SKILL 3038, and combined MCP descriptions 1400; ceilings are ceil(70%): 3736, 3962, 3620, 2112, 2127, and 980 chars respectively.

**Plan:**
1. Inspect current search, expansion, GitHub integration, descriptions, and E2E harnesses; record exact response and boundary contracts.
2. Implement the smallest reusable MCP shaping/canonicalization changes, retaining retrieval/ranking and visibility behavior. Budget the complete JSON string returned by the FastMCP tool function, including wrapper keys and escaping: search <=2000 characters (zero results <=300), expansion <=4000 characters with defaults before=1, after=1, max_chars=4000; validate or apply fixed minimum overhead rather than violating a too-small caller ceiling. Compact hits always include source_item_id and excerpt; role and occurred_at are omitted when absent, never emitted as null placeholders; retain top-level lookup_event_id. Truncate huge anchors deterministically, always include an anchor representation, and set content_truncated=true when clipped. Build excerpts with normalized whitespace and literal Unicode-aware query-token matches at start/middle/end and multiple matches, using ellipses; use a prefix fallback for vector-only/no-literal matches, with no LLM, reranker, or tokenizer dependency. Expansion serializes required wrapper/item metadata with empty content first; if metadata alone exceeds max_chars, drop farthest non-anchor items until it fits, never dropping the anchor; if anchor metadata alone cannot fit, return a fixed compact validation error within minimum accepted max_chars=256. Allocate remaining content to the anchor first, then nearest neighbors, restore chronological order, clip deterministically, set content_truncated on every clipped item, and assert/trim against actual escaped JSON length.
3. Align integration guidance, tool descriptions, docs, and roadmap with actual behavior.
4. Add actual public-surface MCP server.call_tool (or mounted tools/call) E2E backed by HTTP state, asserting compact payloads and search→expand lifecycle. Cover empty/1/3/over-limit, invalid bounds, Unicode/escaping, missing/forgotten/visibility, zero/max/over-max neighbors, huge anchors, match start/middle/end/multiple/no literal match, create→mutate→dispose, and returned IDs. Read HTTP telemetry/audit paths to assert unconditional lookup/exposure events, lookup_event_id/parent_lookup_id linkage, and that retrieval/expansion does not mutate accessibility state.
5. Measure current rendered Claude/Codex guidance plus generated AGENTS/CLAUDE block and tool descriptions; set a meaningful reduced combined character/token ceiling from that baseline, preserve full operational semantics, and add a rendered-text regression. Run focused and full relevant checks, redline, workflow checker, and diff validation; stop if a schema, persistence, or security-boundary change appears.

Key conventions and target files:
- Preserve `PalliumMcpClient.search_history` / `get_source_context` and `app.mcp.server` tool contracts; shape only serialized response and guidance.
- Canonicalize GitHub remotes at `integrations/claude-code/hooks/common.py` and `integrations/codex/hooks/common.py`, or extract one shared helper only if smaller; do not canonicalize arbitrary non-GitHub refs.
- Keep historical lookup telemetry unconditional and linked through `lookup_event_id` / `parent_lookup_id`; retrieval alone must not update accessibility state.
- Name one total serialized budget and allocation before editing, including wrapper overhead, large-anchor truncation, and match-centred excerpt rules.
- Target files are explicit: `app/mcp/client.py`, `app/mcp/server.py`, the existing Claude/Codex normalization seams under `integrations/*/hooks/common.py`, rendered integration guidance/skill and generated AGENTS/CLAUDE block sources, named docs/roadmap files, and public MCP/HTTP E2E tests; retrieval/common or callers only if match-centering cannot be implemented at the MCP shaping seam. Avoid `api/schemas.py`, `api/routes.py`, `core/service.py`, and storage schema unless a test proves unavoidable, which returns the task to planning.
- Keep guidance/tool descriptions under a measured baseline-derived combined token/character ceiling and test rendered guidance text.
- Baseline regression ceilings (70% rounded up) are fixed: Claude base <=3736, Claude strong <=3962, Codex/AGENTS <=3620, Claude SKILL <=2112, Codex SKILL <=2127, combined search_history+expand_source descriptions <=980 characters. Measure rendered text in tests; do not substitute token estimates.

**Verification plan:**
When historical search is requested, MCP shall return compact match-centred excerpts -> MCP client/server E2E with Unicode and boundary limits.
When an excerpt is expanded, the response shall include the anchor and honor bounded limits without implying unbounded context -> HTTP/MCP source-context E2E.
When GitHub supplies a container reference, all supported forms shall canonicalize identically -> integration tests and fixture matrix.
When lifecycle or visibility conflicts occur, the public surfaces shall preserve existing denial, idempotence, and forgotten filtering -> full E2E lifecycle/visibility matrix.
When documentation is read, it shall match the shipped contract -> docs/roadmap review plus workflow/redline checks.

**Plan review:** Final clean-context review recorded below; approved for implementation.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Created and switched to `codex/budget-aware-historical-recall`.
- Read operating-mode, risk, plan-review, gray-zone, policy, and workflow configuration guidance.
- Generated pre-edit redline classification; no guarded implementation edits made.
- Revised planning fields to specify complete serialized budgets, deterministic excerpts/anchor clipping, both GitHub normalization seams, public MCP+HTTP E2E and telemetry assertions, accessibility-state invariants, and baseline-derived guidance ceilings.
- Measured exact baselines and recorded 70%-of-baseline ceilings; clarified optional compact-hit keys and the metadata-first expansion allocator, including fixed minimum error behavior.
- Added public MCP regression tests for compact Unicode/escaping output with null optional omission and fixed minimum expansion-budget errors. Full lifecycle/HTTP telemetry matrix remains for Verify because current production shaping does not yet expose all requested cases.
- Implemented MCP-only bounded search/expansion projection, deterministic excerpts, GitHub-only case-preserving normalization seams, compressed tool descriptions, and public server.call_tool regression coverage; HTTP internals remain unchanged.
- Continued implementation: compacted installed/generated guidance to measured ceilings, added rendered-size regression coverage, and added public compact-payload E2E. Full edge-matrix verification remains for Verify.
- Corrective pass: added query-aware retrieval excerpts and explicit context canonicalization seam; hook reversion was attempted but blocked by the execution safety gate, so this remains an unmet cleanup item. Full allocator edge matrix remains for Verify.
- Verification complete; 80 focused public-surface, 23 context/excerpt, 28 integration/guidance, 34 vector/rebuild; import-linter zero; final redline GRAY/no checkpoints or boundary/contract changes; roadmap entry added.
- Skill feedback trigger 3 fired; source repository for the installed GitHub plugin is not accessible, so the report is recorded below as unsent.
- PR #43 review opened four threads; three in-scope fixes are underway (neighbor omission metadata, lookup-link guidance, Unicode casefold index mapping). Global HTTP write-path canonicalization is under scope/architecture assessment.
- PR #43 corrective pass: added budget-accounted items_omitted metadata, reused the shared excerpt builder with index-preserving Unicode casefold mapping, and restored explicit search lookup_event_id -> expansion parent_lookup_id guidance across all surfaces. Focused review suite: 61 passed; import-linter and diff check passed. The direct-HTTP canonicalization request was declined as a cross-core policy/migration expansion; MCP reads and writes already share resolved canonical context.
- Completed the MCP boundary hardening: total escaped-JSON trimming, error preservation, sub-minimum/over-max expansion validation, anchor-first deterministic clipping, and earliest literal match centering. Focused pytest was unavailable because the environment lacks pytest and mcp; venv py_compile, projection assertions, and git diff checks passed. apply_patch hit Windows 1385, so the authorized deterministic local fallback was used.
- Corrective pass: search now defaults and projects at most three hits with efficient escaped-budget trimming; expansion budgets skeleton metadata, omits supported-memory metadata before turns, flags all clipped items, allocates anchor then every nearest neighbor, clamps over-max to 4000, and bounds errors. Added focused direct projection assertions.
- Scope correction: restored pallium_query default limit=5 while retaining historical search limit=3. Expansion preflight now serializes the exact output skeleton (including empty content and truncation flags), then mutates the same output list during farthest-neighbor dropping and allocation; venv py_compile, skeleton assertions, and diff checks passed.
- Added and passed one real-ASGI public MCP call_tool search→expand lifecycle test: mixed-case GitHub context canonicalization, /items→/query→/source, escaped payload caps, anchor chronology, lookup exposed_json linkage, expansion parent linkage, and dataclasses.asdict memory-state equality before/after retrieval.
- Final context/excerpt pass: GitHub canonicalization now accepts case-insensitive prefix/host with optional trailing slash and .git while preserving unknown refs exactly; retrieval excerpt matching selects the earliest textual occurrence across query tokens. Added 23 focused tests; all passed, plus venv py_compile and diff checks.
- Guidance regression pass: repaired Claude/Codex rendered blocks and both skill templates with exact compatibility/tool/lifecycle semantics, single builder-owned strength markers, and anti-dup/rating/retrieval-is-not-use wording. Exact guidance suite passed 28 tests; rendered sizes are Claude 1486/1809, Codex AGENTS 1444, and both skills 1422 characters, all under ceilings.
- Final budget corrective pass: empty expansion responses now enforce the complete escaped-JSON budget after oversized supported-memory/parent metadata, and structured error payloads preserve fitting detail or fall back to a bounded valid error object. Added two public call_tool regressions; focused MCP server/integration suite passed 34 tests with one existing warning.
- Review follow-up: guidance budget tests now assert the exact collected pallium_search_history/pallium_expand_source function-name set and read guidance files as UTF-8; focused guidance/integration suite passed.

## Evidence

Staged tree based on `77bf897d465a3f7175f5e70c74e733899b75574a`; results above; full non-slow 3637 passed, 23 skipped, 168 deselected, 2 xfailed, one unrelated local-config failure `tests/test_config.py::test_prompt_variants_legacy_fallback_unaffected` because machine Pallium TOML supplies `qar_v1_compact_contract`; action confirm clean PR CI and do not change feature; `git diff --check` passed; skill feedback recorded below.

Follow-up evidence: `tests/test_guidance_budget.py`, `tests/test_claude_code_integration.py`, and `tests/test_codex_integration.py` passed (29 tests); `git diff --check` passed.

## Plan review

Final clean-context review: APPROVED — Ready to implement.

All prior blockers are concretely resolved: exact 70%-of-measured-baseline guidance ceilings are recorded and testable; absent optional compact-hit fields have an omission contract; search and expansion budgets are total serialized escaped-JSON budgets; expansion defines metadata-first allocation, max_chars=256 minimum-error behavior, farthest-item dropping, anchor preservation, deterministic clipping, and final length validation. Public MCP plus HTTP state/telemetry E2E, lifecycle/visibility/error/Unicode/limit coverage, no-accessibility-mutation assertions, both GitHub normalization seams, explicit target files, and red-zone stop conditions are specified. The plan is the smallest viable slice and introduces no hidden red-zone, schema, dependency, or persistence scope.

No implementation files were edited during review.
## Result review

APPROVED after corrective review. The reviewer found two P1 budget leaks (structured error detail and empty-expansion metadata); both were fixed at app/mcp/server.py and covered through public call_tool tests. Re-review confirmed both resolved, no new blocker, no scope/risk expansion, and the final redline remains GRAY with no checkpoints or boundary/contract changes.
PR review produced four threads: three fixed and reverified; one architectural scope-expansion request declined with an explicit rationale.
## Skill feedback (unsent)

**Trigger fired:** 3 — a skill instruction told me to use a helper that did not work.

**What the skill said (or failed to say):** `gh-address-comments` directs agents to `scripts/fetch_comments.py`; the helper does not force UTF-8 decoding on Windows. File: `skills/gh-address-comments/scripts/fetch_comments.py` review-thread workflow.

**What happened:** The helper's subprocess reader used cp1252 and raised `UnicodeDecodeError` on GitHub Unicode output. Retrying with `PYTHONUTF8=1` succeeded.

**Suggested fix:** Decode `gh` subprocess stdout/stderr explicitly as UTF-8 (with a deliberate error policy), or document/set UTF-8 mode in the helper.

**Work Record:** commit `20dd519a`, `.agent-workflow/tasks/codex-budget-aware-historical-recall.md`; installed plugin `github/0.1.8-2841cf9749ae`.