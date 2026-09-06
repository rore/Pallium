"""Shared runner shape for narrow-target scenarios.

Each scenario module exposes a `run()` function returning a dict with the
canonical fields. Runners are deterministic: same inputs → same output.

Every scenario module must carry a top-of-file ``# measures:`` header
naming which measurement dimensions it reports. Enforced by
:func:`assert_scenario_has_measures_header` and covered by
``tests/test_narrow_target_measures_header.py``.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

Verdict = Literal["PASS", "FAIL", "INCOMPLETE"]

# The four allowed measure dimensions (Invariant 2, see
# docs/context/lessons.md and AGENTS.md).
ALLOWED_MEASURES: frozenset[str] = frozenset({
    "candidate-recovery",
    "injection-precision",
    "downstream-task-effect",
    "specificity",
})

_MEASURES_RE = re.compile(r"^#\s*measures:\s*([\w\-,\s]+)$", re.MULTILINE)


@dataclass
class ScenarioResult:
    """Canonical result shape for a narrow-target scenario replay.

    Fields track the measurements the milestone spec requires.
    ``proactive_operational_fact_count`` is the milestone-invariant guard:
    across the scenario replay, this must be zero.
    """

    scenario_id: str
    verdict: Verdict
    precision: float  # correct-injection / total-injection on trigger turn(s); NaN if N/A
    specificity: float  # correct-non-injection / non-injection opportunities; NaN if N/A
    timing: str  # "on_time" | "late" | "early" | "write_only" | "n/a"
    type_distribution: dict[str, int] = field(default_factory=dict)
    diagnostic: str = ""
    # W4 PR 4: per-scenario zero-proactive invariant guard. Aggregated
    # by run_all.py; the milestone acceptance requires the sum across
    # all scenarios to be zero.
    proactive_operational_fact_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def incomplete(scenario_id: str, reason: str) -> ScenarioResult:
    """Standard INCOMPLETE result used until fixtures are wired."""
    return ScenarioResult(
        scenario_id=scenario_id,
        verdict="INCOMPLETE",
        precision=float("nan"),
        specificity=float("nan"),
        timing="n/a",
        type_distribution={},
        diagnostic=f"fixture not wired yet: {reason}",
    )


# --------------------------------------------------------------------------- #
# W4 PR 4: measures-header lint                                               #
# --------------------------------------------------------------------------- #


def assert_scenario_has_measures_header(module) -> None:
    """Fail loudly if a scenario module is missing the # measures: header.

    Enforcement of Invariant 2 (every eval names its metric). Called by
    ``run_all.py`` at startup and by
    ``tests/test_narrow_target_measures_header.py``.
    """
    src = Path(module.__file__).read_text(encoding="utf-8")
    m = _MEASURES_RE.search(src)
    if m is None:
        raise AssertionError(
            f"{module.__name__}: missing '# measures: ...' header. "
            "Every scenario module must declare which measures it reports."
        )
    values = {v.strip() for v in m.group(1).split(",") if v.strip()}
    unknown = values - ALLOWED_MEASURES
    if unknown:
        raise AssertionError(
            f"{module.__name__}: unknown measures {unknown}. "
            f"Allowed: {sorted(ALLOWED_MEASURES)}"
        )


# --------------------------------------------------------------------------- #
# W4 PR 4: isolated Pallium harness with operational_fact derivation on       #
# --------------------------------------------------------------------------- #


def build_isolated_client_with_operational_fact_enabled(
    *,
    scenario_id: str,
):
    """Build a TestClient against an isolated Pallium service.

    Feature flag ``operational_fact_derivation`` is enabled. The
    ``agent_work_trace`` semantic package is wired so
    ``build_thread_summary`` produces both ``task_trace`` and
    ``operational_fact`` MemoryObjects. The ``agent_conversation_memory``
    package is also wired so the routing gate and
    ``operational_intent`` signal are active on ``/query`` requests.

    Note: this deviates from scenario_05's DEMO_SEMANTIC_PACKAGES
    config — see the scenario 5 diagnostic "delivery-side depends on a
    container with the injection policy configured (W1 territory)".
    For operational_fact scenarios we must drive delivery, so we use
    the full agent-conversation package + injection-policy shape.
    """
    from app.config import (
        AppConfig,
        FeaturesConfig,
        InjectionConfig,
        InjectionPolicyConfig,
        InjectionTypePolicy,
        LLMProviderConfig,
        SemanticPackageConfig,
    )
    from app.main import create_app
    from storage.vector_index import VectorIndexConfig
    from starlette.testclient import TestClient

    tmp = Path(tempfile.mkdtemp(prefix=f"pallium-{scenario_id}-"))

    # Stub LLM provider — the derivation predicate never calls it, but
    # agent_work_trace's build_thread_summary invokes it for the
    # task_trace outcome field. We do NOT want real LLM calls in eval.
    import app.dependencies as _deps

    from providers.llm.base import LLMJsonResponse, LLMProvider

    class _StubLLMProvider(LLMProvider):
        def generate_json(self, *, system_prompt, user_prompt, schema_description):
            return LLMJsonResponse(
                raw_text='{"outcome": null}',
                parsed_json={"outcome": None},
            )

    _deps.build_llm_provider = lambda config, **_: _StubLLMProvider()

    config = AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{tmp / f'{scenario_id}.db'}",
        default_use_case="agent_conversation_memory",
        llm_providers={
            "stub": LLMProviderConfig(
                name="stub",
                kind="openai_compatible",
                base_url="http://stub.local",
                api_key="stub",
                timeout_seconds=30.0,
            )
        },
        semantic_packages={
            "agent_conversation_memory": SemanticPackageConfig(
                name="agent_conversation_memory",
                implementation="agent_conversation_memory",
                enabled=True,
                llm_provider="stub",
                model="stub-model",
                prompt_variant="strict_typed_memory_v6_work_state_examples",
            ),
            "agent_work_trace": SemanticPackageConfig(
                name="agent_work_trace",
                implementation="agent_work_trace",
                enabled=True,
                llm_provider="stub",
                model="stub-model",
            ),
        },
        vector_index=VectorIndexConfig(enabled=False),
        injection=InjectionConfig(
            policy=InjectionPolicyConfig(
                types={
                    "operational_fact": InjectionTypePolicy(mode="on_demand"),
                }
            )
        ),
        features=FeaturesConfig(operational_fact_derivation=True),
    )
    app = create_app(config)
    return TestClient(app), tmp


def count_proactive_operational_fact_injections(storage, container_ref: str) -> int:
    """Count query_audit_log rows where an operational_fact was injected proactively.

    "Proactive" here maps to the audit-log schema as: a query with
    ``trigger_origin IS NULL`` (no deterministic Phase-4 trigger fired),
    ``should_inject=1``, and ``injected_blocks_json`` containing at
    least one block whose ``memory_type == "operational_fact"``.

    NOTE ON SCHEMA: ``injection_mode`` is NOT a column on
    ``query_audit_log``. The design doc's phrasing "injection_mode=
    'proactive'" refers conceptually to the routing gate's own mode
    reasoning (proactive vs on_demand vs event vs suspended) which
    lives in ``injection_policy``, not in the audit log. The audit
    log records the *outcome* of the routing decision; a proactive
    injection maps to (trigger_origin IS NULL, should_inject=1,
    block-of-type-operational_fact present).

    Raises the caller's OperationalError if the table shape drifts —
    this is an acceptance-guard function; silent zero would mask
    schema regressions. The outer try/except in scenarios can
    choose to demote to INCOMPLETE, but here we fail loud.
    """
    from sqlalchemy import text as _text

    with storage._engine.connect() as conn:
        row = conn.execute(
            _text(
                "SELECT COUNT(*) FROM query_audit_log "
                "WHERE container_ref = :ref "
                "  AND should_inject = 1 "
                "  AND trigger_origin IS NULL "
                "  AND injected_blocks_json IS NOT NULL "
                "  AND injected_blocks_json LIKE :pat"
            ),
            {"ref": container_ref, "pat": '%"memory_type": "operational_fact"%'},
        ).scalar()
    return int(row or 0)
