<!-- agent-workflow:start -->
**Outcome:** Produce directional evidence from a small real-task replay about whether Pallium history improves answer quality and what context cost it adds.

**Target:** Pallium real-corpus evaluation.

**Scope:** This Work Record, `roadmap/ideas/idea-pull-real-corpus-validation.md`, and ignored private scripts/reports under `.local/research/`; no production or evaluator code changes unless discovery forces a return to planning.

**Constraints:** Keep the source snapshot read-only and all private text local. Use real user requests rather than lookup-query fragments. Pair by requester session and strict timestamps; reject ambiguous ties and any exposed source not older than its paired request. Describe history as reconstructed, not exact. Run bounded reconstructed history versus no-history only, with no model judge; this general-value replay does not test the replacement guard. Spend at most eight answer calls and 10,000 estimated input tokens. Report downstream-task-effect separately from retrieval quality; treat latency as exploratory and do not claim broad product validity from one session.

**Completion criteria:** A zero-cost inventory preregisters temporal and direct task-to-lookup linkage exclusions and identifies up to four answerable, non-duplicate real tasks with non-empty safe history; if fewer remain, report corpus insufficiency before further spend. Any generated pair that fails later provenance review is excluded. The roadmap records only provenance-valid directional results, full attrition/cost, and the remaining 20–30-case/human-review gap.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline classified all intended tracked paths BLUE with no boundary or checkpoint findings. Risk is raised because private historical data and paid provider calls require fail-closed handling; complexity is Moderate because validity depends on temporal task reconstruction, blinded comparison, and an explicit stop gate.

**Discovery:** The existing evaluator is read-only, budget-capped, and can run a two-arm no-judge comparison, but it uses agent-authored lookup queries as tasks; prior review showed those can be malformed fragments. The snapshot has 8,720 source turns overall, 1,165 unforgotten user turns across 55 threads, and 29 agent-pull lookup events that can be paired with 16 distinct earlier user requests, all from one requester session. Exposed payloads store source IDs rather than immutable original text, so the run can reconstruct bounded history from the snapshot but cannot call it exact. The runner executes history before no-history, so latency is order-confounded. Its guarded arm also fails closed when direct replacement lineage is absent, so this zero-lineage general-value replay must use the raw two-arm path with bounded reconstructed source history and must not claim to test the replacement guard.

**Material assumptions:** At least four of the 29 pairable events have distinct, answerable preceding user requests, direct task-to-lookup linkage, and non-answer-leaking sources. A posthoc linkage audit disproved this: two of four generated pairs were unrelated and are excluded; no further calls are permitted and corpus insufficiency must be reported. The local model-provider configuration can provide answers within eight calls / 10,000 estimated input tokens; if credentials or budgets fail, preserve the partial report and make no retries beyond the cap. Answer-mapping blinding and one agent reviewer can provide directional evidence but neither full condition blinding nor human validation; report those limits explicitly.

**Plan:** 1. Create a local-only inventory by joining each lookup to the unique nearest preceding user turn in the same requester session; retain lookup/request/source timestamps and reject ties, missing turns, malformed payloads, duplicates, and exposed sources not strictly older than the request. 2. Before generated answers exist, review task text only using a fixed checklist (clear request, answerable from the prompt plus legitimate history, non-duplicate, no answer embedded in later text), record full attrition, and deterministically take the first four eligible distinct task shapes. 3. Freeze the selected case IDs and inventory hash, then reuse `run_pilot` with locally constructed `PullCase` values, `history_arm="raw"`, no model judge, eight-call / 10,000-token caps, reconstructed point-in-time history, and answer-mapping-blinded review output. 4. Have a low-cost clean reviewer judge the blinded pairs using task completion, correctness, and unsupported claims; aggregate without publishing private text. Treat latency as exploratory. 5. Update the roadmap and Work Record with directional downstream-effect, context cost, harms, full limitations, and the unresolved 20–30-case/human-review gate; verify workflow/redline/diff hygiene and close the PR.

**Verification plan:** Inventory gate → report all exclusion counts, frozen case IDs, source < request < lookup ordering, and explicit task-to-lookup linkage; exclude failures and stop further spend when fewer than four remain. Budget gate → aggregate reports no more than eight model calls and 10,000 estimated input tokens. Blinding → review sheet hides answer-arm mapping and agent reviewer receives only that sheet plus rubric; report that visible history prevents full condition blinding. Privacy/read-only → source snapshot file hash and write timestamp remain unchanged; raw-text artifacts remain only under `.local/research/`, while approved private prompt transmission is limited to the configured model provider. Product evidence → roadmap separately states directional downstream-task-effect, context cost, harm, exploratory latency, one-session limitation, and unresolved final gate. Workflow → agent-workflow checker, redline, and `git diff --check` pass.

