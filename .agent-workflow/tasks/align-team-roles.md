<!-- agent-workflow:start -->
**Outcome:** Align persistent guidance with the agreed manager, architect and developer responsibilities.
**Target:** Pallium role guides and exact-name mappings.
**Scope:** roles/*.md and roles/mapping.yaml.
**Constraints:** Preserve specialist guidance and active assignments; no session replacement, alias takeover, model override or installed service change.
**Completion criteria:** All mappings resolve; manager and architect responsibilities are separate; developers share implementation guidance; cheap delegation retains parent accountability.
**Requirement baseline:**
{"source":"work-record-initial","outcome":"Align persistent guidance with the agreed manager, architect and developer responsibilities.","scope":"roles/*.md and roles/mapping.yaml.","constraints":"Preserve specialist guidance and active assignments; no session replacement, alias takeover, model override or installed service change.","completion_criteria":"All mappings resolve; manager and architect responsibilities are separate; developers share implementation guidance; cheap delegation retains parent accountability."}
**Relationships:** {"schema_version":1,"sources":null,"pull_requests":["https://github.com/rore/Pallium/pull/386"]}
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

## Publication review

The isolated publisher reconciled source `be2a677faae4ba634c9e2d7f5d9a628fbbc64c94` from base `447580f66d1ddeac6e66f2dc2413d46b9da1e4be` with current main `e77e793622cf8c5f907565555695e92fa0cd713c` without conflict. The supported governance selector, checker, workflow and selected test files are unchanged across those bases, so the recorded 47 distinct passing cases remain applicable; publication changes only guidance prose and this record.

An existing unpublished shared developer guide on the held PR #381 branch supplies compatible safeguards. The new shared guide retains its explicit scope/authorization checks, isolation of other developers' files/indexes and incident work, focused and whole-change verification, protection against weakened assertions/hidden failures, exact result handoffs and public-documentation privacy. Its new manager/architect/developer split, cheap bounded delegation and separate publication assignment are preserved. The held source branch and every other publication worktree remain untouched; later integration can reconcile its duplicate guide with this combined content instead of overwriting unpublished work.

Routine/Simple and the normal workflow remain appropriate: all changed paths are explicit blue guidance/bookkeeping, and no runtime permissions, session settings, source behavior or installed configuration changes. Publication review verifies exact-name mappings, relative existing links, content/privacy and current whole-change governance checks before push. No new application tests or session/alias/model changes are required.

Published [PR #386](https://github.com/rore/Pallium/pull/386) from reviewed guidance revision `c0e3364e6045ca11b01fbb7f2fe192c504591da6`. Fresh mapping/link, privacy, whitespace, import-boundary and Redline checks passed. The fresh workflow check retains only the existing nonblocking commit-order advisory; the unchanged governance test evidence remains applicable. Normal PR checks and review govern delivery. The isolated checkout remains needed for those gates; canonical and installed adoption remain separate. No application tests or review were repeated solely for session refresh.
