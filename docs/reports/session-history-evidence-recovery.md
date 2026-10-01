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

## Coordination correction

The prior slice's PR and installed rollout completed, but the umbrella assignment
did not. The lead stopped prematurely. The continuation now checks remaining
feature criteria and acts on the next authorized step at each slice boundary;
another successful PR is not itself the stopping condition.

Owning [feature](../../roadmap/features/improve-session-history-search-quality.md)
and [Work Record](../../.agent-workflow/tasks/history-evidence-recovery.md).
