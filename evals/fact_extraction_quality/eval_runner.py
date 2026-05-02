"""Eval runner for fact extraction quality.

Re-runs fact extraction on source chunks with different prompt variants,
then scores each extracted fact against the reference annotations.

Metrics:
  - noise_rate: % of extracted facts classified as noise
  - precision: % of extracted facts that are good (1 - noise_rate)
  - volume: total facts extracted (lower is better if precision holds)

Usage:
  python -m evals.fact_extraction_quality.eval_runner --variant baseline
  python -m evals.fact_extraction_quality.eval_runner --variant durability
  python -m evals.fact_extraction_quality.eval_runner --variant extract_only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evals.fact_extraction_quality.build_corpus import classify_fact
from providers.llm.base import LLMProvider
from semantic.conversational_knowledge import FACT_EXTRACTION_SYSTEM_PROMPT, FACT_EXTRACTION_SCHEMA_DESCRIPTION

EVAL_DIR = Path(__file__).parent
CHUNKS_PATH = EVAL_DIR / "source_chunks.jsonl"


# ══════════════════════════════════════════════════════════════════════════
# Prompt variants to test
# ══════════════════════════════════════════════════════════════════════════

PROMPT_VARIANTS: dict[str, str] = {}

# Baseline: current production prompt (from conversational_knowledge.py)
PROMPT_VARIANTS["baseline"] = FACT_EXTRACTION_SYSTEM_PROMPT

# Variant: Durability heuristic — single principle replaces SKIP list
PROMPT_VARIANTS["durability"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true — if a statement contradicts common knowledge or a prior fact, still extract it. "
    "Each fact should answer a possible future question about these people, places, events, or preferences. "
    "Each statement must be self-contained and explicitly name its subject; do not return subjectless predicate fragments. "
    "\n\n"
    "DURABILITY RULE (apply to every candidate fact):\n"
    "Only extract facts that will still be true and useful 30 days from now. "
    "If it describes something that will change with the next code commit, conversation, session, or deployment — do not extract it.\n\n"
    "DURABLE (extract):\n"
    "- Root cause analysis: WHY something broke or behaved unexpectedly\n"
    "- System behavior discoveries: how a component actually works under specific conditions\n"
    "- Architectural constraints: what cannot be done and why\n"
    "- Durable configuration truths: what flag/setting controls what behavior and why it was chosen\n"
    "- Personal facts: names, relationships, preferences, significant events\n"
    "- Stated commitments: decisions that were made and implemented\n"
    "\n"
    "EPHEMERAL (never extract):\n"
    "- Implementation narration: what was built, fixed, deployed, committed, renamed, or pushed\n"
    "- Plans and proposals: task breakdowns, improvement plans, recommended approaches not yet proven\n"
    "- Test/eval results: pass counts, scores, benchmark numbers\n"
    "- Runtime state: port numbers, PIDs, memory usage, process counts, disk sizes\n"
    "- Git state: commit hashes, push confirmations, branch status\n"
    "- UI/asset descriptions: layout details, file sizes, pixel dimensions, color values\n"
    "- Session progress: what was checked off, debugging steps taken, options considered\n"
    "- Prescriptive statements: 'should be X', 'needs to Y' (unless stating a discovered constraint)\n"
    "\n"
    "SPECIFICITY: Preserve proper nouns, qualifying details, activity specifics. "
    "Never produce a vague version alongside a specific one. "
    "If the same fact is mentioned multiple times, extract it once in its most specific form. "
    "Resolve relative dates using the session date.\n"
    "\n"
    "Return JSON with key 'facts' containing up to 20 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "Prioritize facts with names, dates, numbers, or specific details. "
    "If no extractable facts, return {\"facts\": []}. "
    "\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: Extract-only (no SKIP list, just positive extraction categories)
PROMPT_VARIANTS["extract_only"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true. "
    "Each fact should answer a possible future question about these people, systems, events, or preferences. "
    "Each statement must be self-contained and explicitly name its subject.\n\n"
    "ONLY extract facts in these categories:\n"
    "1. ROOT CAUSES — why something broke or behaved unexpectedly\n"
    "2. SYSTEM BEHAVIOR — how a component actually works under specific conditions\n"
    "3. ARCHITECTURAL CONSTRAINTS — what cannot be done and why\n"
    "4. DURABLE CONFIGURATION — what setting/flag controls what behavior\n"
    "5. PERSONAL FACTS — names, relationships, preferences, significant life events\n"
    "6. COMMITTED DECISIONS — choices that were made AND implemented (not proposals)\n"
    "\n"
    "Do NOT extract anything else. In particular, skip:\n"
    "- What was built/fixed/deployed/committed (implementation narration)\n"
    "- Plans, tasks, proposals, recommendations\n"
    "- Test results, eval scores, benchmarks\n"
    "- Runtime state, git state, process info\n"
    "- UI descriptions, asset details\n"
    "\n"
    "SPECIFICITY: Preserve proper nouns, qualifying details. "
    "Extract once in most specific form. "
    "Resolve relative dates using the session date.\n\n"
    "Return JSON with key 'facts' containing up to 20 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "If no extractable facts, return {\"facts\": []}. "
    "\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: Option 4 — reduced cap (8) + derivability filter
# Goal: 50%+ noise reduction by targeting the #1 noise source (65% of noise):
# facts that state what code/config/tests currently contain.
PROMPT_VARIANTS["option4_focused"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true — if a statement contradicts common knowledge or a prior fact, still extract it. "
    "Each fact should answer a possible future question about these people, systems, events, or preferences. "
    "Each statement must be self-contained and explicitly name its subject; do not return subjectless predicate fragments. "
    "\n\n"
    "THE REPO TEST (most important rule):\n"
    "Do NOT extract any fact that someone could learn by reading the current codebase, config, git log, tests, or documentation. "
    "If the information is IN the repo right now, it does not belong in memory — memory is for things you can ONLY learn from the conversation.\n\n"
    "Examples of repo-derivable facts (NEVER extract):\n"
    "- What a function/class/module does or how it works\n"
    "- What code was added, changed, moved, renamed, or deleted\n"
    "- What config values, flags, or settings are set to\n"
    "- What tests exist or what they test\n"
    "- File structure, import paths, directory layout\n"
    "- What packages/dependencies are used\n"
    "- What a PR/commit contains\n"
    "\n"
    "ALSO SKIP:\n"
    "- Implementation narration: what was built, fixed, deployed, committed\n"
    "- Plans, proposals, task lists, recommendations not yet proven\n"
    "- Test/eval results, scores, benchmarks (transient)\n"
    "- Runtime state: port numbers, PIDs, memory usage\n"
    "- Git state: commit hashes, branch status\n"
    "- Session progress: debugging steps, options considered\n"
    "- Prescriptive statements: 'should be X', 'needs to Y'\n"
    "\n"
    "ONLY EXTRACT facts in these categories:\n"
    "1. ROOT CAUSES — WHY something broke or behaved unexpectedly (not WHAT was fixed)\n"
    "2. DISCOVERED CONSTRAINTS — what cannot be done and why (learned through experience, not from docs)\n"
    "3. NON-OBVIOUS SYSTEM BEHAVIOR — how something actually works under specific conditions (surprising findings)\n"
    "4. PERSONAL FACTS — names, relationships, preferences, life events\n"
    "5. COMMITTED DECISIONS + RATIONALE — choices that were made AND why (the 'why' is the value, not the 'what')\n"
    "\n"
    "SPECIFICITY: Preserve proper nouns, qualifying details. "
    "Extract once in most specific form. "
    "Resolve relative dates using the session date.\n\n"
    "Return JSON with key 'facts' containing up to 8 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "Prioritize facts with names, dates, numbers, or specific details. "
    "If no extractable facts, return {\"facts\": []}. "
    "Quality over quantity — 3 truly durable facts are better than 8 marginal ones.\n"
    "\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: Option 4 v2 — derivability filter with higher cap (12) + stronger positive guidance
# Hypothesis: v1 was too aggressive on cap (8). Keep the derivability rule but
# allow more room and emphasize what IS valuable to counterbalance suppression.
PROMPT_VARIANTS["option4_v2"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true — if a statement contradicts common knowledge or a prior fact, still extract it. "
    "Each fact should answer a possible future question about these people, systems, events, or preferences. "
    "Each statement must be self-contained and explicitly name its subject; do not return subjectless predicate fragments. "
    "\n\n"
    "CRITICAL FILTER — The Repo Test:\n"
    "Do NOT extract facts that could be learned by reading the codebase, git log, config, or docs today. "
    "Memory is ONLY for things you can learn from the conversation itself:\n"
    "- WHY a decision was made (rationale not in code comments)\n"
    "- WHY something broke (root cause reasoning, not the fix)\n"
    "- Constraints discovered through experience (not documented)\n"
    "- User preferences, goals, and personal context\n"
    "- Non-obvious behavior that surprised the participants\n"
    "\n"
    "NEVER EXTRACT:\n"
    "- What code/config/files currently contain or do (readable from repo)\n"
    "- What was built, changed, renamed, moved, deployed (implementation narration)\n"
    "- Plans, proposals, task breakdowns, recommendations\n"
    "- Test results, scores, benchmarks (transient)\n"
    "- Runtime state: port numbers, PIDs, memory, disk usage\n"
    "- Git state: commit hashes, push confirmations, branch info\n"
    "- Session progress: debugging steps, options considered\n"
    "- Prescriptive 'should/must' statements without constraint justification\n"
    "\n"
    "GOOD examples — extract these:\n"
    "- 'X broke because Y' (root cause — the WHY is not in the fix)\n"
    "- 'We chose X over Y because Z' (decision rationale)\n"
    "- 'X cannot do Y because of Z' (discovered constraint)\n"
    "- 'User prefers X' or 'User's role is Y' (personal context)\n"
    "- 'X actually works by doing Y, which is surprising because...' (non-obvious behavior)\n"
    "\n"
    "BAD examples — never extract:\n"
    "- 'Function X handles Y by doing Z' (readable from code)\n"
    "- 'X was renamed to Y' (in git history)\n"
    "- 'Config has flag X set to Y' (in config file)\n"
    "- 'Tests cover X and Y' (in test files)\n"
    "- 'Service runs on port X' (runtime state)\n"
    "- 'Plan includes task X' (plan detail)\n"
    "\n"
    "SPECIFICITY: Preserve proper nouns, qualifying details, activity specifics. "
    "Extract once in most specific form. "
    "Resolve relative dates using the session date.\n\n"
    "Return JSON with key 'facts' containing up to 12 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "Prioritize facts with names, dates, numbers, or specific details. "
    "If no extractable facts, return {\"facts\": []}.\n"
    "\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: Option 4 v3 — mandatory self-check gate before each extraction
# Hypothesis: the LLM needs a structured decision procedure, not just lists.
# Force it to answer "could this be learned from the repo?" for each candidate.
PROMPT_VARIANTS["option4_v3"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true — if a statement contradicts common knowledge or a prior fact, still extract it. "
    "Each fact should answer a possible future question about these people, systems, events, or preferences. "
    "Each statement must be self-contained and explicitly name its subject; do not return subjectless predicate fragments. "
    "\n\n"
    "BEFORE extracting any fact, apply this test:\n"
    "  → Could someone learn this by reading the current code, config, git log, tests, or docs?\n"
    "  → If YES → do NOT extract.\n"
    "  → Memory is ONLY for things learned from the conversation that cannot be found elsewhere.\n"
    "\n"
    "EXTRACT:\n"
    "- Root causes: WHY something broke (the reasoning, not the fix)\n"
    "- Discovered constraints: what cannot be done and why (not documented)\n"
    "- Non-obvious system behavior: surprising findings about how things work\n"
    "- Personal context: preferences, goals, relationships, life events\n"
    "- Decision rationale: WHY a choice was made (not what was chosen — that's in the code)\n"
    "\n"
    "SKIP (fails the repo test or is ephemeral):\n"
    "- What code does, contains, or looks like → read the file\n"
    "- What was changed, renamed, added, fixed → check git log\n"
    "- What config/settings contain → read the config\n"
    "- What tests cover → read the tests\n"
    "- Plans, proposals, task lists → ephemeral, may never happen\n"
    "- Test/benchmark results → transient numbers\n"
    "- Runtime state (ports, PIDs, memory) → changes every restart\n"
    "- 'Should be' / 'needs to' → prescriptive, not factual\n"
    "\n"
    "SPECIFICITY: Preserve proper nouns, qualifying details, activity specifics. "
    "Extract once in most specific form. "
    "Resolve relative dates using the session date.\n\n"
    "Return JSON with key 'facts' containing up to 10 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "Prioritize facts with names, dates, numbers, or specific details. "
    "If no extractable facts, return {\"facts\": []}.\n"
    "\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: Option 4 generalized — domain-agnostic principle-based filtering
# Core insight: "noise" = anything re-derivable from the current state of
# the world the agent operates in. "Good" = things only learnable from the
# conversation itself. This generalizes beyond dev/code to any agent context.
PROMPT_VARIANTS["option4_generalized"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true — if a statement contradicts common knowledge or a prior fact, still extract it. "
    "Each fact should answer a possible future question about these people, systems, events, or preferences. "
    "Each statement must be self-contained and explicitly name its subject; do not return subjectless predicate fragments. "
    "\n\n"
    "THE DERIVABILITY TEST — apply to every candidate fact:\n"
    "Ask: 'Could this fact be re-learned without access to this conversation?'\n"
    "If the answer is yes — from reading available artifacts, running a search, "
    "checking current system state, or looking at any persistent record — do NOT extract it.\n"
    "Memory exists ONLY for knowledge that lives in the conversation and nowhere else.\n"
    "\n"
    "WHAT TO EXTRACT (passes the derivability test):\n"
    "- Reasoning and rationale: WHY something was decided, not WHAT was decided\n"
    "- Root causes: WHY something failed or behaved unexpectedly\n"
    "- Discovered constraints: limitations learned through experience, not from documentation\n"
    "- Surprising behavior: how something actually works vs. how it was expected to work\n"
    "- Personal context: preferences, relationships, goals, biographical facts\n"
    "- Tacit knowledge: insights that participants carry but that aren't written down anywhere\n"
    "\n"
    "WHAT TO SKIP (fails the derivability test or is ephemeral):\n"
    "- Current state descriptions: what exists, what contains what, how things are structured\n"
    "- Action narration: what was done, built, changed, fixed, deployed, created\n"
    "- Transient measurements: counts, sizes, scores, durations, resource usage\n"
    "- Plans and intentions: what will be done, task lists, proposals, recommendations\n"
    "- Prescriptive statements: what should/must/needs to be done\n"
    "- Progress reports: what was completed, checked off, attempted\n"
    "\n"
    "The key distinction: the WHY behind an action is memory-worthy; "
    "the WHAT of the action is not (it's in the artifacts).\n"
    "\n"
    "SPECIFICITY: Preserve proper nouns, qualifying details, activity specifics. "
    "Extract once in most specific form. "
    "Resolve relative dates using the session date.\n\n"
    "Return JSON with key 'facts' containing up to 10 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "Prioritize facts with names, dates, numbers, or specific details. "
    "If no extractable facts, return {\"facts\": []}.\n"
    "\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: Option 4 generalized v2 — derivability principle + concrete examples
# Combines the generalized principle with concrete good/bad examples for calibration.
# Hypothesis: the LLM needs both the principle AND examples to calibrate threshold.
PROMPT_VARIANTS["option4_gen_v2"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true — if a statement contradicts common knowledge or a prior fact, still extract it. "
    "Each fact should answer a possible future question about these people, systems, events, or preferences. "
    "Each statement must be self-contained and explicitly name its subject; do not return subjectless predicate fragments. "
    "\n\n"
    "THE DERIVABILITY TEST — apply to every candidate:\n"
    "Ask: 'If this conversation disappeared, could someone re-learn this from available artifacts?'\n"
    "If YES → do not extract. Memory exists ONLY for knowledge that lives in the conversation and nowhere else.\n"
    "\n"
    "WHY over WHAT — the key distinction:\n"
    "The WHAT of any action (what was built, what exists, what changed) is recorded in artifacts. "
    "The WHY behind it (rationale, root cause, discovered constraint, preference) often isn't. "
    "Extract the WHY. Skip the WHAT.\n"
    "\n"
    "EXTRACT (not derivable from artifacts):\n"
    "- Reasoning and rationale: WHY a decision was made\n"
    "- Root causes: WHY something failed or behaved unexpectedly\n"
    "- Discovered constraints: limitations found through experience\n"
    "- Surprising behavior: reality vs. expectation\n"
    "- Personal context: preferences, relationships, goals, biographical facts\n"
    "- Tacit knowledge: insights participants carry but haven't written down\n"
    "\n"
    "SKIP (derivable from artifacts or ephemeral):\n"
    "- Current state descriptions: what exists, what contains what, structure\n"
    "- Action narration: what was done, built, changed, fixed, deployed\n"
    "- Transient measurements: counts, sizes, scores, durations, resource usage\n"
    "- Plans and intentions: what will be done, task lists, proposals\n"
    "- Prescriptive statements: what should/must/needs to happen\n"
    "- Progress reports: what was completed, checked off, attempted\n"
    "\n"
    "EXAMPLES:\n"
    "GOOD: 'X broke because Y conflicts with Z under concurrent writes' (root cause — the WHY)\n"
    "BAD:  'X was fixed by adding a lock' (action narration — the WHAT)\n"
    "GOOD: 'Chose X over Y because Y has a 500ms cold-start penalty' (decision rationale)\n"
    "BAD:  'X was configured to use Y' (current state — readable from config)\n"
    "GOOD: 'User prefers outcome-focused summaries over step-by-step' (preference)\n"
    "BAD:  'The system runs on port 8080' (transient runtime state)\n"
    "\n"
    "SPECIFICITY: Preserve proper nouns, qualifying details, activity specifics. "
    "Extract once in most specific form. "
    "Resolve relative dates using the session date.\n\n"
    "Return JSON with key 'facts' containing up to 10 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "Prioritize facts with names, dates, numbers, or specific details. "
    "If no extractable facts, return {\"facts\": []}.\n"
    "\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: Option 4 gen v3 — tightened derivability + "no WHY = no extract" rule
# Based on linguistic analysis of gen_v2 results:
# - 43% of remaining noise uses present-descriptive verbs (uses/contains/returns) without causal language
# - Good facts are 3x more likely to contain "because/due to" (8% vs 3%)
# - Good facts are 3x more likely to contain preference/decision verbs (20% vs 7%)
# Strategy: make "contains a WHY" nearly mandatory for technical facts
PROMPT_VARIANTS["option4_gen_v3"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true — if a statement contradicts common knowledge or a prior fact, still extract it. "
    "Each fact should answer a possible future question about these people, systems, events, or preferences. "
    "Each statement must be self-contained and explicitly name its subject; do not return subjectless predicate fragments. "
    "\n\n"
    "TWO MANDATORY TESTS — apply both to every candidate:\n\n"
    "TEST 1 — Derivability:\n"
    "'If this conversation disappeared, could someone re-learn this from available artifacts?'\n"
    "If YES → do not extract. Memory is ONLY for knowledge that lives in the conversation and nowhere else.\n\n"
    "TEST 2 — The WHY test:\n"
    "'Does this fact contain a WHY, a preference, or a constraint — not just a WHAT?'\n"
    "Statements that only describe what something IS, DOES, or CONTAINS are almost never worth extracting. "
    "They describe current state that's readable from artifacts. "
    "The valuable part is always the WHY behind it, the preference that drove it, or the constraint that limits it.\n"
    "\n"
    "EXTRACT (passes both tests):\n"
    "- 'X because Y' — any causal explanation\n"
    "- 'Chose X over Y because Z' — decision with rationale\n"
    "- 'Prefers X' / 'Wants Y' — stated preferences\n"
    "- 'X cannot do Y because Z' — discovered constraints\n"
    "- 'X broke/failed because Y' — root causes\n"
    "- 'Surprisingly, X actually does Y' — expectation violations\n"
    "- Personal facts: names, relationships, biographical events\n"
    "\n"
    "SKIP (fails either test):\n"
    "- 'X uses/contains/returns/handles Y' without explaining WHY it matters\n"
    "- 'X was built/changed/fixed/added/deployed' — action narration\n"
    "- 'The plan/task includes X' — plan details\n"
    "- 'X recommends/proposes Y' — unconfirmed recommendations\n"
    "- 'X should/must/needs to Y' — prescriptive without constraint\n"
    "- Runtime state: ports, PIDs, counts, sizes, scores\n"
    "- Current structure: what exists, where things are, how things are organized\n"
    "\n"
    "EXAMPLES:\n"
    "GOOD: 'Service crashed because killing PID 560 corrupted the vector index file — it was being written to' (WHY it crashed)\n"
    "BAD:  'Service uses exclusive file lock and port check for single-instance' (WHAT it does — in the code)\n"
    "GOOD: 'User prefers outcome-focused summaries over action narration' (preference)\n"
    "BAD:  'Log file rotates at 5MB with 5 backups' (WHAT the config is — in the config)\n"
    "GOOD: 'Chose SQLite over Redis because the use case is single-machine with <1000 writes/day' (WHY)\n"
    "BAD:  'The function returns False for preference categories' (WHAT it does — in the code)\n"
    "\n"
    "SPECIFICITY: Preserve proper nouns, qualifying details, activity specifics. "
    "Extract once in most specific form. "
    "Resolve relative dates using the session date.\n\n"
    "Return JSON with key 'facts' containing up to 10 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "Prioritize facts with names, dates, numbers, or specific details. "
    "If no extractable facts, return {\"facts\": []}.\n"
    "\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: Option 4 gen v4 — gen_v2 base + targeted micro-rules for remaining noise
# Analysis showed gen_v2 is the sweet spot (17.8% noise, 82.2% precision).
# Remaining noise has 3 dominant patterns:
# 1. "X uses/contains/returns Y" without causal language (43% of remaining noise)
# 2. "Plan/Task N..." references (10%)
# 3. Recommendations/proposals (6%)
# Strategy: keep gen_v2 structure, add 3 targeted negative signals
PROMPT_VARIANTS["option4_gen_v4"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true — if a statement contradicts common knowledge or a prior fact, still extract it. "
    "Each fact should answer a possible future question about these people, systems, events, or preferences. "
    "Each statement must be self-contained and explicitly name its subject; do not return subjectless predicate fragments. "
    "\n\n"
    "THE DERIVABILITY TEST — apply to every candidate:\n"
    "Ask: 'If this conversation disappeared, could someone re-learn this from available artifacts?'\n"
    "If YES → do not extract. Memory exists ONLY for knowledge that lives in the conversation and nowhere else.\n"
    "\n"
    "WHY over WHAT — the key distinction:\n"
    "The WHAT of any action (what was built, what exists, what changed) is recorded in artifacts. "
    "The WHY behind it (rationale, root cause, discovered constraint, preference) often isn't. "
    "Extract the WHY. Skip the WHAT.\n"
    "\n"
    "EXTRACT (not derivable from artifacts):\n"
    "- Reasoning and rationale: WHY a decision was made\n"
    "- Root causes: WHY something failed or behaved unexpectedly\n"
    "- Discovered constraints: limitations found through experience\n"
    "- Surprising behavior: reality vs. expectation\n"
    "- Personal context: preferences, relationships, goals, biographical facts\n"
    "- Tacit knowledge: insights participants carry but haven't written down\n"
    "\n"
    "SKIP (derivable from artifacts or ephemeral):\n"
    "- Current state descriptions: what exists, what contains what, structure\n"
    "- Action narration: what was done, built, changed, fixed, deployed\n"
    "- Transient measurements: counts, sizes, scores, durations, resource usage\n"
    "- Plans and intentions: what will be done, task lists, proposals\n"
    "- Prescriptive statements: what should/must/needs to happen\n"
    "- Progress reports: what was completed, checked off, attempted\n"
    "\n"
    "THREE SPECIFIC TRAPS to watch for:\n"
    "1. 'X uses/contains/returns/handles Y' — This describes current implementation, not memory. "
    "ONLY extract if followed by WHY ('...because Z') or an expectation violation.\n"
    "2. 'The plan/task includes/creates/proposes X' — Plans are ephemeral. Skip entirely.\n"
    "3. 'Recommends/proposes/suggests X' — Unconfirmed recommendations are not facts. "
    "Only extract if the recommendation was ACCEPTED and became a decision.\n"
    "\n"
    "EXAMPLES:\n"
    "GOOD: 'X broke because Y conflicts with Z under concurrent writes' (root cause — the WHY)\n"
    "BAD:  'X was fixed by adding a lock' (action narration — the WHAT)\n"
    "GOOD: 'Chose X over Y because Y has a 500ms cold-start penalty' (decision rationale)\n"
    "BAD:  'X uses a RotatingFileHandler set to 5MB' (current state — readable from config)\n"
    "GOOD: 'User prefers outcome-focused summaries over step-by-step' (preference)\n"
    "BAD:  'The system runs on port 8080' (transient runtime state)\n"
    "GOOD: 'Cannot use approach X because of constraint Y discovered when...' (constraint)\n"
    "BAD:  'The plan includes 8 new files across two packages' (plan detail)\n"
    "\n"
    "SPECIFICITY: Preserve proper nouns, qualifying details, activity specifics. "
    "Extract once in most specific form. "
    "Resolve relative dates using the session date.\n\n"
    "Return JSON with key 'facts' containing up to 10 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "Prioritize facts with names, dates, numbers, or specific details. "
    "If no extractable facts, return {\"facts\": []}.\n"
    "\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: Option 4 gen v5 — minimal/simplified version of gen_v2
# Test hypothesis: shorter prompt with just the core principle performs as well or better
PROMPT_VARIANTS["option4_gen_v5"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true. "
    "Each fact should answer a possible future question. "
    "Each statement must be self-contained and explicitly name its subject.\n\n"
    "THE RULE: Extract the WHY, skip the WHAT.\n"
    "If someone could re-learn this fact without access to this conversation "
    "(from artifacts, current state, or any persistent record), do not extract it. "
    "The WHY behind an action is memory-worthy; the WHAT of the action is not.\n\n"
    "EXTRACT: rationale, root causes, constraints, preferences, surprising behavior, tacit knowledge.\n"
    "SKIP: current state, action narration, measurements, plans, prescriptions, progress.\n\n"
    "Return JSON with key 'facts' containing up to 10 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "If no extractable facts, return {\"facts\": []}.\n\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: Option 4 gen v6 — medium-length: gen_v2 core without examples
# Test: does removing the example pairs hurt or help?
PROMPT_VARIANTS["option4_gen_v6"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true — if a statement contradicts common knowledge or a prior fact, still extract it. "
    "Each fact should answer a possible future question about these people, systems, events, or preferences. "
    "Each statement must be self-contained and explicitly name its subject; do not return subjectless predicate fragments. "
    "\n\n"
    "THE DERIVABILITY TEST — apply to every candidate:\n"
    "Ask: 'If this conversation disappeared, could someone re-learn this from available artifacts?'\n"
    "If YES → do not extract. Memory exists ONLY for knowledge that lives in the conversation and nowhere else.\n"
    "\n"
    "WHY over WHAT — the key distinction:\n"
    "The WHAT of any action (what was built, what exists, what changed) is recorded in artifacts. "
    "The WHY behind it (rationale, root cause, discovered constraint, preference) often isn't. "
    "Extract the WHY. Skip the WHAT.\n"
    "\n"
    "EXTRACT (not derivable from artifacts):\n"
    "- Reasoning and rationale: WHY a decision was made\n"
    "- Root causes: WHY something failed or behaved unexpectedly\n"
    "- Discovered constraints: limitations found through experience\n"
    "- Surprising behavior: reality vs. expectation\n"
    "- Personal context: preferences, relationships, goals, biographical facts\n"
    "- Tacit knowledge: insights participants carry but haven't written down\n"
    "\n"
    "SKIP (derivable from artifacts or ephemeral):\n"
    "- Current state descriptions: what exists, what contains what, structure\n"
    "- Action narration: what was done, built, changed, fixed, deployed\n"
    "- Transient measurements: counts, sizes, scores, durations, resource usage\n"
    "- Plans and intentions: what will be done, task lists, proposals\n"
    "- Prescriptive statements: what should/must/needs to happen\n"
    "- Progress reports: what was completed, checked off, attempted\n"
    "\n"
    "SPECIFICITY: Preserve proper nouns, qualifying details, activity specifics. "
    "Extract once in most specific form. "
    "Resolve relative dates using the session date.\n\n"
    "Return JSON with key 'facts' containing up to 10 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "Prioritize facts with names, dates, numbers, or specific details. "
    "If no extractable facts, return {\"facts\": []}.\n"
    "\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: gen_v7 — gen_v5 brevity + example pairs only
# Test: are the examples the secret sauce of gen_v2?
PROMPT_VARIANTS["option4_gen_v7"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true. "
    "Each fact should answer a possible future question. "
    "Each statement must be self-contained and explicitly name its subject.\n\n"
    "THE RULE: Extract the WHY, skip the WHAT.\n"
    "If someone could re-learn this fact without access to this conversation "
    "(from artifacts, current state, or any persistent record), do not extract it. "
    "The WHY behind an action is memory-worthy; the WHAT of the action is not.\n\n"
    "EXTRACT: rationale, root causes, constraints, preferences, surprising behavior, tacit knowledge.\n"
    "SKIP: current state, action narration, measurements, plans, prescriptions, progress.\n\n"
    "EXAMPLES:\n"
    "GOOD: 'X broke because Y conflicts with Z under concurrent writes' (WHY)\n"
    "BAD:  'X was fixed by adding a lock' (WHAT — action narration)\n"
    "GOOD: 'Chose X over Y because Y has a 500ms cold-start penalty' (rationale)\n"
    "BAD:  'X is configured to use Y' (WHAT — current state)\n"
    "GOOD: 'User prefers outcome-focused summaries over step-by-step' (preference)\n"
    "BAD:  'The system runs on port 8080' (transient state)\n\n"
    "Return JSON with key 'facts' containing up to 10 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "If no extractable facts, return {\"facts\": []}.\n\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: gen_v8 — gen_v7 + one-line specificity + "proposals are not facts"
# Test: does adding the specificity instruction + one extra SKIP help?
PROMPT_VARIANTS["option4_gen_v8"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true. "
    "Each fact should answer a possible future question. "
    "Each statement must be self-contained and explicitly name its subject.\n\n"
    "THE RULE: Extract the WHY, skip the WHAT.\n"
    "If someone could re-learn this fact without access to this conversation "
    "(from artifacts, current state, or any persistent record), do not extract it. "
    "The WHY behind an action is memory-worthy; the WHAT of the action is not.\n\n"
    "EXTRACT: rationale, root causes, discovered constraints, preferences, surprising behavior, tacit knowledge.\n"
    "SKIP: current state, action narration, measurements, plans, proposals/recommendations, prescriptions, progress.\n\n"
    "EXAMPLES:\n"
    "GOOD: 'X broke because Y conflicts with Z under concurrent writes' (WHY)\n"
    "BAD:  'X was fixed by adding a lock' (WHAT — action narration)\n"
    "GOOD: 'Chose X over Y because Y has a 500ms cold-start penalty' (rationale)\n"
    "BAD:  'X uses a RotatingFileHandler set to 5MB' (WHAT — readable from config)\n"
    "GOOD: 'User prefers outcome-focused summaries over step-by-step' (preference)\n"
    "BAD:  'The plan includes 8 new files across two packages' (plan detail)\n\n"
    "Preserve proper nouns, qualifying details, and specifics. Extract once in most specific form. "
    "Resolve relative dates using the session date.\n\n"
    "Return JSON with key 'facts' containing up to 10 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "If no extractable facts, return {\"facts\": []}.\n\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: gen_v9 — ultra-minimal: just the derivability principle + examples
PROMPT_VARIANTS["option4_gen_v9"] = (
    "Extract atomic facts from the conversation that cannot be re-learned from any artifact outside this conversation. "
    "Each fact must name its subject and be self-contained.\n\n"
    "Extract the WHY, skip the WHAT. Rationale, root causes, constraints, preferences, "
    "and tacit knowledge are memory-worthy. Current state, actions taken, measurements, "
    "plans, and prescriptions are not.\n\n"
    "GOOD: 'X broke because Y' / 'Chose X over Y because Z' / 'User prefers X'\n"
    "BAD: 'X uses Y' / 'X was fixed' / 'plan includes X' / 'runs on port Y'\n\n"
    "Return JSON: {\"facts\": [{\"subject\": ..., \"statement\": ..., \"category\": \"personal|event|preference|relationship|activity\"}]}. "
    "Up to 10 items. Empty list if nothing qualifies.\n\n"
    "LANGUAGE: Same language as the conversation."
)

# Variant: gen_v10 — target: gen_v2 quality at gen_v8 length
# Key insight from analysis: gen_v2's retention advantage comes from:
# 1. "If this conversation disappeared..." framing (makes derivability concrete)
# 2. The EXTRACT list naming "tacit knowledge" and "surprising behavior" explicitly
# Strategy: gen_v8 base + the "disappeared" framing + richer EXTRACT one-liners
PROMPT_VARIANTS["option4_gen_v10"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true. "
    "Each fact should answer a possible future question. "
    "Each statement must be self-contained and explicitly name its subject.\n\n"
    "THE RULE: Extract the WHY, skip the WHAT.\n"
    "Ask: 'If this conversation disappeared, could someone re-learn this from any artifact?'\n"
    "If yes → skip. Memory is ONLY for knowledge that lives in the conversation and nowhere else.\n\n"
    "EXTRACT: reasoning/rationale behind decisions, root causes of failures, "
    "constraints discovered through experience, preferences and personal context, "
    "surprising behavior (reality vs expectation), tacit knowledge not written down anywhere.\n\n"
    "SKIP: what things currently are/do/contain, what was built/changed/fixed, "
    "measurements and counts, plans/proposals/recommendations, "
    "prescriptive should/must statements, progress reports.\n\n"
    "EXAMPLES:\n"
    "GOOD: 'X broke because Y conflicts with Z under concurrent writes' (WHY)\n"
    "BAD:  'X was fixed by adding a lock' (WHAT — action narration)\n"
    "GOOD: 'Chose X over Y because Y has a 500ms cold-start penalty' (rationale)\n"
    "BAD:  'X uses a RotatingFileHandler set to 5MB' (WHAT — readable from artifacts)\n"
    "GOOD: 'User prefers outcome-focused summaries over step-by-step' (preference)\n"
    "BAD:  'The plan includes 8 new files across two packages' (plan detail)\n\n"
    "Preserve proper nouns and qualifying details. Extract once in most specific form. "
    "Resolve relative dates using the session date.\n\n"
    "Return JSON with key 'facts' containing up to 10 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "If no extractable facts, return {\"facts\": []}.\n\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: gen_v11 — gen_v10 + adjusted bad examples to catch git/narration leaks
PROMPT_VARIANTS["option4_gen_v11"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true. "
    "Each fact should answer a possible future question. "
    "Each statement must be self-contained and explicitly name its subject.\n\n"
    "THE RULE: Extract the WHY, skip the WHAT.\n"
    "Ask: 'If this conversation disappeared, could someone re-learn this from any artifact?'\n"
    "If yes → skip. Memory is ONLY for knowledge that lives in the conversation and nowhere else.\n\n"
    "EXTRACT: reasoning/rationale behind decisions, root causes of failures, "
    "constraints discovered through experience, preferences and personal context, "
    "surprising behavior (reality vs expectation), tacit knowledge not written down anywhere.\n\n"
    "SKIP: what things currently are/do/contain, what was built/changed/fixed/committed, "
    "measurements and counts, plans/proposals/recommendations, "
    "prescriptive should/must statements, progress reports.\n\n"
    "EXAMPLES:\n"
    "GOOD: 'X broke because Y conflicts with Z under concurrent writes' (root cause)\n"
    "BAD:  'X was fixed by adding a lock' (action narration)\n"
    "GOOD: 'Chose X over Y because Y has a 500ms cold-start penalty' (decision rationale)\n"
    "BAD:  'X uses Y with Z setting' (current state — in the artifacts)\n"
    "GOOD: 'User prefers outcome-focused summaries over step-by-step' (preference)\n"
    "BAD:  'Commit abc123 fixed the issue' / 'deployed in version X' (git state)\n"
    "GOOD: 'Cannot do X because of Y discovered when...' (constraint)\n"
    "BAD:  'The plan includes X' / 'Recommends Y' (plan/proposal)\n\n"
    "Preserve proper nouns and qualifying details. Extract once in most specific form. "
    "Resolve relative dates using the session date.\n\n"
    "Return JSON with key 'facts' containing up to 10 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "If no extractable facts, return {\"facts\": []}.\n\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: Baseline with stronger negative examples
PROMPT_VARIANTS["baseline_reinforced"] = FACT_EXTRACTION_SYSTEM_PROMPT + (
    "\n\n"
    "ADDITIONAL REMINDERS — common mistakes to avoid:\n"
    "- 'X was renamed to Y' → SKIP (implementation narration)\n"
    "- 'Task N was completed' → SKIP (session progress)\n"
    "- 'Plan includes/creates/defers X' → SKIP (plan detail)\n"
    "- 'Recommended approach is X' → SKIP (assistant recommendation)\n"
    "- 'X should be Y' without explaining WHY → SKIP (prescriptive)\n"
    "- 'Improvement targets N% of X' → SKIP (plan metric)\n"
    "- 'All N tests pass' → SKIP (test result)\n"
    "- 'X now does Y' describing a code change → SKIP (implementation)\n"
    "Apply the SKIP rules strictly. When in doubt, do NOT extract."
)


def load_chunks(max_chunks: int | None = None) -> list[dict]:
    chunks = []
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        for line in f:
            chunks.append(json.loads(line))
            if max_chunks and len(chunks) >= max_chunks:
                break
    return chunks


def extract_facts_with_prompt(
    provider: LLMProvider,
    prompt_variant: str,
    chunk_text: str,
    existing_facts: list[dict] | None = None,
) -> list[dict]:
    """Run fact extraction with a specific prompt variant.

    When existing_facts is provided, prepends them to simulate production
    conditions where the LLM sees prior extractions.
    """
    system_prompt = PROMPT_VARIANTS[prompt_variant]
    user_prompt = chunk_text
    if existing_facts:
        existing_lines = "\n".join(
            f"- {f.get('subject', '')}: {f.get('statement', '')}"
            for f in existing_facts[-40:]
        )
        user_prompt = (
            f"IMPORTANT: Only extract facts that are genuinely new and durable. "
            f"If the conversation below contains no new extractable facts beyond what is already known, "
            f"return {{\"facts\": []}}. Do NOT lower your quality bar to produce output.\n\n"
            f"Previously extracted facts (do NOT re-extract these):\n"
            f"{existing_lines}\n\n"
            f"New conversation messages:\n"
            f"{chunk_text}"
        )
    response = provider.generate_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema_description=FACT_EXTRACTION_SCHEMA_DESCRIPTION,
    )
    raw_facts = response.parsed_json.get("facts", [])
    if not isinstance(raw_facts, list):
        return []
    return [f for f in raw_facts if isinstance(f, dict) and f.get("statement")]


def score_extraction(extracted_facts: list[dict]) -> dict:
    """Score extracted facts against noise classifier."""
    total = len(extracted_facts)
    if total == 0:
        return {"total": 0, "noise": 0, "good": 0, "noise_rate": 0.0, "precision": 1.0}

    noise = 0
    noise_reasons: dict[str, int] = {}
    for fact in extracted_facts:
        judgment, reason = classify_fact(fact.get("statement", ""), subject=fact.get("subject", ""))
        if judgment == "noise":
            noise += 1
            noise_reasons[reason or "unknown"] = noise_reasons.get(reason or "unknown", 0) + 1

    good = total - noise
    return {
        "total": total,
        "noise": noise,
        "good": good,
        "noise_rate": noise / total,
        "precision": good / total,
        "noise_reasons": noise_reasons,
    }


def load_existing_facts_from_db(thread_ref: str | None = None) -> list[dict]:
    """Load real production facts from the DB for existing_facts simulation."""
    import sqlite3
    db_path = Path(os.environ.get("PALLIUM_DB", r"C:\Users\I347041\.pallium\data\pallium.db"))
    if not db_path.exists():
        return []
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    if thread_ref:
        rows = db.execute("""
            SELECT payload_json FROM memory_objects
            WHERE type = 'atomic_fact' AND lifecycle = 'active'
            AND json_extract(payload_json, '$.thread_ref') = ?
            ORDER BY created_at
        """, (thread_ref,)).fetchall()
    else:
        rows = db.execute("""
            SELECT payload_json FROM memory_objects
            WHERE type = 'atomic_fact' AND lifecycle = 'active'
            ORDER BY created_at
            LIMIT 100
        """).fetchall()
    db.close()
    facts = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        facts.append({
            "subject": payload.get("subject", ""),
            "statement": payload.get("statement", ""),
            "category": payload.get("category", ""),
        })
    return facts


def run_eval(variant: str, max_chunks: int | None = None, verbose: bool = False,
             with_existing_facts: bool = False, existing_facts_count: int | None = None,
             apply_filters: bool = False):
    """Run the full evaluation for a prompt variant.

    Args:
        existing_facts_count: When set, controls how many existing facts are passed
            to the LLM. Tests the "pressure effect" — does having N prior facts
            push the model into lower-quality extraction? Defaults to all available
            when with_existing_facts is True.
        apply_filters: When True, applies the production post-extraction filters
            to LLM output before scoring. Isolates filter contribution.
    """
    from app.config import AppConfig
    from app.dependencies import build_llm_provider

    config = AppConfig.from_env()
    package_config = config.semantic_packages.get("conversational_knowledge")
    if package_config and package_config.llm_provider and package_config.model:
        provider = build_llm_provider(
            config,
            provider_name=package_config.llm_provider,
            model=package_config.model,
        )
    else:
        for pkg_name, pkg_config in config.semantic_packages.items():
            if pkg_config.llm_provider and pkg_config.model:
                provider = build_llm_provider(config, provider_name=pkg_config.llm_provider, model=pkg_config.model)
                break
        else:
            raise RuntimeError("No LLM provider configured")

    chunks = load_chunks(max_chunks)
    print(f"Running variant '{variant}' on {len(chunks)} chunks...")
    print(f"Prompt length: {len(PROMPT_VARIANTS[variant])} chars")
    if with_existing_facts:
        cap_desc = f", capped at {existing_facts_count}" if existing_facts_count else " (all available)"
        print(f"  (simulating production: existing_facts context enabled{cap_desc})")
    if apply_filters:
        print(f"  (applying production post-extraction filters before scoring)")
    print()

    # Pre-load existing facts per thread if simulating production
    thread_facts_cache: dict[str, list[dict]] = {}
    if with_existing_facts:
        for chunk in chunks:
            tr = chunk.get("thread_ref")
            if tr and tr not in thread_facts_cache:
                all_facts = load_existing_facts_from_db(tr)
                if existing_facts_count is not None:
                    all_facts = all_facts[-existing_facts_count:]
                thread_facts_cache[tr] = all_facts

    all_extracted: list[dict] = []
    chunk_scores: list[dict] = []

    for i, chunk in enumerate(chunks):
        chunk_text = chunk["chunk_text"]
        existing = thread_facts_cache.get(chunk.get("thread_ref", "")) if with_existing_facts else None
        try:
            facts = extract_facts_with_prompt(provider, variant, chunk_text, existing_facts=existing)
        except Exception as e:
            print(f"  ERROR on chunk {chunk['chunk_id']}: {e}")
            continue

        if apply_filters:
            facts = apply_production_filters(facts)

        score = score_extraction(facts)
        chunk_scores.append(score)
        all_extracted.extend(facts)

        if verbose:
            print(f"  {chunk['chunk_id']}: {score['total']} facts, {score['noise']} noise ({score['noise_rate']:.0%})")
            if score["noise"] > 0:
                for fact in facts:
                    j, r = classify_fact(fact.get("statement", ""), subject=fact.get("subject", ""))
                    if j == "noise":
                        print(f"    NOISE [{r}]: {fact.get('statement', '')[:90]}")

        # Progress
        if (i + 1) % 10 == 0:
            running_total = sum(s["total"] for s in chunk_scores)
            running_noise = sum(s["noise"] for s in chunk_scores)
            print(f"  ... {i+1}/{len(chunks)} chunks, {running_total} facts, noise rate: {running_noise/max(running_total,1):.1%}")

    # Aggregate scores
    total_facts = sum(s["total"] for s in chunk_scores)
    total_noise = sum(s["noise"] for s in chunk_scores)
    total_good = sum(s["good"] for s in chunk_scores)
    good_per_chunk = total_good / max(len(chunk_scores), 1)

    all_noise_reasons: dict[str, int] = {}
    for s in chunk_scores:
        for reason, count in s.get("noise_reasons", {}).items():
            all_noise_reasons[reason] = all_noise_reasons.get(reason, 0) + count

    print()
    print(f"{'='*60}")
    print(f"RESULTS: variant='{variant}'")
    print(f"{'='*60}")
    print(f"  Chunks processed: {len(chunk_scores)}")
    print(f"  Total facts extracted: {total_facts}")
    print(f"  Good facts: {total_good}")
    print(f"  Noise facts: {total_noise}")
    print(f"  Noise rate: {total_noise/max(total_facts,1):.1%}")
    print(f"  Precision: {total_good/max(total_facts,1):.1%}")
    print(f"  Good/chunk (yield): {good_per_chunk:.2f}")
    print(f"  Avg facts/chunk: {total_facts/max(len(chunk_scores),1):.1f}")
    print()
    if all_noise_reasons:
        print("  Noise breakdown:")
        for reason, count in sorted(all_noise_reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason:35s} {count}")

    # Write results
    results_path = EVAL_DIR / f"results_{variant}.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({
            "variant": variant,
            "chunks_processed": len(chunk_scores),
            "total_facts": total_facts,
            "good_facts": total_good,
            "noise_facts": total_noise,
            "noise_rate": total_noise / max(total_facts, 1),
            "precision": total_good / max(total_facts, 1),
            "good_per_chunk": good_per_chunk,
            "avg_facts_per_chunk": total_facts / max(len(chunk_scores), 1),
            "noise_reasons": all_noise_reasons,
            "per_chunk": chunk_scores,
        }, f, indent=2)
    print(f"\n  Results written to: {results_path}")

    return total_noise / max(total_facts, 1)


def apply_production_filters(facts: list[dict]) -> list[dict]:
    """Apply the same post-extraction filters as the production pipeline.

    Simulates what conversational_knowledge.py does after LLM extraction:
    quality viability, durability check, subject presence.
    """
    from semantic.common import fact_statement_is_quality_viable, normalize_for_index
    from semantic.conversational_knowledge import _is_durable_fact_statement, _clean_fact_text, _fact_subject_is_present

    result = []
    for fact in facts:
        subject = _clean_fact_text(str(fact.get("subject") or ""))
        statement = _clean_fact_text(str(fact.get("statement", "")))
        if not fact_statement_is_quality_viable(statement):
            continue
        if not _fact_subject_is_present(subject):
            continue
        if not _is_durable_fact_statement(subject, statement):
            continue
        result.append(fact)
    return result


def main():
    parser = argparse.ArgumentParser(description="Fact extraction quality eval")
    parser.add_argument("--variant", required=True, choices=list(PROMPT_VARIANTS.keys()))
    parser.add_argument("--max-chunks", type=int, default=None, help="Limit chunks for quick test")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--with-existing-facts", action="store_true",
                        help="Simulate production by prepending real existing facts from DB")
    parser.add_argument("--existing-facts-count", type=int, default=None,
                        help="Cap existing facts to N most recent (tests pressure effect)")
    parser.add_argument("--apply-filters", action="store_true",
                        help="Apply production post-extraction filters before scoring")
    args = parser.parse_args()

    run_eval(args.variant, max_chunks=args.max_chunks, verbose=args.verbose,
             with_existing_facts=args.with_existing_facts,
             existing_facts_count=args.existing_facts_count,
             apply_filters=args.apply_filters)


if __name__ == "__main__":
    main()
