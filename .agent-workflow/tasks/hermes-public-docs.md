# Hermes public documentation cleanup

User request: "so do a pass on all hermes docs and public docs, we should remove historical things and \"experimental\" and stuff and just have it correctly documented. don't wait for me, just do and merger". This authorizes the bounded documentation update and normal merge, not installed rollout.

<!-- agent-workflow:start -->
**Outcome:** Public Hermes documentation describes current setup, capabilities and concrete support limits without development chronology or stale release labels.

**Target:** Pallium repository documentation.

**Scope:** README.md; docs/README.md, getting-started.md, agent-relay.md, session-history.md, derived-memory.md, how-it-works.md, hermes-integration.md and designs/hermes-native-qualification.md; integrations/hermes/README.md; this Work Record. Read bundled skills and runtime source to verify claims, without changing their behavior or instructions. The existing manager retains canonical roadmap ownership.

**Constraints:** Documentation only; preserve accurate compatibility, identity/privacy, optional-memory, ownership and recovery limits and exact CLI behavior. Do not imply new platform/provider qualification or promote unrelated experimental features. Preserve historical evidence in existing records, PRs and Git history. Do not change code, tests, dependencies, CI, policy, installed environments or the primary dirty checkout.

**Completion criteria:** The public guide is concise and user-oriented; Hermes references consistently describe the current integration without stale experimental/approval labels or run chronology; setup commands, links and actual support limits remain correct. Static checks, independent review and configured PR checks are evaluated, the update is pushed and normally merged, and the owning roadmap receives the contribution.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Public Hermes documentation describes current setup, capabilities and concrete support limits without development chronology or stale release labels.","scope":"README.md; docs/README.md, getting-started.md, agent-relay.md, session-history.md, derived-memory.md, how-it-works.md, hermes-integration.md and designs/hermes-native-qualification.md; integrations/hermes/README.md; this Work Record. Read bundled skills and runtime source to verify claims, without changing their behavior or instructions. The existing manager retains canonical roadmap ownership.","constraints":"Documentation only; preserve accurate compatibility, identity/privacy, optional-memory, ownership and recovery limits and exact CLI behavior. Do not imply new platform/provider qualification or promote unrelated experimental features. Preserve historical evidence in existing records, PRs and Git history. Do not change code, tests, dependencies, CI, policy, installed environments or the primary dirty checkout.","completion_criteria":"The public guide is concise and user-oriented; Hermes references consistently describe the current integration without stale experimental/approval labels or run chronology; setup commands, links and actual support limits remain correct. Static checks, independent review and configured PR checks are evaluated, the update is pushed and normally merged, and the owning roadmap receives the contribution."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-hermes-agent-integration"}],"pull_requests":["https://github.com/rore/Pallium/pull/343"]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Intended paths are BLUE except integrations/hermes/README.md, which is GRAY; the public support statements require independent factual review across multiple entry points. No runtime contract changes.

**Discovery:** Started clean from merged main0e78151824bdb4297d802a5e4023de8672ed8f2d in a new managed checkout, branch feat/hermes-public-docs. Whole-change applicability denies exemption because the package/design guide paths are not allowlisted; build/hermes-docs-initial-applicability.json. Intended-path Redline is GRAY with no boundary violations; build/redline-verdict.json, reusing the accepted unchanged application import report. The 192-line public guide repeats qualification receipts before setup, package guide duplicates them, design file carries obsolete attempt chronology, and how-it-works still says actual UI qualification is open. Human acceptance and PR324 merge are complete; setup/memory/privacy/recovery limits remain real. Bundled skill has no obsolete experimental label and remains normative, so inspect without editing.

**Material assumptions:** Removing development labels and evidence chronology changes presentation only. If a source or acceptance record contradicts a proposed capability, preserve the concrete limit and narrow the wording; do not change implementation or invent readiness. Coordinate any overlapping documentation assignment with the manager before touching the same paths.

**Plan:** First invoke Agent Workflow, evaluate applicability and create/classify this record before documentation edits. Obtain clean nonimplementer plan review. Rewrite the main guide as capability/setup/support instructions, the package README as exact install/update/removal reference, and the qualification design as a concise current contributor procedure and coverage/limits reference. Remove duplicated chronology, SHAs, timings and obsolete approval/experimental prose from public entry points. Keep material user-facing boundaries and needed stable links. A cheap bounded worker may edit only seven entry-point Hermes references; parent owns three principal guides and this record. Reuse unchanged runtime/native proof; no host launches or broad diagnosis. Independently review the combined diff, run static docs/governance/selector checks, push a coherent PR, inspect actual CI and actionable threads, then normal merge under explicit user authority and hand off its receipt. Retire only the new docs worktree after preserving needed evidence; retain the older qualification worktree/VHDX.

