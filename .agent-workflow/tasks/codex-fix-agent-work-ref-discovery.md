<!-- agent-workflow:start -->
**Outcome:** Agents receive one exact current work reference they can copy directly into narrow Session History search, without guessing prefixes or processing branch/work-record names.

**Target:** Pallium Session History integrations.

**Scope:** Current-work reference discovery and injected scope for Codex, Claude Code, and OpenCode; exact-search tool and skill guidance; focused caller-surface and end-to-end tests; existing Session History roadmap record and this Work Record.

**Constraints:** Reuse the same bounded defensive structural discovery used during ingestion; perform no additional Git process calls; do not infer namespaces server-side; preserve opaque explicit references, exact-match semantics, visibility, and normal behavior outside Git/Agent Workflow projects; do not refresh installed integrations until coordinated with pall-arc.

**Completion criteria:** On a supported current work item, the agent-visible Pallium scope contains one copyable `work_ref` that exact search resolves to the same items tagged during ingestion; without a safe current reference the field is absent and guidance directs broad search; installed and deterministic E2E witnesses cover supported integrations and all failure boundaries without disrupting normal developer work.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Agent-redline classifies integration and optional MCP surfaces GRAY/watch-only with no boundary or checkpoint; engineering judgment keeps Elevated because this is a cross-integration identity/context contract. Moderate complexity spans three integrations and installed behavior.

**Discovery:** Dogfooding proved that a bare branch name returns no exact results while its stored `git-branch:` reference succeeds. Shared core normalization already runs on write and read; only write-side integrations discover namespaced structural refs, and current injected scope omits them. Blank exact search can also return unrelated turns made while the branch was active, so guidance must reserve blank query for newest-state resumption and require query text for a specific question.

**Material assumptions:** One resolver-generated primary structural ref can be selected deterministically from the same one-pass write-side discovery without widening exact matching; disprove by finding a supported integration where ingestion and injection cannot share the resolved value, then return to planning. Existing lookup telemetry can represent empty exact searches without schema work; disprove by tracing the delivery record and add only the smallest required observability change.

**Plan:** In each self-contained integration helper, expose the existing bounded filesystem-only structural resolver through one reusable function. User-prompt handling calls it once before either Relay or memory scope formatting, selects only its first safe structural value, and passes that same precomputed list into ingestion metadata so there is no second filesystem scan and arbitrary explicit refs can never become the injected current work_ref. The optional scalar is omitted—not fatal to the rest of the scope—when it fails the core-equivalent 128-character, redaction, NUL/control-character, or nonempty checks; the exact-search server still performs the authoritative case/separator normalization on the copied raw value. Pass the scalar to both Relay-return and normal memory scope paths. OpenCode preserves its Windows no-filesystem rule, yielding no current work_ref there. Update the exact-search MCP description and exact-empty bounded hint plus every bundled guidance surface to say: copy injected work_ref exactly; when absent use broad search; omit query only for newest-state resumption and provide it for a specific question. Extend existing parity/caller E2E tests to drive hook discovery → emitted scope → HTTP ingest → copied exact search, record the dogfood fix as a focused roadmap item, then run focused suites, full suite, clean-context result review, PR/CI/comment closure, merge, and coordinated installed refresh/witness. Stop and return to planning if safe selection requires namespace inference, a second Git/filesystem pass, a schema change, or exposure of explicit/unredacted metadata.

**Verification plan:** When a supported hook ingests a prompt on a non-base branch, its emitted scope shall contain one safe work_ref whose copied value retrieves that same source through exact search → extend structural caller→HTTP→exact-query E2E for Codex, Claude, and supported OpenCode. When Git/Work Record discovery is missing, unsafe, detached, base-branch, changing, Windows-unsupported, overlong, secret-like, or malformed, normal ingestion/context shall continue with no work_ref and broad-search guidance → existing defensive resolver matrices plus scope/caller regressions. When multiple or explicit refs exist, the agent shall receive one deterministic safe structural ref and exact namespace collisions shall not alias → parity and MCP exact-search tests. When exact search is empty, its bounded response shall direct the agent to copy injected work_ref or use broad search; when asking a specific question, guidance shall require nonblank query → MCP/guidance-budget tests. Existing container/actor/visibility/forgotten/search→expand contracts shall remain unchanged → focused MCP/E2E suites. The merged installed integration shall expose a copyable ref and complete one real exact lookup without manual prefix discovery → coordinated post-merge witness with recorded ids/timing.

**Plan review:** Clean-context Luna second-pass APPROVE recorded under the Plan review section.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Established the task from a live dogfood failure before touching product code.
- Pre-edit redline verdict: GRAY/watch-only for integration and optional MCP surfaces; no boundary violation or required checkpoint.
- Plan review initially found four blockers; the revised provenance-preserving, one-pass, Relay-aware plan received clean-context APPROVE.

## Evidence

- Live exact search with `codex/fix-windows-restart-safety` returned no results; `git-branch:codex/fix-windows-restart-safety` returned current tagged turns.
- `core/work_ref.py` applies the same case/separator normalization on write and query.
- Codex and Claude hooks discover `git-branch:` and optional `agent-workflow:` refs for ingestion, while `format_injection` exposes no work reference.

## Plan review

The first clean-context Luna review blocked implementation until the plan preserved structural-ref provenance, enforced length/redaction/control safety, covered the early Relay-return path without a second discovery pass, wired an exact-empty MCP hint, and extended the caller E2E through emitted scope and exact retrieval. The revised plan incorporates all four findings. The same clean-context reviewer re-read the record and returned APPROVE.

## Result review

Pending.
