<!-- agent-workflow:start -->
**Outcome:** High-count Session History responses use the fixed 2,000-character MCP budget to help an agent choose a source to expand, while preserving response identity and safety contracts; otherwise the bounded study records why no safe allocation should ship.

**Target:** Pallium Session History MCP presentation.

**Scope:** This Work Record; ignored offline replay artifacts under `.local/history-response-packaging/`; at most one rank-prioritized minimum-preview allocation candidate; and, only after review acceptance, `app/mcp/server.py`, focused MCP/history tests, `docs/reports/session-history-search-quality-study.md`, and `roadmap/features/improve-session-history-search-quality.md`.

**Constraints:** Reuse PR #156's frozen development/holdout selection and evidence; do not repeat broad research or the rejected density-window candidate. Keep ranking, candidate membership/order/count, exact-work scope, visibility, source/lookup identity, parent lookup, historical/replacement cautions, and 2,000-character response budget unchanged. Restrict candidate activation to exactly 10 returned hits; preserve every 0/2/3/5/6-result response byte-for-byte even when baseline trimming occurs. No external paid judge/model calls, new skill prose, installed-service change, or production edit before architect acceptance. Retrieval alone never updates accessibility or ranking.

**Completion criteria:** On frozen development data, one candidate either (a) increases blind-reviewed useful source-choice previews for previously empty high-count hits without losing any material qualifier/currentness cue or any lookup's ability to choose a useful expansion, while keeping all IDs/order/count/contracts and every actual serialized response within 2,000 characters, or (b) records an explicit no-change tradeoff. A shippable candidate must also leave fitting low-count outputs identical, pass Unicode/escaped-text/realistic-long-ID/identity-only over-budget boundaries, stay within predeclared latency gates, receive clean-context and architect design approval before production editing, pass caller-surface search-to-expansion E2E plus focused unit tests, and align the report/roadmap.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Clean-context redline classified `app/mcp/server.py` as gray plus `app/**` watch, so minimum Risk is Elevated; no checkpoint or contract surface is currently triggered. Moderate complexity reflects frozen private replay, blind preview judgment, performance bounds, and a production gate after design review.

**Discovery:** Current base is merged PR #156 at `fc33e741`; its report and roadmap preserve the rejected density-window result and the next high-count packaging question. `_compact_history` builds identity/provenance/caution fields, removes match/session cues and then work refs when oversized, and finally shortens the single longest excerpt by the whole current excess; on four real 10-result responses this retained all hits but turned five excerpts empty in each variant at 1,998–1,999 characters. Frozen evidence distinguishes those 20 retained empty-text hits from 12 zero-result replay inputs. Source IDs remain expansion handles and lookup IDs remain parent lineage. Existing tests cover budgets, Unicode, exact-work identity, stale updates, and expansion parent IDs, but not fair high-count excerpt allocation through the complete MCP search-to-expansion surface. Redline verdict is GRAY/Elevated: runtime path watched, tests/docs/roadmap/Work Record blue, no boundary/API/schema/security/config flags.

**Material assumptions:** (1) The ignored PR #156 selection, snapshot, requirements, and hashes remain readable and unchanged; disprove by hash/path validation, then stop rather than rebuild broad research. (2) After mandatory identity, role, lookup lineage, and caution fields, realistic 10-result payloads have enough budget for at least 24 visible characters per nonempty input excerpt; disprove on actual serialization, then report the identity-versus-preview tradeoff without raising budget or dropping hits. (3) A 24-character minimum preview followed by rank-order allocation can add useful expansion cues without material qualifier/currentness loss; disprove on frozen development blind review, then stop before holdout and production. (4) Candidate logic can remain local to MCP presentation without changing public field names or imports; disprove during prototype/source review, then return to planning and reclassify.

