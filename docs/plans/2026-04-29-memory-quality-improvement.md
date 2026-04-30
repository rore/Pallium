# Memory Quality Improvement Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve memory extraction quality from D/F to B+/A across all dimensions: decision extraction, noise filtering, type classification, turn_summary quality, interest durability, and atomic_fact relevance.

**Architecture:** Four layers of improvement, in priority order:

1. **Prompt fixes** (primary) — instruct LLMs to produce grounded output and skip ephemeral state
2. **Post-extraction quality gates** (defense-in-depth) — suppress what prompts miss
3. **Thread-level decision detection** (new capability) — extract multi-turn decisions from thread aggregates
4. **Measurement** — corpus-backed eval to validate improvements and catch false negatives

The key architectural insight: the existing grounding checks (`has_grounded_decision_text`, `has_grounded_decision_evidence`) are correct and must not be relaxed. The problem is the LLM **paraphrases** instead of quoting. When instructed to quote verbatim, grounding passes naturally:

```
Source: "I've implemented the dashboard using vanilla HTML/CSS/JS"
Paraphrased decision_text: "Use vanilla HTML/CSS/JS" → FAILS grounding (not a substring)
Quoted decision_text: "implemented the dashboard using vanilla HTML/CSS/JS" → PASSES grounding
```

**Tech Stack:** Python 3.12+, pytest, existing eval infrastructure (`evals/semantic_runner.py`), SQLite corpus at `~/.pallium/data/pallium.db`

**Validation:** Every change is validated by (a) existing tests pass, (b) new unit tests for the specific fix, and (c) re-extraction against real corpus items shows improvement.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `semantic/llm_agent_memory.py` | Extraction prompt — decision quoting rules, implicit-decision detection |
| `semantic/conversational_knowledge.py` | Fact extraction prompt — stronger ephemeral negatives + post-filter |
| `semantic/common.py` | Quality gates: turn_summary suppression, interest durability, source pre-filter |
| `semantic/agent_conversation_memory_threads.py` | Thread-level decision detection from conversational flow |
| `tests/test_extraction_quality_gates.py` | Unit tests for all new quality gates |
| `evals/memory_quality_eval.py` | Corpus-backed dimension scorer (measures before/after) |
| `evals/memory_quality_corpus.jsonl` | Annotated real corpus with expected outcomes + must_not_suppress flags |
| `evals/semantic/input/items.jsonl` | Extended with implicit-decision and ephemeral-state test items |

---

### Task 1: Fix Decision Prompt — Require Verbatim Quoting

**Root cause:** The LLM paraphrases `decision_text` into a statement that doesn't appear in the source. The grounding check correctly rejects it. Fix: instruct the LLM to quote the source fragment verbatim.

**Files:**
- Modify: `semantic/llm_agent_memory.py:277-316` (the `strict_typed_memory_v8b_work_refs_separate` variant)
- Modify: `evals/semantic/input/items.jsonl` (add implicit-decision test cases)
- Test: `evals/semantic_runner.py` (run comparative eval)

- [ ] **Step 1: Add implicit-decision test items to eval corpus**

Append to `evals/semantic/input/items.jsonl`:

```jsonl
{"source_type": "assistant_artifact", "source_id": "decision-implicit-001", "content_type": "text/plain", "content": "Done. I've implemented the dashboard using vanilla HTML/CSS/JS — no framework, no build step, just a single static file served from the /dashboard route. This gives us zero dependencies and instant loading.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "workspace:library-alpha", "thread_ref": "thread-impl-1", "actor_ref": "agent:assistant", "source_ref": "memory://fixture/decision-implicit-001", "occurred_at": "2026-03-09T11:01:00Z", "metadata": {"topic": "implementation_decision", "expected_kind": "decision"}}
{"source_type": "assistant_artifact", "source_id": "decision-implicit-002", "content_type": "text/plain", "content": "Fixed. The service install now writes only the LLM provider and the two production package sections to the config file. Everything else uses built-in defaults. This keeps the config minimal and maintainable.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "workspace:library-alpha", "thread_ref": "thread-impl-2", "actor_ref": "agent:assistant", "source_ref": "memory://fixture/decision-implicit-002", "occurred_at": "2026-03-09T11:02:00Z", "metadata": {"topic": "implementation_decision", "expected_kind": "decision"}}
{"source_type": "assistant_artifact", "source_id": "decision-implicit-003", "content_type": "text/plain", "content": "Switched the embedding model to multilingual-e5-small across all config paths. This is now the default for all new installations.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "workspace:library-alpha", "thread_ref": "thread-impl-3", "actor_ref": "agent:assistant", "source_ref": "memory://fixture/decision-implicit-003", "occurred_at": "2026-03-09T11:03:00Z", "metadata": {"topic": "implementation_decision", "expected_kind": "decision"}}
{"source_type": "assistant_artifact", "source_id": "decision-implicit-004", "content_type": "text/plain", "content": "The demo packages have been removed from the default configuration. Only agent_conversation_memory and conversational_knowledge are active by default now.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "workspace:library-alpha", "thread_ref": "thread-impl-4", "actor_ref": "agent:assistant", "source_ref": "memory://fixture/decision-implicit-004", "occurred_at": "2026-03-09T11:04:00Z", "metadata": {"topic": "implementation_decision", "expected_kind": "decision"}}
```

- [ ] **Step 2: Update the extraction prompt**

