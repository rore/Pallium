<!-- agent-workflow:start -->
**Outcome:** Pallium's always-loaded installed guidance is smaller and non-duplicative while fresh agents still discover and correctly use Relay, Session History, optional derived memory, and optional work associations across supported runtimes.

**Target:** Pallium generated global/project instructions, packaged `pallium-memory` skills and references, tool descriptions, hook injection, installers, and their focused behavioral contracts.

**Scope:** Change only `integrations/claude-code/claude_md_block.py`, `integrations/codex/AGENTS.md`, `integrations/opencode/AGENTS.md`, `tests/test_guidance_budget.py`, `tests/test_codex_integration.py`, `tests/test_claude_code_integration.py`, this Work Record, and the canonical roadmap board/item. Reuse unchanged installers, hooks, MCP descriptions, packaged skills/references, and OpenCode packaging unless review or a failing focused contract proves a concrete gap. Do not touch Relay delivery reliability files owned by relaydev.

**Constraints:** Preserve exact identity/scope, privacy/provenance, hook-versus-receive ownership, stale and ACK-only handling, narrow-versus-broad History search choice, optional derived memory, optional work associations, runtime-specific fallback when skills are unavailable, and all unrelated user cost/style/session settings outside managed blocks. No install, restart, service, private-history replay, private-memory write, arbitrary token target, new framework, or duplicated registry. Do not hide critical safeguards behind an unreliable skill-load trigger.

**Completion criteria:** A reviewed directive inventory maps every essential rule from current location to retained location and discovery path; the same identified measurement method shows a smaller always-loaded payload; fresh-context bounded scenarios demonstrate correct earlier-work discovery, inter-session coordination, hook delivery, empty-wake recovery, missing-scope handling, optional memory/work refs, and irrelevant-task non-loading across honestly stated runtime coverage; generator/install/update regressions pass; roadmap and Work Record close only after independent result review.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Intended `integrations/**` generator/template paths are gray and the changed tests/roadmap/record are blue, so conservative Redline translation is Elevated. Moderate complexity covers three runtime integrations, generated arms, and behavioral validation. A required clean-context classifier attempt was blocked by Windows error 1327 plus approval-reviewer capacity; no boundary, API, schema, security, persistence, runtime-config, or red-zone path is intended.

**Discovery:** No existing branch or Work Record owns cross-capability always-loaded compaction. Related completed slices explain each rule and already provide byte-identical skills plus lazy work-association and field-feedback references. Actual emitted managed-block baselines measured with Python `len(text)` and `len(text.split())`: Claude base 3,521/452 and strong 3,937/513; Codex base 3,522/452 and strong 3,937/513; OpenCode 3,482/449. Current skills are separately on-demand and capped at 2,800 characters. The installed generator path is Claude `CLAUDE_MD_BLOCK/get_claude_md_block`, Codex static `AGENTS.md` through `_build_agents_md_block`, and OpenCode packaged `AGENTS.md`; existing installers replace only marker-bounded managed text and deploy the full skill tree. Hooks inject delivery/scope evidence dynamically and must not become the only home of normal-task safeguards. The exact canonical Minimap item reference is attached to this session as `work:v1:6ea00d2fb492c25b508f888fab87bd4bb081aec2ce6d307609d170c11b65062f`.

**Material assumptions:** Existing skills/references and MCP descriptions remain self-sufficient for operation-specific recipes after the global block is compacted. This is disproved by directive inventory, focused source tests, or a fresh-context run that misses a required action; then retain the missing directive always-visible and return to design. Codex/Claude can be exercised on this host; OpenCode runtime coverage is conditional on confirmed availability, otherwise only packaging/static behavior may be claimed. Any need to change installers, hooks, MCP runtime behavior, API, config, storage, or Relay reliability returns to planning and risk assessment.

