# Integration Example: Slack Agent

A concrete walkthrough showing how a Slack-connected agent integrates with
Pallium. Based on a real production integration pattern.

For API reference, see [http-api.md](http-api.md). For integration
principles, see [agent-integration.md](agent-integration.md).

## The Setup

Your agent listens to Slack events. When a user sends a message, the agent
answers using an LLM. Pallium sits between the Slack event and the LLM call —
it stores selected evidence, derives compact memory, and returns it before the
next answer so the agent can stay oriented across conversations.

```text
Slack message  →  your agent  →  Pallium /items   (store user message)
                               →  Pallium /query   (get relevant memory)
                               →  LLM              (answer with injected memory)
                               →  Slack            (post reply)
                               →  Pallium /items   (store reply + artifacts)
```

## Mapping Slack Concepts to Pallium Fields

| Slack concept | Pallium field | Example value |
|---------------|--------------|---------------|
| Channel ID | `container_ref` | `"slack:channel:C04ABC123"` |
| DM channel | `container_ref` | `"slack:dm:D01XYZ789"` |
| Thread timestamp | `thread_ref` | `"slack:thread:C04ABC123:1700000001.000100"` |
| Channel type | `container_visibility` | `"public"`, `"limited"`, or `"private"` |
| Message timestamp | `source_id` | `"slack-message:C04ABC123:1700000001.000100"` |
| User ID | `actor_ref` | `"slack:user:U01XYZ789"` |
| Bot/agent ID | `agent_ref` | `"slack-bot:B04DEF456"` |

`container_ref` groups related conversations. `container_visibility` controls
who can see the memory — a private channel's memory never leaks into queries
from a different context.

## The Client

A thin async client wraps the two Pallium endpoints:

```python
import aiohttp

class PalliumClient:
    def __init__(self, base_url: str, timeout_seconds: int = 5):
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def post_item(self, payload: dict) -> None:
        session = await self._ensure_session()
        async with session.post(f"{self._base_url}/items", json=payload) as r:
            if r.status >= 400:
                logging.warning("Pallium ingest failed: HTTP %s", r.status)

    async def query(self, payload: dict) -> dict | None:
        session = await self._ensure_session()
        async with session.post(f"{self._base_url}/query", json=payload) as r:
            if r.status != 200:
                return None
            return await r.json()
```

Keep the client simple — Pallium owns the memory decisions, not the client.

## Step 1: Ingest the User Message

When a Slack message arrives:

```python
async def ingest_user_message(client: PalliumClient, event: dict):
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]

    await client.post_item({
        "source_type": "conversation_agent_event",
        "source_id": f"slack-message:{channel}:{event['ts']}",
        "content_type": "text/plain",
        "content": event["text"],
        "role": "user",
        "artifact_kind": "message",
        "container_ref": container_ref(channel, event["user"], is_dm(event)),
        "thread_ref": f"slack:thread:{channel}:{thread_ts}",
        "container_visibility": channel_visibility(event),
        "actor_ref": f"slack:user:{event['user']}",
    })
```

Notes:
- `source_id` is stable per message — re-ingesting the same message is
  idempotent.
- Processing happens in the background. The response returns immediately with
  `processing_status: "pending"`.
- Skip empty messages — don't ingest them.

## Step 2: Query for Memory Before Answering

Before the LLM draft, ask Pallium for relevant memory:

```python
async def query_memory(
    client: PalliumClient,
    event: dict,
    session_id: str,
) -> str | None:
    """Returns formatted memory block for prompt injection, or None."""
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]

    result = await client.query({
        "text": event["text"],
        "limit": 12,
        "container_ref": container_ref(channel, event["user"], is_dm(event)),
        "thread_ref": f"slack:thread:{channel}:{thread_ts}",
        "container_visibility": channel_visibility(event),
    })

    if result is None or not result.get("should_inject"):
        return None

    blocks = result.get("injectable_blocks", [])
    if not blocks:
        return None

    # Format blocks for prompt injection
    formatted = []
    for block in blocks:
        title = block.get("title") or block.get("memory_type") or "context"
        text = block.get("text", "")
        if text.strip():
            formatted.append(f"{title}\n{text}")

    if not formatted:
        return None

    return (
        "[Prior context from earlier related work]\n"
        + "\n\n".join(formatted)
        + "\n[End prior context]\n"
    )
```

The key contract: check `should_inject` first, then use `injectable_blocks`.
Don't filter, rerank, or second-guess — Pallium already made the decision.

## Step 3: Build the LLM Prompt

Include the memory block as a distinct section in the prompt, separate from
the current conversation:

```python
async def handle_message(event: dict, session_id: str):
    # 1. Ingest user message
    await ingest_user_message(pallium, event)

    # 2. Query for memory
    memory_block = await query_memory(pallium, event, session_id)

    # 3. Build prompt
    parts = []
    if memory_block:
        parts.append(memory_block)
    parts.append(f"User: {event['text']}")
    prompt = "\n".join(parts)

    # 4. Call LLM and post reply
    reply = await call_llm(prompt)
    reply_ts = await post_slack_reply(event, reply)

    # 5. Ingest reply
    await ingest_assistant_reply(pallium, event, reply_ts, reply)
```

## Step 4: Ingest the Assistant Reply and Artifacts

After the LLM responds, store the reply. If the agent produced tool results
or todo snapshots, ingest those too:

```python
async def ingest_assistant_reply(
    client: PalliumClient, event: dict, reply_ts: str, text: str
):
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]

    await client.post_item({
        "source_type": "conversation_agent_artifact",
        "source_id": f"agent-artifact:{channel}:{reply_ts}:assistant_output",
        "content_type": "text/plain",
        "content": text,
        "role": "assistant",
        "artifact_kind": "assistant_output",
        "container_ref": container_ref(channel, event["user"], is_dm(event)),
        "thread_ref": f"slack:thread:{channel}:{thread_ts}",
        "container_visibility": channel_visibility(event),
        "agent_ref": f"slack-bot:{BOT_ID}",
    })
```

For tool summaries and todo snapshots, use `artifact_kind="tool_use_summary"`
and `artifact_kind="todo_snapshot"` respectively. Format them as compact text:

```python
# Tool summary example
"Tool summary: search_codebase [done]: found 3 matches in auth module | run_tests [done]: 12 passed"

# Todo snapshot example
"Todo snapshot: in_progress: implement rate limiting | pending: update API docs"
```

## Visibility Mapping

```python
def container_ref(channel: str, user: str, dm: bool) -> str:
    return f"slack:dm:{channel}" if dm else f"slack:channel:{channel}"

def channel_visibility(event: dict) -> str:
    if is_dm(event):
        return "private"
    if is_public_channel(event):
        return "public"
    return "limited"  # private channels
```

## What You Don't Need to Do

- **Don't filter or rerank results** — `should_inject` and
  `injectable_blocks` are the contract.
- **Don't send `runtime_context`** for normal chat — the structural refs
  are sufficient. Only send it when you genuinely know the session state
  (e.g. `turn_kind: "resumed_session"` after a reconnect).
- **Don't send `use_case`** — server-side config selects the semantic package.
- **Don't ingest everything** — user questions and final assistant answers are
  the high-value inputs. Skip reactions, ephemeral messages, and bot noise.

## Debugging

When results are wrong, use the debug endpoint:

```python
result = await client.query_debug({
    "text": user_text,
    "container_ref": container_ref(channel, user, dm),
    "container_visibility": channel_visibility(event),
})

# result["trace"] shows retrieval matches, visibility exclusions,
# routing decisions, and why Pallium chose to inject or abstain
```
