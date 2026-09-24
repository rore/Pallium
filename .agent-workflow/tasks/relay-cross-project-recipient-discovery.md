<!-- agent-workflow:start -->
**Outcome:**
Agents can find a known Relay recipient in another Pallium project without mistaking container-local discovery for absence.

**Target:**
Pallium Relay integration guidance.

**Scope:**
Update docs/agent-relay.md, the Codex, Claude Code, and OpenCode pallium-memory SKILL.md sources and mirrored cross-project discovery references, plus focused guidance-budget coverage.

**Constraints:**
Keep ordinary MCP discovery container-local; use only read-only global session lookup for cross-project discovery; verify the exact target before sending; do not change Relay behavior, APIs, or CI; install only from the stable checkout after merge.

**Completion criteria:**
When the destination is in another project, each skill explains the global read-only lookup, exact task-session match, current endpoint or alias, and safe fallback; Relay docs agree; the three skill sources stay identical.

**Requirement baseline:**
{"source":"2d8fc659-fce7-4c9a-ab7d-f090a2f2f823","outcome":"Agents can find a known Relay recipient in another Pallium project without mistaking container-local discovery for absence.","scope":"Update docs/agent-relay.md and the Codex, Claude Code, and OpenCode pallium-memory SKILL.md sources.","constraints":"Keep ordinary MCP discovery container-local; use only read-only global session lookup for cross-project discovery; verify the exact target before sending; do not change Relay behavior, APIs, or CI; install only from the stable checkout after merge.","completion_criteria":"When the destination is in another project, each skill explains the global read-only lookup, exact task-session match, current endpoint or alias, and safe fallback; Relay docs agree; the three skill sources stay identical."}

**Behavior changes:**
[{"target":"task-context.scope","classification":"equivalent","before":"Update docs/agent-relay.md and the Codex, Claude Code, and OpenCode pallium-memory SKILL.md sources.","after":"Update docs/agent-relay.md, the Codex, Claude Code, and OpenCode pallium-memory SKILL.md sources and mirrored cross-project discovery references, plus focused guidance-budget coverage.","reason":"The original three skill entries were already at the measured 2,800-byte ceiling. Bundled references carry the same requested guidance without stripping existing safety rules; the focused test adjusts only the measured ceiling and checks this same obligation."}]

**Risk:**
Elevated

**Complexity:**
Simple

**Reason:**
Redline classifies three integration skill files gray and the Relay doc blue; no checkpoint or boundary applies. One coherent guidance change.

**Discovery:**
The three integration skill sources are byte-identical. pallium_relay_recipients and GET /relay/sessions require the caller container; exact session filtering does not cross containers. The read-only GET /dashboard/api/relay/sessions has optional container/runtime filters, so omitting container enumerates service-global sessions in bounded pages. Its rows expose id, runtime, session_ref, container_ref, alias, and destination health; code and a live lookup confirmed this. Source docs distinguish service-global routing from container-local ordinary discovery. No canonical roadmap item tracks this guidance correction.

**Material assumptions:**
The destination task exact session ID and target container are independently known from trusted context. If either is unknown, the dashboard is unavailable, or a complete lookup cannot be verified, request the target own address or use an app-message fallback instead of guessing.

**Plan:**
Keep the three SKILL.md entries short and link a mirrored `references/global-relay-discovery.md` that carries the complete procedure. Clarify docs/agent-relay.md: dashboard global listing has no exact session filter, so page to completion; match exact runtime, session_ref, and independently known target container; reject incomplete, absent, or ambiguous matches; inspect lifecycle and destination health; send only to the verified canonical id or current alias. If required independent identity is missing, request the target address or use app-message fallback. The existing skill was exactly at its 2,800-byte measured ceiling before this change; raise only that test ceiling to fit the new pointer after measuring the final text. Preserve all pre-existing safety wording and exact guidance assertions. Keep sender injected scope, existing routing, APIs, and installation paths unchanged. Stop if the final diff needs product code, schema, or runtime configuration.