In `semantic/llm_agent_memory.py`, replace the `strict_typed_memory_v8b_work_refs_separate` prompt's Typed Memory Classification section. Key changes: (a) explicit quoting requirement for all fields, (b) recognize implementation-confirms-choice as a decision pattern.

```python
"""You extract reusable typed memory and work-state signals from one technical source item. Return exactly one JSON object and no extra prose.

## Typed Memory Classification

Only promote to typed memory when the source contains explicit evidence:
- decision: requires committed-choice language:
  - Explicit: "Decision:", "we decided", "we chose", "chosen approach", "we will use".
  - Implementation-confirms-choice: the assistant reports completing a specific technical approach ("Done. I've implemented X using Y", "Switched to X", "Fixed. Now uses Y", "Removed X from Y"). The implementation report IS the decision evidence — the choice was made and executed.
- investigation_outcome: requires resolved-finding language ("Root cause:", "Investigation found", "Analysis found", "Findings:", "Outcome:", "We found that", "Verdict:", "Conclusion:", "Investigation concluded", "The conclusion is").
- interest: the user (not the assistant) identifies a specific named subject as worth future attention but does not commit to a concrete action or timeline. Fill interest_text with the subject. No proof phrase needed. Do NOT classify as interest: assistant responses, follow-up questions without a named subject, backward-looking recall, or restatements of prior content.
- otherwise candidate_type = null.

CRITICAL GROUNDING RULE: decision_text, decision_evidence_text, investigation_text, and investigation_evidence_text must be EXACT QUOTES copied from the source text. Do not paraphrase or rewrite. Copy a substring of the source verbatim (you may trim to the essential fragment but never rephrase).

For implementation-confirms-choice decisions:
- decision_text: quote the fragment naming the chosen approach (e.g., "implemented the dashboard using vanilla HTML/CSS/JS")
- decision_evidence_text: quote the broader context confirming it's a committed choice (e.g., "I've implemented the dashboard using vanilla HTML/CSS/JS — no framework, no build step")

REJECT as null: needs, proposals, preferences, recommendations, symptoms, risks, monitoring notes, status updates, and unresolved discussion.
REJECT as null for decision: progress updates that don't name a specific chosen approach ("Fixed the bug", "Tests pass now"), partial implementations that haven't committed to a design, and generic completions without a named technical choice.
"""
```

- [ ] **Step 3: Run the semantic eval to compare baseline vs new prompt**

