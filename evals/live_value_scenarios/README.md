# Live Value Scenarios

Tests Pallium's value proposition using real scenarios from production usage.

## What This Tests

Each scenario represents a **specific moment** where Pallium should (or should
not) provide value by injecting memory. Unlike synthetic evals that test
retrieval mechanics, this eval tests the **end-to-end value judgment**: did
Pallium surface the right memory at the right time, and would that memory
actually help the agent?

## How It Works

1. Scenarios are derived from confirmed feedback-rated injection events
2. Each scenario includes a **value story** explaining WHY the memory matters
3. Scenarios run against the live memory pool (no synthetic setup)
4. Assertions are content-pattern based (the pool evolves over time)

## Running

```bash
# Requires running Pallium service
python -m evals.live_value_scenarios.runner

# Custom host
python -m evals.live_value_scenarios.runner --host http://localhost:8000
```

## Scenario Structure

Each scenario specifies:

- **value_story** — what the agent gains from this memory (the WHY)
- **category** — what type of value this represents
- **expected** — what Pallium should do (inject/not inject, which types, content patterns)
- **anti_patterns** — what Pallium should NOT do
- **expected_status** — `"pass"` or `"known_fail"` with documented reason

## Categories

| Category | What it tests |
|----------|---------------|
| `constraint_carry_forward` | User-stated preferences/constraints surface in new threads |
| `investigation_continuation` | Prior findings prevent re-investigation |
| `analysis_handoff` | Analysis results carry to implementation sessions |
| `decision_recall` | Established decisions surface when relevant |
| `negative_no_inject` | Pallium stays silent for operational commands, greetings |

## Adding Scenarios

To add a scenario from live data:

1. Find a confirmed-relevant injection in the query_audit_log
2. Verify the memory still exists and is active
3. Articulate the value story: what does the agent gain?
4. Write expected assertions (type, content patterns)
5. Write anti-patterns (what should NOT be surfaced)
6. Run the eval to confirm pass/fail matches expectations

## Known Limitations

- Runs against live DB — results may shift as the memory pool grows
- Content patterns may need updating when memories are superseded
- The `known_fail` status documents regressions that need routing fixes
- Evidence endpoint enrichment adds latency (one extra HTTP call per block)