**Plan review:** Clean-context reviews recorded below; later PR review exposed a missing task-linkage preflight, and the result was corrected to two valid cases.

**Approvals:** User explicitly approved private model-provider transmission on 2026-08-25: "proceed".

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Zero-cost discovery completed without provider calls. Pre-edit redline verdict: BLUE-only; no boundary or checkpoint findings.

## Plan review

- The clean-context reviewer found an 8-call conflict if three arms were used, an overstrong causal Outcome, underspecified temporal pairing and leakage controls, an inaccurate claim of exact exposed text, favorable-subset selection bias, partial rather than full blinding, and order-confounded latency. The plan now uses only bounded-history/no-history, narrows the claim to directional answer effect, records strict timestamps and full attrition, calls context reconstructed, freezes selection before answers, states blinding limits, and excludes latency from the product decision.
- Assumption failure before implementation: `run_pilot(history_arm="guarded")` stops at zero calls when the corpus has no direct replacement lineage. The revised raw two-arm run tests general bounded-history value only; replacement-guard validation remains blocked.
- Clean-context re-review confirmed four raw-history/no-history cases use exactly eight answer calls, both budgets fail closed, answer mapping is hidden but condition is inferable, and the result can support only directional downstream-task-effect.
- Zero-cost inventory completed: 39 valid lookup cases yielded 12 temporally safe distinct candidates after 11 missing-request, 6 future/same-time-source, and 10 duplicate exclusions. A pre-answer low-cost review found exactly four eligible distinct task shapes and froze their case IDs.
- Paid execution was initially blocked before transmission. The user then explicitly approved sending the four selected private historical tasks and bounded reconstructed history to the configured model provider: "proceed".

- Authenticated replay completed: four paired cases, eight successful answer calls, zero answer failures, no model judge, and no credential persistence. A low-cost reviewer judged answer mapping blind; mapping was revealed only after judgments were frozen.
- Roadmap updated with the directional result and unchanged final product gate.
- Independent result review identified missing latency, incomplete safe attrition/order evidence, split setup-token accounting, and harm/category ambiguity; all were corrected without additional model calls.
- PR review then found that timestamp order did not prove task provenance. A pre-answer-data linkage audit excluded two unrelated pairs; no additional model calls were made, and future paid replay now requires linkage validation before selection.

## Evidence

- Full attrition: 53 lookup - 5 missing/blank query -> 48 query-bearing - 9 empty exposed-history lists -> 39 non-empty valid -> 12 temporally safe distinct -> 4 pre-answer eligible/generated -> 2 directly task-linked analysis cases. Structural invalid categories were zero; reconstruction exclusions were 11 missing earlier request, 6 future/same-time source, 10 duplicates, 8 pre-answer ineligible, and 2 posthoc linkage failures. All generated cases prove source < request < lookup, but only two prove query-to-task linkage. Inventory SHA-256: `ff575c72d3adc1d2a1a073d79ef64dc3739fc0e2b9aa610b32beab77af40575b`.
- Replay generation: 4 pairs, 8 successful model calls, 0 failures, 0 judge calls, 1,612 estimated successful-call input tokens, and 890 estimated added-history tokens; only 2 pairs survive provenance validation. Four earlier unauthenticated local-proxy rejections reached no upstream model and reserved 1,255 estimated tokens; combined estimate 2,867 under the 10,000 cap. Exploratory latency: 18,427.692 ms with history vs 13,914.475 ms without, explicitly order-confounded.
- Blinded agent review across all generated pairs initially gave history 3 wins and no history 1. The posthoc answer-hidden linkage audit excluded one apparent win from each arm. Provenance-valid result: history 2 wins, no history 0, from two uncategorized cases. Agent review only, not human validation or a four-case estimate.
- Privacy/read-only: credential loaded from the local credential store only into the replay process and never printed or persisted; source snapshot SHA-256 and write timestamp unchanged; raw outputs remain ignored under `.local/research/`.
- Artifact assertions passed, including reconciled attrition and all four temporal-order booleans; local helper syntax check passed; `git diff --check` passed. Agent-workflow clean and final redline BLUE with no checkpoints or boundary/API/schema/security/runtime-config changes. Skill-feedback triggers all evaluated No.

## Result review

- Independent review corrections for latency, attrition, ordering, budget, harm, and categories were completed without more model calls.
- PR review correctly found that temporal order alone did not establish task provenance. An answer-hidden audit excluded two of four generated pairs as unrelated. The public claim is now limited to two anecdotal history wins, the corpus is insufficient, and direct linkage is a mandatory pre-spend gate for future replay.
- Final independent re-review passed the two-case provenance correction, arithmetic, cost accounting, privacy-safe wording, and absence of internal identifiers. Product gate remains in progress. Final risk stays Elevated; tracked-path redline remains BLUE.
