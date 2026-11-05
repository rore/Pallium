# Skip Codex composer-suggestion capture

<!-- agent-workflow:start -->
**Outcome:** Keep recognized Codex composer-suggestion turns out of Pallium Session History while preserving normal submitted conversation.
**Target:** Codex hooks and Session History capture in Pallium.
**Scope:** Codex hook capture, focused regression coverage, and a private read-only preview of already captured suggestion requests.
**Constraints:** Preserve Relay wake handling and genuine prompts. Keep live installations, source rows, and settings untouched. Use exact observed template variants and keep private evidence out of the repository.
**Completion criteria:** Recognized requests and any paired output do not reach Pallium capture. Genuine prompts, ordinary assistant replies, and Relay wakes retain their behavior. Legacy cleanup candidates are counted and privately listed for a separate live-data decision.
**Requirement baseline:**
{"source":"work-record-initial","outcome":"Keep recognized Codex composer-suggestion turns out of Pallium Session History while preserving normal submitted conversation.","scope":"Codex hook capture, focused regression coverage, and a private read-only preview of already captured suggestion requests.","constraints":"Preserve Relay wake handling and genuine prompts. Keep live installations, source rows, and settings untouched. Use exact observed template variants and keep private evidence out of the repository.","completion_criteria":"Recognized requests and any paired output do not reach Pallium capture. Genuine prompts, ordinary assistant replies, and Relay wakes retain their behavior. Legacy cleanup candidates are counted and privately listed for a separate live-data decision."}
**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}
**Risk:** Elevated
**Complexity:** Simple
**Reason:** Codex hooks are gray paths. The change is limited to identifying one class of background request in the integration.
**Discovery:** The submit hook can treat a composer request as a user turn and run Relay before capture. The stop hook independently parses the last user turn to decide which assistant response to capture. Two observed provider templates differ in the response schema. The published submit hook fields do not distinguish composer origin.
**Material assumptions:** Exact known full templates are identifiable after line-ending normalization. Unrecognized requests and user-authored near matches stay eligible. If supported provenance is available or other capture paths are observed, reassess before expanding scope.
**Plan:** Add a shared exact template fingerprint check in the Codex hook helper. Keep exact Relay wake recognition and skip composer requests before scope resolution, Relay requests, or capture. In the stop parser inspect the specific user boundary already selected by the existing latest-turn parser. Match only a complete plain-text prompt in the supported transcript shapes. If a later turn-start or malformed transcript record makes the pairing ambiguous, preserve existing capture behavior. Keep recognized requests as boundaries and suppress only the assistant capture bracketed by that request. Reuse the classifier for a private, scoped, read-only legacy preview. Keep live cleanup separate.
**Verification plan:**
- Recognized requests and paired output stay outside History → `test_codex_composer_suggestion_capture` drives both hooks and inspects the scoped HTTP source projection.
- Genuine capture and wake behavior are preserved → exercise later turns, ambiguous boundaries, quotation, altered text, Unicode and ordinary/wake paths in the Codex hook tests.
- Legacy candidates are counted and privately listed → verify the scoped dashboard enumeration against the same normalized fingerprints without live writes.
- Repository validation → run the test selector and full non-slow suite.
**Plan review:** Agent technical review: independent suggestion-plan review of base fba314a4 and this Work Record. Initial review identified a Stop pairing gap. Revised latest-boundary and ambiguity handling and corresponding verification accepted.
**Approvals:** Not required at this risk level. Live changes need separate authorization.
**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Plan review accepted after adding explicit Stop transcript boundary checks.

Added the exact-template check to submit and to the existing latest-turn parser. The hook-to-History regression covers both prompt shapes, normalized line endings, later real turns, and uncertain transcript boundaries. The private preview contains exact source IDs and fingerprints only.
