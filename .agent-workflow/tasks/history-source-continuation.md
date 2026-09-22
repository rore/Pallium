<!-- agent-workflow:start -->
**Outcome:**
An authorized MCP caller can read one oversized Session History source to completion through bounded, stateless continuation pages with explicit effective limits, stable source identity and content revision, preserved lookup lineage, and no gap or overlap.

**Target:**
Pallium Session History MCP source expansion.

**Scope:**
Add optional Unicode-code-point `content_offset` and visible-anchor `content_revision` inputs to `pallium_expand_source`; extend the existing MCP response-budget formatter with continuation metadata; add focused formatter/tool and real MCP-to-HTTP integration regressions; align `docs/session-history.md` and the owning roadmap item. Do not change the HTTP route, service, storage, schemas, ranking, search-result navigation, or integration skill guidance in this slice.

**Constraints:**
Preserve existing fields, defaults, authorization, ordering, warning semantics, and the 4,000-character MCP response ceiling; added paging metadata may reduce available content near the cap. Every page must refetch through `PalliumMcpClient.get_source_context`, reusing visibility, actor/container scope, redaction, forgetting, parent-lineage, and delivery-finalization checks. Offsets count Python Unicode code points in the freshly authorized, redacted anchor content and remain correct under JSON escaping. A nonzero offset requires the revision returned with page zero; a changed visible revision fails without content or delivery finalization and instructs the caller to restart at zero. Retrieval alone must not update accessibility or ranking state. No cache, cursor store, generated summary, dependency, or ingestion-record split.

**Completion criteria:**
- An oversized anchor can be read from offset zero to completion by following returned offsets; concatenated page content equals the visible redacted anchor exactly once, including non-ASCII, quotes, backslashes, and newlines.
- Every successful page is at most the reported effective response budget, retains the same `source_item_id`, `parent_lookup_id`, and visible-content revision, and reports its effective current offset, total visible characters, whether more content exists, and the next offset when applicable. Every page with `has_more` makes positive progress.
- Negative or malformed offsets and nonzero offsets without the matching revision fail deterministically without content. Exact-end and over-end offsets normalize to the total and return stable empty terminal anchor pages with `next_offset: null`; minimum, maximum, and over-maximum budgets report explicit deterministic behavior, including the effective 4,000-character cap. The 256-character minimum is an accepted request floor, not a promise that every anchor's metadata fits.
- Equal-length or unequal-length visible-content changes between pages produce a bounded stale-revision error, release no content, do not finalize delivery, and direct the caller to restart at offset zero.
- Every continuation call re-runs the existing source-context scope checks, so a source forgotten or made inaccessible after page one cannot be read on page two.
- Existing non-continuation source expansion, historical warning/update metadata, neighbor ordering, and delivery finalization remain covered and passing.
- The caller-facing contract is documented and the owning roadmap item records this slice's evidence without claiming the broader feature is complete.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Redline classifies the additive optional MCP tool parameters and response semantics as a public Python contract requiring `api-review`; contract surfaces map to High. The change is one coherent slice but has meaningful response-budget, Unicode, visibility, revision, and lifecycle edge cases.

**Discovery:**
`app/mcp/server.py::_bounded_expansion` already enforces the caller-visible 4,000-character JSON budget and clips an oversized anchor, while `pallium_expand_source` refetches via `PalliumMcpClient.get_source_context` and finalizes only delivered source IDs. `core/service.py::get_source_context` already revalidates forgotten/visibility/redaction on every request and deliberately exempts the anchor from its neighbor budget. `app/tools/secrets_purge.py` and its undo path can rewrite `source_items.content` in place, so a bare offset is not stable across calls. Existing tests cover clipping, the cap, validation errors, visibility, lineage, and delivery receipts but provide no same-anchor continuation. The existing `tests/test_mcp_integration.py` adapter reimplements `get_source_context` and omits actor/visibility forwarding, so permission/lifecycle coverage must use the real client over ASGI transport. Redline found no boundary violation and requires only `api-review` if this scope stays out of HTTP/core/schema/storage files.

