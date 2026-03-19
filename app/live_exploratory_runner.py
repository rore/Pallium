from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi.testclient import TestClient

from app.agent_simulation import AgentSimulationApp, TerminalIO
from app.agent_simulation_model import ThinAgentModel
from app.config import AppConfig
from app.main import create_app
from app.worker import run_worker
from core.contracts import ItemProcessingResult
from semantic.agent_conversation_memory_routing import RoutingOverrides

TERMINAL_PROCESSING_STATUSES = {"completed", "failed", "skipped"}
DEFAULT_STAGE_TIMEOUT_SECONDS = 180.0
DEFAULT_STAGE_POLL_INTERVAL_SECONDS = 0.25


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')


@dataclass
class FakeIO:
    responses: list[str]

    def __post_init__(self) -> None:
        self.outputs: list[str] = []

    def prompt(self, text: str) -> str:
        self.outputs.append(text)
        if not self.responses:
            raise AssertionError(f"unexpected prompt: {text}")
        return self.responses.pop(0)

    def write(self, text: str) -> None:
        self.outputs.append(text)


class HarnessHttpFromTestClient:
    def __init__(self, client: TestClient) -> None:
        self.base_url = "http://testserver"
        self._client = client

    def create_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post("/items", json=payload)
        response.raise_for_status()
        return response.json()

    def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post("/query", json=payload)
        response.raise_for_status()
        return response.json()

    def query_debug(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post("/query/debug", json=payload)
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        return None


class TimedHarnessHttpFromTestClient(HarnessHttpFromTestClient):
    def __init__(self, client: TestClient) -> None:
        super().__init__(client)
        self.create_item_timings: list[float] = []
        self.query_timings: list[float] = []
        self.query_debug_timings: list[float] = []

    def create_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        response = super().create_item(payload)
        self.create_item_timings.append(time.perf_counter() - started)
        return response

    def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        response = super().query(payload)
        self.query_timings.append(time.perf_counter() - started)
        return response

    def query_debug(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        response = super().query_debug(payload)
        self.query_debug_timings.append(time.perf_counter() - started)
        return response


class TimedThinAgentModel:
    def __init__(self, *, config: AppConfig) -> None:
        self._model = ThinAgentModel(config=config)
        self.resolution_timings: list[float] = []
        self.draft_timings: list[float] = []

    def resolution(self):
        started = time.perf_counter()
        resolution = self._model.resolution()
        self.resolution_timings.append(time.perf_counter() - started)
        return resolution

    def draft_answer(self, *, user_message: str, injectable_blocks: list[dict[str, Any]]):
        started = time.perf_counter()
        draft = self._model.draft_answer(user_message=user_message, injectable_blocks=injectable_blocks)
        self.draft_timings.append(time.perf_counter() - started)
        return draft


@dataclass(frozen=True)
class LiveScenarioWaits:
    wait_for_initial_user_processing: bool = True
    wait_for_initial_assistant_processing: bool = True
    wait_for_thread_rebuild: bool = False
    wait_for_followup_assistant_processing: bool = False
    timeout_seconds: float = DEFAULT_STAGE_TIMEOUT_SECONDS
    poll_interval_seconds: float = DEFAULT_STAGE_POLL_INTERVAL_SECONDS
    use_full_queue_drain: bool = False


@dataclass(frozen=True)
class LiveScenario:
    id: str
    description: str
    initial_scope: dict[str, Any]
    followup_scope: dict[str, Any]
    initial_message: str
    followup_message: str
    initial_required_terms: list[str]
    followup_expectations: dict[str, Any]
    waits: LiveScenarioWaits = field(default_factory=LiveScenarioWaits)


class StageTimeoutError(RuntimeError):
    def __init__(
        self,
        *,
        stage_label: str,
        source_item_id: str,
        timeout_seconds: float,
        last_status: ItemProcessingResult | None,
    ) -> None:
        super().__init__(f"{stage_label} after {timeout_seconds:.2f}s for source_item_id={source_item_id}")
        self.stage_label = stage_label
        self.source_item_id = source_item_id
        self.timeout_seconds = timeout_seconds
        self.last_status = last_status

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage_label": self.stage_label,
            "source_item_id": self.source_item_id,
            "timeout_seconds": self.timeout_seconds,
            "last_status": self.last_status.as_dict() if self.last_status is not None else None,
        }


@dataclass(frozen=True)
class WaitOutcome:
    status: ItemProcessingResult
    item_processing_seconds: float
    thread_rebuild_wait_seconds: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_processing_seconds": self.item_processing_seconds,
            "thread_rebuild_wait_seconds": self.thread_rebuild_wait_seconds,
            "final_status": self.status.as_dict(),
        }


