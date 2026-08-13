# Task: roadmap external-implementation refinements

<!-- agent-workflow:start -->
**Outcome:** vNext roadmap items are sharpened with concrete design details, acceptance criteria, and one experiment/control requirement drawn from read-only inspection of an external reference implementation — without importing features, changing milestones/gates, or naming the external system.

**Target:** Pallium repository — `roadmap/` and `docs/` only (planning documentation).

**Scope:** Six existing roadmap items:
- roadmap/features/add-historical-lookup-funnel-telemetry.md (deterministic verified-incorporation signal via citation handles)
- roadmap/features/add-raw-historical-search-mode.md (source-only filter at candidate level before top-K; K-integrity)
- roadmap/features/add-source-context-expansion.md (bounded AND paginated read)
- roadmap/ideas/idea-cross-context-work-continuity.md (first experiment favors pointer+pull over eager synthesis)
- roadmap/ideas/idea-multi-vector-long-text-embedding.md (resolve open questions: structure-aware boundaries, small forward overlap, surface matching chunk text; keep priority low)
- roadmap/ideas/idea-raw-derived-hybrid-shadow-eval.md (RAW arm must be candidate-level source-only, no derived contamination)

**Constraints:** No production code. No guarded-path files (api/ app/ capabilities/ core/ providers/ redaction/ retrieval/ semantic/ storage/). Preserve existing milestones, priorities, and experiment gates. Do not name the external system or "inspired by" phrasing in any committed file. Prefer small edits to existing items over new items; create no new items.

**Completion criteria:** Six items edited with the changes above; board references still resolve; no new files; no milestone/priority/gate changes; external system unnamed in all edits.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Documentation-only planning edits; no guarded paths; reversible.

**Approach:** Apply the six pre-analyzed edits directly (evidence chains already established). Keep each edit tightly scoped to a clarification / acceptance-criterion / control-requirement.

**Verification:** Re-read each edited file for scope adherence; confirm board.md item ids all resolve to files; `git diff` limited to the six files.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Context established: research done via four read-only agents (external Rust reference impl + Pallium baseline). Evidence chains recorded in the session and summarized per edit below. No guarded paths in scope, so redline verdict is Routine by construction (docs-only).
- Implemented: six edits applied, each a clarification / acceptance-criterion / control-requirement on an existing item. No new items; no milestone/priority/gate changes.
  1. `add-historical-lookup-funnel-telemetry` — citation handle kept **only as an optional, separately-evaluated attribution signal**; explicitly not equated with verified incorporation and not required in the baseline Experiment 1 condition. Rung 1 restored to observational.
  2. `add-raw-historical-search-mode` — source-only eligibility restricted at candidate level before top-K/fusion so memory objects can't consume the budget; acceptance is **up to K** eligible source results (legitimately fewer is allowed). Inflated-pool mechanics removed.
  3. `add-source-context-expansion` — **bounded** expansion window kept as the P1 contract (governance property); generic pagination removed.
  4. `idea-cross-context-work-continuity` — pointer+pull framed as the **first mechanism to test**, with eager synthesis compared as a second mechanism (not declared inferior).
  5. `idea-multi-vector-long-text-embedding` — kept structure-aware boundaries, matching-chunk surfacing, parent dedup; overlap left as an **implementation/evaluation parameter** (not resolved to a fixed strategy). Priority left low.
  6. `idea-raw-derived-hybrid-shadow-eval` — RAW arm must be candidate-level source-only (control against derived contamination).
- Second review incorporated: weakened the citation-handle claim, dropped Atomic-specific inflated-pool/always-K mechanics, reverted expansion pagination to bounded, kept overlap as a parameter; kept the P2 pointer-first refinement and the RAW-arm control.

## Verification

- `git status --short`: diff limited to the six target files + this Work Record. Confirmed.
- External-system-name leak check (`grep -niE` over roadmap/ docs/ .agent-workflow/): no reference to the external system in any edited file; all "atomic" hits are the ordinary adjective in unrelated pre-existing files. Confirmed.
- Board references unchanged (no new files added to board; all ids still resolve).
- Scope/constraints honored: no production code, no guarded paths, milestones/priorities/gates preserved.
