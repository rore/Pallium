<!-- agent-workflow:start -->
**Outcome:** Align persistent guidance with the agreed manager, architect and developer responsibilities.
**Target:** Pallium role guides and exact-name mappings.
**Scope:** roles/*.md and roles/mapping.yaml.
**Constraints:** Preserve specialist guidance and active assignments; no session replacement, alias takeover, model override or installed service change.
**Completion criteria:** All mappings resolve; manager and architect responsibilities are separate; developers share implementation guidance; cheap delegation retains parent accountability.
**Requirement baseline:**
{"source":"work-record-initial","outcome":"Align persistent guidance with the agreed manager, architect and developer responsibilities.","scope":"roles/*.md and roles/mapping.yaml.","constraints":"Preserve specialist guidance and active assignments; no session replacement, alias takeover, model override or installed service change.","completion_criteria":"All mappings resolve; manager and architect responsibilities are separate; developers share implementation guidance; cheap delegation retains parent accountability."}
**Relationships:** {"schema_version":1,"sources":null,"pull_requests":[]}
**Risk:** Routine
**Complexity:** Simple
**Reason:** Explicit blue role paths; requested responsibility separation changes no runtime permissions or authority safeguards. Documentation exemption excludes agent guidance, so normal workflow applies.
**Approach:** Add manager, architect and shared developer guides; retain specialist guidance and an owner compatibility reference; align exact mappings.
**Verification:** Validate unique exact-name mappings, relative existing guide targets and local Markdown links; run diff whitespace and workflow checks. No application behavior changes.
**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Created the isolated feat/align-team-roles branch before role edits. Existing shared-checkout changes remain untouched. This task does not refresh running sessions; mappings select guidance only.

## Evidence

- Unique exact-name mappings, existing relative guide targets and all local role links validated successfully.
- Test selector chose the governance lane. The selected three files produced 44 passes, one Git Bash access failure and two temporary-directory setup errors under restricted execution. The exact three affected tests then passed with elevated execution in an isolated directory: 47 distinct tests passed across these runs. The initial default temporary-directory run also had setup errors; these are not application failures or hidden green evidence.
- Import boundary reporter and Redline-backed Agent Workflow check returned clean. Whitespace check passed.
- A bounded independent low-cost review found the role content and links aligned with the request, with no private operational disclosures. Its stale Work Record state finding is addressed here. The reviewer could not locate the host skill in the checkout; the implementing manager loaded the installed skill and setup reference directly.

## Handoff

Branch: feat/align-team-roles. Role guidance is ready for publication review; canonical checkout adoption and session refresh remain separate. No application tests, model overrides, name transfers, service operations or installed changes were performed. Publication must preserve the existing dirty checkout and ongoing incident work; do not auto-sync or restart the installed service for this governance-only change.