class BackgroundProcessor:
    def __init__(
        self,
        *,
        config: AppConfig,
        worker_id: str,
        poll_interval_seconds: float = 0.1,
        lease_seconds: int | None = None,
        max_attempts: int | None = None,
    ) -> None:
        self._config = config
        self.worker_id = worker_id
        self._poll_interval_seconds = poll_interval_seconds
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts
        self._stop_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._exit_code: int | None = None
        self._failure: BaseException | None = None

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("background processor already started")

        def _target() -> None:
            try:
                args = [
                    "--worker-id",
                    self.worker_id,
                    "--poll-interval-seconds",
                    str(self._poll_interval_seconds),
                ]
                if self._lease_seconds is not None:
                    args.extend(["--lease-seconds", str(self._lease_seconds)])
                if self._max_attempts is not None:
                    args.extend(["--max-attempts", str(self._max_attempts)])
                self._exit_code = run_worker(
                    args,
                    config=self._config,
                    should_stop=self._stop_requested.is_set,
                    install_signal_handlers=False,
                )
            except BaseException as exc:  # pragma: no cover - surfaced through stop()
                self._failure = exc

        self._thread = threading.Thread(target=_target, name=f"live-runner:{self.worker_id}", daemon=True)
        self._thread.start()

    def stop(self, *, join_timeout_seconds: float = 60.0) -> None:
        if self._thread is None:
            return
        self._stop_requested.set()
        self._thread.join(timeout=join_timeout_seconds)
        if self._thread.is_alive():
            raise RuntimeError(f"background processor did not stop cleanly: {self.worker_id}")
        if self._failure is not None:
            raise RuntimeError(f"background processor failed: {self.worker_id}") from self._failure

    def __enter__(self) -> BackgroundProcessor:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()


def build_explicit_live_config(db_path: Path) -> AppConfig:
    base = AppConfig.from_env()
    packages = dict(base.semantic_packages)
    packages["llm_agent_memory"] = replace(
        packages["llm_agent_memory"],
        prompt_variant="strict_typed_memory_v5_compact_examples",
    )
    packages["agent_conversation_memory"] = replace(
        packages["agent_conversation_memory"],
        prompt_variant="strict_typed_memory_v6_work_state_examples",
    )
    return AppConfig(
        storage_backend=base.storage_backend,
        sqlite_url=f"sqlite:///{db_path.as_posix()}",
        default_use_case="agent_conversation_memory",
        llm_providers=base.llm_providers,
        semantic_packages=packages,
        observability=base.observability,
        retention=base.retention,
        llm_provider=None,
        llm_model=None,
        llm_base_url=None,
        llm_api_key=None,
        llm_prompt_variant=None,
        llm_timeout_seconds=None,
    )


def set_scope(harness: AgentSimulationApp, scope: dict[str, Any]) -> None:
    harness.session.defaults.container_ref = scope["container_ref"]
    harness.session.defaults.thread_ref = scope["thread_ref"]
    harness.session.defaults.session_ref = scope["session_ref"]
    harness.session.defaults.visibility_context = {"kind": "public", "id": None}
    harness.session.defaults.set_runtime_context("turn_kind", scope["turn_kind"], manual=True)
    harness.session.defaults.set_runtime_context("session_has_sufficient_local_context", scope["session_has_sufficient_local_context"], manual=True)


