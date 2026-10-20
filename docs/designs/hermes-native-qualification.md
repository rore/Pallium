# Hermes native qualification proposal

Status: proposed. Hermes remains experimental; this document does not authorize a
workflow change, a test dispatch, installation or local rollout.

The remaining integration proof needs real Desktop and Ink TUI journeys. Gateway
RPC tests and test-helper checks establish narrower contracts. The current
[qualification matrix](../../integrations/hermes/README.md#production-qualification-in-progress)
remains authoritative about unqualified behavior.

## Disposable Windows runner

Propose one manual-only GitHub Actions workflow, with `contents: read`, no
credentials, no publishing, no scheduled runs and no changes to existing CI or
branch protection. Run releases sequentially with fail-fast cancellation,
concurrency protection and a 60-minute limit per release. Use only synthetic
profiles and loopback service/provider stubs; no paid inference.

| Release | Immutable source revision |
|---|---|
| v0.22.0 | `e06df9c2eae6901f4c88f464e0ae6e753c0428b8` |
| v0.22.2 | `d923a5eb487a17c0a68801bba9ef0f56c81040a8` |

Each job would prepare separate Pallium Python 3.13/MCP SDK1 and Hermes Python
3.14.6/MCP SDK2 environments. Preserve Hermes's Python lock and source workspace
scripts. Both pinned sources declare uv 0.12.3 in `pm/lock.json`; verify its
Windows x64 archive hash before executing it from runner temp. Use supported Node
24 and task-local npm 11.9.0, including nested npm scripts. Build the TUI using
`npm run build --workspace ui-tui` and the unpacked Desktop using
`npm run pack --workspace apps/desktop`. Fail explicitly on each native command
error and missing or ambiguous output; do not install MSIX packages or patch
upstream source. Build prerequisites and the unpacked executable layout still
need verification on the runner.

Desktop startup can register native URL handlers. A temporary profile does not
isolate that effect, so Desktop must launch only in a disposable OS runner.
Tests must fail closed outside that approved runner, preserve owned-process
identity, and clean up only their own process trees. TUI tests additionally use
child-level network guards and self-checks; these are not an OS sandbox.

The existing `windows-latest` hosted image is Windows Server 2025 x64. Evidence
from it must be labeled accordingly; it cannot establish Windows 11 x64 support.
The released MSIX package requires Windows 11 22H2 or later. Qualification on that
actual target, including normal launch and update behavior, remains a separate
release gate. See the [GitHub runner images](https://github.com/actions/runner-images)
and [upstream Desktop build contract](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/apps/desktop/BUILDING.md).

## Required observations

Drive real composer input and rendered answers with default Tool Search, then
correlate public state reads with actual tool results. Cover Relay address/send,
an incoming no-reply turn followed by an explicit reply, a new conversation and
later-session History search/expansion, and opt-in memory lifecycle with
memory-disabled independence. Preserve synthetic terminal/UI, provider, HTTP and
JUnit evidence. A scripted provider proves native integration transport and
dispatch; it does not qualify ordinary providers or competing middleware.

Implement and review the caller drivers before dispatch. The current TUI driver
work and any future Desktop driver are separate from this proposal. Adding the
manual workflow and running it require an explicit scoped approval. Approval for
that disposable runner would not authorize changing everyday applications,
services, settings, data, installation or updater behavior.
