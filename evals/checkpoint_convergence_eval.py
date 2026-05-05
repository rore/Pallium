"""Checkpoint convergence eval.

Tests whether the task_checkpoint correctly reflects thread resolution state
when a prior summary carries stale "unresolved" or "blocked" framing.

Three dimensions tested per scenario:
  - converge_to_resolved: stale prior says "blocked/unresolved", recent items resolve it
  - keep_blocker: prior says "blocked", recent items confirm it is still blocked
  - partial_resolve / regression_no_prior: mixed / baseline cases

Prompt variants compared:
  baseline            — production prompts unchanged
  A_checkpoint_recency — recency gate added to checkpoint section of system prompt
  B_incremental       — recency instruction added to incremental grounding clause
  C_both              — both A and B

Usage:
    python -m evals.checkpoint_convergence_eval
    python -m evals.checkpoint_convergence_eval --cache-dir .local/llm-cache
    python -m evals.checkpoint_convergence_eval --variant baseline --variant A_checkpoint_recency
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from app.config import AppConfig
from app.dependencies import build_llm_provider
from semantic.agent_conversation_memory_threads import (
    THREAD_SUMMARY_WITH_CHECKPOINT_SCHEMA_DESCRIPTION,
    THREAD_SUMMARY_WITH_CHECKPOINT_SYSTEM_PROMPT,
    _format_selected_work_artifacts,
)

CORPUS_PATH = Path(__file__).parent / "checkpoint_convergence_corpus.jsonl"
RESULTS_PATH = Path(__file__).parent / "checkpoint_convergence_results.json"


# ---------------------------------------------------------------------------
# LLM cache
# ---------------------------------------------------------------------------

class LLMCache:
    def __init__(self, cache_dir: Path | None):
        self._dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> dict | None:
        if not self._dir:
            return None
        path = self._dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def put(self, key: str, value: dict) -> None:
        if not self._dir:
            return
        path = self._dir / f"{key}.json"
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _cache_key(variant: str, scenario_id: str) -> str:
    h = hashlib.sha256(f"{variant}:{scenario_id}".encode()).hexdigest()[:16]
    return f"checkpoint_conv_{variant}_{h}"


# ---------------------------------------------------------------------------
# Prompt variants
# ---------------------------------------------------------------------------

# Baseline incremental instruction (mirrors build_thread_summary lines 523-528)
BASELINE_INCREMENTAL_INSTRUCTION = (
    "The prior summary is context only. "
    "Produce an updated summary that incorporates both the prior context and new developments. "
    "decision_text and investigation_text may be synthesized, but evidence must be EXACT QUOTES from the NEW thread items below only. "
    "Do not quote from the prior summary.\n\n"
)

# Variant A: replace the checkpoint instruction section in the system prompt
# to add a recency gate for current_state and blocker_state.
_CHECKPOINT_SECTION_ORIGINAL = (
    "For the task_checkpoint section: capture the task, the current state, key findings, "
    "blocker or failed-attempt state when present, the next supported step when present, "
    "and a concise freshness signal. "
)
_CHECKPOINT_SECTION_WITH_RECENCY = (
    "For the task_checkpoint section: capture the task, the current state, key findings, "
    "and a concise freshness signal. "
    "For current_state and blocker_state: base them on the MOST RECENT thread items — "
    "a blocker is present only if the most recent items confirm it is still open; "
    "if recent items show it was resolved, reflect the resolved state and omit the blocker. "
    "The next supported step, when present. "
)

# Variant B: extend the incremental instruction to add a checkpoint-specific override
VARIANT_B_INCREMENTAL_INSTRUCTION = (
    "The prior summary is context only. "
    "Produce an updated summary that incorporates both the prior context and new developments. "
    "decision_text and investigation_text may be synthesized, but evidence must be EXACT QUOTES from the NEW thread items below only. "
    "Do not quote from the prior summary. "
    "For the task_checkpoint fields current_state and blocker_state: reflect the MOST RECENT items — "
    "if recent items show resolution or completion, use that state regardless of what the prior summary said.\n\n"
)

VARIANTS = ["baseline", "A_checkpoint_recency", "B_incremental", "C_both"]


def _build_system_prompt(variant: str) -> str:
    base = THREAD_SUMMARY_WITH_CHECKPOINT_SYSTEM_PROMPT
    if variant in ("A_checkpoint_recency", "C_both"):
        if _CHECKPOINT_SECTION_ORIGINAL not in base:
            raise ValueError(
                "Checkpoint section anchor not found in system prompt — "
                "update _CHECKPOINT_SECTION_ORIGINAL to match current prompt."
            )
        base = base.replace(_CHECKPOINT_SECTION_ORIGINAL, _CHECKPOINT_SECTION_WITH_RECENCY, 1)
    return base


def _build_incremental_instruction(variant: str) -> str:
    if variant in ("B_incremental", "C_both"):
        return VARIANT_B_INCREMENTAL_INSTRUCTION
    return BASELINE_INCREMENTAL_INSTRUCTION


# ---------------------------------------------------------------------------
# User prompt construction (mirrors build_thread_summary lines 530-542)
# ---------------------------------------------------------------------------

def _build_thread_text(items: list[dict]) -> str:
    lines = []
    for item in items:
        role = item.get("role") or "unknown"
        artifact_kind = item.get("artifact_kind") or "unknown"
        content = (item.get("content") or "").strip()
        if content:
            lines.append(f"{role}\\{artifact_kind}: {content}")
    return "\n".join(lines)


def _build_user_prompt(scenario: dict, incremental_instruction: str) -> str:
    prior_summary = scenario.get("prior_summary")
    container_ref = scenario.get("container_ref", "test:eval")
    thread_ref = scenario.get("thread_ref", "test:eval:thread")
    thread_items = scenario.get("thread_items", [])
    carried_conclusions = scenario.get("carried_conclusions", [])
    selected_work_artifacts = scenario.get("selected_work_artifacts", [])

    prior_summary_section = ""
    instruction = ""
    if prior_summary:
        prior_summary_section = f"Prior summary of earlier discussion:\n{prior_summary}\n\n"
        instruction = incremental_instruction

    conclusion_lines = [
        f"- {c['type']}: {c['text']}"
        for c in carried_conclusions
        if c.get("type") and c.get("text")
    ]

    thread_material = _build_thread_text(thread_items)

    return (
        "Summarize this thread conservatively for later recall and "
        "create one compact resumed-work checkpoint from the same content. "
        "Use only explicit information from the provided content.\n\n"
        f"{instruction}"
        f"{prior_summary_section}"
        f"Container ref: {container_ref}\n"
        f"Thread ref: {thread_ref}\n"
        f"Latest occurred at: 2026-05-05T13:00:00+00:00\n"
        f"Carried conclusions:\n{chr(10).join(conclusion_lines) if conclusion_lines else '- none'}\n\n"
        f"Selected work artifacts:\n{_format_selected_work_artifacts(selected_work_artifacts)}\n\n"
        f"Thread items:\n{thread_material}"
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _checkpoint_full_text(parsed: dict) -> str:
    cp = parsed.get("task_checkpoint") or {}
    parts = [
        cp.get("summary", ""),
        cp.get("current_state", ""),
        cp.get("blocker_state", ""),
        cp.get("next_step", ""),
        " ".join(cp.get("key_findings") or []),
    ]
    return " ".join(str(p) for p in parts if p).lower()


def _score_scenario(parsed: dict, expected: dict) -> dict:
    text = _checkpoint_full_text(parsed)
    should_contain = expected.get("checkpoint_should_contain", [])
    should_not_contain = expected.get("checkpoint_should_not_contain", [])

    found = [kw for kw in should_contain if kw.lower() in text]
    found_bad = [kw for kw in should_not_contain if kw.lower() in text]

    recall = len(found) / len(should_contain) if should_contain else 1.0
    passed = recall >= 0.5 and len(found_bad) == 0

    return {
        "pass": passed,
        "recall": recall,
        "found_keywords": found,
        "missing_keywords": [kw for kw in should_contain if kw not in found],
        "bad_keywords_found": found_bad,
        "checkpoint_text_snippet": text[:400],
    }


# ---------------------------------------------------------------------------
# Main eval loop
# ---------------------------------------------------------------------------

def run_eval(
    corpus: list[dict],
    variants: list[str],
    provider,
    cache: LLMCache,
    *,
    verbose: bool = False,
) -> dict:
    results: dict[str, dict] = {}

    for variant in variants:
        sys_prompt = _build_system_prompt(variant)
        incr_instruction = _build_incremental_instruction(variant)
        variant_results: dict[str, dict] = {}

        print(f"\nRunning variant: {variant}", flush=True)

        for scenario in corpus:
            sid = scenario["scenario_id"]
            user_prompt = _build_user_prompt(scenario, incr_instruction)
            cache_key = _cache_key(variant, sid)

            cached = cache.get(cache_key)
            if cached is not None:
                parsed = cached
                print(f"  {sid}: (cached)", flush=True)
            else:
                print(f"  {sid}: calling LLM...", end=" ", flush=True)
                response = provider.generate_json(
                    system_prompt=sys_prompt,
                    user_prompt=user_prompt,
                    schema_description=THREAD_SUMMARY_WITH_CHECKPOINT_SCHEMA_DESCRIPTION,
                )
                parsed = response.parsed_json
                cache.put(cache_key, parsed)
                print("done", flush=True)

            score = _score_scenario(parsed, scenario["expected"])
            variant_results[sid] = {
                "score": score,
                "type": scenario["type"],
                "description": scenario["description"],
                "user_prompt_chars": len(user_prompt),
                "sys_prompt_chars": len(sys_prompt),
            }

            if verbose and not score["pass"]:
                cp = (parsed.get("task_checkpoint") or {})
                print(f"    FAIL — current_state: {cp.get('current_state', '')!r}")
                print(f"           blocker_state: {cp.get('blocker_state', '')!r}")

        results[variant] = variant_results

    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _print_report(results: dict, corpus: list[dict]) -> None:
    scenario_ids = [s["scenario_id"] for s in corpus]
    variants = list(results.keys())

    print("\n" + "=" * 70)
    print("CHECKPOINT CONVERGENCE EVAL")
    print("=" * 70)

    # Token budget comparison
    baseline_sys_chars = results["baseline"][scenario_ids[0]]["sys_prompt_chars"]
    print("\n--- Prompt size (system prompt chars) ---")
    for variant in variants:
        sys_chars = results[variant][scenario_ids[0]]["sys_prompt_chars"]
        delta = sys_chars - baseline_sys_chars
        delta_str = f"+{delta}" if delta > 0 else (f"{delta}" if delta < 0 else "±0")
        passes = sum(1 for sid in scenario_ids if results[variant][sid]["score"]["pass"])
        print(f"  {variant:25s}  {sys_chars:5d} chars ({delta_str:>5s})  {passes}/{len(scenario_ids)} pass")

    # Per-scenario breakdown
    print("\n--- Per-scenario ---")
    for sid in scenario_ids:
        scenario = next(s for s in corpus if s["scenario_id"] == sid)
        print(f"\n  [{scenario['type']}] {sid}")
        print(f"  {scenario['description']}")
        for variant in variants:
            r = results[variant][sid]["score"]
            status = "PASS" if r["pass"] else "FAIL"
            bad = f"  BAD:{r['bad_keywords_found']}" if r["bad_keywords_found"] else ""
            miss = f"  MISS:{r['missing_keywords']}" if r["missing_keywords"] else ""
            print(f"    {variant:25s}  {status}{bad}{miss}")
            if not r["pass"]:
                print(f"      → {r['checkpoint_text_snippet'][:200]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Checkpoint convergence prompt variant eval.")
    parser.add_argument("--cache-dir", type=Path, default=None,
                        help="Directory for LLM response cache (enables fast re-runs).")
    parser.add_argument("--variant", action="append", dest="variants", default=None,
                        help="Run only this variant (repeatable). Default: all.")
    parser.add_argument("--output", type=Path, default=RESULTS_PATH)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    corpus = [
        json.loads(line)
        for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cache = LLMCache(args.cache_dir)
    variants = args.variants or VARIANTS

    config = AppConfig.from_env()
    provider = build_llm_provider(config, role="thread_aggregation")

    results = run_eval(corpus, variants, provider, cache, verbose=args.verbose)

    args.output.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nResults saved to {args.output}")

    _print_report(results, corpus)

    total_pass = sum(
        1
        for v in variants
        for sid in [s["scenario_id"] for s in corpus]
        if results[v][sid]["score"]["pass"]
    )
    total = len(variants) * len(corpus)
    print(f"\nTotal: {total_pass}/{total} ({total_pass / total:.0%})\n")
    return 0 if total_pass == total else 1


if __name__ == "__main__":
    sys.exit(main())