def evaluate_followup(query_response: dict[str, Any], expectations: dict[str, Any]) -> dict[str, Any]:
    blocks = query_response.get("injectable_blocks") or []
    combined_text = "\n".join(block.get("text", "") for block in blocks)
    combined_text += "\n" + "\n".join((result.get("excerpt") or "") for result in query_response.get("results", []))
    selected_layer = query_response.get("trace", {}).get("routing", {}).get("selected_layer")
    must_include_hits = [term for term in expectations["must_include"] if term.lower() in combined_text.lower()]
    must_not_include_hits = [term for term in expectations["must_not_include"] if term.lower() in combined_text.lower()]
    return {
        "selected_layer": selected_layer,
        "should_inject": query_response.get("should_inject"),
        "decision_reason": query_response.get("decision_reason"),
        "should_inject_match": query_response.get("should_inject") == expectations["should_inject"],
        "decision_reason_match": query_response.get("decision_reason") == expectations["decision_reason"],
        "selected_layer_match": selected_layer in expectations["selected_layers"],
        "must_include_hits": must_include_hits,
        "must_include_ok": len(must_include_hits) == len(expectations["must_include"]),
        "must_not_include_hits": must_not_include_hits,
        "must_not_include_ok": not must_not_include_hits,
    }


def classify_result(initial_answer: str, initial_required_terms: list[str], followup_eval: dict[str, Any]) -> tuple[str, list[str]]:
    lowered = initial_answer.lower()
    initial_hits = [term for term in initial_required_terms if term.lower() in lowered]
    initial_usable = len(initial_hits) == len(initial_required_terms)
    followup_pass = all(
        (
            followup_eval["should_inject_match"],
            followup_eval["decision_reason_match"],
            followup_eval["selected_layer_match"],
            followup_eval["must_include_ok"],
            followup_eval["must_not_include_ok"],
        )
    )
    if followup_pass:
        return "pass", initial_hits
    if not initial_usable:
        return "model_quality_miss", initial_hits
    return "pallium_failure_after_usable_answer", initial_hits


def wait_for_item_processing(
    get_status: Callable[[str], ItemProcessingResult],
    source_item_id: str,
    *,
    stage_timeout_label: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
    wait_for_thread_rebuild: bool = False,
) -> WaitOutcome:
    started = time.perf_counter()
    item_completed_at: float | None = None
    last_status: ItemProcessingResult | None = None
    while True:
        last_status = get_status(source_item_id)
        now = time.perf_counter()
        if last_status.processing_status in TERMINAL_PROCESSING_STATUSES and item_completed_at is None:
            item_completed_at = now
        if last_status.processing_status in TERMINAL_PROCESSING_STATUSES:
            needs_thread_wait = wait_for_thread_rebuild and last_status.thread_rebuild_requested and not last_status.thread_rebuild_completed
            if not needs_thread_wait:
                item_done = item_completed_at if item_completed_at is not None else now
                return WaitOutcome(
                    status=last_status,
                    item_processing_seconds=item_done - started,
                    thread_rebuild_wait_seconds=max(0.0, now - item_done),
                )
        if now - started >= timeout_seconds:
            raise StageTimeoutError(
                stage_label=stage_timeout_label,
                source_item_id=source_item_id,
                timeout_seconds=timeout_seconds,
                last_status=last_status,
            )
        time.sleep(poll_interval_seconds)


