# Integration documentation alignment

Task owner request: "Can you do another documentation pass and let's align all of the integrations together into a similar format. I don't see a reason why every one of them needs to be separate." Existing user authorization covers independent documentation completion and normal merge, with no installed rollout.

<!-- agent-workflow:start -->
**Outcome:** Claude Code, Codex, OpenCode and Hermes are presented together with comparable delivery information and a consistent integration-guide structure.

**Target:** Pallium public integration documentation.

**Scope:** README.md; docs/README.md, getting-started.md, agent-relay.md, how-it-works.md, claude-code-integration.md, codex-integration.md and hermes-integration.md; integrations/opencode/README.md and integrations/hermes/README.md; this Work Record. Existing roadmap ownership stays with the manager. Inspect runtime/setup source and accepted records only to verify individual claims.

**Constraints:** Documentation only. Preserve each host's actual setup, trust, scope/privacy, memory defaults, capture, wake, fallback, recovery and platform/version limits; a shared table does not create shared guarantees. Do not change runtime, tests, skills, dependencies, CI, policy, primary checkout or installed environments. Retain useful details and existing link targets; no new qualification, unrelated feature promotion or historical evidence deletion.

**Completion criteria:** All four primary guides use the same readable top-level structure; shared overview/setup/delivery tables include all four integrations without a separate Hermes exception paragraph. Host differences are expressed in the appropriate rows and sections, commands and links remain correct, and old useful reference anchors remain accessible. Static checks, independent review and configured hosted checks are evaluated; the documentation is pushed and normally merged, with exact delivery and safe worktree cleanup reported.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Claude Code, Codex, OpenCode and Hermes are presented together with comparable delivery information and a consistent integration-guide structure.","scope":"README.md; docs/README.md, getting-started.md, agent-relay.md, how-it-works.md, claude-code-integration.md, codex-integration.md and hermes-integration.md; integrations/opencode/README.md and integrations/hermes/README.md; this Work Record. Existing roadmap ownership stays with the manager. Inspect runtime/setup source and accepted records only to verify individual claims.","constraints":"Documentation only. Preserve each host's actual setup, trust, scope/privacy, memory defaults, capture, wake, fallback, recovery and platform/version limits; a shared table does not create shared guarantees. Do not change runtime, tests, skills, dependencies, CI, policy, primary checkout or installed environments. Retain useful details and existing link targets; no new qualification, unrelated feature promotion or historical evidence deletion.","completion_criteria":"All four primary guides use the same readable top-level structure; shared overview/setup/delivery tables include all four integrations without a separate Hermes exception paragraph. Host differences are expressed in the appropriate rows and sections, commands and links remain correct, and old useful reference anchors remain accessible. Static checks, independent review and configured hosted checks are evaluated; the documentation is pushed and normally merged, with exact delivery and safe worktree cleanup reported."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-hermes-agent-integration"}],"pull_requests":["https://github.com/rore/Pallium/pull/346"]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** The two package READMEs are GRAY and other intended paths BLUE; independent review must prevent a uniform layout from overstating wake/fallback or removal guarantees. No runtime contract changes.

**Discovery:** Clean new managed checkout at current main642b17160b4587a6308974bbc2f9008ba12ebebc, branch feat/integration-docs-alignment. Whole-change exemption denied for unapproved paths and risk; initial reports in build/integration-docs-applicability.json and build/redline-verdict.json. Claude/Codex use similar older layouts, OpenCode a different package-first layout, and Hermes a separate abbreviated format. The Relay table omits Hermes and also lags per-host guides describing Windows Codex retained wake and opt-in OpenCode V2. OpenCode has no setup CLI; Hermes needs an explicit profile/two SDK environments; Claude/Codex uninstall also clears managed hook state. Preserve these differences. Prior runtime evidence remains unchanged and out of this formatting task.

**Material assumptions:** Comparable structure is a presentation change, not identical guarantees or one giant guide. If current source or accepted qualification contradicts a summary, retain the narrower supported statement and identify the uncertainty; do not modify runtime or rerun qualification. If another owner changes these docs, coordinate and reuse its exact contribution before editing overlap.

**Plan:** Invoke Agent Workflow, evaluate applicability and write/classify this record before documentation edits; obtain independent plan review. Standardize the four primary guides on Capabilities, Prerequisites, Setup, Verify the connection, Delivery and recovery, History and memory, Update and removal, Compatibility and troubleshooting, and Reference. Reuse existing advanced content under Reference and stable old anchors, rather than inventing a second reference or merging everything into one large page. Present all four integrations together in the existing documentation index, getting-started setup table and Relay delivery table; remove exclusion-style prose and link to per-host details. A cheap bounded worker may restructure only Claude/Codex guides; parent owns the other docs and record. Verify command/capability facts against source, audit links/anchors and common headings, review the combined result, publish one coherent docs revision with its actual PR relationship, evaluate configured CI and fresh merge rules/threads, then normal merge and retire only this task checkout after preserving evidence.

