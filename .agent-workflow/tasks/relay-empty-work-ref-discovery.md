# Skip repository qualification when no structural refs exist

<!-- agent-workflow:start -->
**Outcome:** Empty structural discovery cannot invoke optional repository qualification before required Relay registration and delivery in either Python prompt hook.

**Target:** Claude Code and Codex UserPromptSubmit integration helpers.

**Scope:** integrations/claude-code/hooks/common.py, integrations/codex/hooks/common.py, tests/test_agent_relay_hooks.py, tests/test_hook_common_parity.py and this Work Record.

**Constraints:** Return the existing empty list for supported empty discovery inputs. Preserve deadlines, identity, nonempty qualification, validation, caller assertions and hook claim/emission/ACK behavior. No protocol, API, schema, dependency, protected-contract, configuration or installed-environment changes. No broader optional-budget redesign, historical attribution, full-run retry or parent recovery closure.

**Completion criteria:** Both helpers return [] for empty discovery without repository or roadmap lookup. Both actual prompt-hook callers preserve registration, cross-container send, emission and ACK under a deterministic optional lookup that would otherwise exhaust the unchanged deadline, with the lookup never invoked. Existing nonempty and identity/parity behavior passes. Independent technical plan/result review and required exact-candidate validation/CI pass before publication; the manager controls full-run sequencing. Nonempty starvation and historical probe/closed-intent failures remain explicitly open.

**Requirement baseline:**
{"source":"pallium-manager:2026-10-07:empty-structural-refs-ownership","outcome":"Empty structural discovery cannot invoke optional repository qualification before required Relay registration and delivery in either Python prompt hook.","scope":"integrations/claude-code/hooks/common.py, integrations/codex/hooks/common.py, tests/test_agent_relay_hooks.py, tests/test_hook_common_parity.py and this Work Record.","constraints":"Return the existing empty list for supported empty discovery inputs. Preserve deadlines, identity, nonempty qualification, validation, caller assertions and hook claim/emission/ACK behavior. No protocol, API, schema, dependency, protected-contract, configuration or installed-environment changes. No broader optional-budget redesign, historical attribution, full-run retry or parent recovery closure.","completion_criteria":"Both helpers return [] for empty discovery without repository or roadmap lookup. Both actual prompt-hook callers preserve registration, cross-container send, emission and ACK under a deterministic optional lookup that would otherwise exhaust the unchanged deadline, with the lookup never invoked. Existing nonempty and identity/parity behavior passes. Independent technical plan/result review and required exact-candidate validation/CI pass before publication; the manager controls full-run sequencing. Nonempty starvation and historical probe/closed-intent failures remain explicitly open."}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Both integration common.py paths are unclassified GRAY, so the policy requires an Elevated floor despite the small output-preserving change. Simple is one coherent two-copy guard with focused caller coverage; parent recovery remains High/Large and open.

**Discovery:** Exact caller map and deterministic susceptibility evidence are recorded below. Only the two prompt hooks call the helper; empty discovery currently triggers unnecessary Git qualification before required Relay. Pre-edit technical review found the original Routine classification invalid and required the GRAY floor and expanded shape. No implementation occurred at the rejected revision.

**Material assumptions:** Supported typed empty discovery already returns []; disproof is an accepted caller contract requiring repository/roadmap lookup or input validation side effects for empty refs, in which case stop and revise before edits. The reused caller journey retains its observable registration/send/emission/ACK assertions; if private-clock injection changes budgets or masks an error, stop and correct only the test mechanism. This fix does not solve nonempty optional starvation or explain historical failures; any contrary result claim must be rejected and recorded separately.

