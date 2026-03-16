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
- open the direct harness with `python -m app.agent_simulation`
- ask a repeated-question or resumed-work prompt
- inspect `should_inject`, `decision_reason`, injected blocks, top results, and routing/debug context
- accept, edit, or discard the assistant draft
- save the session and replay it later after a code change

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

Optional verification:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 2. Start Pallium

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

## 3. Run The Direct Harness

In another terminal:

```powershell
.\.venv\Scripts\python.exe -m app.agent_simulation
```

This is the preferred exploratory workflow. `chat` mode is the default and runs
an actual thin-agent loop against the live Pallium HTTP service.

Useful commands in the harness:

- `/scope` to set or review container, thread, session, and visibility defaults
- `/show scope` to print current defaults
- `/turn` to set `runtime_context.turn_kind`
- `/local-context` to set `runtime_context.session_has_sufficient_local_context`
- `/fork` to start a new thread while preserving container and visibility
- `/fork --new-session` to rotate the session boundary too
- `/debug on` to show fuller trace detail
- `/save demo-run` or `/export demo-run` to write a replayable JSON bundle under `.local/harness-sessions/`
- `/replay .local/harness-sessions/demo-run.json` to rerun a saved session
- `/mode manual` to switch into direct `/items`, `/query`, and `/query/debug` control

A normal `chat` turn does this in order:

1. ingests the user turn through `POST /items`
2. calls `POST /query/debug` before the assistant turn
3. renders Pallium's carry-forward decision and top results
4. calls the configured model with only Pallium-approved injected blocks when
   `should_inject=true`
5. lets you accept, edit, or discard the assistant draft
6. ingests accepted assistant turns through `POST /items`
7. optionally records one explicit artifact after the turn

## 4. Use The Lower-Level Sample Flow When Needed

If you want a small scripted example that shows raw ingest and query requests
without the interactive harness, run:

```powershell
.\.venv\Scripts\python.exe examples\agent_memory_simulation.py
```

That script is still useful as a lower-level example of the HTTP flow. The
supported exploratory workflow is now the harness at
`python -m app.agent_simulation`.

## 5. What You Should See

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

## 6. Manual Next Step

Once the harness flow makes sense, open the docs that match your next question:

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
