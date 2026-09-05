# Session History

Session History records selected user and agent turns so later coding-agent sessions can search earlier work. Scope checks, redaction, telemetry, and forgetting govern what is stored and returned.

It is useful when the important context is not in the current checkout: why a
decision was made, what an earlier investigation found, which constraint shaped
the work, or why an approach was rejected.

## Basic use

Ask the agent to search earlier work in plain language:

> Search Pallium Session History for why we rejected the queue approach.

The agent uses `pallium_search_history` with a query such as:

```text
why did we reject the queue approach?
```

Search returns concise matches with source identifiers. When a match looks
relevant, the agent uses `pallium_expand_source` to open a bounded number of
turns around it.

Search answers “where did we discuss this?” Expansion answers “what was the
surrounding reasoning?” The bounds keep one match from turning into an entire
transcript replay.

## Historical evidence is not live state

Session History reports what an earlier session said or did. It cannot prove
that an external fact is still true.

For example, an earlier turn saying “the pull request is approved” does not
prove that the pull request is approved now. Check the live system for current
status. Pallium labels history results accordingly and identifies known
superseded guidance.

## Scope and governance

History search and expansion enforce the requesting session's container, actor,
and visibility scope before returning content. Expansion applies the same checks
to every surrounding turn.

Pallium records lookup and expansion telemetry, supports raw-turn forgetting,
and applies redaction on both search and expansion.

The current scope model is intended for one local operator. It is not a
cross-user sharing or authorization system.

## Available now

- broad search across accessible earlier sessions with `pallium_search_history`
- bounded surrounding-turn expansion with `pallium_expand_source`
- linked lookup and expansion telemetry
- redaction, visibility checks, and forgetting
- safeguards that distinguish outdated guidance from current replacements
- structural references from supported integrations, including a non-base Git
  branch, an exact Agent Workflow Work Record when safely resolved, and
  explicitly supplied references

## Planned, not yet available

- a separate exact work-scoped search operation
- baseline Session History that runs with every semantic package disabled
- additional navigation and temporary on-demand compression options

Agent Workflow is not required to use Session History. Its Work Record is one
optional structural reference when an integration can resolve it safely.

## What Session History is not

- a record of every tool call forever
- a complete machine audit log
- proof that old external state remains current
- generated summaries by default
- cross-user sharing without an explicit authorization contract

For API details, see [HTTP API](http-api.md). For the direction and validation
plan, see the [Session History vNext strategy](context/strategy-vnext.md).
