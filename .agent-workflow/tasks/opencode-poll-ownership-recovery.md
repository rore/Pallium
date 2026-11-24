# Preserve OpenCode polling after a failed native ownership lookup

<!-- agent-workflow:start -->
**Outcome:**
An enrolled OpenCode session resumes automatic pickup after a transient native session lookup failure without a human prompt.

**Target:**
OpenCode V2 poll ownership check.

**Scope:**
The poll's first ownership check, its shared boolean-style lookup helper, and the existing Node and real-HTTP caller tests.

**Constraints:**
Do not poll the backend or claim while native ownership is unknown. Preserve detachment for a confirmed different location and all scope, generation, and lifecycle checks. Do not change timers, backend state, replay behavior, or live configuration.

**Completion criteria:**
A rejected native lookup does not detach the enrolled session. The next healthy timer tick uses the same owner and automatically picks up the exact pending delivery once. A verified foreign location or a concurrent retirement cannot poll or attach work.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"An enrolled OpenCode session resumes automatic pickup after a transient native session lookup failure without a human prompt.","scope":"The poll's first ownership check, its shared boolean-style lookup helper, and the existing Node and real-HTTP caller tests.","constraints":"Do not poll the backend or claim while native ownership is unknown. Preserve detachment for a confirmed different location and all scope, generation, and lifecycle checks. Do not change timers, backend state, replay behavior, or live configuration.","completion_criteria":"A rejected native lookup does not detach the enrolled session. The next healthy timer tick uses the same owner and automatically picks up the exact pending delivery once. A verified foreign location or a concurrent retirement cannot poll or attach work."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}

**Risk:**
Elevated

**Complexity:**
Simple

**Reason:**
The integration source is unclassified by Redline and changes one detachment decision. No persistence, custody, or authorization boundary changes.

**Discovery:**
The initial poll detaches on any false `owned` result, including a rejected native lookup. Detach retires the local entry; after nonempty startup discovery the timer does not rediscover it. Other callers only use the lookup result as a truth test. The field report confirms missed pickup but lacks evidence of the native lookup outcome.

**Material assumptions:**
The native lookup can fail transiently without moving the session. A rejected lookup is not proof of ownership or movement. If timer-only recovery does not reach the original delivery, stop rather than weakening a binding check.

**Plan:**
Return a distinct falsy result for a thrown ownership lookup. On the first poll check only, clear the old witness and defer the tick rather than detach on that result. Preserve all other false-result handling. Use the existing timer, not a new retry loop. Reproduce the original detachment and recover the same delivery through normal HTTP claim and ACK with a controlled native caller.

**Verification plan:**
Unknown lookup, foreign location and retirement → focused Node caller tests.
Same-owner recovery with one admission and ACK → real-HTTP caller journey.
Whole-change validation → selector, non-slow suite, and required PR checks.

**Plan review:**
Agent technical review: independent read-only review approved the plan.
Only a rejected lookup is unknown. Preserve existing handling of missing
or different locations and all lifetime checks. On rejection, clear only
the witness seen by that poll; issue no poll, enrollment, claim, or detach.

**Approvals:**
Not required at this risk level.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Only the V2 plugin, its Node caller tests, and
`tests/test_opencode_native_wake_e2e.py` are in scope. The focused Node
regression failed on the old detach behavior; the verified move and
retirement controls passed. The real-HTTP variant uses the existing
delayed-wake journey and injects a rejected lookup before later work.

## Verification

- Before the fix, the Node case observed detach and the real-HTTP case
  recorded a successful detach request followed by no automatic pickup.
- With the fix, six focused Node cases passed. Both real-HTTP variants
  passed, including exact same-owner admission and a single ACK of the
  original pending delivery on the next healthy tick. No human turn or
  backend request was used to recover unknown ownership.
- The first patched HTTP run reached delivery but failed an assertion
  that counted a legitimate enrollment from the preceding ordinary turn.
  The corrected assertion measures requests issued after the lookup
  boundary and before disposal. The first run remains failed.
- The whole-change selector chose the full lane. Local collection first
  stopped because MCP could not import `pywintypes` from the isolated
  dependency target. With that import fixed and verified, collection
  stopped on missing `pyte` in the same target. Both runs remain failed
  at collection. The hosted full lanes install the supported extras.
  No live fault or host reload was performed.

## Result review

Agent technical review: independent read-only reviewer approved the three-file patch.
Reviewed revision: base `312aca09`; plugin and test blobs `aed775060`, `ce3af8129`, and `79ebcb943`.
Verification adequacy: reviewed lifetime fences, move handling, and the same-owner HTTP recovery oracle. Both final HTTP runs passed. This is not evidence of the cause of a historical missed pickup.

## Publication handoff

Publication is limited to the three reviewed files and this Work Record.
The publisher verified all three reviewed Git blobs and the unchanged base.
The implementation handoff reports Import Linter clean, Redline GRAY with no
checkpoint, and the workflow checker clean using its generated verdict.
These checks are reused, not reported as new executions.

Hosted validation is pending. Merge requires the exact reviewed head, passing
applicable required checks, and no unresolved findings. A failed hosted lane,
material base change, or finding requiring product edits stops publication
before merge. The two failed local collection attempts remain failed.
No installed clone, host, service, live configuration, or other worktree changes
are part of this publication. Retain this worktree and its local evidence.

The related roadmap item is `add-wake-first-relay-delivery` at
`roadmap/features/add-wake-first-relay-delivery.md`. Its broader work remains
active. Roadmap reconciliation belongs to the assigning owner; it is pending
the publication result and is not included in this four-file change.
