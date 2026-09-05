# Getting Started

This guide starts the local service, connects a coding tool, sends one Relay
message, and searches earlier session work.

## Prerequisites

- Python 3.12 or 3.13 recommended
- Git
- Claude Code or Codex for the shortest setup path
- an OpenAI-compatible or Anthropic API key for the current installation

The planned base service is intended to run Relay and Session History without an LLM.
That package-independent setup has not shipped yet, so the current installation
still includes semantic-package and provider configuration.

## 1. Install and start Pallium

From the repository checkout:

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev,vector,mcp]"
cp pallium.example.toml pallium.local.toml
cp .env.example .env.local
```

Set the provider key required by your selected package in `.env.local`, then
install the local service:

```bash
pallium service install
pallium service status
```

The installed service uses port `19836` and starts at login. For local Pallium
development, use the repository's `scripts/restart-service.ps1` wrapper when
restarting it; the wrapper removes stale child processes before checking the
service again.

For foreground development instead:

```bash
python -m app.run --host 127.0.0.1 --port 8000 --processors 1
```

## 2. Connect a coding tool

Run the setup command for the tool you use:

```bash
pallium setup claude-code
# or
pallium setup codex
```

Run setup from the checkout you intend to keep. The integrations contain
absolute local paths, so moving or deleting that checkout requires uninstalling
and reinstalling the integration.

OpenCode uses a local plugin path. Follow the
[OpenCode integration guide](../integrations/opencode/README.md).

Open two sessions in the same Git repository after setup. Pallium derives their
shared container from the repository identity while keeping each session
separately addressable.

## 3. Try Relay

In the second session, give it a Relay alias:

> Use Pallium Relay to name this session `review`.

In the first session, ask:

> List Pallium Relay recipients.

Confirm that the `review` alias points to the intended session, then send a small message. Use the target runtime shown by recipient discovery (`codex:@review` or `claude-code:@review`). An exact session or alias is safer than a runtime-wide send when several sessions are open:

> Use Pallium Relay to send `codex:@review`: "Please check whether the API change
> preserves the old response field."

On qualified Windows Claude Code targets, Pallium can start a new turn in the
existing session. Windows Codex wake is proven but still completing broader
lifecycle qualification. OpenCode and unqualified platforms keep the message
pending until the next normal recipient turn.

The recipient can reply using the received delivery. Pallium derives the return
address; the recipient does not need to look up the sender again.

See [Relay](agent-relay.md) for aliases, delivery limits, recovery tools, and
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

This is an experimental optional subsystem in the product direction, although
the current runtime has not yet been decoupled from its package configuration.

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
