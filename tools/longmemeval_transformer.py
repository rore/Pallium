"""Transform LongMemEval benchmark questions into Pallium external_memory_pressure scenarios.

Reads data/longmemeval/longmemeval_oracle.json, selects ~45 diverse questions
from strong-fit categories, and writes Pallium-native scenarios to
evals/external_memory_pressure/longmemeval_extended_scenarios.json.

Usage:
    python -m tools.longmemeval_transformer
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = ROOT / "data" / "longmemeval" / "longmemeval_oracle.json"
OUTPUT_PATH = ROOT / "evals" / "external_memory_pressure" / "longmemeval_extended_scenarios.json"

# ---------------------------------------------------------------------------
# Mapping: question_type -> pressure_family
# ---------------------------------------------------------------------------
TYPE_TO_FAMILY: dict[str, str] = {
    "temporal-reasoning": "temporal_ordering",
    "knowledge-update": "update_vs_stale_memory",
    "multi-session": "cross_session_carry_forward",
    "single-session-assistant": "cross_session_carry_forward",
}

# ---------------------------------------------------------------------------
# Hand-curated selection of question IDs
# ---------------------------------------------------------------------------
# We select ~45 questions across families ensuring topic diversity,
# 2-4 sessions where possible, and including abstention variants.

SELECTED_IDS: list[str] = [
    # --- temporal-reasoning (12 total: 9 normal + 3 abstention) ---
    "gpt4_2655b836",      # first car issue after service -> GPS system
    "gpt4_2487a7cb",      # first event: time mgmt workshop vs data analysis webinar
    "gpt4_76048e76",      # bike vs car in February
    "gpt4_2312f94c",      # Samsung Galaxy S22 vs Dell XPS 13
    "gpt4_385a5000",      # tomatoes vs marigolds seeds
    "0bb5a684",           # days before team meeting after workshop
    "2c63a862",           # days to find house after starting with Rachel
    "08f4fc43",           # days between Sunday mass and Ash Wednesday
    "gpt4_0b2f1d21",      # coffee maker purchase vs stand mixer malfunction
    "gpt4_2d58bcd6",      # finished reading The Hate U Give vs The Nightingale
    "gpt4_8c8961ae",      # Europe family trip vs solo Thailand trip
    # temporal abstention
    "gpt4_70e84552_abs",  # fixing fence vs purchasing cows (cows not mentioned)
    "982b5123_abs",       # Airbnb in Sacramento (only SF mentioned)
    "gpt4_c27434e8_abs",  # Ferrari vs Porsche model (Porsche not mentioned)

    # --- multi-session (12 total: 9 normal + 3 abstention) ---
    "0a995998",           # clothing items to pick up or return
    "b5ef892d",           # days on camping trips
    "e831120c",           # weeks to watch MCU + Star Wars
    "3a704032",           # plants acquired last month
    "6d550036",           # projects led or leading
    "gpt4_59c863d7",      # model kits worked on or bought
    "gpt4_d84a3211",      # bike-related expenses since start of year
    "gpt4_f2262a51",      # different doctors visited
    "gpt4_a56e767c",      # movie festivals attended
    # multi-session abstention
    "88432d0a_abs",       # bake egg tarts (not mentioned)
    "eeda8a6d_abs",       # fish in 30-gallon tank (tank not mentioned)
    "60bf93ed_abs",       # iPad case arrival (not mentioned)

    # --- knowledge-update (10 total: 7 normal + 3 abstention) ---
    "6a1eabeb",           # personal best 5K time
    "830ce83f",           # where Rachel moved
    "852ce960",           # mortgage pre-approval amount
    "945e3d21",           # yoga class frequency for anxiety
    "d7c942c3",           # mom using same grocery list method
    "6aeb4375",           # Korean restaurants tried
    "9ea5eabc",           # most recent family trip -> Paris
    "71315a70",           # hours on abstract ocean sculpture
    "ce6d2d27",           # cocktail-making class day
    # knowledge-update abstention
    "6aeb4375_abs",       # Italian restaurants (only Korean mentioned)
    "031748ae_abs",       # engineers led as SW Eng Mgr (only Senior SWE mentioned)
    "2698e78f_abs",       # Dr. Johnson visits (only Dr. Smith mentioned)

    # --- single-session-assistant (8 total: 6 normal + 2 abstention) ---
    "7161e7e2",           # shift rotation for GM social media agents
    "c4f10528",           # restaurant in Cihampelas, Bandung
    "e9327a54",           # dessert shop in Orlando with giant milkshakes
    "4c36ccef",           # romantic Italian restaurant in Rome
    "89527b6b",           # dinosaur book — Plesiosaur color
    "6ae235be",           # CITGO refinery processes
    # single-session-assistant — no native _abs in dataset, use single-session-user _abs
    # that have similar assistant-recall flavor
    "gpt4_93159ced_abs",  # how long working before Google (not mentioned)
    "c8090214_abs",       # days before iPad bought vs Holiday Market (iPad not mentioned)
]


# ---------------------------------------------------------------------------
# Signal extraction heuristics
# ---------------------------------------------------------------------------

# Stop words to exclude from signal extraction
_STOP_WORDS = frozenset(
    "a an the is was were are am be been being have has had do does did "
    "will would shall should may might can could of in on at to for with "
    "by from as into through during before after above below between out "
    "up down about over again further then once also just not only very "
    "too so no nor or and but if than that which who whom this these those "
    "it its he she they them their his her my your our your i me we you "
    "what how when where there here both each few more most other some such "
    "all any every many much own same different new old first last next "
    "one two three four five six seven eight nine ten yes ".split()
)


def extract_signals(answer: str) -> list[str]:
    """Extract 2-4 key signal phrases from a LongMemEval answer string.

    Strategy:
    - If the answer contains a recognizable proper noun or specific phrase, keep it intact.
    - If the answer is a short factual nugget, use 2-3 keywords.
    - If the answer is long (e.g. contains explanation), extract the core fact.
    """
    # Strip the "is also acceptable" suffix common in temporal answers
    answer = re.sub(r"\.\s*\d+\s+days?\s*\(including.*?\).*", "", answer, flags=re.IGNORECASE)
    answer = answer.strip().rstrip(".")

    # If the answer is numeric or very short (one word), use it directly
    if len(answer.split()) <= 3:
        return [answer.lower().strip()]

    # Try to extract quoted phrases
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", answer)
    if quoted:
        return [q.lower() for q in quoted[:3]]

    # Try to extract proper noun phrases (capitalized multi-word)
    proper_nouns = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", answer)
    if proper_nouns:
        signals = [pn.lower() for pn in proper_nouns[:3]]
        # Also add a keyword or two from remaining text
        remaining = answer
        for pn in proper_nouns:
            remaining = remaining.replace(pn, "")
        extra_words = [
            w.lower()
            for w in re.findall(r"\b[a-zA-Z]{4,}\b", remaining)
            if w.lower() not in _STOP_WORDS
        ]
        if extra_words:
            signals.append(extra_words[0])
        return signals[:4]

    # Fall back: extract content words
    words = re.findall(r"\b[a-zA-Z0-9$]{2,}\b", answer)
    content_words = [w.lower() for w in words if w.lower() not in _STOP_WORDS]
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for w in content_words:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return unique[:4]


# ---------------------------------------------------------------------------
# Curated signal overrides for questions where auto-extraction is insufficient
# ---------------------------------------------------------------------------

SIGNAL_OVERRIDES: dict[str, list[str]] = {
    "gpt4_2655b836": ["gps", "not functioning"],
    "gpt4_2487a7cb": ["data analysis", "python", "webinar"],
    "gpt4_76048e76": ["bike"],
    "gpt4_2312f94c": ["samsung galaxy s22"],
    "gpt4_385a5000": ["tomatoes"],
    "0bb5a684": ["7 days"],
    "2c63a862": ["14 days"],
    "08f4fc43": ["30 days"],
    "gpt4_0b2f1d21": ["stand mixer", "malfunction"],
    "gpt4_2d58bcd6": ["the hate u give"],
    "gpt4_8c8961ae": ["solo trip", "thailand"],
    "0a995998": ["3"],
    "b5ef892d": ["8 days"],
    "e831120c": ["3.5 weeks"],
    "3a704032": ["3"],
    "6d550036": ["2"],
    "gpt4_59c863d7": ["five", "model kits"],
    "gpt4_d84a3211": ["185"],
    "gpt4_f2262a51": ["three", "doctors"],
    "gpt4_a56e767c": ["four", "festivals"],
    "6a1eabeb": ["25", "50 seconds"],
    "830ce83f": ["suburbs"],
    "852ce960": ["400,000"],
    "945e3d21": ["three times", "week"],
    "d7c942c3": ["yes"],
    "6aeb4375": ["four"],
    "9ea5eabc": ["paris"],
    "71315a70": ["10", "12 hours"],
    "ce6d2d27": ["friday"],
    "7161e7e2": ["admon", "8 am", "day shift", "sundays"],
    "c4f10528": ["miss bee providore"],
    "e9327a54": ["sugar factory", "icon park"],
    "4c36ccef": ["roscioli"],
    "89527b6b": ["plesiosaur", "blue"],
    "6ae235be": ["atmospheric distillation", "catalytic cracking"],
}


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def parse_longmemeval_date(date_str: str) -> datetime:
    """Parse LongMemEval date like '2023/04/10 (Mon) 17:50' into a datetime."""
    # Remove the day-of-week part
    cleaned = re.sub(r"\s*\([A-Za-z]+\)\s*", " ", date_str).strip()
    return datetime.strptime(cleaned, "%Y/%m/%d %H:%M").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Core transformer
# ---------------------------------------------------------------------------

def transform_question(q: dict[str, Any]) -> dict[str, Any]:
    """Transform one LongMemEval question into a Pallium external_memory_pressure scenario."""
    qid = q["question_id"]
    qtype = q["question_type"]
    is_abstention = qid.endswith("_abs")

    # Map to pressure family
    if is_abstention:
        pressure_family = "unsupported_or_ambiguous_memory_abstention"
    else:
        pressure_family = TYPE_TO_FAMILY[qtype]

    # Build scenario_id
    scenario_id = f"longmemeval-{qid.replace('_', '-')}"

    # Parse session timestamps
    session_dates: list[datetime] = []
    for ds in q["haystack_dates"]:
        session_dates.append(parse_longmemeval_date(ds))

    # Build prior_events from haystack_sessions
    prior_events: list[dict[str, Any]] = []
    for sess_idx, session in enumerate(q["haystack_sessions"]):
        # Determine base timestamp for this session
        if sess_idx < len(session_dates):
            base_ts = session_dates[sess_idx]
        else:
            # Fallback: offset from the last known date
            base_ts = session_dates[-1] + timedelta(days=sess_idx - len(session_dates) + 1)

        thread_ref = f"thread:longmemeval-{qid}-s{sess_idx}"

        for turn_idx, turn in enumerate(session):
            turn_ts = base_ts + timedelta(minutes=turn_idx)
            source_id = f"longmemeval-{qid}-s{sess_idx}-t{turn_idx}"

            prior_events.append({
                "source_type": "chat_message",
                "source_id": source_id,
                "content_type": "text/plain",
                "content": turn["content"],
                "artifact_kind": "message",
                "role": turn["role"],
                "container_ref": f"chat:longmemeval-{qid}",
                "thread_ref": thread_ref,
                "timestamp": turn_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })

    # Build required_signals
    if is_abstention:
        required_signals: list[str] = []
        forbidden_signals: list[str] = []
        should_memory_help = False
        expected_failure_target: str | None = "unsupported_memory_overreach"
    else:
        if qid in SIGNAL_OVERRIDES:
            required_signals = SIGNAL_OVERRIDES[qid]
        else:
            required_signals = extract_signals(str(q["answer"]))
        forbidden_signals = []
        should_memory_help = True
        expected_failure_target = None

    # Build description
    if is_abstention:
        description = (
            f"Abstention: the chat history does not contain information to answer "
            f"'{q['question'][:80]}'. Pallium should not inject misleading memory."
        )
    else:
        description = (
            f"{pressure_family.replace('_', ' ').title()} pressure: "
            f"'{q['question'][:80]}'"
        )

    return {
        "scenario_id": scenario_id,
        "scenario_kind": "external_memory_pressure",
        "description": description,
        "pressure_family": pressure_family,
        "dataset_tier": "pressure",
        "source_benchmark_family": "longmemeval",
        "source_question_id": qid,
        "source_question_type": qtype,
        "prior_events": prior_events,
        "current_query": {
            "text": q["question"],
            "limit": 4,
            "container_ref": f"chat:longmemeval-{qid}",
            "visibility_context": {"kind": "public"},
            "runtime_context": {
                "turn_kind": "new_thread",
                "session_has_sufficient_local_context": False,
            },
        },
        "should_memory_help": should_memory_help,
        "expected_primary_layer": "lower_level_memory" if should_memory_help else None,
        "acceptable_layers": (
            ["lower_level_memory", "source_evidence"] if should_memory_help else []
        ),
        "expected_memory_types": [],
        "required_signals": required_signals,
        "forbidden_signals": forbidden_signals,
        "expected_failure_target": expected_failure_target,
    }


# ---------------------------------------------------------------------------
# Selection logic
# ---------------------------------------------------------------------------

def load_source_data() -> list[dict[str, Any]]:
    """Load the LongMemEval oracle dataset."""
    with open(INPUT_PATH, encoding="utf-8") as f:
        return json.load(f)


def select_questions(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select questions matching SELECTED_IDS from the dataset."""
    by_id = {q["question_id"]: q for q in data}
    selected: list[dict[str, Any]] = []
    missing: list[str] = []
    for qid in SELECTED_IDS:
        if qid in by_id:
            selected.append(by_id[qid])
        else:
            missing.append(qid)
    if missing:
        print(f"WARNING: {len(missing)} selected IDs not found: {missing}", file=sys.stderr)
    return selected


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    data = load_source_data()
    print(f"Loaded {len(data)} questions from {INPUT_PATH}")

    selected = select_questions(data)
    print(f"Selected {len(selected)} questions for transformation")

    # Transform
    scenarios: list[dict[str, Any]] = []
    for q in selected:
        scenario = transform_question(q)
        scenarios.append(scenario)

    # Report distribution
    from collections import Counter
    family_counts = Counter(s["pressure_family"] for s in scenarios)
    print(f"Total scenarios: {len(scenarios)}")
    for family, count in sorted(family_counts.items()):
        abstention = sum(
            1 for s in scenarios
            if s["pressure_family"] == family and not s["should_memory_help"]
        )
        normal = count - abstention
        print(f"  {family}: {normal} normal + {abstention} abstention = {count}")

    # Write output
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(scenarios, f, indent=2, ensure_ascii=False)
    print(f"Written to {OUTPUT_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
