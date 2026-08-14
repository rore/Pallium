# History-pull decision-agent harness — validation report

Validation of a new simulation harness (`evals/history_pull_decision/`) in which
an LLM agent, given the history-search and source-expansion tools, **decides on
its own** whether to pull prior history for each scenario. Agent-chosen pulls
flow through the real service so the historical-lookup reuse-funnel events
persist; the existing rollup (`evals/historical_lookup_measurement.py`) and
reuse-ladder judge (`evals/historical_lookup_judge.py`) — imported as libraries,
not reimplemented — turn those events into Experiment-1-shaped numbers
(design 015, decision-point 1).

This is a **measure-and-flag** report. It produces a first *simulated* lookup
rate, unprompted-pull rate, lookup→useful-result rate, and reuse-ladder rungs. It
does **not** change any product behaviour, and a simulated rate is a **proxy**
for — not a substitute for — the live Phase-1 gate (see Honesty & ceilings).

Re-run commands are at the bottom.

## 1. What the harness does

Per scenario the agent is placed in a **new session** working on a task; relevant
(or irrelevant) prior work is seeded as **past turns in the same container** under
an earlier thread. The agent is **not shown** the prior turns — it only sees the
task and a description of two tools, and decides:

1. whether to call `pallium_search_history(query)` (a source-only search,
   `trigger_origin=agent_pull`), and with what query;
2. after seeing results, whether to `pallium_expand_source(index)` for neighbor
   context, then writes its answer.

If the agent **does not** search, it completes the task from its own general
knowledge (no history); if it **does** search, it writes a final answer over the
retrieved (and optionally expanded) context. Either way a real assistant-work
turn is persisted, so the session is legitimately *substantive* and the judge has
genuine "work after" to inspect. Pulls are **agent-chosen, never scripted** —
that is what makes the numbers non-circular. Tools are modelled as a JSON decision
protocol over `generate_json` (provider-agnostic; mirrors the thin-agent + judge),
not native tool-use.

Design notes:
- Guidance is **tool-description-only** and neutral: the agent is never told
  whether relevant history exists, nor instructed to incorporate it. (Design 015
  lists tool-description-only vs. stronger skill guidance as an Experiment-1
  lever; this run uses the weaker arm.)
- Each scenario runs under its **own container**, so a search only sees that
  scenario's seeded history (no cross-scenario contamination).
- Multi-seed: the seed value is folded into the prompt as an inert tag (same
  trick the judge uses to defeat the seedless LLM cache key), giving independent
  draws per seed.

## 2. What it does NOT validate

- Not the live gate. Authored scenarios cannot establish the real unprompted-pull
  rate on production traffic; they bound realism (§5).
- Not rung-3 (downstream benefit) — controlled-exposure only, by contract.
- Not the installed service's write path: everything runs **in-process** against
  a disposable scratch SQLite DB (§6).
- Not production retrieval/injection behaviour — unchanged and untouched.

## 3. Real multi-seed run — behavioural metrics

Provider/model: the repo's configured default agent-conversation provider/model
(resolved from `pallium.local.toml`). Scenarios: 7 (5 with genuinely relevant
history, 2 self-contained). Seeds: 0,1,2 → **21 trials**. LLM cache on. Zero
errors, zero post-decision soft-failures.

| Metric | Value | Basis |
|---|---|---|
| lookup rate | **0.714** (15/21) | trials where the agent searched |
| unprompted-pull rate | **0.60** (9/15) | searched among scenario-tagged *undirected* trials |
| user-directed pull rate | 1.00 (6/6) | searched among *directed* trials |
| opportunity pull rate | **1.00** (15/15) | searched when relevant history existed |
| no-opportunity pull rate | **0.00** (0/6) | searched when no relevant history existed |
| lookup → non-empty-result | 1.00 (15/15) | searches that returned ≥1 source hit |

The agent **discriminated cleanly**: it searched on 100% of trials where relevant
prior work existed and on **0%** of the self-contained tasks — consistently across
all three seeds. This is the encouraging shape for decision-point 1: given the
tools and no hint, the agent pulled when (and only when) history was relevant.

## 4. Reuse judge + eligibility rollup (real, over the same persisted events)

Reuse-ladder judge (`historical_lookup_judge`, `--eligibility-n 1`), 3 rater seeds
over the 15 lookups:

- genuine opportunity: **15/15** — every lookup judged genuinely relevant.
- Cohen's kappa: **1.0** over 15 double-rated lookups (seeds 0/1). Perfect
  agreement here reflects an easy, well-separated authored set — **not** evidence
  of judge robustness on messy real data (the calibration item owns that; expect
  ~20pp variance in the wild).
- rung breakdown (per sampled lookup, Wilson 95%): incorporation **15/15 = 100%
  [79.6, 100.0]**; influence 0%; downstream 0% (controlled-only).
- judge failures: 0. direction split: 14 `user_directed`, 1 `agent_decided`.

Eligibility rollup (`historical_lookup_measurement`, `eligibility_n=1`, consensus
labels): **21 eligible sessions, 15 lookup events**; rung-1 incorporation
**15/21 = 71.4 per 100 eligible [50.0, 86.2]**; rung-2/3 = 0.

**Hard invariant — visibility violations = 0** (22 events checked, 72 exposed ids;
`cross_container=0`, `forgotten_exposed=0`).

### Before/after the answer-completion fix (CodeRabbit finding 2)

The first version of this report (initial PR) persisted a placeholder
`"(no answer produced)"` on no-search trials, and on search trials where the agent
expanded, the after-results answer was often empty so **no work turn was persisted
at all**. Consequences and the fix:

