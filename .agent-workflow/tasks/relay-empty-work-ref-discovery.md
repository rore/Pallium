# Skip repository qualification when no structural refs exist

<!-- agent-workflow:start -->
**Outcome:** Empty structural discovery cannot invoke optional repository qualification before required Relay registration and delivery in either Python prompt hook.

**Target:** Claude Code and Codex UserPromptSubmit integration helpers.

**Scope:** integrations/claude-code/hooks/common.py, integrations/codex/hooks/common.py, tests/test_agent_relay_hooks.py, tests/test_hook_common_parity.py and this Work Record.

**Constraints:** Return the existing empty list for supported empty discovery inputs. Preserve deadlines, identity, nonempty qualification, validation, caller assertions and hook claim/emission/ACK behavior. No protocol, API, schema, dependency, protected-contract, configuration or installed-environment changes. No broader optional-budget redesign, historical attribution, full-run retry or parent recovery closure.

**Completion criteria:** Both helpers return [] for empty discovery without repository or roadmap lookup. Both actual prompt-hook callers preserve registration, cross-container send, emission and ACK under a deterministic optional lookup that would otherwise exhaust the unchanged deadline, with the lookup never invoked. Existing nonempty and identity/parity behavior passes. Independent technical plan/result review and required exact-candidate validation/CI pass before publication; the manager controls full-run sequencing. Nonempty starvation and historical probe/closed-intent failures remain explicitly open.

**Requirement baseline:**
{"source":"pallium-manager:2026-10-07:empty-structural-refs-ownership","outcome":"Empty structural discovery cannot invoke optional repository qualification before required Relay registration and delivery in either Python prompt hook.","scope":"integrations/claude-code/hooks/common.py, integrations/codex/hooks/common.py, tests/test_agent_relay_hooks.py, tests/test_hook_common_parity.py and this Work Record.","constraints":"Return the existing empty list for supported empty discovery inputs. Preserve deadlines, identity, nonempty qualification, validation, caller assertions and hook claim/emission/ACK behavior. No protocol, API, schema, dependency, protected-contract, configuration or installed-environment changes. No broader optional-budget redesign, historical attribution, full-run retry or parent recovery closure.","completion_criteria":"Both helpers return [] for empty discovery without repository or roadmap lookup. Both actual prompt-hook callers preserve registration, cross-container send, emission and ACK under a deterministic optional lookup that would otherwise exhaust the unchanged deadline, with the lookup never invoked. Existing nonempty and identity/parity behavior passes. Independent technical plan/result review and required exact-candidate validation/CI pass before publication; the manager controls full-run sequencing. Nonempty starvation and historical probe/closed-intent failures remain explicitly open."}

**Risk:** Routine

**Complexity:** Simple

**Reason:** Two matching early-return guards preserve the supported empty result and bypass only unnecessary, read-only optional work. No nonempty, authority, identity, state-transition or deadline change. Independent review must confirm this classification; parent recovery remains High/Large and open.

**Approach:** Invoke agent-workflow, establish immutable requirements and classify before production edits (completed). Reuse the clean managed diagnostics checkout on feat/relay-empty-work-ref-discovery from e9eb3956; prior diagnostic/fixture publication branches and ignored evidence remain preserved. Obtain independent technical review of this record before edits. Add caller regression using the existing configured-actor hook/TestClient journey and unchanged lifecycle assertions; model slow repository qualification with a private logical clock, retaining budget 8 and reserve 1. Prove pre-fix missing registration. Add the minimal empty discovery guard before repository_scope_ref in both duplicated helpers, not at individual callers. Add parity controls forbidding repository/roadmap lookup for empty discovery, and reuse existing nonempty/identity coverage. Root owns record/evidence; a bounded cheap worker may implement the exact allowlist after approval. No new framework, real sleep, native transport replay, global environment change or independent broad suite.

**Verification:** Focus the new caller node and empty parity controls with python -m pytest <node> -q -n 0. Run the affected hook/parity/identity files after a coherent change, then the whole-change selector and fresh governance. Source/test changes require full non-slow and exact-head CI before completion, but the manager has explicitly held new full runs until combined candidate sequencing is settled. Focused passes, simulated transport or this deterministic susceptibility witness do not qualify installed recovery or explain previous failures. Preserve active claim and successful ACK behavior; never weaken protected assertions. Native mutation prevention is not claimed for these integration paths; no installation or evaluator outcome substitutes for a denied native operation.

**State:** Ready to implement
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
