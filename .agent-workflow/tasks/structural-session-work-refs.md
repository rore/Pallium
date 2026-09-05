<!-- agent-workflow:start -->
**Outcome:** Raw session turns from Claude Code, Codex, and OpenCode carry deterministic references for their current Git branch, exact Agent Workflow Work Record when present, and explicit external work identifiers already supplied by the integration.

**Target:** Pallium.

**Scope:** Integration hook ingestion and existing work-reference metadata/normalization seams; focused integration, parity, and end-to-end tests; necessary roadmap/docs status updates.

**Constraints:** No Relay changes, schema changes, semantic task inference, repository-wide Work Record scans, speculative caching, or installed-integration mutation before coordination with pall-arc. Preserve caller-provided references, redaction, bounds, and normalization.

**Completion criteria:** The three supported integrations attach the same canonical structural references before semantic processing; base/detached/non-Git/missing-record inputs invent nothing; multiple references are normalized, deduplicated, bounded, redacted, and proven through caller-surface lifecycle tests; measured hook overhead does not justify a cache unless one is explicitly tested.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Agent-redline classifies integration paths and core/work_ref.py as gray/watch with no boundary violation. Moderate complexity reflects three integration surfaces and uncertain existing parity seams.

**Discovery:** Pending focused inspection of existing integration payload builders, work-ref normalization, tests, and recent related changes.

**Material assumptions:** Existing metadata["pallium_work_refs"] and normalization can carry the new references without schema/core-contract changes; disproved by code/tests requiring a contract change, which returns the task to planning. Git branch and direct Work Record path can be resolved within hook latency without caching; disproved by measurement, which triggers a bounded cache design review.

**Plan:** Pending discovery and clean-context architecture review. Intended approach is one shared deterministic resolver reused by thin integration adapters, only if an existing shared seam supports it; otherwise use the smallest parity-preserving native implementation without a new framework. Stop on core contract/persistence scope expansion or unavoidable Relay overlap.

**Verification plan:** Map each completion criterion to focused unit/parity tests and full caller-surface ingest-to-history retrieval E2E after discovery identifies the existing harnesses; measure cold/warm resolver latency; run integration suites and repository workflow/redline checks.

**Plan review:** Pending clean-context architect review after discovery.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked
<!-- Ready to implement | Blocked | Ready for review -->
<!-- agent-workflow:end -->

## Implementation

- Work Record created before implementation discovery. Pre-edit redline verdict: gray, no boundary violation; translated to Elevated / Moderate.

## Evidence

- Pending.

## Result review

- Pending.
