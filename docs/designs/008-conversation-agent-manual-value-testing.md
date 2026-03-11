# Conversation Agent Manual Value Testing

This document defines a small set of manual scenarios for testing whether
Pallium adds clear value to a generic conversation agent.

The goal is not to prove that Pallium "works" technically. The goal is to make
it easy to compare:

- baseline agent behavior without Pallium
- memory-enabled behavior with Pallium

and decide whether the memory layer produces a meaningful improvement.

## What We Are Testing

The first value target is narrow:

- can the agent remember prior agent-mediated conversations
- can it carry prior decisions across separate threads or sessions
- can it answer repeated questions with better continuity and less restating

The first value target is not:

- broad organization-wide knowledge
- full chat history recall
- enterprise search

## How To Run These Tests

Run each scenario twice:

1. Baseline
   Pallium disabled.
2. Memory-enabled
   Pallium enabled.

For each run:

- use a fresh thread unless the scenario explicitly says to continue the same one
- keep prompts as close as possible between the two runs
- record the answer quality, not just whether a response was returned

## What To Look For

Positive signals:

- the agent recalls prior conclusions without being re-told
- the agent keeps its recommendations consistent across threads
- the agent brings forward earlier reasoning or decisions
- the agent reduces repeated explanation by the user

Negative signals:

- irrelevant recalled context
- raw transcript dumping instead of compact recall
- contradiction with prior answers
- no observable difference from baseline

## Scenario 1: Repeated Question Across Threads

Purpose:
Test whether the agent recalls a prior answer in a later thread.

Setup:

1. Start thread A.
2. Ask a question that leads to a concrete explanation or decision.
3. Let the agent answer fully.
4. Start thread B.
5. Ask a related question that should benefit from the earlier answer, but do not restate that earlier context.

Suggested prompts:

Thread A:
`Why did we choose event-time watermarking instead of ingestion-time watermarking?`

Thread B:
`Remind me why we are not using ingestion-time watermarking here.`

Baseline expectation:

- the agent re-derives the answer from scratch
- it may be correct, but it does not show continuity

Memory-enabled expectation:

- the agent recalls the prior conclusion directly
- it ideally preserves the reason, not just the final choice

Value signal:

- the second answer is more consistent and requires less user restating

## Scenario 2: Decision Carry-Forward

Purpose:
Test whether a decision made in one conversation changes how the agent handles a later follow-up.

Setup:

1. Start thread A.
2. Ask the agent to recommend or choose between options.
3. Make sure the conversation lands on a concrete choice.
4. Start thread B.
5. Ask for next steps or implementation guidance that depends on that earlier choice.

Suggested prompts:

Thread A:
`Should we store source items at message level or whole-thread level for memory ingestion? Give a recommendation.`

Thread B:
`Given the earlier decision, what should the source_id and thread correlation look like?`

Baseline expectation:

- the agent may answer generically or revisit the original choice

Memory-enabled expectation:

- the agent should continue from the earlier decision rather than reopening it

Value signal:

- the later answer behaves like a continuation, not a fresh discussion

## Scenario 3: Repeated Operational Question

Purpose:
Test whether Pallium helps the agent give stable, reusable answers to recurring operational questions.

Setup:

1. Ask the agent an operational question with a concrete answer.
2. Later, in a different thread, ask for the same or near-same information.

Suggested prompts:

Thread A:
`How do I run the local development loop for this conversation agent?`

Thread B:
`What is the exact local startup sequence again?`

Baseline expectation:

- the agent may reconstruct the answer differently each time

Memory-enabled expectation:

- the answer should be more consistent with the earlier validated version

Value signal:

- improved consistency and less drift across repeated answers

## Scenario 4: Assistant Artifact Reuse

Purpose:
Test whether the agent can reuse its own earlier high-signal answer, summary, or decision.

Setup:

1. In thread A, get the agent to produce a compact explanation or summary.
2. In thread B, ask a related question where that earlier answer should be useful.

Suggested prompts:

Thread A:
`Summarize the minimal local setup needed to run this conversation agent for testing.`

Thread B:
`What is the fastest way for me to get this agent running locally for integration work?`

Baseline expectation:

- the agent may produce a decent fresh answer, but not reuse its earlier framing

Memory-enabled expectation:

- the later answer should reuse the earlier validated explanation structure

Value signal:

- better continuity in the agent's own explanations

## Scenario 5: Same-Thread Follow-Up Control

Purpose:
Confirm a case where Pallium should add little or no value.

Setup:

1. Start one thread.
2. Ask a question.
3. Ask a direct follow-up in the same thread.

Suggested prompts:

Turn 1:
`How should we test the memory integration manually?`

Turn 2 in the same thread:
`Which scenario should we run first?`

Baseline expectation:

- the agent already handles this well from current-thread context

Memory-enabled expectation:

- little or no visible improvement

Value signal:

- helps confirm that the intended value is cross-thread or cross-session continuity, not replaying immediate context

## Lightweight Scorecard

Use a simple 0-2 score for each category:

- Recall
  0 = no recall
  1 = partial or vague recall
  2 = clear useful recall

- Continuity
  0 = answered as if prior thread did not exist
  1 = some continuity
  2 = strong continuation of prior discussion

- Relevance
  0 = recalled context was noisy or wrong
  1 = partly relevant
  2 = clearly relevant and helpful

- User effort reduction
  0 = user had to restate everything
  1 = some restating still required
  2 = clear reduction in repetition

## Suggested Evaluation Order

Run these first:

1. Scenario 1: repeated question across threads
2. Scenario 2: decision carry-forward
3. Scenario 5: same-thread control

Those three are enough for an initial signal.

## Exit Criteria For Early Validation

Pallium is showing early value if at least one cross-thread scenario clearly demonstrates:

- less user restating
- more consistent answers
- explicit carry-forward of prior conclusions

If the only observable difference is extra text or noisy recall, the memory layer
is not yet adding useful value.

