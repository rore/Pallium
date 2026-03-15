# Integration-Readiness Bruno Collection

This collection mirrors the canonical integration-readiness milestone for Pallium.

Use it for manual inspection against a local Pallium server after the automated milestone is already green.
The automated runner is still the canonical gate; this collection exists so a human can see the stored items,
query results, and debug trace directly.

## Before You Run

1. Start Pallium locally, preferably with the combined runner:

```powershell
.\.venv\Scripts\python.exe -m app.run --host 127.0.0.1 --port 8000 --processors 1
```
2. Use the `local` Bruno environment in [C:/Dev/rore/Pallium/bruno/environments/local.bru](C:/Dev/rore/Pallium/bruno/environments/local.bru).
3. Run against a fresh local database when possible.

Quick reset helper from the repo root:

```powershell
.\scripts\reset-dev-db.ps1
```

Why a fresh database matters:
- these requests use stable ids and refs for readability
- rerunning them against an old db can create duplicate memory and make inspection noisier

## Folders

### 01-positive-resumed-work

What it proves:
- Pallium can carry forward blocker state, preserved progress, next step, evidence, and freshness
- `task_checkpoint` should be the top useful layer

What to inspect in `/query/debug`:
- top result should be `task_checkpoint`
- blocker should mention the expired service token
- preserved progress should mention the 312 refreshed records / batch 313
- next step should say refresh token and resume from batch 313

### 02-no-value-control

What it proves:
- when the current thread already contains the live blocker and next step, Pallium should not create a fake memory advantage

What to inspect in `/query/debug`:
- no strong higher-level memory should take over just because related older memory exists
- the result set should stay restrained and not surface irrelevant old review details as if they were needed

### 03-scope-guard

What it proves:
- a public query can use public rollout memory
- a public query must not leak limited-scope rollout state even when it is topically similar and sharper

What to inspect in `/query/debug`:
- top result should stay on the public rollout conclusion
- limited-scope blocker details must not appear in results
- visibility trace may report exclusions, but it must not expose hidden candidate ids or hidden context details

## Suggested Manual Flow

For each folder:
1. run the item-ingest requests in sequence
2. run the final `/query/debug` request
3. inspect the returned `results` and `trace`

If you want a rough baseline comparison:
- run the final query first against a fresh empty db
- then ingest the items and run the same query again

## Related Automated Gate

The automated version of this milestone lives under:
- [C:/Dev/rore/Pallium/evals/integration_readiness/scenarios.json](C:/Dev/rore/Pallium/evals/integration_readiness/scenarios.json)
- [C:/Dev/rore/Pallium/evals/integration_readiness_scenario.py](C:/Dev/rore/Pallium/evals/integration_readiness_scenario.py)
- [C:/Dev/rore/Pallium/tests/test_integration_readiness_scenario.py](C:/Dev/rore/Pallium/tests/test_integration_readiness_scenario.py)
