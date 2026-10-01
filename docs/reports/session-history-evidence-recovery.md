# Session History evidence recovery and caller investigation

Started 2026-10-01 from `542e867e`; investigation in progress.

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
anonymized fixtures. Two source-traced questions are being tested:

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
downstream-task-effect estimates. No production correction is selected until
the probe evidence and concrete plan have independent review. Visibility,
forgetting, redaction, exact-work scope, and retrieval-is-not-use remain binding.

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

Next acceptance decisions are ordered: reproduce the two caller hypotheses;
select and verify any justified small correction; review remaining equivalent
result/source-choice questions using safe cases; only then consider a fixed-pool
rank-only preflight. A negative probe or unavailable dataset closes that avenue,
not automatically the umbrella assignment.

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

Owning [feature](../../roadmap/features/improve-session-history-search-quality.md)
and [Work Record](../../.agent-workflow/tasks/history-evidence-recovery.md).