**Material assumptions:**
- Assumption: stateless paging of the freshly authorized, redacted anchor in the MCP formatter is sufficient for this embedded-local caller contract. Disproved by evidence that the agent-facing path cannot retrieve the full anchor on each request or that callers require HTTP-level continuation; action: return to planning and expand scope/risk before editing those layers.
- Disproved assumption and pivot: source content is not immutable; secret-purge and undo rewrite it in place. The plan now returns a stdlib digest of visible redacted content and requires it on nonzero offsets. If a visible-content digest cannot remain safe and deterministic, stop and replace it with an opaque revision contract before implementation.
- Assumption: delivery telemetry is intentionally source-ID based, so each successful MCP page may mint and finalize a separate expansion attempt; retrying the same page is content-stable but not telemetry-deduplicated. Disproved by an existing cross-attempt uniqueness contract; action: return to planning rather than silently changing telemetry semantics.

**Plan:**
1. Freeze the current failure with focused `_bounded_expansion` tests and a real MCP-to-HTTP journey before production edits. Reuse the Relay-style `next_offset` convention already present in `app/mcp/server.py`, with expansion-specific `content_offset` and `content_revision` inputs.
2. Make the smallest shared formatter change in `app/mcp/server.py`: validate the offset, compute a stdlib digest of the freshly redacted full anchor, require a matching revision for nonzero offsets, normalize offsets beyond the end to the total, and slice only the anchor from that Unicode-code-point position. Binary-search the largest prefix whose complete envelope—including revision, offsets, effective limit, omission counts, warning metadata, and terminal flags—fits the existing serialized response budget. A nonterminal page that cannot include at least one character returns a bounded insufficient-budget error. Preserve neighbor behavior on offset zero; continuation pages retain an empty anchor item at terminal positions and do not introduce a cache or second paging model. `content_truncated` means the page does not contain the entire source from offset zero, so it remains true on a final nonzero page and false only when page zero contains the complete source.
3. Add the optional inputs to `pallium_expand_source`, always refetch through the existing client, return no content and skip finalization on validation/revision/budget errors, and finalize every successful page—including an empty terminal anchor—through the existing delivery receipt path. Preserve the supplied finalized `parent_lookup_id` on every page. Repeated calls with unchanged content and inputs return the same content page, but mint separate telemetry attempts under the existing contract. Stop and re-plan if this requires HTTP/core/schema/storage changes or changes source visibility semantics.
4. Run focused regressions, affected History/MCP files, known failures, and the full non-slow suite once. Update documentation and the roadmap with shipped-slice evidence, then obtain independent result review and the required PR-time `api-review` checkpoint.

Key conventions: use existing `_json_text` serialized-length budgeting and binary search; use `hashlib` only; offsets are Unicode code points, not bytes or escaped JSON positions; preserve response-local historical warnings and lookup lineage; tests use anonymized deterministic fixtures.

Target files: `app/mcp/server.py`, `tests/test_mcp_server.py`, `tests/test_mcp_integration.py`, `docs/session-history.md`, `roadmap/features/fix-session-history-evidence-access.md`, and this Work Record.

