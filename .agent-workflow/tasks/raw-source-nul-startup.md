<!-- agent-workflow:start -->
**Outcome:** Startup detects missing raw-source vectors using the same Unicode character-length eligibility as actual inventory, including embedded NUL.
**Target:** SQLite startup backfill detection and real HTTP vector startup/reopen lifecycle.
**Scope:** storage/sqlite.py; tests/test_rebuild_coordinator.py; tests/test_vector_startup.py; this Work Record. Root owns canonical REL-09 ledger and combined integration.
**Constraints:** Preserve allowed source kinds, current source/view/missing-vector predicates, character semantics, race rechecks and existing native deadlines. Keep fast ordinary positive query; do not restore full-source DTO hydration or N+1 checks. No schema/config/provider/cache/dependency changes, shared source edits, live operations or duplicate full suite.
**Completion criteria:** NUL39 is ineligible; NUL40 is eligible; 127/128/129 short candidates cannot hide later eligible text. Real HTTP ingestion/startup/reopen repairs missing NUL40 vector and preserves exact content; existing vector does not rebuild unnecessarily. Normal positive remains one query; normal negative adds one empty bounded fallback query.
**Requirement baseline:**
{"source":"parent-REL09-assignment-2026-10-12","outcome":"Startup detects missing raw-source vectors using the same Unicode character-length eligibility as actual inventory, including embedded NUL.","scope":"storage/sqlite.py; tests/test_rebuild_coordinator.py; tests/test_vector_startup.py; this Work Record. Root owns canonical REL-09 ledger and combined integration.","constraints":"Preserve allowed source kinds, current source/view/missing-vector predicates, character semantics, race rechecks and existing native deadlines. Keep fast ordinary positive query; do not restore full-source DTO hydration or N+1 checks. No schema/config/provider/cache/dependency changes, shared source edits, live operations or duplicate full suite.","completion_criteria":"NUL39 is ineligible; NUL40 is eligible; 127/128/129 short candidates cannot hide later eligible text. Real HTTP ingestion/startup/reopen repairs missing NUL40 vector and preserves exact content; existing vector does not rebuild unnecessarily. Normal positive remains one query; normal negative adds one empty bounded fallback query."}
**Risk:** High
**Complexity:** Moderate
**Reason:** Eligibility controls persisted index repair and startup lifecycle; incorrect true/false results can omit content or rebuild repeatedly. The change is read-only detection with bounded existing SQLite mechanisms.
**Discovery:** SQL length(TEXT) ends at embedded NUL, while source_item_embedding_text counts Python Unicode characters. Inventory now correctly uses Python eligibility; startup optimized boolean retains the preexisting false-negative. Existing predicate already handles artifact kind/view/missing-vector state. Baseline b16d14678dfc897c326e3fdac804ceff09445427 supplied by root, isolated branch fix/raw-source-nul-startup.
**Material assumptions:** Actual source content is authoritative, not stale lexical text. Outer source alias must not alter correlated EXISTS source predicate. Query errors propagate. Stop if any broader startup/authority/schema change becomes necessary.
**Plan:** Invoke Agent Workflow, classify whole-change risk and create this record before code/test edits. Application change is non-exempt. Retain fast positive EXISTS. On false, reuse missing/source/view predicate without SQL length; join aliased current source, select lexical ID/content for NUL-only candidates, page 128 by lexical ID and decide Python len>=40. Always advance past short rows. Add only existing fixture regressions and HTTP journey parametrization. Capture exact RED on unchanged helper, then apply reviewed source and focused GREEN in private guard runner. Root owns combined selected full and release.
**Verification plan:** Character eligibility and paging -> real SQLite 127/128/129 short NUL rows followed by NUL40; exact truth/query-count and no SourceItem DTO assertions.
HTTP repair/reopen -> existing real POST items then vector startup/status/source context journey for Unicode/NUL40 with missing/existing vector.
Compatibility -> existing boolean state matrix and bounded/completed-vector checks.
Whole change -> import/workflow checks and root combined full; no live integration.
**Plan review:** Agent technical review: architecture_check REL-09 GO 2026-10-12. Preserve fast path; bounded NUL-only scalar fallback reproduces exact existing Python source eligibility, correlated alias semantics, cursor advancement and actual HTTP repair. Root approved branch and immediate implementation after baseline handoff.
**Approvals:** Approved by user 2026-10-12: "So keep driving this with the developers until the 50-message test passes and the remaining bottlenecks are fixed. Keep it simple, verify the fixes, and get them merged and deployed. Don't stop at another report." Additional direct human scope: "these are all bugs we should make sure we fix" and "so we should track this list - this all should be fixed. also, see if there are things here we can parallalize with a second developer". Root forwarded exact human messages; no source-item ID was available or invented. This worker has no live-operation scope.
**Exceptions:** —
**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