Run: `python -m evals.semantic_runner --variants strict_typed_memory_v8b_work_refs_separate --input evals/semantic/input/items.jsonl`
Expected: Decision promotion rate increases for implicit-decision items. Existing decisions still pass. No new false positives on discussion/status items.

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass (prompt text changes don't break deterministic mocks)

- [ ] **Step 5: Commit**

```bash
git add semantic/llm_agent_memory.py evals/semantic/input/items.jsonl
git commit -m "feat: improve decision detection — require verbatim quoting, recognize implementation-confirms-choice"
```

---

### Task 2: Strengthen Fact Extraction Prompt — Skip Ephemeral State

The fact prompt already says "skip runtime/deployment/debug status" but lacks concrete negative examples. The LLM still extracts port numbers, PIDs, test counts.

**Files:**
- Modify: `semantic/conversational_knowledge.py:119-147` (`FACT_EXTRACTION_SYSTEM_PROMPT`)

- [ ] **Step 1: Update the fact extraction prompt with explicit negatives**

Replace the "Skip:" section in `FACT_EXTRACTION_SYSTEM_PROMPT`:

```python
FACT_EXTRACTION_SYSTEM_PROMPT = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true — if a statement contradicts common knowledge or a prior fact, still extract it. "
    "Each fact should answer a possible future question about these people, places, events, or preferences. "
    "Each statement must be self-contained and explicitly name its subject; do not return subjectless predicate fragments. "
    "Extract: names, dates, numbers, places, activities, preferences, relationships, events, stated plans, "
    "emotional reactions to significant events, what was discussed or learned, recommendations between people. "
    "\n\n"
    "SKIP (never extract):\n"
    "- greetings, filler, generic encouragement, meta-conversation, trivial restatements\n"
    "- hypothetical or conditional future states\n"
    "- current runtime/deployment/debug status: port numbers, PIDs, uptime, memory usage, process counts, disk sizes\n"
    "- test results: 'all N tests pass', 'test suite green', specific test counts\n"
    "- git state: commit hashes ('committed as abc1234'), push confirmations, branch status\n"
    "- one-off failures, monitoring chatter, and generic platform behavior instructions\n"
    "- assistant's own options, recommendations, or brainstorming (these are not facts about the user)\n"
    "\n"
    "BAD (do NOT extract):\n"
    "- {\"subject\": \"service\", \"statement\": \"service runs on port 19836\"} — ephemeral runtime\n"
    "- {\"subject\": \"tests\", \"statement\": \"All 1579 tests pass\"} — transient test result\n"
    "- {\"subject\": \"commit\", \"statement\": \"committed with hash 9e19594\"} — git state\n"
    "- {\"subject\": \"process\", \"statement\": \"3 processes using 5MB each\"} — runtime snapshot\n"
    "- {\"subject\": \"assistant\", \"statement\": \"assistant recommends option A\"} — not a user fact\n"
    "\n"
    "If the same fact is mentioned multiple times, extract it once in its most specific form. "
    "Resolve relative dates using the session date. \"Last Tuesday\" with session date 2024-03-15 → \"approximately 2024-03-12\". "
    "\n\n"
    "SPECIFICITY: Preserve proper nouns (country names, book titles, pet names), qualifying details "
    "('abstract art' not 'art', 'single parent' not 'parent'), activity specifics "
    "('roasted marshmallows and hiked' not 'went camping'), and what was discussed/learned at events. "
    "Extract aside mentions in multi-topic turns. Never produce a vague version alongside a specific one. "
    "\n"
    "Good: {\"subject\": \"Jordan\", \"statement\": \"Jordan completed a half-marathon in Denver on approximately 2024-03-12\", \"category\": \"event\"}\n"
    "Bad: {\"subject\": \"Jordan\", \"statement\": \"Jordan likes running\", \"category\": \"personal\"} — too vague.\n"
    "\n"
    "Return JSON with key 'facts' containing up to 20 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "Prioritize facts with names, dates, numbers, or specific details. "
    "If no extractable facts, return {\"facts\": []}. "
    "\n"
    "LANGUAGE: Examples above are in English for illustration only. "
    "Write statements in the same language as the conversation. Do not translate."
)
```

- [ ] **Step 2: Run existing tests**

Run: `python -m pytest tests/test_incremental_fact_extraction.py tests/test_container_extraction_edge_cases.py -x -q`
Expected: PASS (these use LLM mocks, prompt text doesn't affect them)

- [ ] **Step 3: Commit**

```bash
git add semantic/conversational_knowledge.py
git commit -m "feat: strengthen fact extraction prompt — explicit negative examples for ephemeral runtime state"
```

---

### Task 3: Add Ephemeral Fact Post-Filter (Defense-in-Depth)

Even with better prompts, add a regex-based safety net that catches ephemeral facts the LLM still produces.

**Files:**
- Modify: `semantic/conversational_knowledge.py` (add `_is_ephemeral_fact` function + integrate)
- Create: `tests/test_extraction_quality_gates.py`

- [ ] **Step 1: Write failing tests for the ephemeral filter**

```python
"""Tests for extraction quality gates."""
import pytest
from semantic.conversational_knowledge import _is_ephemeral_fact


class TestEphemeralFactFilter:
    def test_filters_port_number(self):
        assert _is_ephemeral_fact({"subject": "Pallium service", "statement": "Pallium service runs on port 19836", "category": "event"})

    def test_filters_test_count(self):
        assert _is_ephemeral_fact({"subject": "test suite", "statement": "All 1579 tests pass", "category": "event"})

    def test_filters_commit_hash(self):
        assert _is_ephemeral_fact({"subject": "service", "statement": "Service lifecycle feature was committed with commit hash 9e19594", "category": "event"})

    def test_filters_uptime(self):
        assert _is_ephemeral_fact({"subject": "Pallium", "statement": "Pallium service uptime is 4.5 seconds", "category": "event"})

    def test_filters_pid(self):
        assert _is_ephemeral_fact({"subject": "Pallium", "statement": "Pallium service was running as PID 36440", "category": "event"})

    def test_filters_process_count(self):
        assert _is_ephemeral_fact({"subject": "Pallium", "statement": "Pallium has 3 small wrapper processes each using 5MB memory", "category": "event"})

    def test_keeps_durable_preference(self):
        assert not _is_ephemeral_fact({"subject": "Pallium packages", "statement": "Demo packages should never be activated", "category": "preference"})

    def test_keeps_architecture_choice(self):
        assert not _is_ephemeral_fact({"subject": "dashboard", "statement": "dashboard uses vanilla HTML/CSS/JS with no framework dependencies", "category": "preference"})

    def test_keeps_named_model_choice(self):
        assert not _is_ephemeral_fact({"subject": "embedding", "statement": "multilingual-e5-small was chosen as the embedding model", "category": "preference"})

    def test_keeps_user_activity_without_numbers(self):
        assert not _is_ephemeral_fact({"subject": "user", "statement": "user requested a documentation pass covering install and dashboard docs", "category": "activity"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_extraction_quality_gates.py::TestEphemeralFactFilter -x -q`
Expected: FAIL — function doesn't exist yet

- [ ] **Step 3: Implement the filter**

In `semantic/conversational_knowledge.py`, add:

```python
import re

_EPHEMERAL_PATTERNS = [
    re.compile(r"\bport \d{4,5}\b", re.IGNORECASE),
    re.compile(r"\bPID \d+\b"),
    re.compile(r"\ball \d+ tests? pass", re.IGNORECASE),
    re.compile(r"\d+ tests? (?:pass|green|succeed)", re.IGNORECASE),
    re.compile(r"commit(?:ted)? (?:hash |with hash )?[0-9a-f]{7,}", re.IGNORECASE),
    re.compile(r"\buptime (?:is|of|was) ", re.IGNORECASE),
    re.compile(r"running (?:as|for|on|with) (?:PID|port|\d)", re.IGNORECASE),
    re.compile(r"\d+\s*(?:MB|GB|KB)\s*(?:memory|RAM|disk|each)", re.IGNORECASE),
    re.compile(r"\b\d+ (?:small |wrapper )?processes?\b", re.IGNORECASE),
]


def _is_ephemeral_fact(fact: dict) -> bool:
    """Return True if a fact describes transient runtime state."""
    category = fact.get("category", "")
    if category in ("preference", "relationship", "personal"):
        return False
    statement = fact.get("statement", "")
    return any(p.search(statement) for p in _EPHEMERAL_PATTERNS)
```

Integrate into the extraction flow — in `build_thread_summary`, after the existing quality filters (after `_canonicalize_fact_statement` and `fact_statement_is_quality_viable` checks), add:

```python
new_facts = [f for f in new_facts if not _is_ephemeral_fact(f)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_extraction_quality_gates.py::TestEphemeralFactFilter -x -q`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add semantic/conversational_knowledge.py tests/test_extraction_quality_gates.py
git commit -m "feat: add ephemeral fact post-filter — regex safety net for runtime state"
```

---

### Task 4: Strengthen Discussion Summary Quality Gate

Suppress summaries that are too short or are just restating a user question without any outcome.

**Files:**
- Modify: `semantic/common.py:500-517` (`_is_substantive_summary`)
- Modify: `tests/test_extraction_quality_gates.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_extraction_quality_gates.py`:

```python
from core.models import SourceItem
from semantic.common import SemanticExtraction, _should_create_turn_summary


def _make_source(content: str, role: str = "user") -> SourceItem:
    return SourceItem(
        source_type="test",
        source_id="test-gate-1",
        content_type="text/plain",
        content=content,
        role=role,
        container_ref="test",
        visibility="private",
    )


def _make_extraction(summary: str, **kwargs) -> SemanticExtraction:
    return SemanticExtraction(summary=summary, **kwargs)


class TestDiscussionSummaryQualityGate:
    def test_suppresses_very_short_summary(self):
        source = _make_source("what?")
        extraction = _make_extraction("what?")
        assert not _should_create_turn_summary(source, extraction)

    def test_suppresses_bare_user_question(self):
        source = _make_source("why is it like that?")
        extraction = _make_extraction("User asks why it is like that.")
        assert not _should_create_turn_summary(source, extraction)

    def test_suppresses_user_instructs_short(self):
        source = _make_source("ok, delete it")
        extraction = _make_extraction("User instructs to confirm deletion.")
        assert not _should_create_turn_summary(source, extraction)

    def test_suppresses_user_opened_file(self):
        source = _make_source("User opened foo.py")
        extraction = _make_extraction("User opened the file foo.py in the IDE.")
        assert not _should_create_turn_summary(source, extraction)

    def test_allows_substantive_outcome(self):
        source = _make_source(
            "Root cause analysis: SQL race condition in claim_next_source_item caused duplicate processing"
        )
        extraction = _make_extraction(
            "Root cause analysis and fixes for duplicate memory items: SQL race condition in claim_next_source_item, vector index corruption from killed process"
        )
        assert _should_create_turn_summary(source, extraction)

    def test_allows_summary_with_explicit_signal(self):
        source = _make_source("We fixed the race condition and all tests pass now.")
        extraction = _make_extraction(
            "Fixed race condition, tests passing.",
            progress_text="Race condition fixed in claim_next_source_item",
        )
        assert _should_create_turn_summary(source, extraction)

    def test_allows_long_user_asks_with_outcome(self):
        """Longer 'User asks...' summaries that also contain the answer should pass."""
        source = _make_source("Does the install create the directory structure?")
        extraction = _make_extraction(
            "User asking whether the install process creates the directory structure and files. The service install creates the full layout including config, logs, and run directories."
        )
        assert _should_create_turn_summary(source, extraction)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_extraction_quality_gates.py::TestDiscussionSummaryQualityGate -x -q`
Expected: FAIL on `test_suppresses_very_short_summary` and `test_suppresses_bare_user_question`

- [ ] **Step 3: Implement stronger quality gate**

In `semantic/common.py`, replace `_is_substantive_summary`:

```python
_BARE_RESTATEMENT_PREFIXES = (
    "user asks",
    "user asking",
    "user requests",
    "user requesting",
    "user instructs",
    "user opened",
    "user is asking",
    "user is requesting",
    "user is requesting",
)

_MINIMUM_SUBSTANTIVE_SUMMARY_LENGTH = 30


def _is_substantive_summary(source_item: SourceItem, extraction: SemanticExtraction) -> bool:
    if _looks_like_low_value_meta_update(source_item, extraction):
        return False
    if _has_explicit_thread_signal(extraction):
        return True
    summary = extraction.summary.strip()
    if len(summary) < _MINIMUM_SUBSTANTIVE_SUMMARY_LENGTH:
        return False
    summary_lower = summary.lower()
    if any(summary_lower.startswith(prefix) for prefix in _BARE_RESTATEMENT_PREFIXES):
        if len(summary) < 100:
            return False
    summary_tokens = tokenize_text(extraction.summary)
    content_tokens_list = tokenize_text(source_item.content)
    if len(summary_tokens) >= 4:
        return True
    return len(content_tokens_list) >= 4
```

The threshold of `< 100` for bare-restatement prefixes means:
- "User asks why it is like that." (31 chars) → suppressed
- "User asks... The service install creates the full layout including config..." (150+ chars) → allowed (contains the answer too)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_extraction_quality_gates.py::TestDiscussionSummaryQualityGate -x -q`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add semantic/common.py tests/test_extraction_quality_gates.py
git commit -m "feat: strengthen turn_summary quality gate — suppress short/question-only summaries"
```

---

### Task 5: Add Interest Durability Filter

Reject interest memories that are too vague or are just single-turn questions rephrased.

**Files:**
- Modify: `semantic/common.py:347-349` (add `_is_durable_interest` gate)
- Modify: `tests/test_extraction_quality_gates.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_extraction_quality_gates.py`:

```python
from semantic.common import _is_durable_interest


class TestInterestDurability:
    def test_rejects_generic_two_word(self):
        assert not _is_durable_interest("architectural review")

    def test_rejects_single_word(self):
        assert not _is_durable_interest("review")

    def test_rejects_question_form(self):
        assert not _is_durable_interest("why is the summary field absent?")

    def test_rejects_vague_evaluation(self):
        assert not _is_durable_interest("pallium effectiveness evaluation")

    def test_accepts_specific_task_with_context(self):
        assert _is_durable_interest("Pallium memory extraction quality audit — evaluating correctness and value of stored items")

    def test_accepts_feature_integration(self):
        assert _is_durable_interest("Memory Feedback feature integration in the dashboard")

    def test_accepts_concrete_documentation_task(self):
        assert _is_durable_interest("public documentation pass for pallium (local setup/service install, Claude integration, dashboard)")

    def test_rejects_linux_ad_push_no_context(self):
        """Completely context-free fragment."""
        assert not _is_durable_interest("Linux ad push")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_extraction_quality_gates.py::TestInterestDurability -x -q`
Expected: FAIL

- [ ] **Step 3: Implement durability check**

In `semantic/common.py`, add:

```python
_VAGUE_INTEREST_TAILS = frozenset({
    "review", "evaluation", "analysis", "investigation",
    "debugging", "testing", "implementation", "push",
})


def _is_durable_interest(interest_text: str) -> bool:
    """Return True if the interest is specific enough to be reusable across sessions."""
    text = interest_text.strip()
    words = text.split()
    if len(words) < 3:
        return False
    if text.endswith("?"):
        return False
    text_lower = text.lower()
    # "X evaluation", "Y review" — too generic without qualifying context
    if len(words) <= 3 and words[-1] in _VAGUE_INTEREST_TAILS:
        return False
    # Must have some specificity marker: parenthetical, dash-separated context, proper noun density
    has_specificity = (
        "(" in text
        or "—" in text
        or " - " in text
        or len(words) >= 6
        or any(w[0].isupper() and len(w) > 2 for w in words[1:])  # non-first proper noun
    )
    return has_specificity
```

Integrate at line 347 of `build_process_result`:

```python
    elif not extraction.is_low_value_meta and extraction.candidate_type == "interest" and extraction.interest_text and (
        not source_item.role or source_item.role.lower() == "user"
    ) and source_item.visibility not in ("container", "public") and _is_durable_interest(extraction.interest_text):
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_extraction_quality_gates.py::TestInterestDurability -x -q`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add semantic/common.py tests/test_extraction_quality_gates.py
git commit -m "feat: add interest durability filter — reject vague or context-free interest subjects"
```

---

### Task 6: Add Source Pre-Filter (Both Packages)

Skip extraction for very short messages and bare IDE events. Applied at both package entry points to avoid wasting LLM calls.

**Files:**
- Modify: `semantic/common.py` (add `should_skip_extraction`)
- Modify: `semantic/llm_agent_memory.py` (integrate pre-filter)
- Modify: `semantic/conversational_knowledge.py` (integrate pre-filter in thread item filtering)
- Modify: `tests/test_extraction_quality_gates.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_extraction_quality_gates.py`:

```python
from semantic.common import should_skip_extraction


class TestSourcePreFilter:
    def test_skips_very_short_user_message(self):
        source = _make_source("what?")
        assert should_skip_extraction(source)

    def test_skips_single_word(self):
        source = _make_source("ok")
        assert should_skip_extraction(source)

    def test_skips_ide_event(self):
        source = _make_source("<ide_opened_file>The user opened foo.py in the IDE.</ide_opened_file>")
        assert should_skip_extraction(source)

    def test_keeps_substantive_user_message(self):
        source = _make_source("I want the dashboard to use a dark theme with monospace font")
        assert not should_skip_extraction(source)

    def test_keeps_short_decision_approval(self):
        source = _make_source("yes, use that approach")
        assert not should_skip_extraction(source)

    def test_keeps_assistant_output_even_if_short(self):
        source = _make_source("Done. Implemented.", role="assistant")
        assert not should_skip_extraction(source)

    def test_keeps_constraint_language(self):
        source = _make_source("don't use that")
        assert not should_skip_extraction(source)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_extraction_quality_gates.py::TestSourcePreFilter -x -q`
Expected: FAIL

- [ ] **Step 3: Implement pre-filter**

In `semantic/common.py`:

```python
_APPROVAL_CUES = {"yes", "yeah", "yep", "correct", "exactly", "approved", "go ahead", "do it", "ship it"}
_CONSTRAINT_CUES = {"don't", "dont", "never", "must not", "should not", "no ", "stop"}
_MINIMUM_EXTRACTION_LENGTH = 15


def should_skip_extraction(source_item: SourceItem) -> bool:
    """Return True if source item is too low-value to warrant LLM extraction."""
    content = (source_item.content or "").strip()

    if "<ide_opened_file>" in content and len(content) < 200:
        return True

    if len(content) < _MINIMUM_EXTRACTION_LENGTH:
        content_lower = content.lower().rstrip("!.,")
        if any(cue in content_lower for cue in _APPROVAL_CUES):
            return False
        if any(cue in content_lower for cue in _CONSTRAINT_CUES):
            return False
        return True

    if (source_item.role or "").lower() == "assistant":
        return False

    return False
```

- [ ] **Step 4: Integrate into llm_agent_memory.py**

In `process_item` method (or `analyze_item`), add at the top:

```python
from semantic.common import should_skip_extraction

# At the start of process_item:
if should_skip_extraction(source_item):
    return build_process_result(
        source_item=source_item,
        extraction=SemanticExtraction(summary="", is_low_value_meta=True),
        schema_prefix="llm",
    )
```

- [ ] **Step 5: Integrate into conversational_knowledge.py thread item filtering**

In the `build_thread_summary` method, when building `thread_text` from source items, skip items that match the pre-filter:

```python
# When building chunk text from thread items, skip low-value items
eligible_items = [item for item in new_items if not should_skip_extraction(item)]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_extraction_quality_gates.py::TestSourcePreFilter -x -q`
Expected: PASS

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add semantic/common.py semantic/llm_agent_memory.py semantic/conversational_knowledge.py tests/test_extraction_quality_gates.py
git commit -m "feat: add source pre-filter — skip very short messages and IDE events in both packages"
```

---

### Task 7: Thread-Level Decision Detection (Merged into Existing Call)

Detect multi-turn decisions during thread rebuild by extending the *existing* thread summary LLM call. The thread summary already uses `generate_json` — we add a `"decisions"` field to the schema so the same call returns both summary and any decisions from the conversational flow. Zero additional LLM cost.

The thread aggregate contains all turns as `thread_material`, so grounding checks pass naturally against the full text.

**Files:**
- Modify: `semantic/agent_conversation_memory_threads.py` (extend both prompt variants + schema + post-parse logic)
- Create: `tests/test_thread_decision_detection.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_thread_decision_detection.py`:

```python
"""Test thread-level decision detection via merged thread summary call."""
import json
import pytest
from unittest.mock import MagicMock
from semantic.agent_conversation_memory_threads import _validate_thread_decisions


class TestValidateThreadDecisions:
    """Test the grounding validation applied to LLM-returned decisions."""

    def test_accepts_grounded_decision(self):
        thread_text = (
            "[user] I think the dashboard should use vanilla HTML/CSS/JS, no framework\n"
            "[assistant] Done. I've implemented the dashboard using vanilla HTML/CSS/JS — "
            "no framework, no build step, just a single static file.\n"
        )
        raw_decisions = [
            {
                "decision_text": "implemented the dashboard using vanilla HTML/CSS/JS",
                "evidence": "I've implemented the dashboard using vanilla HTML/CSS/JS — no framework, no build step",
            }
        ]
        result = _validate_thread_decisions(raw_decisions, thread_text)
        assert len(result) == 1
        assert "vanilla" in result[0]["decision_text"]

    def test_rejects_hallucinated_decision(self):
        thread_text = "[user] Should we use React?\n[assistant] Let me think about it.\n"
        raw_decisions = [
            {
                "decision_text": "chose React for the frontend",
                "evidence": "we decided to use React",
            }
        ]
        result = _validate_thread_decisions(raw_decisions, thread_text)
        assert len(result) == 0

    def test_rejects_empty_fields(self):
        thread_text = "[user] Use vanilla JS\n[assistant] Done.\n"
        raw_decisions = [{"decision_text": "", "evidence": "Done."}]
        result = _validate_thread_decisions(raw_decisions, thread_text)
        assert len(result) == 0

    def test_returns_empty_for_none_input(self):
        result = _validate_thread_decisions(None, "some text")
        assert result == []

    def test_returns_empty_for_non_list(self):
        result = _validate_thread_decisions("not a list", "some text")
        assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_thread_decision_detection.py -x -q`
Expected: FAIL — `_validate_thread_decisions` doesn't exist

- [ ] **Step 3: Extend schema descriptions**

In `semantic/agent_conversation_memory_threads.py`, update both schema descriptions to include the `decisions` field:

```python
THREAD_SUMMARY_SCHEMA_DESCRIPTION = json.dumps(
    {
        "summary": "string",
        "content_quality": "string",
        "retrieval_context": "string or null",
        "decisions": [{"decision_text": "string (exact quote)", "evidence": "string (exact quote)"}],
    },
    indent=2,
)
```

And for the checkpoint variant, add the same `decisions` key to `THREAD_SUMMARY_WITH_CHECKPOINT_SCHEMA_DESCRIPTION`.

- [ ] **Step 4: Extend both system prompts**

Append to both `THREAD_SUMMARY_SYSTEM_PROMPT` and `THREAD_SUMMARY_WITH_CHECKPOINT_SYSTEM_PROMPT`:

```python
    "For decisions: identify choices that were made AND committed during the thread. "
    "A decision exists when a specific approach was proposed or discussed AND then implemented, confirmed, or accepted. "
    "For each decision, decision_text and evidence must be EXACT QUOTES copied verbatim from the thread items. Do not paraphrase. "
    "Not decisions: unresolved discussion, proposals without follow-through, questions, status updates, preferences without implementation. "
    "Return an empty array if no decisions were committed in this thread."
```

- [ ] **Step 5: Implement grounding validation function**

Add to `semantic/agent_conversation_memory_threads.py`:

```python
from semantic.common import _normalize_for_containment


def _validate_thread_decisions(raw_decisions: any, thread_text: str) -> list[dict]:
    """Validate and filter thread decisions by grounding check.

    Both decision_text and evidence must be literal substrings of thread_text.
    """
    if not isinstance(raw_decisions, list):
        return []
    normalized_thread = _normalize_for_containment(thread_text)
    grounded = []
    for d in raw_decisions:
        if not isinstance(d, dict):
            continue
        dt = d.get("decision_text", "")
        ev = d.get("evidence", "")
        if (
            dt and ev
            and _normalize_for_containment(dt) in normalized_thread
            and _normalize_for_containment(ev) in normalized_thread
        ):
            grounded.append({"decision_text": dt, "evidence": ev})
    return grounded
```

- [ ] **Step 6: Integrate into build_thread_summary post-parse**

After `response = provider.generate_json(...)` and the existing summary parsing, add:

```python
# Extract thread-level decisions from the same LLM response
raw_decisions = response.parsed_json.get("decisions")
thread_decisions = _validate_thread_decisions(raw_decisions, thread_material)
```

Then after the thread_summary MemoryObject and relations are built, create decision objects:

```python
for td in thread_decisions:
    decision_memory = MemoryObject(
        type="decision",
        schema_id=f"{thread_summary_schema_id.rsplit('.', 1)[0]}.decision",
        schema_version="v1",
        payload={
            "decision": td["decision_text"],
            "decision_evidence_text": td["evidence"],
            "rationale": None,
            "canonical_key": normalize_for_index(td["decision_text"]),
            "source_type": "thread_detection",
            "source_id": f"thread:{aggregate.thread_ref}",
            "semantic_provenance": semantic_provenance,
        },
        visibility=aggregate.visibility,
        container_ref=aggregate.container_ref,
        actor_ref=None,
    )
    memory_objects.append(decision_memory)
    for source_item_id in aggregate.source_item_ids:
        relations.append(Relation(
            from_kind="memory_object",
            from_id=decision_memory.id,
            relation_type="supported_by",
            to_kind="source_item",
            to_id=source_item_id,
        ))
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_thread_decision_detection.py -x -q`
Expected: PASS

- [ ] **Step 8: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 9: Commit**

```bash
git add semantic/agent_conversation_memory_threads.py tests/test_thread_decision_detection.py
git commit -m "feat: thread-level decision detection merged into existing summary call"
```

---

### Task 8: Build Quality Eval Harness with False-Negative Protection

Build the measurement tool. Includes `must_not_suppress` annotations to catch false negatives from the new gates.

**Files:**
- Create: `evals/memory_quality_eval.py`
- Create: `evals/export_quality_corpus.py`
- Create: `evals/memory_quality_corpus.jsonl`

- [ ] **Step 1: Write the corpus export script with annotations**

```python
"""Export production DB source items into annotated eval corpus.

Annotations:
- expected_type: what type of memory this SHOULD produce
- expected_suppress: True if this should produce NO memory at all
- must_not_suppress: True if this MUST produce memory (false-negative guard)
"""
import json
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".pallium" / "data" / "pallium.db"
OUTPUT = Path(__file__).parent / "memory_quality_corpus.jsonl"

# Items that MUST NOT be suppressed by new quality gates
MUST_NOT_SUPPRESS_PATTERNS = [
    "root cause",
    "race condition",
    "vector index corruption",
    "demo packages",
    "multilingual-e5-small",
    "vanilla html",
    "documentation pass",
    "minimal config",
]


def export():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("""
        SELECT id, content, role, artifact_kind, thread_ref, container_ref,
               visibility, source_type, source_id
        FROM source_items
        WHERE processing_status = 'completed' AND container_ref != 'test-container'
        ORDER BY thread_position, created_at
    """)
    items = []
    for row in cur.fetchall():
        content = row[1] or ""
        items.append({
            "source_item_id": row[0],
            "content": content,
            "role": row[2],
            "artifact_kind": row[3],
            "thread_ref": row[4],
            "container_ref": row[5],
            "visibility": row[6],
            "source_type": row[7],
            "source_id": row[8],
            "expected_suppress": _should_suppress(content),
            "must_not_suppress": _must_not_suppress(content),
        })
    conn.close()

    with open(OUTPUT, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"Exported {len(items)} items to {OUTPUT}")


def _should_suppress(content: str) -> bool:
    c = content.strip()
    if len(c) < 15:
        return True
    if "<ide_opened_file>" in c and len(c) < 200:
        return True
    return False


def _must_not_suppress(content: str) -> bool:
    cl = content.lower()
    return any(p in cl for p in MUST_NOT_SUPPRESS_PATTERNS)


if __name__ == "__main__":
    export()
```

- [ ] **Step 2: Write the quality eval harness**

```python
"""Memory quality dimension scorer.

Scores:
1. noise_suppression: % of expected_suppress items that produce NO memory
2. false_negative_protection: % of must_not_suppress items that DO produce memory
3. turn_summary_quality: % of discussion_summaries with summary >= 50 chars
4. interest_durability: % of interests with specific, reusable subjects
5. ephemeral_filtering: % of ephemeral-pattern facts that are NOT in active state
"""
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path.home() / ".pallium" / "data" / "pallium.db"
CORPUS_PATH = Path(__file__).parent / "memory_quality_corpus.jsonl"


@dataclass
class Dimension:
    name: str
    passed: int = 0
    total: int = 0

    @property
    def score(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def grade(self) -> str:
        s = self.score
        if s >= 0.9: return "A"
        if s >= 0.8: return "B+"
        if s >= 0.7: return "B"
        if s >= 0.6: return "C"
        if s >= 0.5: return "D"
        return "F"


def main():
    corpus = [json.loads(l) for l in open(CORPUS_PATH, encoding="utf-8") if l.strip()]
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # Build source_item_id → active memories map
    cur.execute("""
        SELECT r.to_id, m.type, m.payload_json
        FROM relations r JOIN memory_objects m ON m.id = r.from_id
        WHERE r.relation_type='supported_by' AND r.from_kind='memory_object'
          AND r.to_kind='source_item' AND m.lifecycle='active'
    """)
    memories_by_source: dict[str, list[dict]] = {}
    for row in cur.fetchall():
        memories_by_source.setdefault(row[0], []).append({"type": row[1], "payload": json.loads(row[2])})

    dims = {}

    # 1. Noise suppression
    d = Dimension("noise_suppression")
    for item in corpus:
        if item.get("expected_suppress"):
            d.total += 1
            if not memories_by_source.get(item["source_item_id"]):
                d.passed += 1
    dims["noise_suppression"] = d

    # 2. False negative protection
    d = Dimension("false_negative_protection")
    for item in corpus:
        if item.get("must_not_suppress"):
            d.total += 1
            if memories_by_source.get(item["source_item_id"]):
                d.passed += 1
    dims["false_negative_protection"] = d

    # 3. Discussion summary quality
    d = Dimension("turn_summary_quality")
    for mems in memories_by_source.values():
        for m in mems:
            if m["type"] == "turn_summary":
                d.total += 1
                if len(m["payload"].get("summary", "")) >= 50:
                    d.passed += 1
    dims["turn_summary_quality"] = d

    # 4. Interest durability
    d = Dimension("interest_durability")
    for mems in memories_by_source.values():
        for m in mems:
            if m["type"] == "interest":
                d.total += 1
                text = m["payload"].get("interest_text", "")
                words = text.split()
                if len(words) >= 4 and not text.endswith("?"):
                    d.passed += 1
    dims["interest_durability"] = d

    conn.close()

    print("Memory Quality Report")
    print("=" * 50)
    for name, dim in dims.items():
        print(f"  {name:30s} {dim.score:5.1%} ({dim.passed}/{dim.total}) → {dim.grade}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run export and eval**

Run: `python evals/export_quality_corpus.py && python evals/memory_quality_eval.py`
Expected: Baseline scores showing current state. `false_negative_protection` should be at A (nothing suppressed yet).

- [ ] **Step 4: Commit**

```bash
git add evals/export_quality_corpus.py evals/memory_quality_eval.py evals/memory_quality_corpus.jsonl
git commit -m "feat: add memory quality eval harness with false-negative protection dimension"
```

---

### Task 9: Integration Validation

Re-process a subset of real source items through the improved pipeline and verify end-to-end improvement.

- [ ] **Step 1: Run semantic eval with new prompt on existing corpus**

Run: `python -m evals.semantic_runner --variants strict_typed_memory_v8b_work_refs_separate --input evals/semantic/input/items.jsonl`

Verify:
- All 10 original explicit-decision items still produce `decision`
- The 4 new implicit-decision items also produce `decision`
- Discussion items still produce `turn_summary` (no false promotions)

- [ ] **Step 2: Run memory quality eval**

Run: `python evals/memory_quality_eval.py`

Verify:
- `noise_suppression` ≥ 80% (B+)
- `false_negative_protection` = 100% (no valuable content accidentally suppressed)
- `turn_summary_quality` ≥ 80% (B+)
- `interest_durability` ≥ 80% (B+)

- [ ] **Step 3: If any dimension below B+, iterate**

| Dimension | If below B+ |
|-----------|-------------|
| noise_suppression | Add more patterns to `should_skip_extraction` |
| false_negative_protection | Relax the gate that's causing false suppression |
| turn_summary_quality | Adjust `_MINIMUM_SUBSTANTIVE_SUMMARY_LENGTH` or prefix list |
| interest_durability | Adjust `_is_durable_interest` thresholds |

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "docs: record memory quality improvement validation results"
```

---

## Architecture Summary

```
Source Item arrives
    │
    ├─ Pre-filter (Task 6): skip if < 15 chars or bare IDE event
    │   └─ exception: decision-approval cues, constraint language
    │
    ├─ agent_conversation_memory package:
    │   ├─ LLM extraction (Task 1 prompt: verbatim quoting, implicit decisions)
    │   ├─ Grounding checks (UNCHANGED — work because LLM now quotes)
    │   ├─ Interest durability gate (Task 5)
    │   ├─ Discussion summary quality gate (Task 4)
    │   └─ Thread rebuild → decision detection merged into existing summary call (Task 7, zero extra LLM cost)
    │
    └─ conversational_knowledge package:
        ├─ Pre-filter same items (Task 6)
        ├─ Fact extraction LLM (Task 2 prompt: stronger negatives)
        └─ Ephemeral fact post-filter (Task 3: regex safety net)
```

Key properties preserved:
- **Anti-hallucination grounding** — not relaxed, works by requiring verbatim quotes
- **Parallel package processing** — both packages respect same pre-filter
- **Existing test suite** — all changes are additive gates, nothing removed
- **Defense-in-depth** — prompt improvements are primary, post-filters are safety nets
