<!-- agent-workflow:start -->
**Outcome:**
Agents can find a known Relay recipient in another Pallium project without mistaking container-local discovery for absence.

**Target:**
Pallium Relay integration guidance.

**Scope:**
Update docs/agent-relay.md and the Codex, Claude Code, and OpenCode pallium-memory SKILL.md sources.

**Constraints:**
Keep ordinary MCP discovery container-local; use only read-only global session lookup for cross-project discovery; verify the exact target before sending; do not change Relay behavior, APIs, or CI; install only from the stable checkout after merge.

**Completion criteria:**
When the destination is in another project, each skill explains the global read-only lookup, exact task-session match, current endpoint or alias, and safe fallback; Relay docs agree; the three skill sources stay identical.

**Requirement baseline:**
{"source":"2d8fc659-fce7-4c9a-ab7d-f090a2f2f823","outcome":"Agents can find a known Relay recipient in another Pallium project without mistaking container-local discovery for absence.","scope":"Update docs/agent-relay.md and the Codex, Claude Code, and OpenCode pallium-memory SKILL.md sources.","constraints":"Keep ordinary MCP discovery container-local; use only read-only global session lookup for cross-project discovery; verify the exact target before sending; do not change Relay behavior, APIs, or CI; install only from the stable checkout after merge.","completion_criteria":"When the destination is in another project, each skill explains the global read-only lookup, exact task-session match, current endpoint or alias, and safe fallback; Relay docs agree; the three skill sources stay identical."}

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
Add one concise cross-project lookup rule to the three mirrored SKILL.md sources. Clarify docs/agent-relay.md: dashboard global listing has no exact session filter, so page to completion; match exact runtime, session_ref, and independently known target container; reject incomplete, absent, or ambiguous matches; inspect lifecycle and destination health; send only to the verified canonical id or current alias. If required independent identity is missing, request the target address or use app-message fallback. Keep sender injected scope, existing routing, APIs, and installation paths unchanged. Stop if the final diff needs code, schema, or runtime configuration.

**Verification plan:**
When a known destination is in another project, the guidance requires complete pagination, exact runtime/session/container match, ambiguity rejection, and safe fallback → inspect final diff against dashboard route and live response.
When the guidance is mirrored, all three skill sources remain identical → compare file hashes, run skill quick validation, and run focused integration packaging checks.

**Plan review:**
Clean-context agent /root/relay_guidance_plan_review APPROVE after revision; see Plan review prose.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Plan review

Initial clean-context finding: the dashboard has no session_ref filter, pages at at most 200 rows, and runtime/session_ref can collide across containers. Revised plan requires complete pagination, an independently known target container, and fail-closed fallback. Same reviewer re-reviewed and returned APPROVE with no remaining blocker.

## Implementation

Initial context and immutable Requirement baseline committed first as 129781df. User confirmed shared Pallium skill scope: "yes, i want this to be updated so other agents will know how to use this" (source item 2f79cf9e-bd0e-4969-9b77-778b1775b531). Pre-edit Redline: GRAY (three skill files gray, Relay doc blue), no watch, boundary, contract flag, or checkpoint. Target files: the three integration pallium-memory/SKILL.md sources and docs/agent-relay.md. No code or installed skill is to be edited before merge. Initial plan review found a pagination and identity-check gap; the approved plan now fails closed on incomplete or ambiguous global lookup. Implementation starts only after this plan commit.

Implemented the approved guidance in the four named files. The skill variants are byte-identical; the public doc explains full pagination, independent target-container confirmation, nonclosed unique selection, sender-scope preservation, admission inspection, and fail-closed fallback. No product code or live integration was changed. The patch helper failed with the documented Windows 1385 error; deterministic replacements were limited to these named files.

## Evidence

Pending.

## Result review

Pending.
