<!-- agent-workflow:start -->
**Outcome:** Raw session turns carry deterministic branch and exact Work Record references where the host can derive them without risking ordinary developer work. Every integration preserves explicit work identifiers; Windows OpenCode deliberately remains structural-discovery-free.

**Target:** Pallium.

**Scope:** The shared raw-ingest metadata sanitation seam in `core/service.py`; existing work-reference normalization and semantic merge seams; the three integration helper implementations and six ingest callers; focused integration, parity, lifecycle, and performance tests; necessary roadmap/docs updates.

**Constraints:** No Relay, API/schema, persistence, task inference, repository-content scan, subprocess, cache, dependency, or installed-integration change before coordination with pall-arc. Discovery is bounded and failure must never alter or suppress normal ingestion. Preserve existing integration behavior. Treat only list-valued `pallium_work_refs` as the Pallium-owned explicit extension; do not parse undocumented host fields.

**Completion criteria:** Python Claude/Codex and non-Windows OpenCode attach the same structural references before semantic processing; Windows OpenCode performs no structural filesystem access and preserves explicit refs; base/detached/non-Git/missing-or-invalid-record inputs invent nothing; the metadata key is sanitized for every artifact kind without changing note content or unrelated metadata; references are normalized, deduplicated, redacted, and capped at five; all six real caller surfaces reach HTTP/raw storage; measured overhead meets the no-impact threshold.

**Risk:** High

**Complexity:** Moderate

**Reason:** Agent-redline classifies `core/service.py` as a red, load-bearing architecture-core seam requiring architecture review. The remaining core/semantic files are watch/gray, integrations are gray, and tests/docs are blue. No API, persistence, security boundary, or layer-contract change is expected.

**Discovery:** Six ingest call sites exist: user and assistant turns in Claude Code, Codex, and OpenCode. Their standalone helpers are intentionally mirrored. `core/work_ref.py` normalizes references but has no aggregate cap; semantic processing rewrites `metadata["pallium_work_refs"]` late and currently gives extracted refs precedence. Standard host payloads expose cwd but no stable Jira/PR/issue fields. Integration-side secret handling is not equivalent to server metadata redaction: normalizing first can mutate provider-token separators and prevent the server from recognizing the secret. Therefore the root-cause seam is shared ingest after existing metadata redaction, not duplicated hook sanitation. No public response exposes raw metadata; a product API added only for testing is unnecessary.

**Material assumptions:** Existing `metadata["pallium_work_refs"]` carries raw candidate strings without API/schema/persistence changes, confirmed by composed hook-to-real-API storage tests. Python Claude/Codex and non-Windows OpenCode use bounded local filesystem discovery with no resolver subprocess or cache. Windows OpenCode is explicit-only because Node stdlib cannot safely classify every reparse-point and cloud-placeholder case. OpenCode workspace cwd changes take effect on plugin reinitialization because no documented per-event cwd exists.

**Plan:** 1) Keep shared server sanitation/cap and semantic precedence unchanged. 2) Use bounded stdlib filesystem discovery on Python Claude/Codex and non-Windows OpenCode; Windows OpenCode is explicit-only. Reject unsafe paths, symlink/reparse components, malformed Git metadata, and invalid records; all failures return explicit refs only. 3) Keep all six caller paths and verify them through real HTTP/storage E2E. 4) Measure the final filesystem-only implementation and update docs/roadmap.
**Verification plan:**
- Cross-runtime bounded filesystem derivation and every local-path/Git-metadata/Work-Record edge → mirrored Python parity tables plus OpenCode common tests.
- Structural resolver spawns no process and every failure returns explicit-only without logs/throws → isolated subprocess spies and defensive error tables.
- Each real Claude/Codex/OpenCode user/assistant surface, resolver failure, empty/max/over-max/secret inputs, exact raw storage output → captured-caller-to-real-HTTP/storage E2E.
- Metadata precedence and final semantic cap → `TestMergeWorkRefs`.
- Local Git/non-Git/missing-Git-equivalent latency → 200-call Python and Node measurements with p95 <= 10 ms and observed max recorded.
- Regression and workflow integrity → focused Python/OpenCode suites, compile, diff check, agent-workflow checker, redline report, CI, PR review, and fresh clean-context result review.

**Plan review:** Prior subprocess designs were reviewed by `/root/architect_structural_refs_plan`, `/root/validate_revised_structural_refs_plan`, `/root/final_structural_refs_architecture`, and `/root/review_opencode_cache_plan`. Fresh defensive review `/root/review_zero_impact_filesystem_plan` required bounded local-path/file handling and real caller capture; amendments are incorporated above.

**Approvals:** Original High-risk plan approved by user 2026-09-05: "i don't underfstand what happened in this session, what are you waiting for? why didn't you continue?" Defensive filesystem-only redesign explicitly required by user 2026-09-05: "this is top priority to see there's 0 negative impact on developer work".

