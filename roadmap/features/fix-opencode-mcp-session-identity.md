---
id: fix-opencode-mcp-session-identity
title: Fix OpenCode MCP current-session identity
status: blocked
priority: P1
commitment: committed
lane: integration
---

## Summary

Use OpenCode's per-request MCP session metadata for current-session Relay operations. The V2 plugin already records session identity, but the shared MCP resolver currently expects process-level identity and rejects an unconfigured remote MCP call.

## Why

History capture and a connected MCP endpoint can work while self-address, work-reference operations and recovery receive fail. A global session environment variable is not a safe repair for a shared server with concurrent conversations.

## In Scope

- The shared current-session Relay identity resolver and its OpenCode metadata parser.
- Existing address, work-reference list/attach/detach and recovery-receive callers.
- Caller-surface metadata, concurrency, scope and lifecycle coverage, plus isolated released-host verification for direct and Code Mode calls.
- Accurate setup and identity guidance.

## Out of Scope

- Wake scheduling, claims/ACK semantics, storage schemas, History ranking or capture changes.
- A new identity framework, authentication authority, global runtime/session variables or broader permissions.
- Changes to installed applications, integrations, configuration or services without separate approval.
- Taking over the existing OpenCode reliability or automatic-History-use items.

## Done When

- Valid host metadata selects the exact invoking session on all existing self-bound callers, including concurrent calls through a shared transport.
- Invalid or conflicting metadata cannot borrow another session; existing scope and other-runtime behavior stay intact.
- MCP and native direct/Code Mode checks establish the claimed behavior on the exact tested release.
- Required review and whole-change validation pass. Source delivery and installed deployment remain separate.

## Current checkpoint

The user accepted the source-only plan with the condition that other integrations are unaffected. The shared resolver fix is implemented. Focused compatibility checks passed 70 tests, real stdio/HTTP MCP checks passed 29, and native OpenCode 2.2.7 passed both direct and Code Mode variants. The existing broader MCP subsystem passed 400 tests before the final mixed-metadata guard; the final focused checks cover that guard.

Full validation remains open: the local non-slow run stopped after 4600 passes on an unchanged Codex wake path when SQLite setup exceeded its existing one-second busy budget. All four variants passed in isolation on both this branch and clean base. Do not relabel the full run as passing. Full PR CI and final independent result review remain merge gates. Earlier collection/native prerequisite failures are retained in the Work Record.

The user authorized PR/merge, then explicitly paused local rollout after learning both shared and installed checkouts contain unrelated uncommitted runtime work. Preserve those changes. No installed update or live restart is authorized or claimed; a source merge alone will not repair the running session.

Owning record: [OpenCode MCP session identity](../../.agent-workflow/tasks/opencode-mcp-session-identity.md).
