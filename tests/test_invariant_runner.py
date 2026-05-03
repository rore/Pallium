"""Tests for invariant checks and the invariant runner.

The invariant check unit tests run against synthetic payloads and are fast.
Integration tests that spin up full Pallium instances should be added as
separate test classes with ``@pytest.mark.slow``.
"""
from __future__ import annotations

from evals.generated_exploratory import invariant_runner as runner
from evals.generated_exploratory.invariants import (
    InvariantResult,
    check_idf_discrimination,
    check_no_cross_actor_leak,
    check_no_cross_container_leak,
    check_no_greeting_in_blocks,
    check_no_off_topic_injection,
    check_no_personal_memory_in_shared_container,
    check_no_superseded_in_results,
    check_no_visibility_violation,
    check_no_wrong_role_memory,
    check_noise_no_injection,
    check_query_contract_consistency,
    check_recall_not_routed_as_noise,
    check_thread_level_memory_always_shared,
    run_invariants,
)


# ---------------------------------------------------------------------------
# Synthetic payloads for unit testing invariants
# ---------------------------------------------------------------------------

_EMPTY_SCENARIO: dict = {"current_query": {"text": "test", "container_ref": "chat:test"}}
_EMPTY_QUERY: dict = {"injectable_blocks": [], "should_inject": False, "decision_reason": "none"}
_EMPTY_DEBUG: dict = {
    "results": [],
    "should_inject": False,
    "decision_reason": "none",
    "injectable_blocks": [],
    "trace": {"routing": {}},
}


class TestINV01CrossContainerLeak:
    def test_pass_same_container(self):
        scenario = {"current_query": {"container_ref": "chat:A"}}
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_id": "r1", "container_ref": "chat:A", "result_kind": "memory_hit", "visibility": "private"},
        ]}
        result = check_no_cross_container_leak(scenario, _EMPTY_QUERY, debug)
        assert result.passed

    def test_fail_different_container_non_public(self):
        scenario = {"current_query": {"container_ref": "chat:A"}}
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_id": "r1", "container_ref": "chat:B", "result_kind": "memory_hit", "visibility": "private"},
        ]}
        result = check_no_cross_container_leak(scenario, _EMPTY_QUERY, debug)
        assert not result.passed
        assert "Cross-container leak" in result.details

    def test_pass_public_cross_container(self):
        """Public items are visible to all containers — not a leak."""
        scenario = {"current_query": {"container_ref": "chat:A"}}
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_id": "r1", "container_ref": "chat:B", "result_kind": "memory_hit", "visibility": "public"},
        ]}
        result = check_no_cross_container_leak(scenario, _EMPTY_QUERY, debug)
        assert result.passed

    def test_not_applicable_no_container(self):
        scenario = {"current_query": {}}
        result = check_no_cross_container_leak(scenario, _EMPTY_QUERY, _EMPTY_DEBUG)
        assert result.passed


class TestINV02WrongRoleMemory:
    def test_pass_user_evidence(self):
        debug = {**_EMPTY_DEBUG, "results": [
            {
                "result_id": "r1", "result_kind": "memory_hit", "type": "interest",
                "evidence": [{"role": "user"}],
            },
        ]}
        result = check_no_wrong_role_memory(_EMPTY_SCENARIO, _EMPTY_QUERY, debug)
        assert result.passed

    def test_fail_assistant_only_evidence(self):
        debug = {**_EMPTY_DEBUG, "results": [
            {
                "result_id": "r1", "result_kind": "memory_hit", "type": "interest",
                "evidence": [{"role": "assistant"}],
            },
        ]}
        result = check_no_wrong_role_memory(_EMPTY_SCENARIO, _EMPTY_QUERY, debug)
        assert not result.passed

    def test_pass_non_interest_type(self):
        debug = {**_EMPTY_DEBUG, "results": [
            {
                "result_id": "r1", "result_kind": "memory_hit", "type": "decision",
                "evidence": [{"role": "assistant"}],
            },
        ]}
        result = check_no_wrong_role_memory(_EMPTY_SCENARIO, _EMPTY_QUERY, debug)
        assert result.passed


