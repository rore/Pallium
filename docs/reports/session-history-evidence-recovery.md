# Session History evidence recovery and caller investigation

Investigated 2026-10-01 from `542e867e`; two supported corrections selected and
independently reviewed. Validation and rollout evidence is in the Work Record.

## Recovery result

The bounded recovery pass inspected named study locations in the shared and
installed checkouts, surviving study-named worktree directories, and tracked
study scripts/reports. It did not repeat the completed lookup census, open
protected source content, restore unrelated checkouts, or run model providers.

The original selection method and aggregate results survive in
[`history-candidate-study`](../../.agent-workflow/tasks/history-candidate-study.md).
Its private manifest payload and ID-to-request mapping do not. The earlier
response-packaging directory is empty; the candidate and quality-study private
directories were not recovered. A recorded SHA-256 digest can verify recovered
bytes, but cannot reconstruct their identities.

Classification: methodology and aggregate provenance recovered; ID-level
exclusions remain unknown. Neither the aggregate counts nor a reconstruction
based on guesses can establish untouched confirmation cases. Previously unknown
holdout contents remain unopened. Any future real-corpus comparison must freeze
traceable, disjoint cases before grading.

## Work that can proceed independently

Missing ranking confirmation does not block caller-contract investigation with
anonymized fixtures. Two source-traced questions were tested:

1. **Provenance after duplicate collapse.** The query layer retains merged
   evidence references, while the compact History response emits the primary
   source handle. Compare HTTP and MCP output and expansion behavior before
   deciding whether a caller-visible correction is needed. Identical text does
   not imply identical surrounding conversation or date.
2. **Duplicate-saturated candidate pools.** Broad source-only queries stop after
   their initial bounded fetch, while exact-work queries can grow their fetch
   after deduplication leaves result slots empty. Compare both at identical
   requested limits, record candidate budgets and cost, and distinguish a
   reproducible recovery failure from an unsupported ranking hypothesis.

These are development contract probes, not private-corpus confirmation or
downstream-task-effect estimates. The independently reviewed corrections below
are now selected for implementation. Visibility,
forgetting, redaction, exact-work scope, and retrieval-is-not-use remain binding.

### Confirmed generic failures

- **False equivalence:** eligible-length messages differing in C#/C, v1.2/v1-2,
  apostrophes, or slashes received identical fingerprints. Earlier short identifier
  tests never crossed the fingerprint threshold. Four new helper cases and an
  HTTP ingest/search/expand/forget lifecycle failed before the fix. The conservative
  correction preserves identifier punctuation and ignores only commas/full stops
  followed by whitespace or end-of-text, retaining Unicode/case/whitespace rules.
- **Unfilled distinct-result slots:** with thirteen equivalent sources and two
  distinct sources, broad HTTP/SQLite search at limit three returned one result
  after a twelve-candidate request. Exact-work search returned three after requests
  for twelve and twenty-four candidates. These counts measure synthetic
  candidate-recovery, not real-corpus quality or latency. The approved correction
  applies the existing bounded refill to broad search too, retaining its
  200-candidate cap and full/exhausted stopping conditions. The HTTP saturation
  and broad ceiling regressions failed before the fix; all six focused refill
  cases passed afterward, as did 45 affected source-only/exact-work tests.
- **Provenance:** HTTP retained both equivalent source IDs; MCP exposed the primary
  handle, which expanded successfully without neighbors. Forgetting the primary
  left the sibling searchable. This alone does not justify a new presentation API.
  A transient duplicate delivery-ID error in the evolving scratch fixture did not
  reproduce with the final benign-equivalence fixture: default-neighbor MCP
  expansion and delivery finalization passed. Inspection found disjoint strict
  timestamp/ID neighbor ranges. The transient cause remains unassigned; it is not
  evidence for a production change, and the uniqueness validator remains intact.

## Coverage and remaining decisions

Existing caller reliability is the baseline, not a new implementation target.
The following is a source-inspected coverage map; it does not claim those tests
were rerun in this discovery pass.

| Reported class | Existing caller coverage | Remaining decision |
|---|---|---|
| Paging, continuation, retry, stale-result lineage | `test_work_history_contract.py::test_history_page_finalizes_only_subset_and_terminal_page_is_empty`; `test_history_guidance_replay_e2e.py::test_navigation_replay_compares_restart_and_ledger_over_real_mcp` | Mechanics are shipped. Source choice and answer sufficiency are not established by successful navigation. |
| Candidate recovery and duplicate saturation | `test_source_only_search.py::test_source_only_max_page_keeps_bounded_refill_headroom`; `test_history_diagnostics_e2e.py::test_create_and_read_diagnostic_includes_bounded_trace_and_valid_empty` | Probe broad/exact-work behavior with a duplicate-heavy pool; no rank-only prevalence estimate. |
| Equivalent-source provenance | Internal collapse tests merge evidence; compactor tests preserve primary IDs and bounded pages. | Check the actual caller's alternate source-opening paths before proposing a change. |
| Exact-work isolation and older untagged sources | `test_exact_work_ref_search.py::test_exact_http_records_origin_and_expands_with_parent_lookup`; protected `test_history_exact_work_ref_does_not_broaden` | Untagged older sources are expected exclusions, not grounds for automatic broadening. Reuse existing scope tests. |
| Forgetting, visibility, Unicode | `test_source_only_search.py::test_vector_source_only_http_expands_then_forgets_unicode_source`; protected `test_history_forget_hides_search_and_expansion` | Preserve as regression baseline; do not add duplicate coverage absent a changed behavior. |
| Evaluation request linkage | `test_historical_lookup_funnel_e2e.py::test_request_link_actor_is_optional_metadata`, both replay modes | PR271 closed the actor-filter defect; independent case and original-payload provenance remain a separate gate. |

