# Continue an ACKed OpenCode wake before its admission report

<!-- agent-workflow:start -->
**Outcome:** An ongoing OpenCode wake can run its next tool when a fresh context response restores the exact locally ACKed claim before native admission is reported.

**Target:** OpenCode V2 wake context hook.

**Scope:** V2 plugin, its Node tests, the existing real-HTTP context journey, and this Work Record.

**Constraints:** No new request or write, replay, cached payload, fabricated admission, or weaker first-restore, outage or enrollment authority. No live fault or host changes.

**Completion criteria:** The same input can run a second tool before admission is reported, with one prompt and ACK, then report normal admission. Pending admission alone, lost ACK, malformed or changed authority, and outage responses cannot authorize the exception.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"An ongoing OpenCode wake can run its next tool when a fresh context response restores the exact locally ACKed claim before native admission is reported.","scope":"V2 plugin, its Node tests, the existing real-HTTP context journey, and this Work Record.","constraints":"No new request or write, replay, cached payload, fabricated admission, or weaker first-restore, outage or enrollment authority. No live fault or host changes.","completion_criteria":"The same input can run a second tool before admission is reported, with one prompt and ACK, then report normal admission. Pending admission alone, lost ACK, malformed or changed authority, and outage responses cannot authorize the exception."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** The unclassified plugin source has an exact-context authority gate; normal first-restore and outage authority stay unchanged.

**Discovery:** On `24fe8d64` a held native prompt return allowed one real HTTP claim, ACK and first tool. After that, a response restored the same attempt with `admitted: false`, and the guard blocked the second tool. The live screenshot matched the guard, but its response fields were not retained.

**Material assumptions:** The marked input is current throughout the callback. Exact backend restoration and a confirmed local ACK are required independently. A lost ACK response does not qualify.

**Plan:** Retain a locally confirmed exact ACK even while native admission is pending, using the existing scoped wake confirmation. Allow a fresh nonterminal restore with literal `admitted: false` only on a healthy callback for that same lifetime, owner, session, endpoint, scope, location, input, generation, delivery and attempt. Never create, refresh or downgrade proof from this exception. Keep strict admitted authority everywhere else.

**Verification plan:**
Second tool and later admission → existing real-HTTP journey with a held native prompt return.
Changed authority, no reliable local ACK, admission regression and 503 → Node controls.
Unchanged behavior → focused outage and bootstrap cases, then whole-change selector.

**Plan review:** Agent technical review: independent reviewer approved the narrow successful-response exception with distinct local ACK provenance, no admission downgrade, and unchanged first-restore and outage gates.

**Approvals:** Not required for Elevated risk.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Only `integrations/opencode/.opencode/plugins/pallium-v2.mjs`,
`integrations/opencode/tests/v2-plugin.test.mjs`, and
`tests/test_opencode_native_wake_e2e.py` are in scope. The isolated
characterization failed at the exact second-tool assertion in 8.11 seconds.

## Verification

The final focused real-HTTP case passed in 4.93 seconds: the second
tool ran while prompt return was held, with one prompt and one ACK of
attempt one. Releasing the prompt produced one normal admission and
terminal report. The first patched run reached the second tool but
failed the fixture's step allowlist; the fixture was corrected.
Two outage cases and the bootstrapped reload case passed on that run.
All 11 new Node controls passed across two bounded selections. The
first selection stopped at its shell timeout after nine passing cases;
the targeted remaining two passed. Preserve the incomplete run.

The independent reviewer requested a stronger confirmation guard.
Only ordinary wake rotation may clear the prior proof. A callback
cannot replace it with a different identity or attempt, or downgrade
admission. The corrected real-HTTP case passed again in 9.12 seconds.

## Result review

Agent technical review: independent reviewer accepted the corrected guard.
Reviewed revision: reviewed working diff against `24fe8d64` with the rotation-only confirmation rule.
Verification adequacy: the exact real-HTTP case passed again, with no ACK or prompt replay. The broader run started before the last guard correction and does not qualify that correction by itself.

On the corrected diff, all eleven focused Node cases passed, as did
seventeen existing first-restore controls before the outer shell
deadline. Preserve that incomplete run; do not count the unread cases
as passed. Import boundaries, Redline and the local Workflow check
passed.

The selected non-slow Windows run stopped after 3,592 passes. The
Hermes bridge subprocess lacked `pydantic` in its isolated environment,
and a Claude lifecycle fixture failed creating an intent temp file.
Neither exercises the OpenCode context hook. Preserve the two failures;
do not rerun for a green result. Publication will still require hosted
verification and the exact corrected head.