**Verification plan:**
- When an oversized Unicode/escaped anchor spanning at least three pages is expanded repeatedly, the real MCP-to-HTTP caller shall receive bounded pages that concatenate without gap or overlap to the visible anchor → ASGI-transport caller-surface journey in `tests/test_mcp_integration.py` using the real `PalliumMcpClient` path.
- When a page is returned, the system shall expose stable source/lookup identity, current/next offsets, total characters, `has_more`, and the effective response cap → focused contract tests in `tests/test_mcp_server.py` plus the MCP journey.
- When offset, revision, or budget boundaries are exercised, malformed/negative/missing-revision/stale-revision, empty/exact-end/over-end, minimum/maximum/over-maximum, and metadata-only-pressure cases shall be deterministic, bounded, and make positive progress or return an error → focused formatter tests plus real MCP-to-HTTP parameterized journeys.
- When the visible content changes between pages, including an equal-length rewrite, the next call shall reject the stale revision without content or finalized delivery and instruct restart from zero → real MCP-to-HTTP lifecycle journey.
- When visibility, caller scope, or forgetting changes between pages, the next call shall re-enter the existing source-context gate and fail closed → real-client MCP integration cases for forgotten, missing, wrong-container, wrong-actor, and invalid-visibility calls; credit `tests/test_source_context_visibility.py` for unchanged underlying gate combinations.
- When a page or terminal page is retried unchanged, the caller shall receive content-stable results and an empty terminal anchor while the existing telemetry contract may mint separate attempts; delivery-finalization failure shall release no successful page → real MCP-to-HTTP integration and focused mocked finalization tests.
- When existing expansion behavior is used without an offset, historical metadata, neighbors, lineage, and delivery finalization shall remain unchanged → existing `tests/test_mcp_server.py`, `tests/test_historical_lookup_funnel_e2e.py`, and `tests/test_historical_delivery_receipt.py`.
- When continuation completes or fails, historical warning/update metadata shall remain visible where authorized and memory accessibility/ranking state shall remain unchanged → MCP integration baseline/after assertions plus existing historical-state coverage.
- When the implementation is complete, affected and repository-wide contracts shall pass → focused `pytest ... -q -n 0`, affected subsystem files, `pytest --lf --lfnf=none -q -n 0`, `python scripts/agent-workflow-check.py --repo-root . --slug history-source-continuation`, redline report, and one `python -m pytest tests/ -x -q` run before review.

**Plan review:**
Clean-context review recorded under `## Plan review`; initial plan rejected, blocking findings incorporated, MCP-local layer approved subject to High-risk user approval.

**Approvals:**
Approved by user 2026-09-22T17:26:21+03:00: "&#x20;i approve all the work that i assigned to you here, including doing PRs and merge according to guidelines"

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Checkpoint: api-review

What is changing: add optional character-offset and visible-content-revision continuation inputs plus explicit paging metadata to `pallium_expand_source` while preserving existing calls.

Why: oversized History anchors are currently clipped at the MCP response ceiling with no way to reach their tail.

Affected contract / model / boundary: additive MCP tool input and response semantics only; no HTTP, persistence, visibility, or architecture boundary change is planned.

Compatibility / migration risk: low-to-medium — the inputs are optional and existing fields remain, but callers may begin relying on new terminal-page, revision, and effective-limit semantics.

Verification plan: focused budget/offset/revision tests, real MCP-to-HTTP continuation and lifecycle journeys, repeated scope/forgetting checks, affected subsystem tests, and the full suite.

## Implementation

Planning only. No production or test files have been edited. Discovery disproved source immutability: the plan now requires a visible-content revision, positive page progress, explicit terminal semantics, and real-client MCP-to-HTTP edge coverage. User approval is recorded verbatim above. Implementation may begin on the recorded files only.


Tests-first baseline added in `tests/test_mcp_server.py`: formatter metadata/progress, terminal normalization, and continuation tool inputs. The repository venv confirmed all three tests red before production edits: missing `effective_max_chars` / `content_revision` metadata and unsupported continuation inputs. Focused command: `C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest tests/test_mcp_server.py::test_bounded_expansion_reports_explicit_continuation_budget_and_progress tests/test_mcp_server.py::test_bounded_expansion_normalizes_over_end_to_terminal_page tests/test_mcp_server.py::test_expand_source_accepts_continuation_inputs_and_preserves_lineage -q -n 0` → `3 failed`.

## Plan review

Clean-context reviewer `/root/continuation_plan_review` rejected the initial bare-offset plan after finding supported in-place source-content rewrites in `app/tools/secrets_purge.py`. The reviewer approved MCP-local paging as the smallest correct layer once four blockers were addressed: require a caller-carried digest of freshly authorized redacted anchor content; guarantee positive progress within the complete serialized envelope; define terminal, retry, truncation, and delivery semantics; and exercise boundary/lifecycle/security behavior through the real MCP-to-HTTP path instead of the existing incomplete adapter. The plan and verification matrix above incorporate those findings. No HTTP/core/schema/storage expansion is needed.

## Evidence

Pending implementation.

## Result review

Pending implementation.