**Plan:** 1. Invoke the `/agent-workflow` skill to create the Work Record and classify risk before any code edit (completed in `31629a6d`; intended scope remains Gray / Elevated / Moderate). 2. Preserve the directive inventory, emitted baseline, corrected candidate wording, and exact file scope below. 3. Obtain manager design re-approval from `@astra-reviewer` after resolving every finding. 4. Obtain the separately required clean-context Elevated review from an agent that reads only this Work Record, policy, and relevant sources/tests; resolve its findings before changing implementation files. 5. Replace only the three owning global block sources with the doubly reviewed compact text, leaving generators/installers/skills/references/hooks/tool descriptions untouched. 6. Update only focused semantic guidance assertions and run deterministic checks plus nine paired baseline/proposed fresh-context scenarios under the fixed cap below. 7. Obtain independent smart result review, run affected subsystem/workflow/CI checks, reconcile roadmap/record, resolve review threads, and merge.

**Verification plan:** Deterministic: measure all five actual base/strong/runtime outputs with Python `len(text)` and `len(text.split())`; assert cross-runtime safeguard parity including claim/ACK/reply `already_delivered` or conflict versus non-stale trace `delivered`, operation recipes remain in skills/tool descriptions/references, the strong-arm delta and deprecated alias remain unchanged, marker-bounded fresh install/update preserves unrelated user text, and OpenCode still packages/registers its skill and AGENTS block. Behavior: run each of the same nine fixtures once against baseline guidance and once against proposed guidance, for 18 total runs—not 18 per runtime—with the same cheapest-capable model, prompt, safe stubs, normally exposed skill catalog, and tool metadata; do not preload the full skill or tell the model to use Pallium. The approved allocation was Codex cases 1, 3, 4, 6, and 7 (10 runs) and Claude cases 2, 5, 8, and 9 (8 runs). Native Claude initialized the isolated fixture and discovered the project skill but failed authentication before any model turn (zero model tokens and $0), so that attempt is preserved as invalid/unexecuted and is not retried. Under the user's standing approval, the four unavailable Claude pairs are reassigned to the same isolated Codex `gpt-5.6-luna` low fixture. All nine scenario pairs are therefore reported as single-runtime Codex evidence only; no Claude, OpenCode, or cross-runtime model-behavior claim is permitted. OpenCode receives deterministic static/package coverage only. Cap each run at four assistant/tool cycles and six tool calls; a cap/cost stop is a measured failure, not grounds to extend the run. Record whether the skill was loaded when relevant and absent on the irrelevant case. Oracles: (1) injected exact work ref on resume → exact-work search; (2) resume without work ref → broad search; (3) hook delivery → process payload, no receive/raw-HTTP ACK, and reply only after completion/blocker; (4) exact empty wake → trace only, no receive/resend, and never treat trace `delivered` as stale; (5) missing scope → skip only the scoped operation without guessing and continue ordinary work; (6) inter-session coordination → targeted send using a known current `@name`, or discovery when unknown, with queued/wake evidence not treated as receipt or fallback trigger; (7) existing exact provider work association → reuse it without duplicate attachment; (8) explicit durable-memory request → private exact-provenance new write while correction/forget retain existing provenance; (9) irrelevant task → no Pallium skill load or call. Report paired outcomes and failure reasons separately from textual review; one pair per scenario is smoke/regression evidence, not statistical proof or proof of perfect behavior.

**Plan review:** Full-history manager design review `relay-reply-a951944b7e3542919971e91899d0516a26a15bd5349a76e2586b5f6e25362c7e` approved direction, scope, and the corrected candidate while explicitly requiring the separate clean-context gate. Clean-context reviewer `/root/guidance_clean_context_review` resolved four blocking findings across serial passes and returned PASS on `4a5f6d9d`; no implementation edits or model evals were performed.