| | Before | After |
|---|---|---|
| no-search session work turn | placeholder string | real self-completion answer |
| search+expand session work turn | often *none* (empty answer) | real finalize answer over retrieved context |
| judge incorporation (consensus) | 6/15 | **15/15** |
| rung-1 per-100-eligible | 28.6 (6/21) | **71.4 (15/21)** |
| eligible sessions | 21 | 21 (unchanged) |

The incorporation rung rose because searched sessions now actually produce an
answer that uses the retrieved history, giving the judge genuine "work after" to
credit — previously many searched sessions had no visible answer, so the judge
could credit nothing. The finalize prompt is deliberately **neutral** ("use the
retrieved context where genuinely relevant; ignore it where not") — with that
neutral wording incorporation still landed at 15/15, so the high rate reflects the
authored history being genuinely relevant to the opportunity tasks, not a prompt
instructing incorporation. The eligibility **denominator was unchanged (21)**; a
transient intermediate state (14 eligible) while only the placeholder was removed
is what motivated the finalize step.

## 5. Honesty & ceilings

- **Proxy, not the gate.** These are simulated rates over 7 authored scenarios ×
  3 seeds. They demonstrate the harness produces the funnel and the funnel yields
  the Experiment-1 shape end to end; they cannot stand in for the live rate on
  real traffic, which is what decision-point 1 actually turns on.
- **Authored-scenario realism ceiling.** The opportunity/no-opportunity split is
  authored, so the clean 100%/0% discrimination partly reflects that the tasks
  were *written* to be separable. Real tasks are noisier and the pull decision is
  harder; the true unprompted rate could be far lower.
- **Judge direction diverges from the scenario tag — a real finding.** The judge
  labelled **14/15** lookups `user_directed` (1 `agent_decided`), yet 9 were on
  scenario-tagged *undirected* tasks. The undirected tasks still carry soft cues
  ("follow our established approach", "consistent with how we handle holds
  elsewhere"), which the judge reads as the user directing a recall. So the
  harness's tag-based unprompted rate (0.60) and the judge's retrospective
  direction disagree. A cleaner unprompted signal needs tasks with **no**
  reference to prior convention — which may then not motivate a pull at all. This
  tension is the crux of measuring "unprompted" and should shape scenario design
  and the judge's direction rubric before any weight is put on the number.
- **Incorporation is high but bounded by the finalize step.** A searched session
  always ends with a finalize answer over the retrieved context; the wording is
  neutral, but the mere presence of that answer makes incorporation observable.
  Read incorporation as "when the agent pulled genuinely-relevant history, it used
  it," not as an unconditional base rate.
- **Extraction is stubbed.** The service's memory-extraction LLM is a stub;
  source-only retrieval is extraction-independent (it ranks raw turns), so this
  does not touch the measured path. Only the agent's pull decisions and the reuse
  judge use the real LLM.
- **kappa=1.0 is not robustness.** See §4.
- **Small N + no negative lookups.** 15 lookups, all genuine — the agent never
  pulled on a no-opportunity task, so there were no irrelevant lookups to test the
  judge's discrimination.

## 6. Notes

**In-process, no bound port.** The harness drives the service via
`fastapi.testclient.TestClient` against a scratch SQLite DB in a temp/`.local`
dir — the same in-process pattern the funnel e2e tests use. It binds **no network
port**, so the live service/DB (`:19836`) is unreachable from the harness by
construction. This satisfies the isolation requirement more strongly than a
scratch port would; it is a deliberate deviation from the "scratch server on
:19942" suggestion, chosen to avoid Windows uvicorn-thread/file-handle teardown
fragility.

**Fresh-DB discipline.** `--db` refuses to reuse an existing file (reruns would
mix events into one DB the judge then reads); pass `--overwrite` to replace it
(removes the `-wal`/`-shm`/`-journal` sidecars too). `--eligibility-n` (default 1)
is recorded in the run JSON and echoed into the printed judge command, because the
judge/rollup default of 50 would yield 0 eligible sessions for these small seeded
scenarios.

## Re-run

Deterministic self-test (no live LLM):

```
PYTHONPATH="C:/Dev/rore/Pallium/.local/test-env/site-packages;." \
  <cpython> -m pytest tests/test_history_pull_decision_harness.py -x -q
PYTHONPATH="..." <cpython> -m evals.history_pull_decision.harness --dry-run
```

Real run (needs the provider key resolvable in the shell env):

```
PALLIUM_CONFIG_FILE=".../pallium.local.toml" PALLIUM_HAI_API_KEY="$ANTHROPIC_AUTH_TOKEN" \
PYTHONPATH="...;." <cpython> -m evals.history_pull_decision.harness \
  --seeds 0,1,2 --eligibility-n 1 --cache-dir .local/llm-cache \
  --db .local/hpd/scratch.db --overwrite --keep-db --output .local/hpd/run.json
# then, over the produced lookups (note --eligibility-n 1):
<env> <cpython> -m evals.historical_lookup_judge --db .local/hpd/scratch.db \
  --seeds 0,1,2 --eligibility-n 1 --cache-dir .local/llm-cache --output .local/hpd/judge.json
<cpython> -m evals.historical_lookup_measurement --db .local/hpd/scratch.db \
  --eligibility-n 1 --output .local/hpd/rollup.json
```

`<cpython>` is the machine's real interpreter; `<env>` repeats the two env vars.
Scratch DB + run JSONs live under `.local/` (gitignored) and never touch the live
DB.