class TestINV03OffTopicInjection:
    def test_pass_with_overlap(self):
        scenario = {"current_query": {"text": "catalog sync migration plan"}}
        query = {**_EMPTY_QUERY, "injectable_blocks": [
            {"result_id": "r1", "text": "The catalog migration is scheduled for next week."},
        ]}
        result = check_no_off_topic_injection(scenario, query, _EMPTY_DEBUG)
        assert result.passed

    def test_fail_no_overlap(self):
        scenario = {"current_query": {"text": "catalog sync migration plan"}}
        query = {**_EMPTY_QUERY, "injectable_blocks": [
            {"result_id": "r1", "text": "The weather forecast looks clear tomorrow."},
        ]}
        result = check_no_off_topic_injection(scenario, query, _EMPTY_DEBUG)
        assert not result.passed

    def test_pass_no_blocks(self):
        scenario = {"current_query": {"text": "anything"}}
        result = check_no_off_topic_injection(scenario, _EMPTY_QUERY, _EMPTY_DEBUG)
        assert result.passed

    def test_pass_prefix_match_singular_plural(self):
        """'holds' in query should match 'hold' in block via prefix overlap."""
        scenario = {"current_query": {"text": "What are the holds notification limits?"}}
        query = {**_EMPTY_QUERY, "injectable_blocks": [
            {"result_id": "r1", "text": "The hold queue limit was set to 8 active notifications per patron."},
        ]}
        result = check_no_off_topic_injection(scenario, query, _EMPTY_DEBUG)
        assert result.passed

    def test_pass_prefix_match_verb_forms(self):
        """'reserving' in block should match 'reservation' in query."""
        scenario = {"current_query": {"text": "What is the reservation policy?"}}
        query = {**_EMPTY_QUERY, "injectable_blocks": [
            {"result_id": "r1", "text": "Reserving items requires a valid library card."},
        ]}
        result = check_no_off_topic_injection(scenario, query, _EMPTY_DEBUG)
        assert result.passed

    def test_fail_short_prefix_no_match(self):
        """Short words that happen to share a prefix should not match."""
        scenario = {"current_query": {"text": "catalog sync plan"}}
        query = {**_EMPTY_QUERY, "injectable_blocks": [
            {"result_id": "r1", "text": "The cat jumped over the fence yesterday."},
        ]}
        result = check_no_off_topic_injection(scenario, query, _EMPTY_DEBUG)
        assert not result.passed


class TestINV04VisibilityViolation:
    def test_pass_public_results_visible_to_all(self):
        """Public results are exempt from container-scoping per core/filters.py."""
        scenario = {"current_query": {"container_ref": "chat:A", "visibility": "private"}}
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_id": "r1", "container_ref": "chat:B", "visibility": "public"},
        ]}
        result = check_no_visibility_violation(scenario, _EMPTY_QUERY, debug)
        assert result.passed

    def test_fail_private_from_wrong_container(self):
        scenario = {"current_query": {"container_ref": "chat:A", "visibility": "private"}}
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_id": "r1", "container_ref": "chat:B", "visibility": "private"},
        ]}
        result = check_no_visibility_violation(scenario, _EMPTY_QUERY, debug)
        assert not result.passed


class TestINV05RecallNotRoutedAsNoise:
    def test_pass_recall_not_low_value(self):
        scenario = {"current_query": {"text": "Didn't we discuss the catalog migration?"}}
        debug = {**_EMPTY_DEBUG, "trace": {"routing": {
            "query_signal_envelope": {"low_value": False},
        }}}
        result = check_recall_not_routed_as_noise(scenario, _EMPTY_QUERY, debug)
        assert result.passed

    def test_fail_recall_classified_low_value(self):
        scenario = {"current_query": {"text": "Didn't we discuss the catalog migration?"}}
        debug = {**_EMPTY_DEBUG, "trace": {"routing": {
            "query_signal_envelope": {"low_value": True},
        }}}
        result = check_recall_not_routed_as_noise(scenario, _EMPTY_QUERY, debug)
        assert not result.passed

    def test_not_applicable_no_recall_signal(self):
        scenario = {"current_query": {"text": "How do I configure the sync schedule?"}}
        result = check_recall_not_routed_as_noise(scenario, _EMPTY_QUERY, _EMPTY_DEBUG)
        assert result.passed


