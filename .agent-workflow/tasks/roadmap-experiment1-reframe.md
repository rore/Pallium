# roadmap-experiment1-reframe

Refine the P1 roadmap per three converging external reviews: reorder to the critical path
(measurement integrity → calibrated reuse signal → real-corpus value/cost experiment → product
decision), consolidate the two overlapping real-corpus tickets into one product-decision gate, reframe
the Experiment-1 headline (agent-filtered pull net value, not unprompted-pull rate), and correct two
framings for Pallium's trusted-local (no-auth) model. Docs-only.

<!-- agent-workflow:start -->
**Outcome:**
P1 reads as the reviewers' critical path; the pull experiment is one consolidated product-decision gate;
scope.md + tickets frame the headline as net value of agent-filtered pull; attribution is explicitly
telemetry-not-authz; the violation metric claims enforceable policy filtering, not authenticated privacy.

**Target:**
`roadmap/board.md`, `roadmap/scope.md`, and ticket files: idea-pull-real-corpus-validation (survivor),
idea-measure-pull-filtering-accuracy-and-cost + idea-reconcile-unprompted-pull-direction-signal
(superseded), fix-lookup-and-expansion-active-attribution, idea-visibility-violation-metric-completeness,
fix-vector-source-only-starvation, idea-raw-duplicate-ingestion-and-result-diversity. No code.

**Scope:**
- board.md: reorder P1 to the target chain; drop the two superseded tickets from P1.
- scope.md: reframe the Phase-1 / Experiment-1 gate to the net-value headline.
- Consolidate: retitle idea-pull-real-corpus-validation as the decision gate + banner; supersede the
  other two (status: superseded, pointer to survivor).
- Attribution ticket: add "telemetry identity, NOT authorization; no actor-auth machinery" scope note;
  strip authz-flavored DoD rows.
- Visibility-metric ticket: soften to enforceable-policy-filtering; drop actor-to-actor privacy class;
  priority → low.
- Vector-starvation + duplicate tickets: add sequencing/gate notes (support the experiment; measure
  prevalence first).

**Constraints:**
- Roadmap markdown only. Board lines: headers or `- item` only. No internal/product names.
- Do not re-introduce the reverted pseudo-authorization framing (#42); keep trusted-local.

**Completion criteria:**
Board renders; P1 in target order; superseded tickets off P1 with status=superseded; scope.md headline
reframed; attribution + violation-metric framings corrected; CI (agent-workflow + redline) green.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Docs-only roadmap edits; no guarded paths → (Routine, Simple).

**Approach:**
Edit board/scope/tickets on a branch per three converging reviews; PR; merge when green.

**Verification:**
Minimap board renders; `gh pr checks` agent-workflow + redline green.

**State:** Ready for review
<!-- agent-workflow:end -->