**Approvals:** User authorized architect-assigned work, PRs, immediate bug fixes, and standing approvals in this task; this does not waive the required Elevated design review.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-15: Accepted the architect's task offer at a safe boundary and created isolated branch `feat/optimize-always-loaded-guidance` from clean `origin/main` at `0de8a89f`.
- 2026-09-15: Duplicate search found related completed guidance slices but no existing owner for full cross-capability always-loaded compaction.
- 2026-09-15: Clean-context pre-edit Redline delegation failed before reading policy because Windows sandbox error 1327 and approval-reviewer capacity blocked escalation. The primary session read the full policy and classified the provisional gray/blue scope conservatively as Elevated/Moderate; the failed delegation remains explicit evidence, not a successful clean-context verdict.
- 2026-09-15: Created canonical Minimap item `optimize-always-loaded-guidance`, derived its reference with Minimap's own CLI, listed existing session references, and attached only the exact returned pair.
- 2026-09-15: `apply_patch` failed once with Windows 1327 while adding the roadmap files; per local instructions, the edit used a deterministic replacement limited to `roadmap/board.md` and `roadmap/features/optimize-always-loaded-guidance.md`.
- 2026-09-15: Completed read-only rationale/source/test inspection and same-method baseline/candidate measurement. No guidance, generator, installer, hook, skill, tool-description, or test implementation file has been changed.
- 2026-09-15: Manager design review approved direction and file scope in principle, then returned the plan for five blocking corrections: distinguish hook processing from explicit stale-operation results; scope History actor/work-ref rules; pair baseline/proposed bounded scenarios with normal catalog metadata; retain clear triggers plus queued/empty-wake semantics; and correct timing/review evidence. The plan and exact candidate were revised; implementation remains blocked.
- 2026-09-15: The manager then read and approved the exact `928bd316` candidate, requiring the separate clean-context gate before implementation.
- 2026-09-15: A high-reasoning clean-context read-only review found three additional blockers: correction/forget must retain provenance, raw HTTP ACK must remain prohibited, and 18 total runs must be allocated explicitly across runtimes. Those corrections are now in the plan. The review could not finish packaged-skill/test reads because automatic approval capacity rejected them, so it is not recorded as a pass.
- 2026-09-15: Clean-context re-review completed the packaged-skill/test reads and accepted those three corrections. It found one final blocker from the MCP ACK tool contract: explicit `already_delivered` from claim, ACK, or reply marks only that copy stale; a normal trace `delivered` does not. The four-character candidate correction and focused assertion are applied; final re-review remains pending.
- 2026-09-15: Final clean-context read-only review of `4a5f6d9d` passed with no findings, verified claim/ACK/reply stale evidence versus normal trace `delivered`, and found no control-character or prose corruption. The plan gate is closed and State moved to Ready to implement before any guidance source edit.
- 2026-09-15: Before implementation, merged verified `origin/main` commit `e53755a5` without conflict. Planned implementation files are `integrations/claude-code/claude_md_block.py`, `integrations/codex/AGENTS.md`, `integrations/opencode/AGENTS.md`, `tests/test_guidance_budget.py`, `tests/test_codex_integration.py`, and `tests/test_claude_code_integration.py`; no other source/test files are authorized without returning to planning.
- 2026-09-15: Replaced only the three guidance owners with the exact reviewed 2,687-character candidate and updated focused semantic/budget assertions. Deterministic verification passed: 76 focused tests, clean `git diff --check`, byte-equivalent owner content after newline normalization, and zero invalid control characters.
- 2026-09-15: The planned native Claude smoke initialized and discovered `pallium-memory` but failed authentication before a model turn (zero model tokens, $0). User standing approval authorizes reassigning cases 2, 5, 8, and 9 to the same isolated Codex Luna-low fixture; Claude remains invalid/unexecuted and no cross-runtime behavior claim will be made.
- 2026-09-15: After the original case-4 outputs were moved aside and replaced by a relabeled rerun, the first complete relabeled corpus scored baseline 9/9 and candidate 8/9. Reconstructing that arm with the original-prompt outputs gives baseline 8/9 and first candidate 7/9 (case 4 plus case 5). The error was excluding and replacing valid original case-4 failures, not grading those responses as passes. Candidate case 5 also selected a broad search while stating that missing `container_ref` blocked it; independent smart grading rejected that output. The candidate was revised and rerun.
- 2026-09-15: The second candidate arm used the relabeled case-4 prompt, fixed case 5, and measured 8/9 because case 9 loaded `pallium-memory` for pure arithmetic. The global closing rule now says that when no capability applies, answer normally without loading the skill. The second candidate transcripts remain archived; case 9 is rerun first before the rest of the final arm.
- 2026-09-15: The final Codex arm on the relabeled case-4 corpus measured 9/9 after both behavior-driven corrections. Independent smart result review closed PASS. Latest focused tests passed 76/76; the one-time full suite passed 5,018 with 34 skipped and 2 expected xfails in 253.56 seconds. Workflow check was clean.
- 2026-09-15: A delayed post-merge architect delivery exposed that the original case-4 fixture was valid: Relay trace accepts the supplied exact `relay-delivery-*` identifier as its `message_id` value. Original baseline and compact-candidate runs both failed to select trace; relabeling the identifier as `message_id=...` made both pass and incorrectly hid that failure. Follow-up task `fix-empty-wake-trace-id-guidance` added the explicit mapping and one fresh original-prompt candidate decision selected trace. The reconciled smoke comparison is baseline 8/9 versus corrected candidate 9/9.