**Plan:** First validate PR #156's frozen artifact hashes and replay only its 36 development lookups; keep the 12-event, one-component holdout sealed. Measure the current compactor's pre/post actual `_json_text` sizes and baseline latency for 0/2/3/5/6/10-result shapes. Prototype exactly one ignored candidate, activated only for exactly 10 returned hits: only after the existing optional-field passes leave a payload oversized, give every nonempty input excerpt a 24-character prefix when actual serialization permits, then spend remaining serialized budget in result-rank order using bounded binary search; if even mandatory fields plus the floor do not fit on frozen or realistic 36/64/128-character-ID cases, reject the candidate rather than silently treating nonempty count as success. Preserve all lower-count and already-fitting outputs byte-for-byte. A deliberately impossible identity-only-over-budget synthetic case is diagnostic only: detect and report mathematical infeasibility, fall back byte-for-byte to current baseline behavior, and make no no-drop claim for it. Freeze before candidate review: useful preview means enough task-specific content to distinguish why that source merits expansion; a material qualifier/currentness cue includes negation, correction, condition, replacement status/guidance, or explicit stale/current language. Blind-review the four high-count development lookups, reporting row- and lookup-level wins/ties/losses, newly useful formerly-empty previews, lost useful previews, qualifier/context losses, and navigation integrity. Development gates: all IDs/order/count/lookup lineage unchanged; source IDs remain usable expansion handles; reminder, decision/search scope, replacement guidance/status, role and occurred-at presence do not regress; every real response <=2,000 characters; all 0/2/3/5/6-result responses serialize identically; at least 10 of 20 formerly empty rows become useful previews; no lookup-level source-choice loss; no material qualifier/currentness loss; row-level useful-preview wins exceed losses by at least 8. Benchmark baseline and candidate with 2,000 repetitions on observed result-count/size cases plus generic 10x160, Unicode casefold expansion, escaped JSON, 36/64/128-character IDs, and identity-only over-budget shapes. Candidate must have p95 <= baseline + 0.5 ms and max <= baseline + 2 ms per case, and absolute p95/max <= 5/20 ms. Metric class is fixed-candidate agent-visible presentation/navigation; candidate recovery is unchanged, injection precision and downstream-task effect are unmeasured. Submit the design, baseline, gates, and development result to `@astra-reviewer`. Only if clean-context plan review, development gates, and architect review all pass: open the holdout once, require the same zero-regression contracts and at least one useful-preview net win without tuning, then implement the minimal shared compactor change, focused boundary tests, and caller-surface search→expand E2E. Any failed/underpowered gate produces report/roadmap-only no-change and stops.

**Verification plan:**
- Frozen evidence reuse and privacy → verify PR #156 hashes/selection, ignored status, development-only access, and no raw text/IDs in tracked output.
- Useful expansion navigation without context loss → blinded development comparison against frozen request/source evidence, with row/lookup W/T/L, formerly-empty gains, useful-preview losses, and qualifier/currentness loss audit.
- Identity, scope, and caution contracts → exact serialized-field comparison for source/lookup IDs, order/count, work/search scope, parent expansion lineage, role/timestamps, replacement guidance/status, decision reason, and historical reminder.
- Fixed response budget and low-count preservation → actual `_json_text` lengths for frozen 0/2/3/5/6/10-result replies plus byte-identical fitting-output assertions and identity-only over-budget stop evidence.
- Unicode, escaping, identifier, and lifecycle boundaries → focused generic checks for empty/24/160-character excerpts, Unicode/casefold expansion, quotes/backslashes, 36/64/128-character IDs, stale/current replacement qualifiers, and search→expand lifecycle.
- Performance and claim scope → 2,000-repetition paired baseline/candidate benchmarks against incremental and absolute gates; report fixed-candidate presentation/navigation only, with recovery unchanged and injection/downstream effect unmeasured.
- Governance and publication → clean-context plan/result reviews, architect approval before production edit, fresh boundary backend/redline/workflow checks, focused tests, one pre-review full non-slow suite if code ships, and roadmap/report reconciliation.

**Plan review:** PASS for the corrected offline prototype from clean-context gpt-6-astra high review on 2026-09-10. Production remains unauthorized pending development gates and architect review.

**Approvals:** Not required at this risk level. Architect acceptance is an additional task constraint before production editing.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- 2026-09-10: Created a fresh isolated branch/worktree from merged PR #156, confirmed current main and PR status, mapped the compaction/search/expansion flow, and obtained clean-context GRAY/Elevated pre-edit classification. Production remains blocked pending plan and architect review.

## Evidence

- PR #156 report and roadmap on base `fc33e741`; prior ignored artifacts remain in the completed study worktree and will be hash-validated before reuse.

## Plan review

PASS for the offline prototype. The reviewer probed low-count activation and impossible identity-only payloads. The plan now restricts the candidate to exactly 10 hits, preserves every lower-count response byte-for-byte, rejects the candidate if frozen or realistic-ID inputs cannot fit the preview floor, and treats deliberately impossible identity-only inputs as diagnostic baseline fallbacks with no no-drop claim. No remaining blocking finding. Holdout and production remain blocked pending development evidence and architect acceptance.

## Result review

Pending.
