---
id: validate-relay-dependency-workflows
title: Validate Relay dependency workflows and public positioning
status: queued
priority: high
commitment: committed
milestone: pallium-relay
lane: validation
---

## Summary

After `add-wake-first-relay-delivery`, turn the three strongest practical Relay
workflows into reusable end-to-end scenarios and live cross-runtime validations.
Use the resulting evidence as both regression coverage and the source of truth for
how Pallium publicly explains Relay.

This item validates a product hypothesis; it does not add a workflow engine:

> Pallium keeps independently running local agents aligned when one learns
> something another needs.

## Sequencing

This work starts only after wake-first delivery is implemented and stable across
Claude Code, Codex, and OpenCode. Its scenarios depend on observing real wake,
safe busy-turn queuing, replies, and deterministic next-turn fallback. Findings may
produce focused bugs, but must not silently expand Relay into orchestration.

## Research Result Preserved

Observed practice is narrower than “agents chat”:

- separately scoped agents usually work independently
- useful messages happen at unexpected dependency boundaries
- the recurring useful events are assignment, question, discovery, blocker or
  decision, completion or unblock, review request, and review finding
- the strongest value is information that could not have been fully predicted in
  the original prompt
- targeted one-to-one coordination has better evidence than free-form discussion
  or routine progress broadcast
- cross-model review is promising and repeatedly reported, but its quality benefit
  is still anecdotal and must be measured rather than claimed

The evidence consists mainly of working open-source implementations, their authors'
documented workflows, official runtime guidance, and individual community reports.
It establishes credible use cases, not market size or product-market fit.

Wake-first delivery raises the cost of poor message selection: an irrelevant
message can start a paid model turn. Runtime-wide fan-out remains supported when
explicitly intended, but agent guidance must prefer exact recipients and must not
encourage autonomous broadcast.

## Why These Three Scenarios

They are the smallest suite that tests both product value and the important Relay
interaction shapes:

- dependency/discovery is the core unplanned one-way event and can include a later
  completion/unblock notification
- blocked decision is the minimum asynchronous round trip and exercises
  delivery-derived reply routing
- cross-model review is the strongest repeatable quality hypothesis and exercises a
  bounded multi-hop handoff without making Pallium the workflow owner

Assignments are easy to demonstrate but do not prove Relay's distinctive value,
because they can usually be supplied when the worker starts. Routine progress,
file ownership, fleet management, and interrupted-process recovery either have weak
value evidence or belong to separate coordination/orchestration products.

## Scenario 1 — Unexpected dependency or discovery

Two agents own separate, dependent workstreams. The first discovers a contract,
compatibility fact, or implementation constraint that invalidates the second's
current assumption.

Journey:

1. Both sessions begin with enough context to work independently.
2. The discovering agent sends one targeted finding to the affected session.
3. An idle recipient wakes; a busy recipient gets a separate safe turn.
4. The recipient visibly attributes the message and changes its plan or fixture
   output accordingly.
5. If the recipient cannot wake, the same delivery appears exactly once on its next
   natural turn.

The regression fixture must be anonymized and contain an observable downstream
choice whose correct result changes only after the relayed fact. Assert that an
unrelated registered session is not woken. Completion/unblock notification may be
the final leg of this journey, but routine progress chatter is not.

## Scenario 2 — Blocked decision round trip

A worker encounters an ambiguity owned by another session and must not guess.

Journey:

1. The worker sends a bounded question to the named decision owner and may end its
   turn; Pallium does not poll or hold an LLM tool call open.
2. The decision owner wakes, examines the relevant local evidence, and replies from
   the received delivery ID.
3. Pallium derives reply endpoints and wakes the original worker.
4. The worker applies the decision and produces an observable result.

Assert sender attribution, `in_reply_to`, scope isolation, exactly-once wake and
fallback behavior, and that the reply cannot impersonate or redirect either side.
The scenario should also prove that a late reply still resumes the worker without
a human prompt.

## Scenario 3 — Cross-model review and correction

A builder finishes a bounded change and asks a different runtime/model family to
review it independently.

Journey:

1. The builder sends the exact artifact reference—prefer an immutable commit or
   bounded diff reference—plus the requirement and review lens.
2. The reviewer wakes, inspects the shared local artifact, and sends concrete
   findings to the builder.
3. The builder wakes and corrects the planted semantic defect.
4. A second review request is allowed only as another explicit Relay action; Pallium
   does not own or automatically continue a builder/reviewer loop.

Use a tiny anonymized fixture repository with a deterministic defect and expected
corrected state. Do not assert exact model wording. Assert the referenced artifact,
finding category, final observable behavior, attribution, and bounded turn count.

## Validation Architecture

Maintain two complementary layers:

### Deterministic regression E2E

- drive the same MCP send/reply and runtime adapter or hook surfaces callers use
- assert through Relay status, recipient-visible context, audit, and fixture state
- cover wake, safe busy queuing, fallback, duplicate trigger, restart, expiry,
  permission, scope, alias, and unrelated-recipient behavior
- replay anonymized authored scenarios in CI or the slow suite; mark polling or
  scenario-runner modules `pytest.mark.slow` per `docs/testing-conventions.md`