class TestINV06NoGreetingInBlocks:
    def test_pass_no_greeting(self):
        query = {**_EMPTY_QUERY, "injectable_blocks": [
            {"result_id": "r1", "text": "The catalog migration plan was approved last week."},
        ]}
        result = check_no_greeting_in_blocks(_EMPTY_SCENARIO, query, _EMPTY_DEBUG)
        assert result.passed

    def test_fail_greeting_block(self):
        query = {**_EMPTY_QUERY, "injectable_blocks": [
            {"result_id": "r1", "text": "Hello!"},
        ]}
        result = check_no_greeting_in_blocks(_EMPTY_SCENARIO, query, _EMPTY_DEBUG)
        assert not result.passed

    def test_pass_long_block_starting_with_greeting(self):
        """Blocks with substantial content after a greeting word are not phatic."""
        query = {**_EMPTY_QUERY, "injectable_blocks": [
            {"result_id": "r1", "text": "Hello team, I wanted to share the investigation findings about the catalog sync failure root cause analysis."},
        ]}
        result = check_no_greeting_in_blocks(_EMPTY_SCENARIO, query, _EMPTY_DEBUG)
        assert result.passed


class TestINV07QueryContractConsistency:
    def test_pass_consistent(self):
        query = {"should_inject": True, "decision_reason": "carry_forward_available", "injectable_blocks": [{"x": 1}]}
        debug = {**_EMPTY_DEBUG, "should_inject": True, "decision_reason": "carry_forward_available", "injectable_blocks": [{"x": 1}]}
        result = check_query_contract_consistency(_EMPTY_SCENARIO, query, debug)
        assert result.passed

    def test_fail_inconsistent_inject(self):
        query = {"should_inject": True, "decision_reason": "carry_forward_available", "injectable_blocks": []}
        debug = {**_EMPTY_DEBUG, "should_inject": False, "decision_reason": "carry_forward_available", "injectable_blocks": []}
        result = check_query_contract_consistency(_EMPTY_SCENARIO, query, debug)
        assert not result.passed


class TestINV08NoiseNoInjection:
    def test_pass_low_value_no_injection(self):
        debug = {**_EMPTY_DEBUG, "trace": {"routing": {
            "query_signal_envelope": {"low_value": True},
        }}}
        result = check_noise_no_injection(_EMPTY_SCENARIO, _EMPTY_QUERY, debug)
        assert result.passed

    def test_fail_low_value_with_injection(self):
        debug = {
            **_EMPTY_DEBUG,
            "should_inject": True,
            "injectable_blocks": [{"text": "something"}],
            "trace": {"routing": {"query_signal_envelope": {"low_value": True}}},
        }
        result = check_noise_no_injection(_EMPTY_SCENARIO, _EMPTY_QUERY, debug)
        assert not result.passed


class TestINV09NoSupersededInResults:
    def test_pass_active_only(self):
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_id": "r1", "result_kind": "memory_hit", "type": "decision", "payload": {"lifecycle_status": "active"}},
        ]}
        result = check_no_superseded_in_results(_EMPTY_SCENARIO, _EMPTY_QUERY, debug)
        assert result.passed

    def test_fail_superseded(self):
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_id": "r1", "result_kind": "memory_hit", "type": "decision", "payload": {"lifecycle_status": "superseded"}},
        ]}
        result = check_no_superseded_in_results(_EMPTY_SCENARIO, _EMPTY_QUERY, debug)
        assert not result.passed