## Evidence

- Task offer: Relay message `relay-msg-8845d20cfcb24926b7704ebcf63d7d9e`; trace delivered once with no gap/pruning.
- Manager design review: Relay replies `relay-reply-9c416d855fcf7aafc17ec7a1360e9861ddfa7aa4afaa58e85588df118928dc7e` and `relay-reply-a951944b7e3542919971e91899d0516a26a15bd5349a76e2586b5f6e25362c7e`; first body paged to `next_offset=null`, then exact `928bd316` candidate independently read and approved. Exact delivery traces showed no gap/pruning.
- Clean-context plan review: `/root/guidance_clean_context_review`, read-only high-reasoning serial review; packaged skills/references and targeted integration tests were read, four findings were resolved, and final `4a5f6d9d` review returned PASS with no edits or model evals.
- Independent implementation review: `/root/guidance_result_review` returned PASS on the six-file diff with no correctness, safety-parity, or scope findings; it caught and caused correction of terminal-newline measurement accounting. Its result gate stays open until paired behavior evidence is reconciled.
- Isolated base: `origin/main` / `0de8a89fc378e5aab693c9335050f67e0b498252`.
- Work Record first commit: `31629a6d`.
- Canonical item pair: `scope_ref=roadmap:v1:git:github.com/rore/pallium#roadmap`, `local_ref=item:v1:optimize-always-loaded-guidance`; attached exact key `work:v1:6ea00d2fb492c25b508f888fab87bd4bb081aec2ce6d307609d170c11b65062f`.
- History rationale: `9006b85c` (cross-runtime Relay), `1a6e8bf5`/`7fffb346` (exact-vs-broad History), `812490bb`/`097076b5` (current-turn/stale deliveries), `e22dd7d6`/`3e939121` (actor-free Relay/History filter), `a0bccd5a` (lease/ACK), `c59b31c2`/`f22a3d7c` (work associations/fallback), `630130a1` (lazy field-feedback reference).

## Directive inventory

| Essential directive | Current location | Proposed retained location | Discovery/load path |
|---|---|---|---|
| Relay, History, optional derived-memory capability map | global block + skill | compact global trigger; skill detail | always visible, then skill when relevant |
| exact injected identity/scope; never infer; fail closed | global block + tool descriptions | compact global safeguard; argument detail in tools | always visible |
| canonical recipient/global name; no broadcast/bare runtime; takeover consent | global block + Relay tools | compact global safeguard; call syntax in tools/skill | always visible, then relevant tool |
| hook delivery owns claim/ACK; no receive race/raw HTTP ACK | global block + skill/tools/hooks | compact global safeguard; receipt/lease procedure in skill/tools | always visible; dynamic hook evidence stays dynamic |
| current-turn, stale-copy, ACK-only, no status-only semantics | global block + injected delivery | compact global safeguard; exact delivery evidence in hook | always visible plus delivery-local block |
| exact-work versus broad History; never guess | global block + skill/tools | compact global decision rule | always visible |
| request-source/expansion lineage and optional actor filter | global block + tool descriptions | compact global provenance rule; argument recipe in tools/skill | always visible, then relevant tool |
| derived memory privacy/provenance/access invariants | global block + skill/tools | compact global safeguard, including new-write exact provenance and correction/forget provenance retention; operation catalog in skill/tools | always visible, then skill when memory is relevant |
| work associations are optional and grant no access/ownership | skill + work-association reference | unchanged skill trigger/reference; one compact global fallback | skill only when exact work linkage is relevant |
| upstream field feedback | skill + field-feedback reference | unchanged lazy trigger/reference | skill only after concrete repeatable defect |