**Verification plan:**
- Accurate setup and capability claims -> compare app/cli/setup_hermes.py, app/mcp/hermes.py and bundled skill; static audit checks three documented commands and the 12 Relay/3 History/11 optional memory catalogs.
- Concise current documentation and retained concrete limits -> inspect every public Hermes mention and the complete combined diff with a clean-context nonimplementer; scan for stale labels and chronology, check removed/retained scope and truthful evidence reuse.
- Working navigation -> reuse the untracked public-doc audit for all local links/anchors and inspect repository references to removed headings; git diff --check.
- Workflow and delivery -> whole-change Redline/applicability/record checks and test selector; evaluate the configured automatic PR lane once, then fresh actionable-review/head/main/protection checks before normal merge. No local application/native run is needed for unchanged runtime surfaces.

**Plan review:** Agent technical review: /root/hermes_docs_review, clean-context nonimplementer, GO at base0e78151824bdb4297d802a5e4023de8672ed8f2d. Reviewed exact record, applicability/policy, public/package guides and qualification introduction; accepted Elevated/GRAY scope and static validation. Preserve concrete limits and stable evidence pointers/anchors, never reinterpret failed CI as passing. No new runtime qualification is needed.

**Approvals:** User explicitly requested completion and merge without waiting; no additional human approval required for this Elevated documentation-only scope.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Agent Workflow invoked before documentation edits. Independent plan review accepted; proceed with the bounded prose rewrite. The manager received the exact new scope and asked its roadmap worker to avoid public-guide overlap. Canonical feature remains owner-managed; this task delivers a documentation contribution, not new integration qualification.

Implementation complete: parent rewrote the three main guides, while the existing cheap worker /root/hermes_blocker_fix_plan edited exactly the seven public entry points; parent reviewed its complete diff. The main guide now has 85 lines rather than192, setup uses normal explicit-profile examples instead of test-provider fixtures, and the contributor reference replaces attempt chronology with current coverage, boundaries and reproducible observations. Hermes is listed alongside other integrations without extending their fallback guarantees to it. Actual private scope, memory default/reset, capture omissions, SDK/ownership/concurrency limits, middleware placement, platform/provider gaps and shared availability remain documented. Unrelated derived-memory and Codex-plugin labels are preserved. Bundled skill/reference guidance was inspected and needs no instruction change. Historical acceptance and failed evidence remain in the original records, PR324 and Git history.

Edit fallback: apply_patch rejected a combined delete/add replacement because it targeted the same file twice; no changes were applied by that attempt. A deterministic Python replacement was then limited to exactly docs/hermes-integration.md, integrations/hermes/README.md and docs/designs/hermes-native-qualification.md. All other edits used apply_patch. No environment or application changes.

## Evidence

Initial applicability and Redline reports are retained in build/. Existing runtime/native results and failed CI remain available through merged PR324 and its original two Work Records; this task does not rerun, reclassify or erase them.

Static public audit build/hermes-public-docs-audit.json passed11documents/97local links and anchors/3documented CLI commands with0errors; actual CLI flags matched app/cli/setup_hermes.py, catalog matched12Relay/3History/11optional-memory tools. git diff --check passed. Whole-change selector build/hermes-docs-test-plan.json selects full because some Markdown paths are unrecognized, not a docs lane. The normal automatic PR CI will run that lane once; no local application/native rerun or workflow change. Hosted outcome remains to be evaluated before normal merge.

Independent review found two prose errors, both fixed and accepted without broader re-review: distinguish early claim from complete-context-gated ACK, and retain the native new-session confirmation-overlay coverage boundary. Source checks used the actual plugin and native test setting; no runtime or test edit was needed. Clean result GO received from /root/hermes_docs_review. Latest main8a1eb24c adds only the owning Hermes roadmap item/record since base0e, with no public-guide or application overlap. Canonical source remains owner-managed. Trigger2 dropped: prose/coverage wording belongs to this consumer documentation, not Agent Workflow upstream.

Publication: draft PR343 was created from the planning-record checkpoint so its actual returned URL can be stored before the single coherent public-doc push. This avoids a second full application CI loop for a later relationship-only edit; the planning-only checkpoint selects governance. The reviewed ten-document change and this returned relationship are published together next. Fresh hosted outcomes and merge receipt will be recorded on the existing PR result surface, without status-only full-CI commits. No primary-checkout sync or installed rollout.

## Result review

Agent technical review: /root/hermes_docs_review, clean-context nonimplementer, final GO for the corrected documentation-only result.

Reviewed revision: ten public-document working-tree changes and this Work Record against main0e78151824bdb4297d802a5e4023de8672ed8f2d; the reviewer confirmed both precise follow-up corrections and no remaining finding.

Verification adequacy: independent complete-diff/source spot checks and the static audit11documents97links3commands0errors cover setup/defaults, private identity, tool catalogs, ownership, capture, middleware and concrete provider/platform/recovery limits. Failed evidence stays in unchanged records/PR/Git history. Elevated/GRAY is appropriate; no runtime/native test is needed for unchanged behavior. Clear final governance and evaluate the selector-required automatic hosted lane once before fresh head/main/protection/actionable-thread checks and the explicitly authorized normal merge. No additional human approval or installed rollout is required or inferred.