class TestINV10IdfDiscrimination:
    def test_not_applicable_without_metadata(self):
        result = check_idf_discrimination(_EMPTY_SCENARIO, _EMPTY_QUERY, _EMPTY_DEBUG)
        assert result.passed
        assert "not applicable" in result.details

    def test_pass_expected_in_top(self):
        scenario = {"_generation_metadata": {"idf_expected_top_result_id": "r1", "idf_expected_top_n": 3}}
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_id": "r1"}, {"result_id": "r2"}, {"result_id": "r3"},
        ]}
        result = check_idf_discrimination(scenario, _EMPTY_QUERY, debug)
        assert result.passed

    def test_fail_expected_not_in_top(self):
        scenario = {"_generation_metadata": {"idf_expected_top_result_id": "r5", "idf_expected_top_n": 3}}
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_id": "r1"}, {"result_id": "r2"}, {"result_id": "r3"},
        ]}
        result = check_idf_discrimination(scenario, _EMPTY_QUERY, debug)
        assert not result.passed


class TestINV11NoPersonalMemoryInSharedContainer:
    def test_not_applicable_for_private(self):
        scenario = {"current_query": {"text": "test", "container_ref": "c", "visibility": "private"}}
        result = check_no_personal_memory_in_shared_container(scenario, _EMPTY_QUERY, _EMPTY_DEBUG)
        assert result.passed
        assert "not applicable" in result.details

    def test_pass_no_personal_types_in_public(self):
        scenario = {"current_query": {"text": "test", "container_ref": "c", "visibility": "public"}}
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_kind": "memory_hit", "type": "turn_summary", "visibility": "public"},
            {"result_kind": "memory_hit", "type": "decision", "visibility": "public"},
        ]}
        result = check_no_personal_memory_in_shared_container(scenario, _EMPTY_QUERY, debug)
        assert result.passed

    def test_fail_interest_in_public(self):
        scenario = {"current_query": {"text": "test", "container_ref": "c", "visibility": "public"}}
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_kind": "memory_hit", "type": "interest", "result_id": "r1", "visibility": "public"},
        ]}
        result = check_no_personal_memory_in_shared_container(scenario, _EMPTY_QUERY, debug)
        assert not result.passed
        assert "interest" in result.details.lower() or "personal" in result.details.lower()

    def test_fail_constraint_in_limited(self):
        scenario = {"current_query": {"text": "test", "container_ref": "c", "visibility": "container"}}
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_kind": "memory_hit", "type": "constraint_memory", "result_id": "r1", "visibility": "container"},
        ]}
        result = check_no_personal_memory_in_shared_container(scenario, _EMPTY_QUERY, debug)
        assert not result.passed


class TestINV12NoCrossActorLeak:
    def test_not_applicable_without_actor(self):
        result = check_no_cross_actor_leak(_EMPTY_SCENARIO, _EMPTY_QUERY, _EMPTY_DEBUG)
        assert result.passed
        assert "not applicable" in result.details

    def test_pass_shared_memories_visible(self):
        scenario = {"current_query": {"text": "test", "container_ref": "c", "actor_ref": "user:alice"}}
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_id": "r1", "actor_ref": None, "type": "decision"},
            {"result_id": "r2", "actor_ref": "user:alice", "type": "interest"},
        ]}
        result = check_no_cross_actor_leak(scenario, _EMPTY_QUERY, debug)
        assert result.passed

    def test_fail_other_actor_memory(self):
        scenario = {"current_query": {"text": "test", "container_ref": "c", "actor_ref": "user:alice"}}
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_id": "r1", "actor_ref": "user:bob", "type": "interest"},
        ]}
        result = check_no_cross_actor_leak(scenario, _EMPTY_QUERY, debug)
        assert not result.passed
        assert "bob" in result.details.lower() or "cross-actor" in result.details.lower()

    def test_pass_same_actor(self):
        scenario = {"current_query": {"text": "test", "container_ref": "c", "actor_ref": "user:alice"}}
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_id": "r1", "actor_ref": "user:alice", "type": "interest"},
        ]}
        result = check_no_cross_actor_leak(scenario, _EMPTY_QUERY, debug)
        assert result.passed


