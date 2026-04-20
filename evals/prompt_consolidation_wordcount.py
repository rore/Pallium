"""Quick iteration script: test consolidation prompt variants for word count.

Constructs a realistic consolidation group (prior mega-summary + new atomic_facts)
and calls _build_fact_summary directly with the current prompt. Prints the output
summary and word count for fast feedback on prompt changes.

Usage:
    python -m evals.prompt_consolidation_wordcount --cache-dir .local/llm-cache

Each unique (system_prompt, user_prompt) pair is cached, so changing the prompt
constant in conversational_knowledge.py creates a cache miss and hits the real LLM.
Re-running with the same prompt is instant.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import AppConfig
from app.dependencies import build_llm_provider
from capabilities.consolidation import ConsolidationCandidate, ConsolidationGroup
from core.models import MemoryObject
from providers.llm.cached import CachedLLMProvider
from semantic.conversational_knowledge import _build_fact_summary, FACT_CONSOLIDATION_SYSTEM_PROMPT


MEGA_SUMMARY_TEXT = (
    "John's event: signed with the Minnesota Wolves, had a season opener with the "
    "Minnesota Wolves approximately on 2023-05-28, took a trip to NYC, initially had "
    "trouble figuring out the subway in NYC but found it easy after someone explained it, "
    "explored NYC and tried restaurants and enjoyed the culture and food, attended a local "
    "restaurant with new teammates approximately 2023-09-14, is planning a team trip with "
    "his teammates next month (approximately October 2023) to explore a new city, had a "
    "wedding ceremony with his girlfriend approximately 2023-09-25 at a greenhouse venue "
    "that was a smaller, more intimate gathering, had his first dance with his wife at a "
    "cozy restaurant with candlelight, his favorite memory from the wedding was seeing his "
    "wife walking down the aisle, some of his hiking club friends attended the wedding, his "
    "team won a trophy during their season, his basketball team trailed significantly in the "
    "4th quarter of a game approximately one year before 2023-11-06, his basketball team "
    "overtook a deficit and won the game by the final buzzer, took a road trip on the "
    "European coastline with his wife where they bonded and created memories, messed up "
    "during a big basketball game, hurt his ankle last season and required physical therapy, "
    "was unable to play basketball or help his team during his ankle injury recovery, has "
    "received endorsement deals, his basketball team recently won a game against a top team "
    "approximately 2023-12-08, attended a charity event with Anthony and participated in a "
    "Harry Potter trivia contest against other participants in approximately August 2023, "
    "hit a buzzer-beater shot to win a game when his team was down 10 points in the 4th "
    "quarter, achieved a career-high in assists on approximately 2023-12-08 in a game "
    "against a rival team, missed some basketball games due to an injury, his basketball "
    "team won a close game against another team on approximately 2023-12-09, secured a deal "
    "with a renowned outdoor gear company approximately 2023-12-12, received hiking and "
    "outdoor gear as part of a deal with an outdoor gear company"
)

NEW_ATOMIC_FACTS = [
    "John held a benefit basketball game on approximately 2024-01-01",
    "John got an endorsement with a popular beverage company approximately in the week of 2024-01-05",
    "John found a new gym recently to maintain his basketball training",
]


def _make_summary_candidate(summary_text: str) -> ConsolidationCandidate:
    ts = datetime(2023, 12, 15, tzinfo=timezone.utc)
    mo = MemoryObject(
        id="summary-prior-001",
        type="fact_summary",
        schema_id="conversational_knowledge.fact_summary",
        schema_version="v1",
        payload={
            "subject": "John",
            "category": "event",
            "summary": summary_text,
            "fact_count": 3,
            "group_key": "fact_consolidation:public:conv-43:john:event",
        },
        lifecycle="active",
        visibility="public",
        container_ref="conv-43",
    )
    return ConsolidationCandidate(
        memory_object=mo,
        evidence=(),
        text_view=summary_text,
        tokens=frozenset(summary_text.lower().split()),
        container_ref="conv-43",
        thread_ref=None,
        latest_occurred_at=ts,
        visibility="public",
    )


def _make_fact_candidate(statement: str, index: int) -> ConsolidationCandidate:
    ts = datetime(2024, 1, 5 + index, tzinfo=timezone.utc)
    mo = MemoryObject(
        id=f"fact-new-{index:03d}",
        type="atomic_fact",
        schema_id="conversational_knowledge.atomic_fact",
        schema_version="v1",
        payload={
            "subject": "John",
            "category": "event",
            "statement": statement,
        },
        lifecycle="active",
        visibility="public",
        container_ref="conv-43",
    )
    return ConsolidationCandidate(
        memory_object=mo,
        evidence=(),
        text_view=statement,
        tokens=frozenset(statement.lower().split()),
        container_ref="conv-43",
        thread_ref=f"thread-new-{index}",
        latest_occurred_at=ts,
        visibility="public",
    )


def main():
    parser = argparse.ArgumentParser(description="Test consolidation prompt word count")
    parser.add_argument("--cache-dir", type=Path, default=Path(".local/llm-cache"))
    args = parser.parse_args()

    config = AppConfig.from_env()
    default_package = config.package_config(config.default_use_case)
    if not default_package.llm_provider or not default_package.model:
        print("ERROR: No LLM provider configured in default use case", file=sys.stderr)
        sys.exit(1)

    provider = build_llm_provider(
        config,
        provider_name=default_package.llm_provider,
        model=default_package.model,
    )
    provider = CachedLLMProvider(provider, args.cache_dir, model_tag=default_package.model)

    summary_candidate = _make_summary_candidate(MEGA_SUMMARY_TEXT)
    fact_candidates = [_make_fact_candidate(s, i) for i, s in enumerate(NEW_ATOMIC_FACTS)]

    candidates = tuple([summary_candidate] + fact_candidates)
    group = ConsolidationGroup(
        strategy_name="fact_consolidation",
        strategy_version="v1",
        group_key="fact_consolidation:public:conv-43:john:event",
        candidates=candidates,
        container_ref="conv-43",
        thread_ref=None,
        latest_occurred_at=datetime(2024, 1, 8, tzinfo=timezone.utc),
        visibility="public",
        merge_rationale={"subject": "John", "category": "event"},
    )

    print(f"System prompt ({len(FACT_CONSOLIDATION_SYSTEM_PROMPT.split())} words):")
    print(FACT_CONSOLIDATION_SYSTEM_PROMPT[:200] + "...")
    print()
    print(f"Input: 1 prior summary ({len(MEGA_SUMMARY_TEXT.split())} words) + {len(NEW_ATOMIC_FACTS)} new facts")
    print()

    result = _build_fact_summary(
        provider=provider,
        group=group,
        prompt_variant="fact_extraction_v1",
    )

    if not result.memory_objects:
        print("ERROR: No memory objects produced")
        sys.exit(1)

    output_summary = result.memory_objects[0].payload["summary"]
    word_count = len(output_summary.split())
    print(f"Output summary ({word_count} words):")
    print(output_summary)
    print()

    if word_count <= 150:
        print(f"PASS: {word_count} words <= 150 limit")
    else:
        print(f"FAIL: {word_count} words > 150 limit")

    # ── Scenario 2: small group (3 atomic_facts, no prior summary) ──
    print("\n" + "=" * 60)
    print("Scenario 2: small group (3 atomic_facts only, no prior summary)")
    print("=" * 60 + "\n")

    small_facts = [
        "Alice volunteers at a local animal shelter on weekends",
        "Alice adopted a cat named Whiskers from the shelter in March 2024",
        "Alice is studying veterinary medicine at State University",
    ]
    small_candidates = tuple(_make_fact_candidate(s, i) for i, s in enumerate(small_facts))
    small_group = ConsolidationGroup(
        strategy_name="fact_consolidation",
        strategy_version="v1",
        group_key="fact_consolidation:public:conv-43:alice:personal",
        candidates=small_candidates,
        container_ref="conv-43",
        thread_ref=None,
        latest_occurred_at=datetime(2024, 3, 10, tzinfo=timezone.utc),
        visibility="public",
        merge_rationale={"subject": "Alice", "category": "personal"},
    )
    result2 = _build_fact_summary(
        provider=provider,
        group=small_group,
        prompt_variant="fact_extraction_v1",
    )
    if result2.memory_objects:
        out2 = result2.memory_objects[0].payload["summary"]
        wc2 = len(out2.split())
        print(f"Output ({wc2} words): {out2}")
        print(f"{'PASS' if wc2 <= 150 else 'FAIL'}: {wc2} words")
    else:
        print("ERROR: No output")

    # ── Scenario 3: medium group (prior 80-word summary + 3 facts) ──
    print("\n" + "=" * 60)
    print("Scenario 3: medium group (80-word prior summary + 3 new facts)")
    print("=" * 60 + "\n")

    medium_summary = (
        "Tim's activity: joined a hiking club in spring 2023, completed the "
        "Appalachian Trail section hike in June 2023, started a nature photography "
        "blog documenting hikes, won third place in a local photography contest in "
        "August 2023, organized a charity hike raising $2000 for wildlife conservation, "
        "began training for a marathon in September 2023, completed his first marathon "
        "in November 2023 with a time of 4 hours 15 minutes, started mentoring new "
        "hikers at the club"
    )
    medium_new_facts = [
        "Tim completed an ultramarathon in December 2023",
        "Tim was featured in a local newspaper for his conservation work",
        "Tim planned a group expedition to Patagonia for March 2024",
    ]
    medium_summary_candidate = _make_summary_candidate(medium_summary)
    medium_summary_candidate.memory_object.payload["subject"] = "Tim"
    medium_summary_candidate.memory_object.payload["category"] = "activity"
    medium_fact_candidates = [_make_fact_candidate(s, i) for i, s in enumerate(medium_new_facts)]
    medium_candidates = tuple([medium_summary_candidate] + medium_fact_candidates)
    medium_group = ConsolidationGroup(
        strategy_name="fact_consolidation",
        strategy_version="v1",
        group_key="fact_consolidation:public:conv-43:tim:activity",
        candidates=medium_candidates,
        container_ref="conv-43",
        thread_ref=None,
        latest_occurred_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        visibility="public",
        merge_rationale={"subject": "Tim", "category": "activity"},
    )
    result3 = _build_fact_summary(
        provider=provider,
        group=medium_group,
        prompt_variant="fact_extraction_v1",
    )
    if result3.memory_objects:
        out3 = result3.memory_objects[0].payload["summary"]
        wc3 = len(out3.split())
        print(f"Output ({wc3} words): {out3}")
        print(f"{'PASS' if wc3 <= 150 else 'FAIL'}: {wc3} words")
    else:
        print("ERROR: No output")

    # ── Scenario 4: contradiction detection under word pressure ──
    print("\n" + "=" * 60)
    print("Scenario 4: contradiction detection (must still return superseded_indices)")
    print("=" * 60 + "\n")

    contradiction_facts = [
        "Bob was born in London in 1985",
        "Bob studied computer science at Oxford",
        "Bob moved to Berlin in 2010",
        "Bob was born in Berlin in 1985",  # contradicts fact 0
    ]
    contra_candidates = []
    for i, stmt in enumerate(contradiction_facts):
        c = _make_fact_candidate(stmt, i)
        c.memory_object.payload["subject"] = "Bob"
        c.memory_object.payload["category"] = "personal"
        # Make the last fact newer so it supersedes the older one
        c = ConsolidationCandidate(
            memory_object=c.memory_object,
            evidence=(),
            text_view=stmt,
            tokens=frozenset(stmt.lower().split()),
            container_ref="conv-43",
            thread_ref=f"thread-{i}",
            latest_occurred_at=datetime(2024, 1, 1 + i, tzinfo=timezone.utc),
            visibility="public",
        )
        contra_candidates.append(c)

    contra_group = ConsolidationGroup(
        strategy_name="fact_consolidation",
        strategy_version="v1",
        group_key="fact_consolidation:public:conv-43:bob:personal",
        candidates=tuple(contra_candidates),
        container_ref="conv-43",
        thread_ref=None,
        latest_occurred_at=datetime(2024, 1, 4, tzinfo=timezone.utc),
        visibility="public",
        merge_rationale={"subject": "Bob", "category": "personal"},
    )
    result4 = _build_fact_summary(
        provider=provider,
        group=contra_group,
        prompt_variant="fact_extraction_v1",
    )
    if result4.memory_objects:
        mo4 = result4.memory_objects[0]
        out4 = mo4.payload["summary"]
        wc4 = len(out4.split())
        reasoning4 = mo4.payload.get("contradiction_reasoning", "")
        print(f"Output ({wc4} words): {out4}")
        print(f"Contradiction reasoning: {reasoning4}")
        # The summary should reflect the newer birthplace (Berlin), not London
        has_berlin = "Berlin" in out4 or "berlin" in out4
        has_reasoning = bool(reasoning4.strip())
        print(f"  Berlin in summary: {has_berlin}")
        print(f"  Has contradiction reasoning: {has_reasoning}")
        if has_berlin and has_reasoning:
            print("PASS: contradiction detected and newer fact preferred")
        else:
            print(f"FAIL: contradiction handling {'missing reasoning' if not has_reasoning else 'wrong birthplace'}")
    else:
        print("ERROR: No output")

    # ── Scenario 5: distinct events that should NOT be merged ──
    print("\n" + "=" * 60)
    print("Scenario 5: distinct events (should not merge separate games/trips)")
    print("=" * 60 + "\n")

    distinct_events = [
        "John won a basketball game against the Lakers on 2023-11-15 by 5 points",
        "John won a basketball game against the Celtics on 2023-12-02 by 3 points",
        "John went camping in Yosemite in July 2023",
        "John went camping in Yellowstone in October 2023",
        "John attended a charity gala in NYC on 2023-09-20",
        "John attended a charity gala in LA on 2023-10-15",
    ]
    distinct_candidates = tuple(
        _make_fact_candidate(s, i) for i, s in enumerate(distinct_events)
    )
    distinct_group = ConsolidationGroup(
        strategy_name="fact_consolidation",
        strategy_version="v1",
        group_key="fact_consolidation:public:conv-43:john:event",
        candidates=distinct_candidates,
        container_ref="conv-43",
        thread_ref=None,
        latest_occurred_at=datetime(2023, 12, 5, tzinfo=timezone.utc),
        visibility="public",
        merge_rationale={"subject": "John", "category": "event"},
    )
    result5 = _build_fact_summary(
        provider=provider,
        group=distinct_group,
        prompt_variant="fact_extraction_v1",
    )
    if result5.memory_objects:
        out5 = result5.memory_objects[0].payload["summary"]
        wc5 = len(out5.split())
        print(f"Output ({wc5} words): {out5}")
        # Check: all 6 events should be distinguishable
        checks = {
            "Lakers": "Lakers" in out5,
            "Celtics": "Celtics" in out5,
            "Yosemite": "Yosemite" in out5,
            "Yellowstone": "Yellowstone" in out5,
            "NYC": "NYC" in out5 or "New York" in out5,
            "LA": "LA" in out5 or "Los Angeles" in out5,
        }
        all_pass = all(checks.values())
        for key, found in checks.items():
            print(f"  {key}: {'found' if found else 'MISSING'}")
        print(f"{'PASS' if all_pass else 'FAIL'}: {'all' if all_pass else 'some'} distinct events preserved")
    else:
        print("ERROR: No output")

    print(f"\nLLM cache stats: {provider.stats}")


if __name__ == "__main__":
    main()
