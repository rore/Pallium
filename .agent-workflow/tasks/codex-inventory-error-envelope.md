<!-- agent-workflow:start -->
**Outcome:** A failed native Codex tool-list response identifies whether Desktop rejected the request or failed during tool enumeration, without exposing response contents.

**Target:** Windows Codex inventory observer in `app/codex_bridge_pipe.py`.

**Scope:** Existing sanitized failure-stage allowlist and `_observe` envelope classification, with private caller tests in `tests/test_codex_bridge_pipe.py`.

**Constraints:** Preserve request, framing, success validation, public `native-failed`, custody/proof/fencing, authority, retry, and cleanup. Never log response fields, tool names, schema, endpoint, environment, exception text, or live data. No live registration/service action.

**Completion criteria:** Synthetic Desktop invalid-request and tool-list-error envelopes produce distinct fixed stages with unchanged caller failure and privacy; unexpected envelopes retain generic `validate-envelope`; valid success remains accepted.

**Requirement baseline:**
{"source":"installed-protocol-investigation-2026-09-30","outcome":"A failed native Codex tool-list response identifies whether Desktop rejected the request or failed during tool enumeration, without exposing response contents.","scope":"Existing sanitized failure-stage allowlist and `_observe` envelope classification, with private caller tests in `tests/test_codex_bridge_pipe.py`.","constraints":"Preserve request, framing, success validation, public `native-failed`, custody/proof/fencing, authority, retry, and cleanup. Never log response fields, tool names, schema, endpoint, environment, exception text, or live data. No live registration/service action.","completion_criteria":"Synthetic Desktop invalid-request and tool-list-error envelopes produce distinct fixed stages with unchanged caller failure and privacy; unexpected envelopes retain generic `validate-envelope`; valid success remains accepted."}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** The runtime bridge is a Redline watch-zone trust boundary; this is a two-file diagnostic-only change and leaves response acceptance unchanged.

**Discovery:** Installed Codex 26.924.6891.0 `app.asar` backend `main-9XR80eJG.js` defines the native tools/list pipe. Its parser accepts the fixed Pallium request, and its handler emits an exact `{id,jsonrpc,result}` success or one of two exact `{id,jsonrpc,error}` forms: fixed invalid-request code -32602, or fixed callback-failure code -32000. Native transport routes/restores the original request ID and length-prefixes JSON. Observed Pallium `before-validate-envelope/invalid-response` therefore fits a Desktop error envelope, not an added success field; source alone does not distinguish the two error branches or prove the internal exception.

**Material assumptions:** The installed package's `dynamic-app-tools-native-pipe` is the peer-checked pipe reached by the trial. If independent review finds another sender/shape can reach it, return to discovery. The installed fixed error codes/messages must be verified from source before relying on them; unknown shapes stay generic.

**Plan:** First add private-caller red tests for both fixed Desktop error envelopes, unknown/malformed error envelope, valid success, and privacy/fencing. After independent review, set one of two fixed allowlisted stages only when `jsonrpc`, echoed ID, exact top-level/error shape, and fixed code/message match the installed source; otherwise keep `validate-envelope`. Retain the existing unconditional `invalid-response` rejection and public `native-failed` behavior. No response payload logging, new API, storage, or broad framework. Stop if source-to-pipe linkage is not sound or classification requires native content.

**Verification plan:** When the private Desktop fake returns either known fixed error, `register()` shall remain unavailable/native-failed and fenced, while the single sanitized log identifies its branch → parameterized private-caller test. When it returns an unknown error shape, the log shall remain generic and privacy-safe → caller test. When it returns a valid success, before proof and registration shall remain successful → positive control. Run focused slow-marked cases, affected file, selector-required full once, workflow check, independent result review, PR/CI.

**Plan review:** Pending independent security/technical review of installed-source inference and fail-closed classification.

**Approvals:** Not required at Elevated risk; standing user autonomous approval covers this scoped diagnostic plan.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

2026-09-30: Applied Agent Workflow, classified Elevated/Simple before production edits, reused clean managed checkout on new branch `fix/codex-inventory-error-envelope` from current `origin/main`. Installed-source diagnosis is read-only. Awaiting independent plan review; no tests or production edits.

## Evidence

Installed package metadata: `OpenAI.Codex` version 26.924.6891.0. Actual package resources contain `app.asar`; `.vite/build/main-9XR80eJG.js` holds `mce`, `gce`, `Zse`. Source success and two fixed error envelopes are described in Discovery. No live response, payload, endpoint, or environment was read.

## Result review

Pending.
