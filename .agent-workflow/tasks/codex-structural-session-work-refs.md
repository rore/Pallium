<!-- agent-workflow:start -->
**Outcome:** Raw session turns from Claude Code, Codex, and OpenCode carry deterministic references for their current Git branch, exact Agent Workflow Work Record when present, and explicit work identifiers supplied through Pallium's integration metadata.

**Target:** Pallium.

**Scope:** The shared raw-ingest metadata sanitation seam in `core/service.py`; existing work-reference normalization and semantic merge seams; the three integration helper implementations and six ingest callers; focused integration, parity, lifecycle, and performance tests; necessary roadmap/docs updates.

**Constraints:** No Relay, API/schema, persistence, task inference, repository scan, cache, dependency, or installed-integration change before coordination with pall-arc. Preserve existing integration behavior. Treat only list-valued `pallium_work_refs` as the Pallium-owned explicit extension; do not parse undocumented host fields.

**Completion criteria:** The three supported integrations attach the same structural references before semantic processing; base/detached/non-Git/missing-or-invalid-record inputs invent nothing; the new work-reference metadata key is sanitized for every artifact kind without changing note content or unrelated metadata semantics; references are then normalized, deduplicated, and capped at five; values altered by redaction are dropped; structural/caller refs precede derived refs and remain capped after semantic processing; all six caller surfaces and the hook-to-ingest-to-raw-storage lifecycle are covered; measured overhead stays within the declared no-cache threshold.

**Risk:** High

**Complexity:** Moderate

**Reason:** Agent-redline classifies `core/service.py` as a red, load-bearing architecture-core seam requiring architecture review. The remaining core/semantic files are watch/gray, integrations are gray, and tests/docs are blue. No API, persistence, security boundary, or layer-contract change is expected.

**Discovery:** Six ingest call sites exist: user and assistant turns in Claude Code, Codex, and OpenCode. Their standalone helpers are intentionally mirrored. `core/work_ref.py` normalizes references but has no aggregate cap; semantic processing rewrites `metadata["pallium_work_refs"]` late and currently gives extracted refs precedence. Standard host payloads expose cwd but no stable Jira/PR/issue fields. Integration-side secret handling is not equivalent to server metadata redaction: normalizing first can mutate provider-token separators and prevent the server from recognizing the secret. Therefore the root-cause seam is shared ingest after existing metadata redaction, not duplicated hook sanitation. No public response exposes raw metadata; a product API added only for testing is unnecessary.

**Material assumptions:** Existing `metadata["pallium_work_refs"]` can carry raw candidate strings without API/schema/persistence changes; disprove with composed hook-to-real-API storage tests, then return to planning. One combined bounded Git subprocess per ingested turn is acceptable without caching; disprove if Python or Node warm p95 exceeds 100 ms or cold execution exceeds 500 ms in the recorded temporary-repository run, then return for cache review. OpenCode workspace cwd changes take effect on plugin reinitialization because no documented per-event cwd exists.

**Plan:** 1) Extend the existing work-ref normalizer with one shared five-reference bound. In `core/service.py`, immediately before SourceItem construction, sanitize only `metadata["pallium_work_refs"]` for every artifact kind: copy the top-level metadata dict, accept only a list of strings, drop candidates changed by `redact_sensitive` or containing its replacement marker, normalize/deduplicate/cap once, and remove an empty/invalid key. Preserve the note carveout for content and all unrelated metadata. 2) Add the smallest structural resolver to the mirrored Python and JavaScript integration helpers. Use exactly one bounded `git rev-parse --show-toplevel --abbrev-ref HEAD` subprocess; skip detached/non-Git/main/master/develop/trunk/head; derive the exact Agent Workflow slug by stripping only `slice/|feat/|feature/|fix/|bug/|chore/|demo/` and replacing remaining slashes; validate only `<git-root>/.agent-workflow/tasks/<slug>.md` via strict resolution, containment/no symlink escape, regular-file status, and both Work Record markers. Emit branch then Work Record then list-valued explicit caller refs. Do not scan, infer, cache, redact, or normalize in integrations. 3) Attach those raw candidates at all six user/assistant ingest sites. OpenCode resolves per event and supports cwd changes only through plugin reinitialization. 4) Make semantic merge keep metadata refs before extracted refs and apply the same shared cap. 5) Extend existing table-driven Python parity and Node tests, plus a composed E2E that captures each hook payload, posts it through the real API, and reads the raw SourceItem from storage before semantic processing. Cover provider-token and separator mutation cases. 6) Measure one cold and fifty warm Python and Node resolver calls against a temporary Git repository; record median/p95/max. 7) Update roadmap/docs after verification. Stop on API/schema/persistence changes, undocumented host-field parsing, failed performance threshold, or unresolved pall-arc overlap.