The caller probes selected the two corrections above. The provenance path does
not establish a missing-handle defect. Independent real-corpus source-choice
grading and any rank-only preflight remain conditional on traceable cases, not
required experiments to rerun until a favorable result appears.

The existing public-corpus benchmark was also checked as an expansion route.
Its committed manifests lack local materialized data, and the runner uses
derived-memory query/routing with answer generation rather than source-only
History. Running it would neither satisfy this question nor the zero-provider
budget. It was not run; manifest pressure cases are not claimed as independent
raw-history confirmation.

## Coordination correction

The prior slice's PR and installed rollout completed, but the umbrella assignment
did not. The lead stopped prematurely. The continuation now checks remaining
feature criteria and acts on the next authorized step at each slice boundary;
another successful PR is not itself the stopping condition.

## Measurement and completion ledger

This report complements, rather than reruns, the
[fixed-candidate study](session-history-search-quality-study.md) and
[expanded retained-data census](session-history-fresh-review.md). Those reports
retain their sampling, exclusions, serving revisions/configuration, rejected
alternatives, and limitations. This continuation starts at `542e867e` and uses
isolated synthetic HTTP/SQLite fixtures and deterministic local test providers;
it is not a replay of installed production ranking.

| Measure | Evidence and limit |
|---|---|
| Candidate recovery | The duplicate-saturated synthetic caller returns one versus three distinct results at display limit three; requested candidate budgets are twelve versus twelve then twenty-four. This establishes a contract defect, not prevalence or general retrieval accuracy. |
| Evidence precision/sufficiency | The earlier fixed-candidate report records partial wins and qualifier losses with incomplete reconstructed payloads. No new content grading, injection-precision estimate, or sufficiency improvement is claimed here. |
| Scope correctness | Existing and changed caller regressions exercise exact-work isolation, container visibility, request exclusion, redaction, Unicode, expansion, and forgetting. The refill repeats the same filters; normalization changes no source state. |
| Returned/expanded tokens | Not measured in this continuation. Display count is asserted; response character budgets and compaction are unchanged. Historical character limits are not token measurements. |
| Latency and cost | No production or incremental latency estimate. Refill is capped at 200 candidates, with full/exhausted early stops; worst-case budgets are 12, 24, 48, 96, 192, 200 for limit three. No paid provider calls or model downloads; agent execution cost was not measured. |
| Downstream task effect | Unmeasured here. Successful retrieval/expansion is not evidence of verified use, and must not update accessibility or ranking priors. |

The feature's completion criteria permit justified shipped improvements with an
explicit independent-evidence limitation. After validation, review, and rollout,
the bounded search-quality work can close without pretending that conditional
reranking or representation hypotheses were evaluated. Evidence-gated follow-up
requires recovered exact exclusion identities or traceably disjoint prospective
linked episodes, complete original caller options/payloads, and a frozen
development/confirmation partition before content grading. A rank-only preflight
is warranted only if that review establishes a remaining rank-only question.
The separate navigation/compression study remains queued, not authorized by the
delivery of these corrections.

| Feature completion criterion | Disposition |
|---|---|
| Wider bounded investigation | Prior studies plus the expanded census and this recovery pass cover additional measurement, identifier-equivalence, and candidate-saturation failures. Sampling/provenance limitations remain explicit. |
| Justified improvements and regression evidence | Evaluator correction in PR271 plus the identifier/refill corrections; red-before-green caller checks. Independent held-out quality confirmation is unavailable and not claimed. |
| Separate metrics and retrieval-is-not-use | Measurement ledger above; neither correction writes accessibility, verified use, or ranking priors. |
| Governance and source lifecycle | Reuse scope/redaction/Unicode/disabled-derived baselines and changed lifecycle checks; require whole-change validation before delivery. |
| Caller E2E and boundaries | HTTP identifier search/expansion/forgetting and real SQLite duplicate saturation; empty/sufficient/exhausted/capped refill checks, existing enabled-vector and exact-work caller coverage. No new MCP presentation behavior. |
| Guidance, rollout, roadmap | No new skill/tool guidance. Canonical feature, scope, board, and directly affected follow-up must agree; installed fast-forward and supported restart/health checks remain delivery gates in the Work Record. |

Owning [feature](../../roadmap/features/improve-session-history-search-quality.md)
and [Work Record](../../.agent-workflow/tasks/history-evidence-recovery.md).