class TestINV13ThreadLevelMemoryAlwaysShared:
    def test_pass_no_thread_memories(self):
        result = check_thread_level_memory_always_shared(_EMPTY_SCENARIO, _EMPTY_QUERY, _EMPTY_DEBUG)
        assert result.passed

    def test_pass_thread_memory_with_null_actor(self):
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_kind": "memory_hit", "type": "thread_summary", "result_id": "r1", "actor_ref": None},
            {"result_kind": "memory_hit", "type": "task_checkpoint", "result_id": "r2", "actor_ref": None},
        ]}
        result = check_thread_level_memory_always_shared(_EMPTY_SCENARIO, _EMPTY_QUERY, debug)
        assert result.passed

    def test_fail_thread_summary_with_actor_ref(self):
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_kind": "memory_hit", "type": "thread_summary", "result_id": "r1", "actor_ref": "user:alice"},
        ]}
        result = check_thread_level_memory_always_shared(_EMPTY_SCENARIO, _EMPTY_QUERY, debug)
        assert not result.passed

    def test_fail_task_checkpoint_with_actor_ref(self):
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_kind": "memory_hit", "type": "task_checkpoint", "result_id": "r1", "actor_ref": "user:bob"},
        ]}
        result = check_thread_level_memory_always_shared(_EMPTY_SCENARIO, _EMPTY_QUERY, debug)
        assert not result.passed

    def test_ignores_non_thread_types(self):
        debug = {**_EMPTY_DEBUG, "results": [
            {"result_kind": "memory_hit", "type": "decision", "result_id": "r1", "actor_ref": "user:alice"},
        ]}
        result = check_thread_level_memory_always_shared(_EMPTY_SCENARIO, _EMPTY_QUERY, debug)
        assert result.passed


class TestRunInvariants:
    def test_runs_all_by_default(self):
        results = run_invariants(_EMPTY_SCENARIO, _EMPTY_QUERY, _EMPTY_DEBUG)
        assert len(results) == 16
        assert all(isinstance(r, InvariantResult) for r in results)

    def test_runs_selected_subset(self):
        results = run_invariants(
            _EMPTY_SCENARIO, _EMPTY_QUERY, _EMPTY_DEBUG,
            invariant_ids=["INV-01", "INV-07"],
        )
        assert len(results) == 2
        assert {r.invariant_id for r in results} == {"INV-01", "INV-07"}

    def test_unknown_invariant_fails_gracefully(self):
        results = run_invariants(
            _EMPTY_SCENARIO, _EMPTY_QUERY, _EMPTY_DEBUG,
            invariant_ids=["INV-99"],
        )
        assert len(results) == 1
        assert not results[0].passed
        assert results[0].severity == "error"