**Verification plan:**
When a known destination is in another project, the guidance requires complete pagination, exact runtime/session/container match, ambiguity rejection, and safe fallback → inspect final diff against dashboard route and live response.
When the guidance is mirrored, all three skill trees remain identical and the measured skill-size check passes → compare SKILL.md and reference hashes, run skill quick validation, guidance-budget test, and focused integration packaging checks.

**Plan review:**
Initial and budget-revised plans APPROVE by clean-context reviewer /root/relay_guidance_plan_review.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Plan review

Initial clean-context finding: the dashboard has no session_ref filter, pages at at most 200 rows, and runtime/session_ref can collide across containers. Revised plan requires complete pagination, an independently known target container, and fail-closed fallback. Same reviewer re-reviewed and returned APPROVE with no remaining blocker. The first full suite then exposed a 2,800-byte skill ceiling already exhausted by the pre-change text. A compression attempt failed exact safeguard assertions and was fully reversed. The revised plan preserves those assertions, moves the detailed procedure into mirrored skill references, and adjusts only the measured ceiling for a concise loading pointer. The reviewer requested and this record now includes an equivalent Scope change chain; final re-review returned APPROVE. The skill pointer must explicitly say to load the reference for a cross-project target.

## Implementation

Initial context and immutable Requirement baseline committed first as 129781df. User confirmed shared Pallium skill scope: "yes, i want this to be updated so other agents will know how to use this" (source item 2f79cf9e-bd0e-4969-9b77-778b1775b531). Pre-edit Redline: GRAY (three skill files gray, Relay doc blue), no watch, boundary, contract flag, or checkpoint. Target files: the three integration pallium-memory/SKILL.md sources and docs/agent-relay.md. No code or installed skill is to be edited before merge. Initial plan review found a pagination and identity-check gap; the approved plan now fails closed on incomplete or ambiguous global lookup. Implementation starts only after this plan commit.

Implemented the approved guidance in the four named files. The skill variants are byte-identical; the public doc explains full pagination, independent target-container confirmation, nonclosed unique selection, sender-scope preservation, admission inspection, and fail-closed fallback. No product code or live integration was changed. The patch helper failed with the documented Windows 1385 error; deterministic replacements were limited to these named files.

After the budget failure, the approved revised plan moved the detailed procedure to three byte-identical bundled references and replaced the new long SKILL.md paragraph with an explicit conditional load pointer. Existing safety text was preserved. The measured skill limit rose only from 2,800 to 3,072 bytes, and a focused test checks the link, mirror parity, and critical discovery safeguards.

## Evidence

- Final skill text is 3,064 bytes normalized, under the narrowly revised 3,072-byte measured ceiling. The three SKILL.md copies have identical SHA-256 1687970899166EF9810DF70FA8EC44F5F3BAC00A292F94A589B6B9D80A492759; the three new references have identical SHA-256 4C9C7A52D80D14E425FA1B02578CABCA8A9168D8C86F1D28E2FE87F0447D0BA9.
- Skill quick validation passed for Claude Code, Codex, and OpenCode. Focused guidance, Codex and Claude integration, and dashboard route tests: 80 passed. OpenCode npm test: 54 passed, 7 skipped. Final post-review Pallium tests/: 5,296 passed, 34 skipped, 2 xfailed in 264.53 seconds.
- Exact committed source revision 11fb8ebc adds the mirrored reference and coverage-only guidance test, with no Relay API, runtime, config, CI, or roadmap change. The first full-suite attempt failed only the pre-existing 2,800-byte ceiling; a compression attempt violated exact existing safety assertions and was fully reversed. The final focused and full runs pass.
- Expanded pre-edit Redline is GRAY (integration skill/reference paths gray; doc/test/Work Record blue), with no watch, boundary, contract surface, or checkpoint flag.

## Result review

Initial independent result review returned REVISE: the Dashboard Sessions view defaults to Recent in 24h and could hide dormant recipients. The guide and all three references now require Sessions = All history; focused coverage asserts it. Clean-context re-review by `/root/relay_guidance_result_review`: APPROVE. The corrected Dashboard All history setting removes the recent-only filter; all three references agree, focused coverage checks it, and no other finding remains.