## Measured emitted split

Method: Unicode characters via Python `len(text)`; words via `len(text.split())`. Baselines and final follow-up-corrected values are observed generated outputs. The corrected block itself is 2,818 characters / 401 words; Codex and OpenCode files include one terminal newline, and generated Codex/Claude base blocks add the unchanged 40-character arm marker. The runtime-specific strong directives remain unchanged (Claude +416 characters/+61 words; Codex +415/+61).

| Output | Baseline chars/words | Candidate chars/words | Character reduction |
|---|---:|---:|---:|
| Claude base | 3,521 / 452 | 2,858 / 404 | 663 (18.8%) |
| Claude strong | 3,937 / 513 | 3,274 / 465 | 663 (16.8%) |
| Codex base | 3,522 / 452 | 2,859 / 404 | 663 (18.8%) |
| Codex strong | 3,937 / 513 | 3,274 / 465 | 663 (16.8%) |
| OpenCode | 3,482 / 449 | 2,819 / 401 | 663 (19.0%) |

## Proposed always-loaded block

```md
<!-- pallium:start -->
## Pallium

Pallium provides:

- **Relay:** coordinate independent agent sessions when another agent's work should change.
- **Session History:** resume earlier work from relevant prior sessions.
- **Derived memory:** optional compact context that may be injected or queried.

Load the `pallium-memory` skill when any applies. If the skill or tools are unavailable, continue ordinary work; never invent identity, scope, work references, or successful calls.

### Always-safe rules

- Copy injected `container_ref`, `thread_ref`, `actor_ref`, `agent_ref`, `request_source_item_id`, and `work_ref` exactly when an operation requires them. Never derive identity or scope from the working directory, recipient listings, or historical sources. If required scope is missing, skip that scoped call; never call it with guessed or absent values, and continue ordinary work.
- Process each hook-injected Relay payload as current-turn work. The hook owns claim and ACK, so never call receive for it. Complete it or report a genuine blocker; do not send status-only replies or reply to ACK-only deliveries. Never ACK through raw HTTP; use Relay tools. A trace state of `delivered` does not make its payload stale. Only an explicit `already_delivered` or conflict result from a claim/ACK/reply operation marks that copy stale; do not retry, reply to, or reuse that stale copy.
- Relay sends only to a canonical `relay-session-...` or global `@name`; broadcast and bare runtimes are unsupported. Ask before name takeover unless already authorized. Cross-container routing never changes History or memory scope. Queued or wake evidence is not receipt. For an exact empty-wake instruction, pass its supplied `relay-delivery-*` identifier as Relay trace's `message_id`; do not receive or resend.
- Picking up prior work? Search the injected exact `work_ref` when present; otherwise search broadly. Never guess a History search filter. Work associations use only exact provider-returned references.
- For History searches, pass injected `request_source_item_id` only there, expand a returned `source_item_id` with its `lookup_event_id` as `parent_lookup_id`, and omit `actor_ref` unless an exact metadata filter is requested.
- Retrieval alone never changes accessibility or ranking. Derived memory is optional and private by default; global writes require explicit intent. New memory writes copy exact injected provenance; correction and forget retain existing provenance. Work associations are optional, grant no access or ownership, and are skipped when exact provider identity or tools are unavailable. Do not ingest routine turns or re-query content already injected.

Use skill and tool descriptions for procedures. When no capability applies, answer normally without loading the skill.
<!-- pallium:end -->
```