**Verification plan:** Resolver tables cover same repo/branch/caller ordering; non-Git, detached, every base branch, missing/non-file/partially marked/malformed Work Record, exact slug prefixes including unstripped `codex/`, containment and symlink escape, duplicate, Unicode, empty, max, over-max, branch change, and workspace reinitialization. Six user/assistant wiring tests assert metadata without disturbing existing payload behavior. Full lifecycle tests ingest captured hook/plugin payloads through the real HTTP app and verify bounded/redacted raw metadata through storage before processing; a note case proves its content and unrelated metadata stay unchanged while secret-bearing work refs are absent. Semantic tests prove metadata precedence and the final cap. Focused regressions cover Claude/Codex integration, work-ref, parity, raw ingest/redaction, and OpenCode suites. Final gates are the agent-workflow checker, redline report, diff review, CI, PR comments, and fresh clean-context result review.

**Plan review:** Initial clean-context review: `/root/architect_structural_refs_plan`. Revised review: `/root/validate_revised_structural_refs_plan`. Final root-cause review: `/root/final_structural_refs_architecture`; approved after the two amendments recorded below.

**Approvals:** Approved by user 2026-09-05: "i don't underfstand what happened in this session, what are you waiting for? why didn't you continue?"

**Exceptions:** —

**State:** Ready to implement
<!-- Ready to implement | Blocked | Ready for review -->
<!-- agent-workflow:end -->

## Implementation

- Work Record created before discovery.
- Intended implementation files: `core/service.py`, `core/work_ref.py`, `semantic/agent_conversation_memory_memory.py`; `integrations/claude-code/hooks/common.py`, `user_prompt_submit.py`, and `stop.py`; the three mirrored Codex hook files; `integrations/opencode/.opencode/plugins/pallium-common.mjs` and `pallium.mjs`; `tests/test_work_ref.py`, `tests/test_hook_common_parity.py`, `tests/test_claude_code_integration.py`, `tests/test_codex_integration.py`, `tests/test_secret_redaction_e2e.py`, `integrations/opencode/tests/common.test.mjs`, `integrations/opencode/tests/plugin.test.mjs`, and if composition does not fit an existing file, one focused `tests/test_structural_work_refs_e2e.py`; `docs/agent-integration.md` and the existing roadmap feature file. No other production file is approved.
- Discovery found the integration-side redaction approach unsafe and moved canonicalization to the one shared post-redaction ingest seam.
- A new API response field was rejected because storage-level E2E proves the contract without expanding the product surface.
- pall-arc confirmed no overlap with the listed integration paths and assigned their ownership to vnext-dev; both agents will coordinate before any shared integration reinstall or host restart.

## Plan review

Initial clean-context architect `/root/architect_structural_refs_plan` required: redact before normalization; all-six-surface coverage; metadata-before-derived precedence and a final cap; exact-path Work Record validation; documented OpenCode cwd behavior; and fixed performance evidence.

Revised clean-context architect `/root/validate_revised_structural_refs_plan` found that integration redactors do not cover server provider-token rules, so normalization could hide secrets; required complete Work Record markers plus containment/no-symlink-escape; rejected undocumented host-field parsing; and required an explicit no-cache threshold.

Resolution: sanitize only the new work-reference metadata key for every artifact kind at the shared ingest boundary, preserving the deliberate note carveout for content and unrelated metadata; keep integrations limited to raw structural derivation and the documented Pallium-owned list extension; validate both markers and path containment; and use warm p95 <= 100 ms plus cold <= 500 ms as the cache decision threshold. Final root-cause architect `/root/final_structural_refs_architecture` approved this design after requiring the all-artifact key sanitizer and exactly one combined Git subprocess.

## Evidence

- Pending.

## Result review

- Pending.
