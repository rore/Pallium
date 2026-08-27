<!-- agent-workflow:start -->
**Outcome:** Agents can receive and acknowledge pending Relay deliveries via MCP without raw HTTP, claim tokens, or model-supplied identity. pallium_relay_receive claims and returns deliveries using integration-injected scope only; pallium_relay_ack idempotently ACKs after the caller has the payload; pallium_relay_reply ACKs parent receipt; pallium_relay_recipients description says "address book, not inbox"; AGENTS.md distinguishes hook delivery from MCP receive. Automatic hook injection drains the complete eligible pending set in one envelope; no backlog paging or UX.

**Target:** app/mcp/context.py, app/mcp/server.py, app/mcp/client.py, api/routes.py, api/schemas.py, storage/sqlite_relay.py, core/relay.py, AGENTS.md, integrations/claude-code/, integrations/codex/, integrations/opencode/, tests/

**Scope:** Add receipt-based MCP receive/ACK and atomic reply storage; bind MCP session identity from integration-provided runtime environment; keep normal Relay responses bounded while returning complete receive envelopes; preserve validation/redaction in atomic replies; remove RF-008 paging from Claude, Codex, and OpenCode; add HTTP and FastMCP lifecycle regressions.

**Constraints:** No claim tokens in MCP tool inputs, outputs, or docstrings. pallium_relay_receive uses integration-bound identity only: explicit PALLIUM_THREAD_REF first, then the supported runtime's own inherited session identity; no model-supplied runtime/session identity. Existing hook ACK and send/status response bounds remain compatible. Replies retain payload/expiry validation and secret redaction.

**Completion criteria:** pallium_relay_receive returns pending deliveries with opaque delivery_id; pallium_relay_ack confirms idempotently; lease expiry causes redelivery; pallium_relay_reply atomically ACKs; all listed E2E cases pass; no claim token in any MCP surface; pallium_relay_recipients description corrected; AGENTS.md guidance added.

**Risk:** High

**Complexity:** Moderate

**Reason:** Touches app/ (watch zone), api/ (public contract), storage/ (relay persistence). Reclassified High after architect review: `relay_reply_atomic` adds a new atomic path through the write-ahead log; receipt validation uses constant-time compare; MCP overflow protection changes _relay_text behavior. All changes are additive but the atomic reply + receipt path required non-trivial storage changes.

**Discovery:** Final review disproved three assumptions: installers set only static runtime identity, not session identity; atomic reply bypassed payload/expiry validation and redaction; and the shared serializer treated send/status delivery lists as receive envelopes. The claimed FastMCP verification had not executed successfully: the focused suite at 5704151 produced 6 failures. Codex exposes CODEX_THREAD_ID/CODEX_SESSION_ID to child processes; Claude MCP is a direct child of the Claude process and its local session registry maps that parent PID to sessionId.

**Material assumptions:**
- PALLIUM_AGENT_REF is a valid RelayRuntime literal (claude-code/codex/opencode) — if not, receive fails with a clear error. Disproved if: PALLIUM_AGENT_REF is missing or not a valid runtime. Action: fail at tool entry with message explaining which env var is absent.
- Scope-based ACK (delivery_id + runtime + session_ref + container_ref + actor_ref) is sufficient to uniquely identify the claimant without the raw claim_token — holds because the relay session registered with those exact values when it claimed. Disproved if: the storage model allows a single delivery to be claimed by two distinct sessions with the same scope (impossible by design — claim is atomic). Action: none expected.
- pallium_relay_reply atomic ACK: idempotent if delivery is already delivered (hook path already ACKed). Disproved if: there is a side effect on double-ACK. Action: verify storage acknowledge is idempotent on delivered state.

**Plan:**
1. Keep the existing receipt API and atomic storage path, but restore reply payload/expiry validation, redaction, rollback, and receipt-bound idempotence.
2. Restore the compact serializer for send/status and use an explicit unbounded serializer only for MCP receive envelopes after claim-token removal.
3. Resolve trusted session identity at the MCP process boundary from PALLIUM_THREAD_REF, Codex's inherited thread/session ID, or Claude's parent-PID session registry; fail closed otherwise.
4. Repair and extend FastMCP E2E coverage for empty/drain-all, Unicode, ACK/idempotence, expiry/redelivery, atomic reply/redaction/rollback, hook race, restart, and two-session isolation; keep HTTP lifecycle coverage for the service contract.
5. Run focused tests, full Python suite, OpenCode tests, workflow checker, resolve all PR threads, and merge only after CI is green.

**Verification plan:**
- pytest tests/test_relay_mcp_lifecycle.py -q → all cases pass
- pytest tests/ -q → no regressions
- grep -n "claim_token" app/mcp/server.py → zero matches in new code
- grep -n "PALLIUM_AGENT_REF\|PALLIUM_THREAD_REF" app/mcp/server.py → present in pallium_relay_receive guard

**Plan review:** High risk, Moderate complexity. Clean-context architecture review by relayarch (relay-reply-6a1fa006; delivery relay-delivery-23a044aba4c24fcb838aa14f504b422e), followed by consolidated final review and corrections on 2026-08-27.

**Approvals:** Approved by user 2026-08-27: "this time i need you to close this yourself, so if there are more issues, take care of it so we can merge the pr"

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Branch: fix/relay-receive-mcp-lifecycle
PR: https://github.com/rore/Pallium/pull/76

### Changes delivered

- **RF-008**: `max_chars=0` (unlimited) default; complete pending set drained per turn; backlog UX removed from claude-code + codex hooks
- **P0 1**: Receipt-based MCP ACK — `receipt = sha256(claim_token)[:32]`; new `/relay/deliveries/mcp-ack`; `pallium_relay_ack` uses receipt
- **P0 2**: `PALLIUM_AGENT_REF="codex"` in codex `.mcp.json`; AGENTS.md documents trusted per-session `PALLIUM_THREAD_REF` binding
- **P0 3**: `relay_delivery_context` accepts `claimed` state atomically (validate receipt + mark delivered); `pallium_relay_reply` ACKs in one step

### Final-review corrections in progress

- Focused suite at 5704151: 6 failed, 168 passed; FastMCP happy paths were broken despite the earlier all-green claim.
- Remaining corrections owned by relayarch: runtime-bound session identity, reply validation/redaction, serializer separation, receipt-bound idempotence, and complete caller-surface regressions.

## Evidence

Revision under review: working tree after 5704151, before final commit.

- Focused Relay/MCP/integration suite: 199 passed.
- FastMCP caller-surface lifecycle: 10 passed, including two-session isolation, Unicode, drain-all, receipt secrecy, lease redelivery, stale receipt, idempotent ACK, atomic redacted reply, restart, and hook/MCP race.
- OpenCode adapter: 42 passed from integrations/opencode.
- Full Python suite with user config isolated as CI does: 3985 passed, 12 skipped, 2 xfailed.
- Initial unisolated full run had one unrelated local user-config contamination in test_prompt_variants_legacy_fallback_unaffected; the clean-config rerun passed.
- apply_patch failed with the documented Windows CreateProcessWithLogonW host error; edits used narrow deterministic replacements and were compile/test verified.