**Plan:** Invoke agent-workflow, establish immutable requirements and classify before production edits (completed; classification corrected before implementation). Reuse the clean managed diagnostics checkout on feat/relay-empty-work-ref-discovery from e9eb3956; prior diagnostic/fixture publication branches and ignored evidence remain preserved. Obtain independent technical review of this expanded record before edits. Add caller regression using the existing configured-actor hook/TestClient journey and unchanged lifecycle assertions; model slow repository qualification with a private logical clock, retaining budget 8 and reserve 1. Prove pre-fix missing registration. Add the minimal empty discovery guard before repository_scope_ref in both duplicated helpers, not at individual callers. Add parity controls forbidding repository/roadmap lookup for empty discovery, and reuse existing nonempty/identity coverage. Root owns record/evidence; a bounded cheap worker may implement the exact allowlist after approval. No new framework, real sleep, native transport replay, global environment change or independent broad suite.

**Verification plan:** Focus the new caller node and empty parity controls with python -m pytest <node> -q -n 0. Run the affected hook/parity/identity files after a coherent change, then the whole-change selector and fresh governance. Source/test changes require full non-slow and exact-head CI before completion, but the manager has explicitly held new full runs until combined candidate sequencing is settled. Focused passes, simulated transport or this deterministic susceptibility witness do not qualify installed recovery or explain previous failures. Preserve active claim and successful ACK behavior; never weaken protected assertions. Native mutation prevention is not claimed for these integration paths; no installation or evaluator outcome substitutes for a denied native operation.

**Plan review:** Agent technical review: /root/wake_output_plan_review (gpt-6.1-sol/high) approved corrected exact plan 81a5cdcbef1571963ce9f67296cf795cbf6eceb3 as Elevated/Simple. Case-sensitive comparison confirmed all immutable requirements and baseline fields unchanged. Direct supported-empty guard and proposed caller/parity coverage are technically sound; hook-private clock and original lifecycle assertions/budgets must remain. Review rejected 231a485ea9316c640bc6deda7de1139bda6a064a for its Routine/compact classification; no implementation followed it and it is not retroactively approved. This is plan approval, not result/full/CI or installed acceptance.

**Approvals:** Not required at this risk level. Manager authorized the exact narrow scope; parent High/Large acceptance and all live-environment approvals remain separate.

**Exceptions:** —

**State:** Implemented; independent result review, whole-change governance and manager-sequenced full validation/CI pending. Not accepted or installed.
<!-- agent-workflow:end -->

## Discovery and ownership

Manager assigned only these two common.py guards; pal-dev1 was informed that
shared pin cleanup remains separate. No shared identity or locking edits are
authorized in this slice. Source trace found only two production callers of
structural_work_refs_payload: Claude and Codex UserPromptSubmit, where Python
evaluates it before relay_turn. Each payload helper calls repository_scope_ref
even for empty discovery; that helper can run two Git subprocesses under the
shared deadline. Windows process creation precedes subprocess communication
timeout enforcement. SessionStart and Stop use Relay without this helper.

The association roadmap explicitly requires enrichment failure not to break
ordinary delivery. The structural-ref resolver itself remains file-based;
repository qualification for associations is a separate subprocess path.
Its optional-before-required budget dependency is not an installed reliability
claim and must not be hidden by marking the parent complete. No roadmap feature
status change is made; the manager owns combined acceptance and residual work.

At exact clean combined candidate 0589470e2389dd8b38c0dfb6d39baa0c4fe40b40,
the unchanged configured-actor two-runtime E2E test passed without faults in
14.60 seconds. All three TestClient turn requests per runtime were observed;
each intent and confirmed-state write succeeded. A ten-second per-test stack
sample found Git CreateProcess during the third Claude turn; it does not prove
a ten-second spawn delay or a historical cause.

One authorized deterministic reproduction advanced only a private logical
clock by 7.01 seconds after actual optional repository lookup returned, keeping
the original eight-second budget and one-second reserve. Both discoveries were
empty; nevertheless both lookups ran. Each subsequent Relay lock acquisition
returned None, with no intent write or HTTP request. Both unchanged registration
assertions failed in 18.25 seconds. This proves susceptibility, not attribution
to the earlier full-suite failures or installed outages.