2026-10-12 PR 312 review correction: root authorizes replacing the Python NUL
candidate paging loop with one scalar ID LIMIT 1 query using SQLAlchemy's
existing SQLite REGEXP support and pattern `(?s)^.{40}`. Actual isolated engine
proof matches Python length for 13 NUL, Unicode and newline boundary cases.
The proposed SQLite replace expression failed and is rejected. Preserve the
ordinary fast positive query and all kind/view/missing/source predicates.
This supersedes the paging implementation plan, not the immutable eligibility
baseline. At most two statements and bounded result transfer are guaranteed;
the database may still scan candidates. No new UDF registration, dependency,
schema or cache. Architecture_check independently accepted this exact plan.
Owner edits storage/sqlite.py and existing scoped regression files; verify
39/40 parity, many short candidates plus eligible tail, no content hydration,
two fallback statements, and existing HTTP startup/reopen behavior.

Correction evidence: RED three short-row boundaries failed only their query
counts (3/3/4 rather than 2); focused GREEN 34 passed in 21.36 s. Combined
affected files passed 209 with one skip in 60.37 s. Both private runs had empty
guards and drained all three owned processes. Architecture accepted the actual
source/test delta. Evidence: shared build/service-performance-20261012/nul-regexp,
manifest E8B718648B26FC454F8498BF4E5D64148C342C212F2A948A0575C95E58761DE2.

2026-10-12: Created isolated branch from root-supplied baseline. Reviewed draft patch SHA 97C2145BA919211F7442D24189EE9E48DA7D195B56ADDFBB805F19EC39798126 applies cleanly. Record written before test/source mutation. Own next private execution slot; no shared checkout edits or live actions.

2026-10-12: Applied reviewed draft with narrowly selected Git-native hunks: tests first, source after genuine RED. No apply_patch failure or fallback. NUL40 missing-vector HTTP startup skipped repair on original helper. Candidate repaired it and preserved exact source content/readback, reopening and existing-vector behavior. All 127/128/129 candidate boundaries and existing SQLite eligibility cases passed. Source/test frozen; slot released and final architecture delta review requested. Historical Relay/load issues are separate and no live-resolution claim is made.

## Evidence

- HTTP RED: `pallium-full-suite-run-44cca185a5154c26a22df61dbc95b3f0`, 1 failed/3 passed in 5.81 s. Exact failure `test_raw_source_backfill_http_startup_and_reopen[nul40-False]`: vector_rebuild was None, required repair absent. Stdout SHA `67EF3B07938B53171537C7EBAB882CBFE9673EC18B64313007C3A74473878427`.
- Focused GREEN: `pallium-full-suite-run-13edb8eac33a40cbb152680efb181cf4`, 7 passed in 7.16 s. Stdout SHA `7099FFFA69759438563D99D70DB374B30D22B018C11235D645F1C03C78F834AF`.
- Existing bounded/completed-vector/eligibility matrix: `pallium-full-suite-run-5611c9ef940241b89fae723f7170a478`, 15 passed in 1.82 s. Stdout SHA `6D7B3220BCC9AA92FB411B24E9D0694C6E0BA2B8ABCA6B6DB01D66C2E3DA8EEE`.
- Every run: fresh private profile/paired DBs, network guards empty, stderr empty, three identity-matched owned processes drained. Runner adapted only checkout/branch/HEAD, exact four-path allowlist/new-record admission and selectors; original node runner SHA `FA949993F4FB054C23F1A34978FDE7D0B0AE8D42ECC56142B7FDEAEA8AC93E91`. Root owns combined full; no duplicate local full or live operation.
- Import-linter exit 0; selector reports full validation for the complete NUL slice, delegated to root combined validation. Evidence copies/manifest preserved under `C:/Dev/rore/Pallium/build/service-performance-20261012/raw-source-nul-startup`; manifest SHA `EFCEE44805B35F6CDE270D587D476271E2512C3162C04172D5779ABD8B078838`.
- Fresh four-path slice Redline report and Agent Workflow checker completed clean 0 with no failed predicates against root-supplied baseline. Work Record baseline committed before source commit; root owns whole integrated path-set governance and full run.

## Result review

Agent technical review: architecture_check 2026-10-12 final source/test GO. Separate aliased source join preserves original EXISTS correlation and missing/source/view predicates. Bounded NUL-only scalar scan advances through rejected rows; ordinary positive remains one query.

Reviewed revision: baseline `b16d14678dfc897c326e3fdac804ceff09445427` plus exact reviewed three-path source/test delta and this record.

Verification adequacy: actual HTTP skipped repair on original source, then repaired/reopened correctly after the fix. NUL39/40 and 127/128/129 boundaries, no DTO hydration, fast positive/empty paths and existing eligibility states passed. Root combined affected/full validation remains pending; no live-resolution claim.