**Exceptions:** —

**State:** Ready for review

<!-- agent-workflow:end -->

## Implementation

- Work Record created before discovery.
- Intended implementation files: `core/service.py`, `core/work_ref.py`, `semantic/agent_conversation_memory_memory.py`; `integrations/claude-code/hooks/common.py`, `user_prompt_submit.py`, and `stop.py`; the three mirrored Codex hook files; `integrations/opencode/.opencode/plugins/pallium-common.mjs` and `pallium.mjs`; `tests/test_work_ref.py`, `tests/test_hook_common_parity.py`, `tests/test_claude_code_integration.py`, `tests/test_codex_integration.py`, `tests/test_secret_redaction_e2e.py`, `integrations/opencode/tests/common.test.mjs`, `integrations/opencode/tests/plugin.test.mjs`, and if composition does not fit an existing file, one focused `tests/test_structural_work_refs_e2e.py`; `docs/agent-integration.md` and the existing roadmap feature file. No other production file is approved.
- Discovery found the integration-side redaction approach unsafe and moved canonicalization to the one shared post-redaction ingest seam.
- A new API response field was rejected because storage-level E2E proves the contract without expanding the product surface.
- pall-arc confirmed no overlap with the listed integration paths and assigned their ownership to vnext-dev; both agents will coordinate before any shared integration reinstall or host restart.
- Implemented the minimum shared invariant: a five-ref core cap, sanitation of only the new metadata key for every artifact kind immediately before SourceItem construction, and metadata-first semantic merging. Note content and unrelated note metadata remain untouched.
- The initial Git-subprocess/cache design was discarded after measurement showed roughly 143 ms p95 for OpenCode non-Git calls. The final structural resolver launches no process.
- Python and non-Windows Node use bounded local metadata reads that fail open to ordinary ingestion. Windows OpenCode performs no structural filesystem access and remains explicit-only. Existing unrelated integration Git behavior is unchanged.
- Added helper boundary/parity coverage, six caller-surface assertions, and an HTTP-to-raw-storage note lifecycle assertion. Deterministic file replacement was used after the documented Windows process failure; an incidental `uv.lock` rewrite was removed before review.
- Final defensive coverage includes unsafe and missing paths, permission failures, mapped drives, linked Git dirs, malformed and oversized metadata, depth bounds, symlink and non-link reparse components, Git environment overrides, BOM, invalid and Unicode branches, checkout races, huge explicit lists, and all six real callers through HTTP into raw SQLite.

## Plan review

Initial clean-context architect `/root/architect_structural_refs_plan` required: redact before normalization; all-six-surface coverage; metadata-before-derived precedence and a final cap; exact-path Work Record validation; documented OpenCode cwd behavior; and fixed performance evidence.

Revised clean-context architect `/root/validate_revised_structural_refs_plan` found that integration redactors do not cover server provider-token rules, so normalization could hide secrets; required complete Work Record markers plus containment/no-symlink-escape; rejected undocumented host-field parsing; and required an explicit no-cache threshold.

Resolution: the subprocess/cache design was removed. The final design uses bounded local metadata reads where the host exposes sufficient safety information, with an explicit-only Windows OpenCode fallback. Final clean-context re-review is pending.

## Evidence

- Final focused Python: 210 passed. The full repository suite immediately before the isolated path-admission guard passed 4328 tests, with 14 skipped and 2 expected failures; post-guard caller/parity coverage passed 87 tests. Changed Python files compile and diff check is clean.
- OpenCode: 45 passed and 6 platform-inapplicable tests skipped.
- Final 200-call local measurements after the mapped-drive guard: Python Git median/p95/max 1.3492/1.5349/1.9181 ms; non-Git 0.6437/0.7183/1.0211 ms; missing path 0.3689/0.4640/0.7222 ms. Windows OpenCode explicit-only Git 0.0003/0.0013/0.0074 ms; non-Git 0.0002/0.0010/0.0033 ms; missing path 0.0002/0.0004/0.3918 ms. Every p95 is below the 10 ms local threshold.
- Ruff was unavailable in the existing environment; no dependency was installed.
- The discarded OpenCode subprocess design measured 142.876 ms non-Git p95; this evidence is why it was removed rather than cached.
- Skill feedback issue filed: https://github.com/rore/agent-workflow/issues/16
- Final revision, workflow checks, CI, and PR review are pending.

## Result review

Earlier reviews required the shared post-redaction sanitation seam, exact-path Work Record validation, all-six-caller composition through real HTTP/storage, no subprocess in the new resolver, bounded local reads, path-component safety, race detection, and a conservative Windows OpenCode fallback. The final defensive review additionally required mapped-drive rejection and direct non-link reparse coverage. Those changes are implemented. Final clean-context architect re-review approved the diff with no blocking findings and confirmed that the `architecture-reviewed` PR label is justified.