**Verification plan:**
- Comparable guides and complete shared tables -> static heading/table checks and independent complete-diff review for all four hosts; no separate Hermes exception prose.
- Accurate contracts and commands -> compare existing accepted guides and setup/plugin source, including Codex loaded/unloaded capability, OpenCode V1/V2, Hermes claim/ACK/profile/catalog and Claude trust/scope; parse CLI flags without executing setup.
- Working navigation -> audit all changed Markdown links, retained old anchors and inbound integration links; git diff --check.
- Safe delivery -> Redline and workflow checks on the whole change, run the configured selector lane once, classify actual unrelated inherited CI failures without relabeling them, inspect actionable reviews and actual main/protection before the authorized normal merge. No application/native tests beyond required configured checks for prose-only changes.

**Plan review:** Agent technical review: /root/integration_docs_review, clean-context nonimplementer, GO before guide edits. Common nine-section navigation and shared tables are sufficient; retain old anchors and visible host delivery/qualification limits. No blocking findings.

**Approvals:** Existing direct user authorization to complete and merge documentation without waiting applies; no extra human gate at Elevated risk. It does not authorize installed rollout or new runtime qualification.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Agent Workflow invoked before guide edits. Initial applicability/GRAY classification and independent plan GO recorded. This broader docs contribution follows the Hermes source request without taking over any other integration's runtime or roadmap. Manager informed of exact scope and no runtime overlap.

Implementation complete: ten public documents align all four integrations in the existing setup and delivery comparisons. Four primary guides and the Hermes package command reference use the same nine H2 sections. Advanced host details remain in their own guide with every original anchor retained. The shared Relay table now reflects the existing Codex Windows retained/unloaded path and opt-in OpenCode V2, with Hermes in its own ordinary row and narrower recovery/platform guarantees explicit. Manual OpenCode setup, Hermes explicit profile/SDK split/default-off tools, Codex hook trust, and source-observed shared hook-state removal are documented accurately. No runtime, installed state, historical records or qualification evidence changed.

The cheap bounded worker changed only Claude/Codex guides; parent reviewed its whole diff and owns the remaining eight documents. apply_patch handled ordinary edits; deterministic named-file reassembly reorganized only the two package READMEs. No dependency installation or host test occurred. Draft PR346 was created from a planning-only checkpoint so its actual returned relationship can accompany the coherent documentation revision without a second full CI loop just for linkage.

## Evidence

Initial intended-path reports are in build/. Existing application boundary report is reused only because this task changes no application/import policy; final changed-path reporter and configured hosted checks remain required.

Static audit build/integration-docs-audit.json passed14 documents,130 local links/anchors,3 Hermes setup/status/removal code blocks and actual CLI flags/catalog12 Relay/3 History/11 optional-memory tools, with0errors. It also verifies the exact nine-section sequence, all previous anchors, four-host shared table rows and Claude/Codex setup flags against AST source. git diff --check passed. The whole-change selector chooses full because package Markdown paths are unrecognized; normal automatic PR CI will run once on the coherent revision. No manual application/native rerun or selector/workflow change. Fresh hosted results and authorized merge receipt belong on the existing PR result surface.

Final independent complete-diff/source review GO received. The reviewer initially queried removal of an OpenCode historical sentence, then withdrew it after checking the user's explicit public-doc history cleanup direction and the retained current qualification boundary; underlying historical records and evidence remain unchanged. Final governance checks and actual hosted results are evaluated before normal merge. Owner-managed roadmap handoff follows verified delivery; no runtime feature completion is inferred from this docs contribution.

## Result review

Agent technical review: /root/integration_docs_review, clean-context nonimplementer, complete-result GO with no unresolved findings.

Reviewed revision: ten-document working-tree diff against642b17160b4587a6308974bbc2f9008ba12ebebc plus this Work Record; only concrete publication/evidence bookkeeping follows the reviewed prose. Exact committed head and hosted outcomes will be retained on PR346.

Verification adequacy: static checks14documents/130links/3Hermescommands/0errors cover consistent structure, all previous anchors, complete shared tables and source-valid commands/catalog. Independent source spot checks cover setup transports, Codex authenticated Windows retained wake and hook trust, OpenCode V1/V2/manual loading, Hermes SDK/private scope/defaults/ACK/recovery/platform limits, and shared hook-state removal. Runtime/native behavior is unchanged; existing qualification is reused without extending claims. GRAY/Elevated remains appropriate. Evaluate the configured automatic full hosted lane once, keep any inherited shared failures truthful and apply the user's existing scoped-release proceed policy only after independent impact review; no protected check/assertion/rule bypass and no new human or live-rollout gate.
