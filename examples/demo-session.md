# Demo Session: Cross-Thread Memory Recall

A complete walkthrough showing Pallium remembering a decision from one
conversation and surfacing it in a follow-up thread. All requests and responses
are real API shapes.

## Setup

Pallium running locally with `agent_conversation_memory` and an LLM provider
configured. Two threads in the same container (a shared channel).

---

## Thread 1: The Decision

### Step 1 — Ingest the user question

```bash
curl -s -X POST http://localhost:8000/items \
  -H 'Content-Type: application/json' \
  -d '[{
    "source_type": "conversation_agent_event",
    "source_id": "msg-001",
    "content_type": "text/plain",
    "content": "Should we use event timestamps or wall-clock time for ordering reservation holds?",
    "role": "user",
    "artifact_kind": "message",
    "container_ref": "channel:catalog-sync",
    "thread_ref": "thread-A",
    "visibility": "container",
    "actor_ref": "user:alice"
  }]'
```

Response confirms ingest:

```json
[{
  "source_item_id": "si_a1b2c3",
  "processing_status": "pending",
  "memory_object_ids": [],
  "relation_ids": [],
  "index_entry_ids": []
}]
```

### Step 2 — Ingest the assistant's decision

```bash
curl -s -X POST http://localhost:8000/items \
  -H 'Content-Type: application/json' \
  -d '[{
    "source_type": "conversation_agent_event",
    "source_id": "msg-002",
    "content_type": "text/plain",
    "content": "Decision: use item event time for reservation ordering instead of wall clock. Reason: event time reflects the actual hold sequence and avoids timezone drift across regional deployments. Wall clock ordering would create race conditions when clocks are skewed between regions.",
    "role": "assistant",
    "artifact_kind": "assistant_output",
    "container_ref": "channel:catalog-sync",
    "thread_ref": "thread-A",
    "visibility": "container"
  }]'
```

Processing happens in the background. After a few seconds, the background
worker extracts a `decision` memory object with evidence linking back to both
messages.

---

## Thread 2: The Follow-Up (Different Thread, Same Channel)

### Step 3 — New thread, related question

A colleague asks a follow-up in a different thread, days later:

```bash
curl -s -X POST http://localhost:8000/item-and-query \
  -H 'Content-Type: application/json' \
  -d '{
    "source_type": "conversation_agent_event",
    "source_id": "msg-050",
    "content_type": "text/plain",
    "content": "Why did we choose event time for the reservation ordering?",
    "role": "user",
    "artifact_kind": "message",
    "container_ref": "channel:catalog-sync",
    "thread_ref": "thread-B",
    "visibility": "container",
    "actor_ref": "user:bob"
  }'
```

### Step 4 — Pallium responds with memory

```json
{
  "source_item_id": "si_d4e5f6",
  "should_inject": true,
  "decision_reason": "carry_forward_available",
  "injectable_blocks": [
    {
      "result_id": "mo_x7y8z9",
      "block_type": "memory_hit",
      "title": "decision",
      "text": "Use item event time for reservation ordering instead of wall clock. Event time reflects the actual hold sequence and avoids timezone drift across regional deployments.",
      "memory_type": "decision",
      "evidence": [
        {
          "source_item_id": "si_a1b2c3",
          "excerpt": "Should we use event timestamps or wall-clock time..."
        }
      ]
    }
  ],
  "results": [
    {
      "result_id": "mo_x7y8z9",
      "result_kind": "memory_hit",
      "type": "decision",
      "score": 850,
      "container_ref": "channel:catalog-sync",
      "visibility": "container",
      "retrieval_source": "fused",
      "evidence": [
        {
          "source_item_id": "si_a1b2c3",
          "excerpt": "Should we use event timestamps or wall-clock time..."
        }
      ]
    }
  ]
}
```

Key observations:
- `should_inject: true` — Pallium decided this memory is worth injecting
- `decision_reason: "carry_forward_available"` — a prior decision matched
- The `decision` memory was derived from thread A and retrieved in thread B
- Evidence links back to the original user question
- `retrieval_source: "fused"` — both lexical and vector search contributed

### Step 5 — The agent uses the injected memory

The integrating agent takes the `injectable_blocks` and prepends them to the
LLM prompt:

```
[Prior context from earlier related work]

decision
Use item event time for reservation ordering instead of wall clock. Event time
reflects the actual hold sequence and avoids timezone drift across regional
deployments.

[End prior context]

User: Why did we choose event time for the reservation ordering?
```

The LLM can now answer grounded in the original decision and evidence.

---

## When Pallium Abstains

### Greeting — low value

```bash
curl -s -X POST http://localhost:8000/item-and-query \
  -H 'Content-Type: application/json' \
  -d '{
    "source_type": "conversation_agent_event",
    "source_id": "msg-060",
    "content_type": "text/plain",
    "content": "Hey, good morning!",
    "role": "user",
    "artifact_kind": "message",
    "container_ref": "channel:catalog-sync",
    "thread_ref": "thread-C",
    "visibility": "container"
  }'
```

```json
{
  "source_item_id": "si_g1h2i3",
  "should_inject": false,
  "decision_reason": "low_value_query",
  "injectable_blocks": [],
  "results": []
}
```

Pallium recognized this as a greeting and returned nothing.

### Same-thread context — redundant

If the agent queries from the same thread where the decision was just made:

```json
{
  "should_inject": false,
  "decision_reason": "same_thread_context_sufficient",
  "injectable_blocks": [],
  "results": []
}
```

The agent already has the context in its conversation window — injection would
be redundant.

---

## Debug Trace

For any query, append `/debug` to see the full trace:

```bash
curl -s -X POST http://localhost:8000/query/debug \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "Why did we choose event time for the reservation ordering?",
    "container_ref": "channel:catalog-sync",
    "visibility": "container"
  }'
```

The `trace` field in the response shows:

```json
{
  "trace": {
    "query_text": "Why did we choose event time for the reservation ordering?",
    "query_tokens": ["choose", "event", "time", "reservation", "ordering"],
    "limit": 5,
    "visibility": {
      "query_visibility": "container",
      "query_container_ref": "channel:catalog-sync",
      "excluded_candidates": []
    },
    "fusion_trace": {
      "stage_name": "rrf_fusion",
      "k": 60,
      "rrf_score_scale": 600,
      "lexical_candidate_count": 3,
      "vector_candidate_count": 4,
      "fused_candidate_count": 5,
      "both_sources_count": 2,
      "selected_count": 5,
      "hits": [
        {
          "result_id": "mo_x7y8z9",
          "rrf_score": 0.033,
          "rrf_rank": 1,
          "fused_score": 850,
          "lexical_rank": 1,
          "vector_rank": 1,
          "retrieval_source": "fused"
        }
      ]
    },
    "routing": {
      "query_policy_family": "answer_continuity",
      "query_intent": "carry_forward",
      "structural_lane": "evidence_trace",
      "injection_decision": "inject",
      "reasons": ["cross_thread_carry_forward_support"]
    }
  }
}
```

The trace shows:
- Which tokens were used for lexical matching
- How many candidates each retrieval method found
- How RRF fused the results and what the final ranking was
- Which routing lane and policy family were selected
- Why injection was approved
