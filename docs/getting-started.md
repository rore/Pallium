# Getting Started

This guide starts the local service, connects a coding tool, sends one Relay
message, and searches earlier session work.

## Prerequisites

- Python 3.12 or 3.13 recommended
- Git
- Claude Code, Codex, OpenCode or Hermes Desktop/TUI
- an OpenAI-compatible or Anthropic API key only if you enable optional
  derived memory

Relay and Session History run without an LLM provider. Derived memory is
disabled by default and requires explicit opt-in plus provider credentials.

## 1. Install from source and start Pallium

From the repository checkout:

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[vector,mcp]"
cp pallium.example.toml pallium.local.toml
cp .env.example .env.local
```

Install the local service. No provider key is required for Relay or raw Session
History:

```bash
pallium service install
pallium service status
```

The installed service uses port `19836` by default. Pass `--port PORT` to
`pallium service install` to override it, then use that configured port for
dashboard and endpoint checks. On Windows it starts at login; always
use `scripts/restart-service.ps1` for local development restarts. On Linux it
uses a systemd user unit and supports the full public lifecycle:

```bash
pallium service status
pallium service stop
pallium service start
pallium service restart
pallium service uninstall
```

The Linux `scripts/install-service.sh`, `restart-service.sh`, and
`uninstall-service.sh` wrappers delegate to this same CLI. Pass the same
`--home` to every command when using a custom home; one Linux user has one
Pallium unit, so install refuses to silently switch it to another home. Data is
preserved on uninstall. `--remove-data` deletes only the default managed home;
custom homes must be removed manually after inspection.

Ubuntu 24.04 under WSL2 is live-qualified. WSL stops the service when the distro
is stopped; the enabled unit starts again when the Ubuntu user session starts.
Other systemd Linux environments use the same unit path but have not received
this WSL-specific live qualification.

For foreground development instead:

```bash
python -m app.run --host 127.0.0.1 --port 8000 --processors 1
```

## 2. Connect a coding tool

Choose the integration you use:

| Integration | Setup |
|---|---|
| [Claude Code](claude-code-integration.md#setup) | `pallium setup claude-code` |
| [Codex](codex-integration.md#setup) | `pallium setup codex`, then restart and review new or changed hooks |
| [OpenCode](../integrations/opencode/README.md#setup) | Configure the local plugin, remote MCP and guidance; there is no setup CLI |
| [Hermes Desktop/TUI](hermes-integration.md#setup) | Use the profile-specific setup command with explicit profile, interpreters and private scope |

Run setup from the checkout you intend to keep. The integrations contain
absolute local paths, so moving or deleting that checkout requires uninstalling
and reinstalling the integration.

For Claude Code, Codex or OpenCode, open two sessions in the same Git repository
after setup. Pallium derives their shared container from the repository identity
while keeping each session separately addressable. For Hermes, use the same
explicit private scope when you want shared History; follow its guide to select
an existing profile. Relay can address sessions across containers on the same
service; History and memory remain scoped.

## 3. Try Relay

In the second session, give it a Relay name:

> Use Pallium Relay to name this session `review`.

In the first session, ask:

> List Pallium Relay recipients.

Confirm that the `review` name points to the intended session, then send a
small message using its verified `@review` name. Regular sends require an exact
session address or a name; a bare runtime is rejected:

> Use Pallium Relay to send `@review`: "Please check whether the API change
> preserves the old response field."

Wake and recovery depend on the receiving integration. Compare all four in the
[Relay delivery table](agent-relay.md#delivery-and-wake-behavior), then use the
recipient guide's verification steps. A saved send is not proof of receipt;
confirm the attributed message and reply in the intended session.

The recipient can reply using the received delivery. Pallium derives the return
address; the recipient does not need to look up the sender again.

See [Relay](agent-relay.md) for names, delivery limits, recovery tools, and
current wake status.

## 4. Try Session History

Do a small piece of work in one session and record a clear decision or finding.
Open another session in the same repository and ask:

> Search Pallium Session History for why we chose that approach.

The agent uses `pallium_search_history` to find concise historical matches. Ask
it to expand the relevant match; `pallium_expand_source` returns a bounded part
of the surrounding conversation.

Treat the result as historical evidence. If the answer depends on current pull
request status, files, services, or another external system, verify that live
state separately.

See [Session History](session-history.md) for the current scope and planned work.

## 5. Optional derived memory

The current installation can also extract decisions, findings, facts,
constraints, and work checkpoints from stored turns. Integrations may retrieve
or inject those compact memory objects on later turns.

This is an experimental optional subsystem. To use it, set `enabled = true` on
the chosen semantic package and configure its `llm_provider`, `model`, and
provider credential. Leaving every package disabled keeps history raw and makes
no derived-memory model calls.

## Check the service

Open `http://localhost:19836/dashboard` for service health, Relay activity,
ingestion/search activity, and the current derived-memory views.

```bash
curl http://localhost:19836/health
curl http://localhost:19836/status
curl http://localhost:19836/debug/queue/health
```

See [Dashboard](dashboard.md), [HTTP API](http-api.md), and
[Configuration](configuration.md) for details.