class TestInvariantRunnerSeededMemorySteps:
    def test_seed_memory_objects_step_persists_memory_and_index(self, monkeypatch):
        class FakeStorage:
            def __init__(self):
                self.memory_objects = []
                self.index_entries = []
                self.source_items = []
                self.relations = []

            def create_memory_object(self, memory_object):
                self.memory_objects.append(memory_object)

            def create_index_entry(self, index_entry):
                self.index_entries.append(index_entry)

            def create_source_item(self, source_item):
                self.source_items.append(source_item)

            def create_relation(self, relation):
                self.relations.append(relation)

        class FakeService:
            def __init__(self):
                self._storage = FakeStorage()

        class FakeAppState:
            def __init__(self):
                self.pallium_service = FakeService()

        class FakeApp:
            def __init__(self):
                self.state = FakeAppState()

        class FakeClient:
            def __init__(self):
                self.app = FakeApp()

        client = FakeClient()
        query_payload = {
            "should_inject": True,
            "decision_reason": "carry_forward_available",
            "injectable_blocks": [
                {
                    "result_id": "memory_object:fact-summary-alice",
                    "title": "Fact Summary",
                    "memory_type": "fact_summary",
                    "text": "Alice will take a train to Madrid for a family trip.",
                }
            ],
        }
        debug_payload = {
            **_EMPTY_DEBUG,
            "should_inject": True,
            "decision_reason": "carry_forward_available",
            "injectable_blocks": list(query_payload["injectable_blocks"]),
            "results": [
                {
                    "result_id": "memory_object:fact-summary-alice",
                    "result_kind": "memory_hit",
                    "type": "fact_summary",
                    "visibility": "container",
                    "container_ref": "chat:travel-notes",
                    "payload": {"summary": "Alice will take a train to Madrid for a family trip."},
                }
            ],
        }

        monkeypatch.setattr(runner, "_post_query", lambda client, request: query_payload)
        monkeypatch.setattr(runner, "_post_query_debug", lambda client, request: debug_payload)
        monkeypatch.setattr(
            runner,
            "run_invariants",
            lambda *args, **kwargs: [InvariantResult(invariant_id="INV-01", passed=True)],
        )

        scenario = {
            "scenario_id": "fact-summary-seeded-memory",
            "steps": [
                {
                    "action": "seed_memory_objects",
                    "memory_objects": [
                        {
                            "id": "fact-summary-alice",
                            "type": "fact_summary",
                            "schema_id": "conversational_knowledge.fact_summary",
                            "schema_version": "v1",
                            "visibility": "container",
                            "container_ref": "chat:travel-notes",
                            "payload": {
                                "subject": "Alice",
                                "category": "travel",
                                "summary": "Alice will take a train to Madrid for a family trip.",
                            },
                            "envelope": {
                                "schema_id": "core.memory_envelope",
                                "schema_version": "v1",
                                "kind": "finding",
                                "confidence": "high",
                                "scope": {"container_ref": "chat:travel-notes"},
                                "derivation": {
                                    "producer_kind": "consolidation",
                                    "producer_schema_id": "conversational_knowledge.fact_summary",
                                    "producer_schema_version": "v1",
                                },
                                "subjects": [{"kind": "surface", "value": "Alice"}],
                            },
                            "index_text": "Alice travel plans Madrid train family trip",
                            "evidence": [
                                {
                                    "id": "alice-travel-evidence",
                                    "source_id": "alice-travel-evidence",
                                    "source_type": "assistant_artifact",
                                    "content": "Alice will take a train to Madrid for a family trip.",
                                    "container_ref": "chat:travel-notes",
                                    "visibility": "container",
                                    "role": "assistant",
                                    "artifact_kind": "assistant_output",
                                }
                            ],
                        }
                    ],
                },
                {
                    "step_id": "query",
                    "action": "query",
                    "query": {
                        "text": "What do we know about Alice's travel plans?",
                        "container_ref": "chat:travel-notes",
                        "visibility": "container",
                    },
                    "quality_expectations": {
                        "should_inject": True,
                        "decision_reason": "carry_forward_available",
                        "required_block_labels": ["Fact Summary"],
                        "required_block_content": ["Madrid", "train"],
                        "max_injectable_blocks": 1,
                    },
                },
            ],
        }

        step_results = runner._run_multi_step(scenario, client)
        storage = client.app.state.pallium_service._storage

        assert len(storage.memory_objects) == 1
        assert storage.memory_objects[0].type == "fact_summary"
        assert storage.memory_objects[0].envelope is not None
        assert storage.memory_objects[0].envelope.subjects[0].value == "Alice"
        assert len(storage.index_entries) == 1
        assert storage.index_entries[0].index_type == "lexical"
        assert "Madrid" in storage.index_entries[0].text_view
        assert len(storage.source_items) == 1
        assert storage.source_items[0].container_ref == "chat:travel-notes"
        assert len(storage.relations) == 1
        assert storage.relations[0].relation_type == "supported_by"
        assert len(step_results) == 1
        assert step_results[0]["quality_expectation_results"]["passed"] is True
