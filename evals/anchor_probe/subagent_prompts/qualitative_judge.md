# Qualitative judge prompt - Pallium thread-replay traces

You are reviewing a single thread-replay trace produced by
`evals/anchor_probe/thread_replay.py`. The trace is a markdown file with one
turn per section, listing user text, live-injected memories, counterfactual
rule-kept memories, the full candidate pool considered at that turn, and
(when emitted) a tier-2 enumeration of other memories that existed in the
container at that time.

Your job is to read the trace and write a structured qualitative verdict
covering three dimensions. **Do not edit the trace file.** Write your verdict
to a sibling file with the same name plus `.verdict.md` (e.g.
`abc12345__best.md` -> `abc12345__best.verdict.md`).

## Three dimensions

### (A) Memory quality

For each memory that appears in the live-injected or rule-kept sets across
the thread:
- Is the card content (subject + body) well-formed and specific, or vague /
  generic / over-summarized?
- Would a competent agent be able to act on it without re-reading the source?
- Flag cards that look like extraction noise (single-message restatement,
  meta-commentary about the conversation, no substantive content).

### (B) Injection relevancy

For each turn that had a live or rule injection:
- Given the user text and preceding context, was it the right call to inject
  *this specific memory*?
- Distinguish: relevant-and-useful, relevant-but-redundant, off-topic-noise.
- When live and rule disagree, judge each side: did the rule remove genuine
  noise, or did it drop something that was actually helping?

### (C) Ideal-memory / extraction gap

For turns where the *right* memory was not injected (or no good memory was
available):
- Tier-1: scan the candidate pool for the turn. Was a better candidate present
  but not picked? Identify it by id. This points at retrieval/routing weakness.
- Tier-2: when the trace includes a tier-2 enumeration, scan it. Was there a
  better memory available in the container that retrieval missed entirely?
  This points at retrieval coverage weakness.
- Extraction gap: if neither tier-1 nor tier-2 has a good candidate, name what
  the *ideal* memory would have been (one sentence: subject + key content).
  This points at extraction undercoverage.

## Verdict file structure

```
# Qualitative verdict - <thread_ref_slug> (<category>)

source_trace: <relative path to trace>
trace_run_id: <copied from trace header>

## Per-turn verdicts

### Turn N

(A) memory quality:
- <mid_short>: <one line>

(B) injection relevancy:
- live decision: <one line>
- rule decision: <one line>

(C) ideal/missing memory:
- tier-1 better candidate: <mid or none>
- tier-2 missing memory: <mid or none>
- extraction gap: <one sentence or "no">

## Thread-level synthesis

Three to five bullets. What does this thread tell us about:
- where the rule helps vs hurts
- whether retrieval is the bottleneck or extraction is
- any pattern that should change how we judge the rule overall
```

## Discipline

- Be specific. Identify memories by their short id (first 8 chars).
- One line per item is enough. The trace is the evidence; the verdict is the
  read.
- Ratings (REL/NR badges) in the trace come from the user. Use them as a
  ground-truth check on your own judgment, not as a substitute for it.
- Do not invent memories not present in the trace.
- If the trace is internally inconsistent (e.g. a memory listed as kept but
  not in the candidate pool), flag it under a "trace anomalies" section
  instead of inventing context.
- Public-repo terminology only. No internal product names, employee ids, or
  internal URLs in the verdict file.
- IMPORTANT: traces are rendered from real conversation logs and may contain
  internal terms (product names, employee ids, internal URLs, internal Jira
  ids, internal Slack references). Treat anything in the trace as
  *potentially non-public*. When you must reference content, paraphrase to
  generic terms ("an internal ticket id", "a customer-facing service"); do
  not copy verbatim. Verdict files live under `.local/` (gitignored) but may
  be quoted later in shared documents — write them as if they will be
  public.