Evidence remains in the separate relay-recovery-closure checkout under ignored
build/: relay-optional-discovery-manifest.json, reproduction log SHA256
30D3D3C127885B6FF7BF56EC04D6AD71FF09360B15F77AA07F72AF1C30E278C5,
fault plugin A896FB5813A49C3E6CD9F904CD3DADD94AF84947AA693B02EB690E8F4C75A6B0,
and separate stages 9DF52367B21550A6E83DC54D32DFA39FFE27C913401F2255F94DBFF698FC45A2.
The narrow guard leaves nonempty optional discovery starvation unresolved.
The direct no-request probe and separate closed-intent recovery failure remain
unexplained. No live change or additional broad run has been performed.

## Implementation and focused evidence

The bounded worker changed only the four approved source/test paths after
approval record 3e981fcdc863fbdb4f85cde04e0b866c2b87ea54. Each helper now returns
the existing [] immediately when discovery.structural_refs is empty, before
repository qualification. Nonempty behavior and all deadlines are unchanged.
The existing configured-actor caller journey retains registration, exact
cross-container send, emitted payload and delivered-state readback assertions.
Its added variant uses only a private logical clock; a repository lookup would
advance it by 7.01 seconds after the original lookup returns. Monkeypatch
restores the common module's previous _HOOK_DEADLINE as well as wrapped functions.
Empty discoveries and zero lookup calls are asserted. Helper parity covers both
modules with absent/provided cwd and prohibits both repository and roadmap lookup.

Exact interpreter: C:/Dev/rore/Pallium/.venv/Scripts/python.exe -B.
New-node command: -m pytest
tests/test_agent_relay_hooks.py::test_configured_actor_hook_registers_and_delivers_across_git_containers
tests/test_hook_common_parity.py::test_empty_structural_work_refs_skip_scope_lookups
-k "empty-discovery-optional-lookup or empty_structural_work_refs_skip_scope_lookups"
-q -n 0. Before the source guards, six intended failures and two deselected in
10.76 seconds: both existing caller registration assertions failed, and the
parity sentinels detected scope lookup. After the guards: six passed, two
deselected in 9.74 seconds.

Affected command: -m pytest tests/test_agent_relay_hooks.py
tests/test_hook_common_parity.py tests/test_relay_work_ref_identity.py -q -n 0.
Result: 273 passed in 50.95 seconds. No concurrent root pytest, full run or native
qualification was performed. git diff --check passed.

Ignored logs in this checkout and SHA256:
- build/relay-empty-work-refs-prefixed.log:
  A7D8E1CB3319856E7E0A8F8A60B3891379D0EE2A0F44B9A8444D93D25255A505
- build/relay-empty-work-refs-postfix.log:
  495E2380B4738546F6FE7750D04202D6F7B086503D0C9ABA0DC7E1D0ACA4BE3F
- build/relay-empty-work-refs-affected-files.log:
  66C999D8B3451E06A2EC0EC06DDE04039D196F0A75974594AD08571DB09EABB6

Frozen implementation blob hashes:
- integrations/claude-code/hooks/common.py: ce251a53eca537e7be35054c1f0942228e0b4cb0
- integrations/codex/hooks/common.py: 202451b15f2af2e1f37e0135942c20c322f25bb1
- tests/test_agent_relay_hooks.py: 48cee097ad6dcab29972a5b618386d7fb4b99cc3
- tests/test_hook_common_parity.py: d1c78bc8f7a5e10de69308b519b40a0ea93dc04a

These simulated caller checks establish the narrow output-preserving repair,
not a historical cause, full-suite pass or installed-host recovery acceptance.
Nonempty optional starvation and the earlier probe/closed-intent incidents
remain unresolved. Publication is held for independent review, required gates
and the manager's combined validation sequencing.
