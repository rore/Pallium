# vNext P2 — Cross-Context Work-Continuity Handoff Experiment (Experiment 2)

Measurement-only result for design 015 Phase 2 (idea: work continuity across
sessions and agents). This experiment does **not** build any continuity
mechanism (no session correlation, no agent-routing dimension, no continuation
packaging). It measures whether the shipped P1 primitives — source-only history
search plus bounded source-context expansion — are enough to let a receiving
session continue prior work, versus the manual rituals they would replace.

## The question

When a session must continue work started elsewhere, does a **pointer+pull**
handoff — the source session is *identified* (by shared container), the
receiving session runs a `source_only` search and pulls the relevant raw turns
on demand via `GET /source/{id}/context` — match the **manual baselines**
(paste-a-summary / read-the-transcript) on correctness of prior-work
understanding, while costing the user less orchestration effort?

## Method

One shared continuation-generation path (reused verbatim from the work-
resumption benchmark: `_generate_continuation` / `_score_continuation` /
`_compare_continuations`) is fed by four context sources. Only the context
source differs — the generation and rubric scoring are identical, so the
comparison is apples-to-apples:

| Arm | Context handed to the receiving session |
|---|---|
| `no_memory` | current-thread context only (nothing routed in) |
| `pull_backed` | `source_only` search → top-K source hits → `/source/{id}/context` expansion, assembled from the **actual API response surface** (redacted excerpts + returned neighbor turns) |
| `manual_transcript` | the full prior-session transcript, pasted in |
| `manual_summary` | a human-authored handoff summary, pasted in |

**Correctness** is the reused ~7-dimension continuity rubric (task orientation,
key findings, blocker state, preserved progress, next-step guidance, evidence,
freshness), scored deterministically by lexical signal coverage.

**Orchestration-cost proxy** = the deterministic token count (chars/4) of the
context a *user* must route into the receiving session. The pull arm's raw
context is pulled agent-side, so the user only supplies the pointer+ask (the
query text); the manual arms require the user to paste a summary or the whole
transcript.

**Seed / consensus policy.** Per the repo's judge-variance guidance, the harness
runs ≥3 seeds (independent generations via a per-seed prompt nonce) and reports a
consensus winner — never a single-seed verdict. The scorer is deterministic and
Sonnet's continuations were stable, so observed cross-seed variance was ~0 here;
the multi-seed consensus is still what the verdict is based on.

Cross-session continuity is inherently **private + container-scoped** (raw turns
carry an `actor_ref`, and public retrieval requires `actor_ref is None`), so all
scenarios ingest and query under private visibility.

## Result

Run `real-run-s3-v2` — provider `anthropic_claude`, model `claude-sonnet-4-6`,
3 seeds, top-K = 3, 5 scenarios (4 value + 1 no-value guard). (This is the
corrected re-run after review; see "Corrections" below.)

| Arm | Mean correctness ± spread (value scenarios) | Mean user-orchestration cost (tokens) |
|---|---|---|
| `no_memory` | 0.50 ± 0.00 | 0.0 |
| `pull_backed` | 6.00 ± 0.00 | 19.75 |
| `manual_transcript` | 6.00 ± 0.00 | 70.75 |
| `manual_summary` | 6.00 ± 0.00 | 55.0 |

Spread is the mean per-scenario standard deviation of correctness across the 3
repeatability samples; `± 0.00` means the provider produced stable continuations
for these inputs (measured, not omitted).

- **Consensus winner: `pull_backed` in all 4 value scenarios** (3/3 samples each).
- Pull vs `no_memory`: pull wins 4/4 (memory-free continuation loses prior-work
  understanding).
- Pull vs each manual baseline: **tie on correctness** 4/4, with pull at
  ~2.8–3.6× lower user-orchestration cost (19.75 vs 55.0 / 70.75).
- No-value guard (`same-thread-sufficient-no-value`): `no_memory` wins 3/3. The
  winner rule is now identical for value and no-value scenarios, so a memory arm
  strictly exceeding `no_memory` here *would* flip the winner — the guard is
  falsifiable, and it held.

Per-scenario, the pull arm recovered 2–5 source hits; after de-duplicating
overlapping expansion windows it added 0–2 *new* neighbor turns (0 when every
in-window turn was already a ranked hit) in 3–4 agent-side round-trips.

