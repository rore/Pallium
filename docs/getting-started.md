# Getting Started

This is the fastest way to evaluate Pallium as a developer.

Goal for this walkthrough:

- run the local service
- explore a realistic thin-agent memory loop
- inspect debug decisions before the assistant turn
- save a local replayable session bundle
- keep the lower-level sample flow available when you need raw HTTP shape

A typical quick check now looks like this:

- start Pallium locally
- open the direct harness with `python -m app.agent_simulation chat-lite` for a normal chat loop, or `python -m app.agent_simulation` for the operator/debug flow
- ask a repeated-question or resumed-work prompt
- in `chat-lite`, just chat and let the harness auto-accept replies; in `chat`, inspect `should_inject`, `decision_reason`, injected blocks, top results, and routing/debug context
- save the session and replay it later after a code change when you need a reproducible debugging artifact

## Prerequisites

- Python 3.12 or newer
- an API key for an OpenAI-compatible provider if you want to use the default
  `agent_conversation_memory` setup

If you want to evaluate the service without a live LLM provider first, switch
`default_use_case = "demo_agent_memory"` in `pallium.local.toml`. The
retrieval behavior is simpler, and the harness will fall back to manual
assistant entry when no model is configured.

## 1. Set Up The Local Environment

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
Copy-Item pallium.example.toml pallium.local.toml
Copy-Item .env.example .env.local
```

Set `PALLIUM_OPENAI_API_KEY` in `.env.local`.

If you want to understand the full runtime config surface before editing the
files, read [configuration.md](configuration.md).

Optional verification:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 2. Choose The Initial Runtime Shape

The example config already starts in live `agent_conversation_memory` mode.

Two common starting points are:

- demo mode
  - set `default_use_case = "demo_agent_memory"`
  - useful when you want to inspect the service shape without a live provider
- live conversation-memory mode
  - keep `default_use_case = "agent_conversation_memory"`
  - configure an OpenAI-compatible provider in `pallium.local.toml`
  - keep the secret in `.env.local`

Current shipped config supports:

- named provider blocks
- semantic package blocks
- package prompt defaults
- role-specific prompt overrides
- resolver toggles and timeout
- observability and retention settings

See [configuration.md](configuration.md) for the exact TOML and env syntax.

## 3. Start Pallium

```powershell
.\.venv\Scripts\python.exe -m app.run --host 127.0.0.1 --port 8000 --processors 1
```

The combined local runner now starts one cleaner by default. Set
`[retention].enabled = true` in `pallium.local.toml` to activate retention
passes, or pass `--cleaners 0` when you want an instance without the cleaner.

If you want the split mode instead, use:

```powershell
.\.venv\Scripts\python.exe -m app.run serve --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m app.run processor
.\.venv\Scripts\python.exe -m app.run cleaner
```

## 4. Run The Direct Harness

In another terminal:

```powershell
.\.venv\Scripts\python.exe -m app.agent_simulation chat-lite
```

Use `chat-lite` when you want a normal conversation loop with real HTTP calls,
auto-accepted assistant replies, and no artifact/operator prompts.

If you want the operator/debug workflow instead, run:

```powershell
.\.venv\Scripts\python.exe -m app.agent_simulation
```

`chat` mode remains the default and runs the same thin-agent loop against the
live Pallium HTTP service, but keeps the operator prompts for accept/edit/discard
and optional artifact capture.

If `prompt_toolkit` is available in your environment, the harness also gives you:

- tab completion for slash commands and common command arguments
- colorized prompts and role-prefixed output for agent, debug, and system lines

If advanced terminal support is unavailable, the harness falls back to plain
prompt/input behavior automatically.

Useful commands in the harness:

- `/mode chat-lite` to switch into lightweight auto-accept chat
- `/mode chat` to switch back to operator/debug chat
- `/scope` to set or review container, thread, session, and visibility defaults
- `/show scope` to print current defaults
- `/turn` to set `runtime_context.turn_kind`
- `/local-context` to set `runtime_context.session_has_sufficient_local_context`
- `/new` or `/new-conversation` to start a new conversation in the same memory space and enable cross-thread recall by default
- `/fork` to start a new thread while preserving container and visibility (advanced/debug control)
- `/fork --new-session` to rotate the session boundary too
- `/debug on` to show fuller trace detail
- `/save demo-run` or `/export demo-run` to write a replayable JSON bundle under `.local/harness-sessions/`
- `/replay .local/harness-sessions/demo-run.json` to rerun a saved session
- `/mode manual` to switch into direct `/items`, `/query`, and `/query/debug` control

A `chat-lite` turn does this in order:

1. ingests the user turn through `POST /items`
2. calls `POST /query/debug` before the assistant turn
3. calls the configured model with only Pallium-approved injected blocks when
   `should_inject=true`
4. auto-accepts the assistant reply and ingests it through `POST /items`

A normal `chat` turn adds the operator/debug layer on top:

1. ingests the user turn through `POST /items`
2. calls `POST /query/debug` before the assistant turn
3. renders Pallium's carry-forward decision and top results
4. calls the configured model with only Pallium-approved injected blocks when
   `should_inject=true`
5. lets you accept, edit, or discard the assistant draft
6. ingests accepted assistant turns through `POST /items`
7. optionally records one explicit artifact after the turn

## 5. Use The Lower-Level Sample Flow When Needed

If you want a small scripted example that shows raw ingest and query requests
without the interactive harness, run:

```powershell
.\.venv\Scripts\python.exe examples\agent_memory_simulation.py
```

That script is still useful as a lower-level example of the HTTP flow. The
supported exploratory workflow is now the harness at
`python -m app.agent_simulation`.

## 6. What You Should See

You should see:

- user and assistant turns ingested through the real `/items` contract
- `query/debug` output showing `should_inject`, `decision_reason`, injected
  blocks, top results, and trace context
- a thin assistant draft that only sees Pallium-approved carry-forward blocks
- replayable local JSON sessions under `.local/harness-sessions/`

You are not looking for perfect prose. You are looking for the shape of the
system:

- selected evidence goes in
- compact memory and evidence cards come back out
- only approved carry-forward gets injected into the thin-agent draft
- the debug path explains what retrieval did

## 7. Manual Next Step

Once the harness flow makes sense, open the docs that match your next question:

- if you want the runtime knobs and file layout, read [configuration.md](configuration.md)
- if you want the request and response shapes, read [http-api.md](http-api.md)
- if you want to wire Pallium into a runtime, read [agent-integration.md](agent-integration.md)
- if you want the scope rules, read [privacy-and-visibility.md](privacy-and-visibility.md)
- if you want to understand what is stored and derived, read [memory-model.md](memory-model.md)
- if you want the current validation surface, read [validation.md](validation.md)

## What You Just Proved

In one short run, you verified that the current repo already ships:

- a local service you can run yourself
- a supported exploratory harness for thin-agent debugging against real HTTP endpoints
- scoped ingest for agent-mediated events
- compact retrieval over memory plus evidence
- resumed-work continuity support in today's product focus
- a debuggable retrieval path with replayable local sessions