- assert deterministic contracts and outcomes, never subjective model prose

### Live cross-runtime validation

- run the three journeys with real Claude Code, Codex, and OpenCode integrations
- across the suite, exercise each runtime at least once as sender and once as woken
  recipient; do not pay for every pairwise permutation unless a failure demands it
- require two different runtime/model families for the review scenario
- capture versions, launch/configuration requirements, message and delivery IDs,
  wake/fallback path, timings, turn counts, outcome, and any human intervention
- keep paid model runs as release/product evidence, not a substitute for
  deterministic regression coverage
- promote every confirmed live failure into the smallest anonymized regression
  scenario that reproduces its general failure class

## Measurement and Decision Record

For every live journey, record:

- whether Relay avoided a manual copy or prompt to the recipient
- whether the recipient replied, changed course, or performed the requested review
- send-to-wake, send-to-delivery, and question-to-reply latency
- wake attempts, fallbacks, retries, recipient count, and model turns caused
- irrelevant/no-action, wrong-recipient, stale, duplicate, or loop behavior
- whether the workflow would have been equally easy in the original prompt

Report actual counts and examples before choosing thresholds. The final verdict
must state separately whether the transport contract passed and whether the
workflow demonstrated user value.

## Public Documentation Driven by the Scenarios

Once validated, update public Relay documentation and integration guidance with:

- the positioning: targeted dependency exchange between independently working
  local agents, not an autonomous team manager
- one concise quickstart for each passing scenario
- how to name/select the exact architect, worker, or reviewer session
- wake-first behavior, safe busy queuing, next-turn fallback, attribution, expiry,
  token/turn cost, and permission boundaries
- “when to send”: the recipient's work should change, the sender is blocked on that
  recipient, the recipient is now unblocked, or a concrete review/action is needed
- “when not to send”: routine status, unrelated context, speculative relevance,
  open-ended debate, or “keep everyone informed” broadcast
- how questions and replies work asynchronously without polling

Do not publish claims that cross-model review improves quality, Relay saves time,
or wake is reliable on a runtime unless the corresponding scenario evidence
supports the claim. Keep message intents as guidance and examples; do not add a
protocol enum until real use requires machine-readable behavior.

## Explicit Non-Goals

- spawning, assigning, supervising, or restarting agents
- a planner/worker state machine or durable team-role registry
- automatic reviewer loops, free-form agent conversations, or consensus debates
- semantic recipient inference or agent-initiated broadcast
- file reservations, edit locks, task graphs, queues of assigned work, or ownership
  enforcement; these are separate coordination products
- synchronous LLM waiting or polling for replies
- attachments or structured workflow payloads before plain text plus bounded local
  artifact references proves insufficient

## Done When

1. All three deterministic scenario journeys pass through public Relay and runtime
   integration surfaces, including their failure and fallback paths.
2. Budgeted live runs cover all three runtimes as sender and woken recipient across
   the suite and preserve reproducible evidence without claiming exact prose.
3. Every live defect found during validation has a generalized anonymized
   regression or a documented reason it cannot be deterministic.
4. A written verdict separates transport correctness from observed workflow value
   and reports manual intervention, action/reply, latency, fallback, and turn-cost
   evidence.
5. Public docs, quickstarts, agent guidance, and product positioning use only the
   workflows and claims supported by the recorded results.

## Research References

Practical workflow and implementation evidence:

- [Pi Intercom targeted coordination and planner/worker examples](https://github.com/dataforxyz/agent-intercom-pi)
- [Orc Boss builder/challenger workflow](https://github.com/dataforxyz/orcboss)
- [Agent Mail completion-unblock motivation](https://github.com/osteele/agent-mail)
- [MCP Agent Mail workflows and explicit no-broadcast rule](https://github.com/Dicklesworthstone/mcp_agent_mail_rust)
- [MCP Agent Mail original implementation](https://github.com/dicklesworthstone/mcp_agent_mail)

Runtime and cost guidance:

- [Claude Code cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging)
- [Claude Code agent teams: communication, review, cost, and coordination](https://code.claude.com/docs/en/agent-teams)

Community reports—use as hypotheses, not authoritative validation:

- [Frontend/backend cross-session coordination](https://www.reddit.com/r/ClaudeCode/comments/1vn97ro/i_built_crosssession_messaging_for_claude_code_in/)
- [Autonomous dependency notification between concurrent sessions](https://www.reddit.com/r/ClaudeAI/comments/1vsczag/observation_claude_code_utilizing_autonomous/)
- [Cross-model review and limited-team experience](https://www.reddit.com/r/ClaudeCode/comments/1tbevyy/does_anyone_use_agent_teams_successfully/)
- [One-task-per-session plus main brain workflow](https://www.reddit.com/r/ClaudeCode/comments/1vmey7d/my_claude_code_workflow_after_months_of_daily_use/)
- [Interrupted-session continuation report](https://github.com/anthropics/claude-code/issues/82501)
- [Subagent peer-messaging behavior report](https://github.com/anthropics/claude-code/issues/76388)

Revalidate changing runtime behavior and links when this item starts. The durable
content above is the research conclusion even if an external source later moves.