def wait_for_turn_event_processing(
    get_status: Callable[[str], ItemProcessingResult],
    event: dict[str, Any],
    *,
    wait_for_user_processing: bool,
    wait_for_assistant_processing: bool,
    wait_for_thread_rebuild: bool,
    timeout_seconds: float,
    poll_interval_seconds: float,
    user_timeout_label: str,
    assistant_timeout_label: str,
    use_full_queue_drain: bool = False,
    drain_fn: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if use_full_queue_drain:
        if drain_fn is None:
            raise ValueError("drain_fn is required when use_full_queue_drain is enabled")
        started = time.perf_counter()
        drain_fn()
        elapsed = time.perf_counter() - started
        return {
            "used_full_queue_drain": True,
            "drain_seconds": elapsed,
            "user_item_processing": None,
            "assistant_item_processing": None,
        }

    user_wait = None
    assistant_wait = None
    if wait_for_user_processing:
        user_source_item_id = event["user_item"]["response"]["source_item_id"]
        user_wait = wait_for_item_processing(
            get_status,
            user_source_item_id,
            stage_timeout_label=user_timeout_label,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            wait_for_thread_rebuild=False,
        )
    if wait_for_assistant_processing and event.get("assistant"):
        assistant_source_item_id = event["assistant"]["response"]["source_item_id"]
        assistant_wait = wait_for_item_processing(
            get_status,
            assistant_source_item_id,
            stage_timeout_label=assistant_timeout_label,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            wait_for_thread_rebuild=wait_for_thread_rebuild,
        )
    return {
        "used_full_queue_drain": False,
        "user_item_processing": user_wait.as_dict() if user_wait is not None else None,
        "assistant_item_processing": assistant_wait.as_dict() if assistant_wait is not None else None,
    }


def _default_scenarios() -> list[LiveScenario]:
    return [
        LiveScenario(
            id="live_export_decision_recall",
            description="Live assistant writes a natural carry-forward decision, then a fresh thread asks for the exact resource tweak.",
            initial_scope={
                "container_ref": "chat:live:export",
                "thread_ref": "chat:live:export:history",
                "session_ref": "session:live:export:history",
                "turn_kind": "same_thread_continuation",
                "session_has_sufficient_local_context": True,
            },
            followup_scope={
                "container_ref": "chat:live:export",
                "thread_ref": "chat:live:export:current",
                "session_ref": "session:live:export:current",
                "turn_kind": "new_thread",
                "session_has_sufficient_local_context": False,
            },
            initial_message="I checked the pod events: the export worker keeps getting OOMKilled during CSV generation because it hits the 512Mi memory limit. Give me a short, natural carry-forward answer with the concrete change you would make.",
            followup_message="Wait, which thing were we bumping and what stayed the same?",
            initial_required_terms=["512Mi"],
            followup_expectations={
                "should_inject": True,
                "decision_reason": "carry_forward_available",
                "selected_layers": {"decision", "lower_level_memory"},
                "must_include": ["512Mi"],
                "must_not_include": [],
            },
        ),
        LiveScenario(
            id="live_resume_sync_checkpoint",
            description="Live assistant writes a natural resume summary, then a sloppy resumed-work question asks what is still blocking and where to restart.",
            initial_scope={
                "container_ref": "chat:live:sync",
                "thread_ref": "chat:live:sync:history",
                "session_ref": "session:live:sync:history",
                "turn_kind": "same_thread_continuation",
                "session_has_sufficient_local_context": True,
            },
            followup_scope={
                "container_ref": "chat:live:sync",
                "thread_ref": "chat:live:sync:current",
                "session_ref": "session:live:sync:current",
                "turn_kind": "resumed_session",
                "session_has_sufficient_local_context": False,
            },
            initial_message="Quick recap so I can come back later: token refresh is fixed, the sync got through batch 417, and now the catalog API is rate limiting us after retries. Give me a short natural handoff with what still blocks us and where to resume.",
            followup_message="I am back in this mess. What is still stopping us and where do I pick it up?",
            initial_required_terms=["batch 417"],
            followup_expectations={
                "should_inject": True,
                "decision_reason": "carry_forward_available",
                "selected_layers": {"task_checkpoint"},
                "must_include": ["batch 417"],
                "must_not_include": ["token refresh is fixed"],
            },
            waits=LiveScenarioWaits(wait_for_thread_rebuild=True),
        ),
        LiveScenario(
            id="live_review_followup_checkpoint",
            description="Live assistant writes a natural review-status handoff, then a later follow-up asks what is still open now.",
            initial_scope={
                "container_ref": "chat:live:review",
                "thread_ref": "chat:live:review:history",
                "session_ref": "session:live:review:history",
                "turn_kind": "same_thread_continuation",
                "session_has_sufficient_local_context": True,
            },
            followup_scope={
                "container_ref": "chat:live:review",
                "thread_ref": "chat:live:review:current",
                "session_ref": "session:live:review:current",
                "turn_kind": "resumed_session",
                "session_has_sufficient_local_context": False,
            },
            initial_message="Status recap before I pause: the admin toggle wiring is ready, but branch kiosk fallback coverage is still missing before review can pass. Give me a short carry-forward note in natural language.",
            followup_message="What is actually still open now, not the older blocker?",
            initial_required_terms=["branch kiosk"],
            followup_expectations={
                "should_inject": True,
                "decision_reason": "carry_forward_available",
                "selected_layers": {"task_checkpoint"},
                "must_include": ["branch kiosk", "review"],
                "must_not_include": [],
            },
            waits=LiveScenarioWaits(wait_for_thread_rebuild=True),
        ),
        LiveScenario(
            id="live_exact_evidence_recall",
            description="Live assistant writes a natural summary containing an exact proof line, then a later follow-up asks for the smoking-gun line.",
            initial_scope={
                "container_ref": "chat:live:evidence",
                "thread_ref": "chat:live:evidence:history",
                "session_ref": "session:live:evidence:history",
                "turn_kind": "same_thread_continuation",
                "session_has_sufficient_local_context": True,
            },
            followup_scope={
                "container_ref": "chat:live:evidence",
                "thread_ref": "chat:live:evidence:current",
                "session_ref": "session:live:evidence:current",
                "turn_kind": "new_thread",
                "session_has_sufficient_local_context": False,
            },
            initial_message="The exact clue in the logs was 'job already running, skipping new start'. Give me a one-line takeaway I can reuse later without sounding robotic.",
            followup_message="What was the smoking-gun line again?",
            initial_required_terms=["job already running", "skipping new start"],
            followup_expectations={
                "should_inject": True,
                "decision_reason": "carry_forward_available",
                "selected_layers": {"source_evidence", "investigation_outcome"},
                "must_include": ["job already running", "skipping new start"],
                "must_not_include": [],
            },
        ),
    ]


SCENARIOS = _default_scenarios()


def _build_shadow_diff(
    primary_response: dict[str, Any],
    shadow_response: dict[str, Any],
    primary_eval: dict[str, Any],
    shadow_eval: dict[str, Any],
) -> dict[str, Any]:
    p_inject = primary_eval.get("should_inject")
    s_inject = shadow_eval.get("should_inject")
    p_reason = primary_eval.get("decision_reason")
    s_reason = shadow_eval.get("decision_reason")
    p_layer = primary_eval.get("selected_layer")
    s_layer = shadow_eval.get("selected_layer")
    p_routing = (primary_response.get("trace") or {}).get("routing") or {}
    s_routing = (shadow_response.get("trace") or {}).get("routing") or {}
    p_fallback = bool((p_routing.get("fallback") or {}).get("applied", False))
    s_fallback = bool((s_routing.get("fallback") or {}).get("applied", False))
    p_pass = primary_eval.get("should_inject_match") and primary_eval.get("decision_reason_match") and primary_eval.get("selected_layer_match") and primary_eval.get("must_include_ok") and primary_eval.get("must_not_include_ok")
    s_pass = shadow_eval.get("should_inject_match") and shadow_eval.get("decision_reason_match") and shadow_eval.get("selected_layer_match") and shadow_eval.get("must_include_ok") and shadow_eval.get("must_not_include_ok")
    shadow_improves = bool(not p_pass and s_pass)
    shadow_regresses = bool(p_pass and not s_pass)
    shadow_neutral = not shadow_improves and not shadow_regresses
    return {
        "should_inject_primary": p_inject,
        "should_inject_shadow": s_inject,
        "should_inject_changed": p_inject != s_inject,
        "decision_reason_primary": p_reason,
        "decision_reason_shadow": s_reason,
        "decision_reason_changed": p_reason != s_reason,
        "selected_layer_primary": p_layer,
        "selected_layer_shadow": s_layer,
        "selected_layer_changed": p_layer != s_layer,
        "fallback_applied_primary": p_fallback,
        "fallback_applied_shadow": s_fallback,
        "fallback_changed": p_fallback != s_fallback,
        "primary_eval_pass": bool(p_pass),
        "shadow_eval_pass": bool(s_pass),
        "shadow_improves": shadow_improves,
        "shadow_regresses": shadow_regresses,
        "shadow_neutral": shadow_neutral,
    }


def run_scenario(
    output_dir: Path,
    scenario: LiveScenario,
    *,
    shadow_routing_overrides: RoutingOverrides | None = None,
) -> dict[str, Any]:
    db_path = output_dir / f"{scenario.id}.sqlite3"
    config = build_explicit_live_config(db_path)
    client = TestClient(create_app(config))
    io = FakeIO(["a", "n", "a", "n"])
    model = TimedThinAgentModel(config=config)
    http_client = TimedHarnessHttpFromTestClient(client)
    harness = AgentSimulationApp(
        http_client=http_client,
        io=TerminalIO(input_func=io.prompt, output_func=io.write),
        model=model,
    )
    total_started = time.perf_counter()
    processor = BackgroundProcessor(
        config=config,
        worker_id=f"live-exploratory:{scenario.id}:processor",
        poll_interval_seconds=min(0.1, scenario.waits.poll_interval_seconds),
    )
    try:
        with processor:
            set_scope(harness, scenario.initial_scope)
            harness.process_chat_message(scenario.initial_message)
            first_event = harness.session.events[0]
            initial_waits = wait_for_turn_event_processing(
                client.app.state.pallium_service.get_item_processing,
                first_event,
                wait_for_user_processing=scenario.waits.wait_for_initial_user_processing,
                wait_for_assistant_processing=scenario.waits.wait_for_initial_assistant_processing,
                wait_for_thread_rebuild=scenario.waits.wait_for_thread_rebuild,
                timeout_seconds=scenario.waits.timeout_seconds,
                poll_interval_seconds=scenario.waits.poll_interval_seconds,
                user_timeout_label="user_item_processing_timeout",
                assistant_timeout_label="assistant_item_processing_timeout",
                use_full_queue_drain=scenario.waits.use_full_queue_drain,
                drain_fn=lambda: client.app.state.pallium_service.drain_processing_queue(
                    worker_id=f"live-exploratory:{scenario.id}:initial-drain"
                ),
            )
            initial_answer = first_event.get("assistant", {}).get("request", {}).get("content", "")

            set_scope(harness, scenario.followup_scope)
            harness.process_chat_message(scenario.followup_message)
            second_event = harness.session.events[1]
            followup_waits = wait_for_turn_event_processing(
                client.app.state.pallium_service.get_item_processing,
                second_event,
                wait_for_user_processing=False,
                wait_for_assistant_processing=scenario.waits.wait_for_followup_assistant_processing,
                wait_for_thread_rebuild=False,
                timeout_seconds=scenario.waits.timeout_seconds,
                poll_interval_seconds=scenario.waits.poll_interval_seconds,
                user_timeout_label="followup_user_processing_timeout",
                assistant_timeout_label="followup_processing_timeout",
                use_full_queue_drain=False,
            )
            followup_response = second_event["query_debug"]["response"]
            followup_eval = evaluate_followup(followup_response, scenario.followup_expectations)
            classification, initial_hits = classify_result(initial_answer, scenario.initial_required_terms, followup_eval)

            ingested_items: list[dict[str, Any]] = []
            for event in [first_event, second_event]:
                user_req = (event.get("user_item") or {}).get("request")
                if user_req:
                    ingested_items.append(user_req)
                assistant_req = (event.get("assistant") or {}).get("request")
                if assistant_req:
                    ingested_items.append(assistant_req)

            shadow_comparison: dict[str, Any] | None = None
            if shadow_routing_overrides is not None:
                shadow_client = TestClient(create_app(config, routing_overrides=shadow_routing_overrides))
                try:
                    shadow_query_payload = second_event["query_debug"]["request"]
                    shadow_raw = shadow_client.post("/query/debug", json=shadow_query_payload)
                    shadow_raw.raise_for_status()
                    shadow_response = shadow_raw.json()
                    shadow_eval = evaluate_followup(shadow_response, scenario.followup_expectations)
                    shadow_comparison = _build_shadow_diff(followup_response, shadow_response, followup_eval, shadow_eval)
                finally:
                    shadow_client.close()

            timings = {
                "model_resolution_seconds": model.resolution_timings[0] if model.resolution_timings else None,
                "initial_thin_agent_draft_seconds": model.draft_timings[0] if model.draft_timings else None,
                "followup_thin_agent_draft_seconds": model.draft_timings[1] if len(model.draft_timings) > 1 else None,
                "initial_user_item_processing_seconds": (initial_waits["user_item_processing"] or {}).get("item_processing_seconds"),
                "initial_assistant_item_processing_seconds": (initial_waits["assistant_item_processing"] or {}).get("item_processing_seconds"),
                "thread_rebuild_wait_seconds": (initial_waits["assistant_item_processing"] or {}).get("thread_rebuild_wait_seconds"),
                "followup_query_debug_seconds": http_client.query_debug_timings[1] if len(http_client.query_debug_timings) > 1 else None,
                "followup_assistant_processing_seconds": (followup_waits["assistant_item_processing"] or {}).get("item_processing_seconds"),
                "total_wall_clock_seconds": time.perf_counter() - total_started,
            }

            result = {
                "scenario_id": scenario.id,
                "description": scenario.description,
                "config": {
                    "default_use_case": config.default_use_case,
                    "llm_agent_memory_prompt_variant": config.package_config("llm_agent_memory").prompt_variant,
                    "agent_conversation_memory_prompt_variant": config.package_config("agent_conversation_memory").prompt_variant,
                    "provider": config.package_config("agent_conversation_memory").llm_provider,
                    "model": config.package_config("agent_conversation_memory").model,
                },
                "wait_contract": asdict(scenario.waits),
                "timings": timings,
                "initial_waits": initial_waits,
                "followup_waits": followup_waits,
                "initial_message": scenario.initial_message,
                "initial_answer": initial_answer,
                "initial_required_hits": initial_hits,
                "initial_model_resolution": first_event.get("model", {}).get("resolution"),
                "followup_message": scenario.followup_message,
                "followup_query_request": second_event["query_debug"]["request"],
                "followup_query_response": followup_response,
                "followup_evaluation": followup_eval,
                "classification": classification,
                "ingested_items": ingested_items,
                "shadow_comparison": shadow_comparison,
                "io_outputs": io.outputs,
            }
            _write_json(output_dir / f"{scenario.id}.json", result)
            return result
    finally:
        client.close()


def run_scenarios(
    *,
    scenarios: list[LiveScenario] | None = None,
    output_root: Path | None = None,
    shadow_routing_overrides: RoutingOverrides | None = None,
) -> tuple[Path, list[dict[str, Any]], list[dict[str, Any]]]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (output_root or Path("tmp")) / f"exploratory-live-harness-{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for scenario in scenarios or SCENARIOS:
        try:
            results.append(run_scenario(output_dir, scenario, shadow_routing_overrides=shadow_routing_overrides))
        except StageTimeoutError as exc:
            failure = {
                "scenario_id": scenario.id,
                "failure_kind": "orchestration_timeout",
                "error": type(exc).__name__,
                "message": str(exc),
                "timeout": exc.as_dict(),
            }
            failures.append(failure)
            _write_json(output_dir / f"{scenario.id}__error.json", failure)
        except Exception as exc:
            failure = {
                "scenario_id": scenario.id,
                "failure_kind": "runner_error",
                "error": type(exc).__name__,
                "message": str(exc),
            }
            failures.append(failure)
            _write_json(output_dir / f"{scenario.id}__error.json", failure)
    return output_dir, results, failures


def _extract_drift_signals(result: dict[str, Any]) -> dict[str, Any]:
    routing = (
        (result.get("followup_query_response") or {})
        .get("trace", {})
        .get("routing", {})
    )
    has_trace = bool(routing)
    eval_ = result.get("followup_evaluation") or {}
    timings = result.get("timings") or {}
    should_inject = eval_.get("should_inject")
    selected_layer = eval_.get("selected_layer")
    fallback_applied = bool((routing.get("fallback") or {}).get("applied", False))
    sharp_candidates = routing.get("sharp_candidate_diagnostics") or []
    sharp_miss_stages: list[str] = [
        str(c.get("loss_stage", ""))
        for c in sharp_candidates
        if c.get("loss_stage") != "selected"
    ]
    has_sharp_miss = bool(sharp_miss_stages)
    rebuild_seconds = timings.get("thread_rebuild_wait_seconds")
    has_thread_rebuild = isinstance(rebuild_seconds, (int, float)) and rebuild_seconds > 0
    return {
        "has_trace": has_trace,
        "should_inject": should_inject,
        "selected_layer": selected_layer,
        "fallback_applied": fallback_applied,
        "has_sharp_miss": has_sharp_miss,
        "sharp_miss_stages": sharp_miss_stages,
        "has_thread_rebuild": has_thread_rebuild,
    }


def _aggregate_drift_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios_total = len(results)
    scenarios_with_trace = 0
    injection_count = 0
    sharp_miss_count = 0
    sharp_miss_by_stage: dict[str, int] = {"retrieval": 0, "routing": 0, "packaging": 0, "injection_cap": 0}
    fallback_count = 0
    rebuild_count = 0
    injected_total = 0
    generic_summary_win_count = 0

    for result in results:
        signals = _extract_drift_signals(result)
        if signals["has_trace"]:
            scenarios_with_trace += 1
            if signals["should_inject"] is True:
                injection_count += 1
            if signals["has_sharp_miss"]:
                sharp_miss_count += 1
                for stage in signals["sharp_miss_stages"]:
                    if stage in sharp_miss_by_stage:
                        sharp_miss_by_stage[stage] += 1
            if signals["fallback_applied"]:
                fallback_count += 1
        if signals["has_thread_rebuild"]:
            rebuild_count += 1
        if signals["should_inject"] is True:
            injected_total += 1
            layer = signals["selected_layer"]
            if layer in {"thread_summary", "discussion_summary"}:
                generic_summary_win_count += 1

    def _rate(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator > 0 else None

    return {
        "scenarios_with_trace": scenarios_with_trace,
        "injection_rate": _rate(injection_count, scenarios_with_trace),
        "sharp_miss_rate": _rate(sharp_miss_count, scenarios_with_trace),
        "sharp_miss_by_loss_stage": sharp_miss_by_stage,
        "fallback_rate": _rate(fallback_count, scenarios_with_trace),
        "rebuild_rate": _rate(rebuild_count, scenarios_total) if scenarios_total > 0 else None,
        "generic_summary_win_rate": _rate(generic_summary_win_count, injected_total),
    }


def build_summary(output_dir: Path, results: list[dict[str, Any]], failures: list[dict[str, Any]]) -> dict[str, Any]:
    shadow_results = [r["shadow_comparison"] for r in results if r.get("shadow_comparison") is not None]
    shadow_summary: dict[str, Any] | None = None
    if shadow_results:
        shadow_summary = {
            "shadow_overrides_active": True,
            "scenarios_with_shadow": len(shadow_results),
            "shadow_improves_count": sum(1 for d in shadow_results if d["shadow_improves"]),
            "shadow_regresses_count": sum(1 for d in shadow_results if d["shadow_regresses"]),
            "shadow_neutral_count": sum(1 for d in shadow_results if d["shadow_neutral"]),
            "injection_flip_count": sum(1 for d in shadow_results if d["should_inject_changed"]),
            "layer_flip_count": sum(1 for d in shadow_results if d["selected_layer_changed"]),
        }
    summary = {
        "run_id": output_dir.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results_total": len(results),
        "error_total": len(failures),
        "classifications": {},
        "drift_metrics": _aggregate_drift_metrics(results),
        "shadow_summary": shadow_summary,
        "results": [
            {
                "scenario_id": result["scenario_id"],
                "classification": result["classification"],
                "selected_layer": result["followup_evaluation"]["selected_layer"],
                "should_inject": result["followup_evaluation"]["should_inject"],
                "decision_reason": result["followup_evaluation"]["decision_reason"],
                "must_include_hits": result["followup_evaluation"]["must_include_hits"],
                "must_not_include_hits": result["followup_evaluation"]["must_not_include_hits"],
                "timings": result["timings"],
            }
            for result in results
        ],
        "errors": failures,
    }
    for result in results:
        summary["classifications"][result["classification"]] = summary["classifications"].get(result["classification"], 0) + 1
    _write_json(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    output_dir, results, failures = run_scenarios()
    summary = build_summary(output_dir, results, failures)
    print(json.dumps(summary, indent=2))
    return 0 if not failures else 1