## Friction observed

- This task offer was created at 07:43Z and the design packet was sent at 08:13Z on the same day. Earlier delayed wakes were different messages and are not evidence about this task.
- Work-reference listing initially failed because approval-reviewer capacity blocked the MCP call; later success allowed exact provider-derived attachment. No identity/reference was guessed.
- Two cheap clean-context agents and several read-only source/history checks were blocked by Windows 1327 plus approval-reviewer capacity. One separate cheap rationale pass succeeded; failed passes are not counted as review or coverage.
- The normal patch helper failed once with Windows 1327; the documented narrow deterministic fallback succeeded.

## Plan review

- `/root/guidance_clean_context_review` ran with no conversation context, read-only, against this Work Record, repository policies, the three current guidance owners, budget tests, and the changed-file list.
- Blocking findings: preserve correction/forget provenance, retain the raw-HTTP ACK prohibition promised by the directive inventory, and make the 18-run cross-runtime allocation unambiguous.
- All four findings were corrected across serial passes. Final clean-context review of `4a5f6d9d` returned PASS: claim/ACK/reply explicit stale results and normal trace `delivered` are distinguished, packaged procedures are sufficient and cross-runtime-identical, the 18-run allocation is coherent, and no scope/risk expansion or prose corruption remains.

## Result review

- Historical pre-follow-up review: independent high-reasoning reviewer `/root/guidance_result_review` found no correctness, safety-parity, or file-scope issue in the implementation. It rejected two measured candidate decisions before final approval: case 5 planned a search despite missing scope, and the next revision loaded the skill for irrelevant arithmetic. Both global rules were made explicit and every relabeled-corpus candidate case was rerun on that text. The reviewer returned PASS before the delayed case-4 audit exposed the evidence error.
- Reconciled decision-oracle results using the original case-4 prompt and the follow-up corrected candidate:

| Case | Baseline | Candidate |
|---|---|---|
| exact-work resume | pass | pass |
| broad resume without work ref | pass | pass |
| hook delivery | pass | pass |
| exact empty wake | fail | pass |
| missing required scope | pass | pass |
| inter-session coordination | pass | pass |
| existing work association | pass | pass |
| explicit durable memory | pass | pass |
| irrelevant task | pass | pass |

- Follow-up-corrected candidate owners match after newline/arm normalization at 2,818 characters / 401 words. Reconciled original-prompt totals are 414,613 baseline input / 5,449 output tokens and 327,164 candidate input / 4,269 output tokens across nine decisions. This combines unchanged preserved runs with the one affected candidate rerun and is not a causal cost estimate. Reviewer-counted observable tool attempts remain 10 baseline and 9 candidate, with maxima of 3 and 2; all stayed under the six-call cap. Both arms loaded the skill in relevant cases 1–8 and not in irrelevant case 9.
- Invalid evidence remains excluded and preserved separately: one rejected output schema, one repository-context-contaminated pilot, and one native Claude authentication failure before any model turn (zero model tokens, $0). Valid failure evidence is separate: the original case-4 pair, the first candidate at corrected 7/9, and the second relabeled-corpus candidate at 8/9. The original pair remains valid despite its legacy `invalid-fixture` filenames; the later relabeled pair is preserved as an easier non-primary setup.
- Limits: this is Codex-only decision-selection smoke, not statistical proof, reliable causal improvement evidence, or executed Pallium workflow coverage. The follow-up changed and reran only case 4 after the delayed audit; unaffected cases were reused. Pallium calls were prohibited and pointed at a closed local port; case-7 reference reads were blocked. Claude has no model-behavior result after authentication failure, and OpenCode has deterministic static/package coverage only.
- Final deterministic evidence: exact owner parity and zero invalid control characters; 76 focused guidance/integration tests passed in 9.65 seconds; `python -m pytest tests/ -x -q` passed 5,018 with 34 skipped and 2 xfailed in 253.56 seconds; `git diff --check` and `scripts/agent-workflow-check.py --repo-root . --slug optimize-always-loaded-guidance` passed.
