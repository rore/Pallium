# Preserve exact OpenCode continuation when admission catches up with ACK

<!-- agent-workflow:start -->
**Outcome:** A wake ACKed locally before admission can survive a transient context lookup failure after the same wake is confirmed admitted.
**Target:** OpenCode V2's exact wake continuation on main `5d33ed57`.
**Scope:** The continuation predicate in `integrations/opencode/.opencode/plugins/pallium-v2.mjs` and the existing JavaScript and native OpenCode continuation cases.
**Constraints:** Preserve exact input, owner, endpoint, scope generation, delivery, attempt, terminal, response validation and the original deadline. No new retry categories, second ACK, replay, live probe or installed change.
**Completion criteria:** Reproduce the refusal after local ACK and later exact admission. A typed transient failure then permits only the existing exact lookup and restore; mismatched, unconfirmed or still-unadmitted wakes remain refused. Real caller verification shows same-input tool progress, a single ACK, and successful idle.
**Requirement baseline:**
{"source":"Pallium OpenCode reliability roadmap","outcome":"A wake ACKed locally before admission can survive a transient context lookup failure after the same wake is confirmed admitted.","scope":"The continuation predicate in `integrations/opencode/.opencode/plugins/pallium-v2.mjs` and the existing JavaScript and native OpenCode continuation cases.","constraints":"Preserve exact input, owner, endpoint, scope generation, delivery, attempt, terminal, response validation and the original deadline. No new retry categories, second ACK, replay, live probe or installed change.","completion_criteria":"Reproduce the refusal after local ACK and later exact admission. A typed transient failure then permits only the existing exact lookup and restore; mismatched, unconfirmed or still-unadmitted wakes remain refused. Real caller verification shows same-input tool progress, a single ACK, and successful idle."}
**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:fix-opencode-plugin-reliability"}],"pull_requests":[]}
**Risk:** Elevated
**Complexity:** Moderate
**Reason:** Changes one plugin custody predicate; verification crosses the native provider and durable Relay boundary.
**Discovery:** The reported native turn ran two tools after one relay ACK, then reached idle with outcome failed. Its original HTTP classification is not retained. The current source can keep a pre-admission confirmation after an exact validated poll advances `item.wake.admitted`; its outage predicate then ignores the newer admission. The current fixture can model both halves with the same session and delivery.
**Material assumptions:** Only the locally confirmed ACK plus the same validated admitted wake supplies the missing proof. A normal restore must still return the identical delivered attempt. The failure mode is independently testable but not presumed to be the historical cause.
**Plan:** Agent Workflow invoked before code edits. Reuse the current exact-input fixture to capture a local ACK before admission, advance admission by the existing poll, then inject one typed transient response and a valid restore. Preserve the existing refusal for an ACK with no admission and the stale-owner and malformed-response controls. After independent review, consider only using the already validated admission bit for the matching local ACK in `continuationProof`; no new state/store or retry behavior. Reuse the existing native isolated test for caller-level verification.
**Verification plan:**
- Exact matching ACK and later admission → currently fails on first typed transient reply; fix should restore the identical attempt, attach the payload, not ACK again, and send no new input.
- Refusals → retain still-unadmitted, lost/no local ACK, malformed/wrong-attempt and terminal controls.
- Native caller → only the original input exists, the next tool completes with correct provider context, one ACK is stored, and the turn returns idle successfully.
- Whole change → the repository selector requires the full non-slow suite once; run normal hosted CI after the focused result and independent source review.
**Plan review:** Agent technical review: independent architect GO on `5d33ed57`. Keep matchingConfirmation mandatory; combine only an exact local ACK recorded with admission false and the same validated live admitted snapshot. Retain original restore, attempt, ownership, expiry and one-time registration guards.
**Approvals:** Not required at this risk level; the fix is in the approved reliability queue.
**State:** Ready for review
<!-- agent-workflow:end -->

## Reproduction

The unchanged current plugin failed the isolated exact-input fixture
with the screenshot's error. The fixture first confirmed one ACK with
admission false, then applied an exact admitted poll and returned a
typed retryable 503 to the next context lookup. It failed at the
existing continuation predicate before another context request. This
establishes a reproducible failure mode, not the unretained live HTTP
result. A disposable copy is checking the proposed predicate against
the reproduction and existing refusal controls while plan review is
pending. That comparison passed the reproducer and 32 existing
controls. The independent plan review then approved the exact two-proof
predicate. Implement and qualify it in the task checkout.

## Implementation

The existing continuation gate now combines an exact local early ACK
with the current matching admitted snapshot. All later restore checks
are unchanged. Three focused cases verify recovery, lost ACK-response
refusal and wrong-attempt refusal; they and the eleven pre-admission
controls passed. The real HTTP test holds native promotion until the
original ACK, then drives real admission, an exact poll and transient
context failures, followed by tool progress and successful idle
settlement. Its first command omitted the slow marker and deselected
all five nodes. The corrected run passed all five in 40.34 seconds.
This drives the production plugin and real HTTP/storage with controlled
native ownership and tool/idle events. It does not qualify the live host
or identify the original HTTP error. Exact source/result review is
complete; the whole-change selector requires the full non-slow lane,
which is running on the exact candidate.

## Result review

Agent technical review: The independent architect returned GO for
whole-change CI after directly inspecting the implementation. The
initial request was ACKed but its brief was missing from the reviewer's
context. A direct native follow-up in the same reviewer session produced
the verdict and ended with successful idle.

Reviewed revision: `5d33ed57` plus plugin `6c429604`, JavaScript test
`e95297e1`, and real HTTP caller test `0ae8fa84a`.

Verification adequacy: The review confirmed the same-wake binding,
exact delivered attempt, original retry deadline and one-enrollment
limit. It accepted the 14 focused and five HTTP results without a
duplicate run. Independent installed-host verification is still open.
