from __future__ import annotations

import json
from pathlib import Path

from app.config import AppConfig
from evals.developer_work_confidence import run_developer_work_confidence_suite
from tests.stub_providers import (
    PublicCorpusAnswerProvider,
    PublicCorpusSemanticProvider,
    TieredMemorySemanticProvider,
)
from tests.test_work_resumption_benchmark import StubWorkResumptionAnswerProvider

WORK_SCENARIOS = Path("evals/work_resumption/scenarios.json")
WILDCHAT_FIXTURE = Path("tests/fixtures/wildchat_export_sample.jsonl")
WILDCHAT_MANIFEST = Path("evals/public_corpus/wildchat_review_manifest.json")
WILDBENCH_FIXTURE = Path("tests/fixtures/wildbench_export_sample.json")
WILDBENCH_MANIFEST = Path("evals/public_corpus/wildbench_developer_continuation_manifest.json")

PUBLIC_CORPUS_MARKERS = (
    "1:2:2 starter feed",
    "done / waiting / next owner",
    "problem framing",
    "job already running, skipping new start",
    "fushimi inari",
    "arashiyama",
    "store section",
    "backtracking",
)


class CompositeSemanticProvider:
    def __init__(self) -> None:
        self._tiered = TieredMemorySemanticProvider()
        self._public = PublicCorpusSemanticProvider()

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str):
        lowered = user_prompt.lower()
        delegate = self._public if any(marker in lowered for marker in PUBLIC_CORPUS_MARKERS) else self._tiered
        return delegate.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_description=schema_description,
        )


def _benchmark_config() -> AppConfig:
    return AppConfig(
        default_use_case="agent_conversation_memory",
        llm_provider="openai_compatible",
        llm_model="fake-answer-model",
        llm_base_url="http://fake-provider.local",
        llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
    )


def test_developer_work_confidence_suite_builds_green_confidence_gate(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: CompositeSemanticProvider())

    run_dir = run_developer_work_confidence_suite(
        work_scenario_file=WORK_SCENARIOS,
        wildchat_corpus_file=WILDCHAT_FIXTURE,
        wildchat_manifest=WILDCHAT_MANIFEST,
        wildbench_corpus_file=WILDBENCH_FIXTURE,
        wildbench_manifest=WILDBENCH_MANIFEST,
        output_root=tmp_path / "output",
        config=_benchmark_config(),
        run_name="developer-work-confidence",
        work_answer_provider=StubWorkResumptionAnswerProvider(),
        public_corpus_answer_provider=PublicCorpusAnswerProvider(),
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    report = (run_dir / "report.md").read_text(encoding="utf-8")

    assert summary["components"]["work_resumption"]["scenarios_total"] == 13
    assert summary["components"]["wildchat_reviewed"]["scenarios_total"] == 6
    assert summary["components"]["wildbench_developer"]["scenarios_total"] == 5
    assert summary["aggregate"]["scenarios_total"] == 24
    assert summary["aggregate"]["policy_successes"] == 24
    assert summary["aggregate"]["dominant_tuning_bottleneck"] is None
    assert all(count == 0 for count in summary["aggregate"]["failure_family_counts"].values())
    assert summary["gates"]["confidence_gate_passed"] is True
    assert "## Confidence Gate" in report
    assert "`zero_privacy_leaks`: PASS" in report
