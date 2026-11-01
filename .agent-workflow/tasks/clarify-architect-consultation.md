<!-- agent-workflow:start -->
**Outcome:** Developers know when and how to consult the architect before choosing an approach.
**Target:** Pallium persistent developer guidance.
**Scope:** roles/developer.md and this Work Record; matching manager or architect wording only if necessary.
**Constraints:** Preserve specialist guides, exact-name mappings, implementation ownership and independent/human review requirements; no application, session, installed-environment or other checkout changes.
**Completion criteria:** Guidance names consultation triggers, direct routing, evidence and options to bring, manager updates, routine-fix discretion and review independence; role mappings and links remain valid.
**Requirement baseline:**
{"source":"work-record-initial","outcome":"Developers know when and how to consult the architect before choosing an approach.","scope":"roles/developer.md and this Work Record; matching manager or architect wording only if necessary.","constraints":"Preserve specialist guides, exact-name mappings, implementation ownership and independent/human review requirements; no application, session, installed-environment or other checkout changes.","completion_criteria":"Guidance names consultation triggers, direct routing, evidence and options to bring, manager updates, routine-fix discretion and review independence; role mappings and links remain valid."}
**Relationships:** {"schema_version":1,"sources":null,"pull_requests":[]}
**Risk:** Routine
**Complexity:** Simple
**Reason:** Both intended paths are explicit blue guidance/bookkeeping. The requested clarification changes no permissions, runtime contracts or review authority. Agent guidance is outside the documentation exemption, so normal workflow applies.
**Approach:** Expand the existing developer consultation sentence into concrete triggers and preparation, routing and review boundaries. Reuse the existing manager and architect guidance without edits when already consistent.
**Verification:** Run the whole-change selector and its governance checks; validate unique exact-name mappings, relative existing guide targets and local role links; inspect the diff for requested content, privacy and whitespace; run fresh Redline and Agent Workflow checks. Return the exact revision for manager review before publication.
**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Started a new branch from published main `6a3c36d64f5c154e2ecb286e1fda30b2e3eca39b` in the existing isolated roles checkout. The completed role-publication branch and record remain recoverable and unchanged. Whole-change intended-path review requires a Work Record; fresh pre-edit Redline reports blue paths and no checkpoint. The initial workflow check correctly blocks on this not-yet-created record.

The manager and architect guides already preserve developer implementation ownership, direct consultation and independent/human review boundaries. Only the shared developer guide needs clarification. Self-reviewed the Routine/Simple approach before implementation. No roadmap feature status changes or source-item identity were supplied for this governance task.