**Headline:** on these authored scenarios, pointer+pull was at least as correct
as the manual baselines (pull mean 6.00 vs manual mean 6.00) at strictly lower
user-orchestration cost. The shipped P1 primitives are sufficient to stand up the
handoff without any new mechanism.

## Corrections vs the first run

The first run (`real-run-s3`) reported the same *direction* of result, but a
review surfaced methodology bugs that this run fixes; the conclusion is unchanged
but now rests on corrected measurement:

- **No-value guard made falsifiable.** The winner selection previously hard-coded
  `no_memory` for no-value scenarios, so the guard could never fail. It now uses
  the same rule as value scenarios (highest correctness among non-overreaching
  arms; ties to lowest cost, which `no_memory` wins at cost 0).
- **Expansion turns de-duplicated.** Overlapping `/source/{id}/context` windows
  previously double-counted turns (e.g. 6 "expansions" on a 5-turn thread),
  inflating the pull turn count and diverging from the single-copy transcript.
  Turns are now included once; the long-thread scenario shows 2 genuine
  expansions, others 0.
- **Cost aggregate scoped to value scenarios**, matching the correctness column
  (previously it averaged over all scenarios).
- **Headline predicates tightened** to exactly match the wording: "at least as
  correct" = pull mean ≥ manual mean (no tolerance), "strictly lower cost" = pull
  strictly below each manual arm.
- **Spread reported** per arm.

## What this does and does not prove

- **Discriminator is cost, not correctness.** With Sonnet and faithful context,
  every context-bearing arm saturates the rubric (6.00), so correctness does not
  separate pull from the manual baselines — it only confirms pull does not *lose*
  understanding. The measured advantage is the orchestration-cost proxy.
- **Authored scenarios bound realism.** Five hand-written scenarios in a single
  container with clean, on-topic prior turns are an upper bound on retrieval
  quality. Messier corpora, competing topics, and larger histories would stress
  `source_only` lexical/vector recall and the expansion window — not exercised
  here.
- **No session identity, no cross-agent routing.** The source is identified only
  by shared container; this says nothing about automatic session correlation or

- **Discriminator is cost, not correctness.** With Sonnet and faithful context,
  every context-bearing arm saturates the rubric (6.00), so correctness does not
  separate pull from the manual baselines — it only confirms pull does not *lose*
  understanding. The measured advantage is the orchestration-cost proxy.
- **Authored scenarios bound realism.** Five hand-written scenarios in a single
  container with clean, on-topic prior turns are an upper bound on retrieval
  quality. Messier corpora, competing topics, and larger histories would stress
  `source_only` lexical/vector recall and the expansion window — not exercised
  here.
- **No session identity, no cross-agent routing.** The source is identified only
  by shared container; this says nothing about automatic session correlation or
  a first-class agent-handoff dimension. Those remain deferred mechanism, to be
  built only if this value signal holds up under harder inputs.
- **Cost proxy is a proxy.** Token count of user-supplied context is a defensible
  stand-in for orchestration effort, not a user study.
- **Low seed variance is scenario-specific.** The ~20pp judge variance the repo
  documents applies to LLM-judge evals; this harness scores deterministically,
  so near-zero variance here does not generalize to judge-based lanes.

## Re-run commands

```bash
# Point PY at a real CPython interpreter (some managed environments block the
# per-venv Scripts/python.exe stub launchers; use the interpreter directly).
PY="/path/to/cpython/python"   # e.g. a real python3.12+ binary

# Deterministic self-test (no live LLM) + reuse-regression guard
PYTHONPATH="<repo>/.local/test-env/site-packages;." "$PY" -m pytest tests/test_continuity_handoff_benchmark.py -m slow -n0 -q

# Real multi-seed run (uses the repo LLM provider config + the provider API key)
PALLIUM_CONFIG_FILE="<repo>/pallium.local.toml" PALLIUM_HAI_API_KEY="<provider-api-key>" \
PYTHONPATH="<repo>/.local/test-env/site-packages;." "$PY" \
  -m evals.continuity_handoff_benchmark --seeds 3 --cache-dir .local/llm-cache
```

The runner uses an in-process `TestClient` with a scratch temp DB + scratch
vector index per scenario; it never touches the live service or DB.
