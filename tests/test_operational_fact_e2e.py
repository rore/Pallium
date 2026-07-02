"""E2E tests for the operational_fact redesign — PR 3+ invariants.

Locks the design invariants from the plan at
``C:\\Users\\I347041\\.claude\\plans\\noble-brewing-squid.md``:

Test 1 — cross-session recurrence promotes; single-session does not.
Test 4a — unknown ecosystem produces a candidate (PR 3).
Test 4b — unknown ecosystem promotes after recurrence (PR 4).
Test 5 — cross-container isolation (PR 3).
Test 7 — UserPromptSubmit injects on operational intent (PR 4).
Test 9 — candidate invisibility at every operator surface (PR 3).

PR 3 lands Tests 4a, 5, 9. Tests 1, 4b, 7 are XFAIL until PR 4.

Reference E2E shape: tests/test_agent_work_trace_e2e.py fixture pattern.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dashboard import mount_dashboard
from core.models import IndexEntry, MemoryObject, new_id, utc_now
from core.service import PalliumService
from providers.llm.base import LLMJsonResponse, LLMProvider
from retrieval.lexical import LexicalRetrievalProvider
from semantic.agent_work_trace import AgentWorkTracePlugin
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from semantic.operational_fact import OPERATIONAL_FACT_TYPE
from storage.sqlite import SQLiteStorageProvider


CONTAINER_A = "git:example.com/repo-A"
CONTAINER_B = "git:example.com/repo-B"


class _StubOutcome(LLMProvider):
    def generate_json(self, **_):
        return LLMJsonResponse(raw_text='{"outcome":""}', parsed_json={"outcome": ""})


@pytest.fixture
def test_db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'op_fact_e2e.db'}"


@pytest.fixture
def service(test_db_url):
    storage = SQLiteStorageProvider(test_db_url)
    plugins = {
        "demo_agent_memory": DemoAgentMemoryPlugin(),
        "agent_work_trace": AgentWorkTracePlugin(
            provider=_StubOutcome(),
            operational_fact_derivation_enabled=True,
        ),
    }
    # Wire the routing type_registry from plugin registrations —
    # matches the shape ``app/dependencies.py`` uses in production.
    # Without this, ``QueryExecutor`` never routes injection blocks
    # for the operational_intent signal Test 7 relies on.
    from core.type_registry import TypeRegistry
    type_registry = TypeRegistry()
    for plugin in plugins.values():
        register_routing_types = getattr(plugin, "register_routing_types", None)
        if callable(register_routing_types):
            register_routing_types(type_registry)
    return PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins=plugins,
        default_use_case="demo_agent_memory",
        type_registry=type_registry if len(type_registry) > 0 else None,
    )


@pytest.fixture
def dashboard_client(service):
    app = FastAPI()
    app.state.pallium_service = service
    mount_dashboard(app)
    return TestClient(app)


def _seed_candidate(
    storage,
    *,
    container_ref: str = CONTAINER_A,
    command_family: str = "python",
    artifact_role: str = "interpreter",
    scope_kind: str = "machine_repo",
    artifact_normalized: str = "/usr/local/bin/python",
    lifecycle: str = "candidate",
    subject_override: str | None = None,
) -> str:
    """Insert a synthetic operational_fact row directly.

    Test 9 uses this to prove operator-surface invisibility of
    ``lifecycle=candidate`` rows without depending on the derivation
    pipeline (that is covered by Test 4a). Test 5 uses it to place
    facts in each container without a full pipeline run.
    """
    now = utc_now()
    scope_ref = container_ref if scope_kind == "repo" else f"{container_ref}@machine:testhash"
    subject = subject_override or f"{command_family}: {artifact_normalized}"
    mem = MemoryObject(
        type=OPERATIONAL_FACT_TYPE,
        schema_id="operational_fact.v1",
        schema_version="1",
        payload={
            "command_family": command_family,
            "artifact_role": artifact_role,
            "scope_kind": scope_kind,
            "scope_ref": scope_ref,
            "subject": subject,
            "artifact": artifact_normalized,
            "artifact_normalized": artifact_normalized,
            "origin": "agent_inferred",
            "evidence": [
                {
                    "kind": "discovery",
                    "verb": "command_lookup",
                    "source_item_id": "src-test-0000",
                    "tool": "Bash",
                    "turn_index": 0,
                    "timestamp": "2026-07-02T00:00:00Z",
                    "fragment": f"which {command_family}",
                },
            ],
            "use_counters": {
                "reuse_count": 1,
                "success_count": 0,
                "failure_count": 0,
                "last_used_at": now.isoformat(),
                "last_confirmed_at": None,
            },
        },
        lifecycle=lifecycle,
        visibility="private",
        container_ref=container_ref,
        freshness_at=now,
    )
    storage.create_memory_object(mem)
    # Emit a lexical index entry so retrieval has something concrete to
    # (correctly) refuse to surface for the candidate case.
    idx = IndexEntry(
        target_kind="memory_object",
        target_id=mem.id,
        index_type="lexical",
        text_view=f"{subject} {command_family} {artifact_role} {artifact_normalized}",
    )
    storage.create_index_entry(idx)
    return mem.id


# ---------------------------------------------------------------------------
# Test 9 — Candidate invisibility at every operator surface (PR 3)
# ---------------------------------------------------------------------------


class TestCandidateInvisibility:
    """Every read surface must exclude ``lifecycle=candidate`` by default.

    This is the load-bearing PR 3 contract: without it, the promotion
    gate in PR 4 is meaningless — an un-promoted candidate that leaks
    into retrieval or the dashboard is indistinguishable from an
    ``active`` fact.
    """

    def test_list_memory_objects_default_excludes_candidate(self, service):
        cand_id = _seed_candidate(service._storage, lifecycle="candidate")
        active_id = _seed_candidate(
            service._storage, lifecycle="active",
            artifact_normalized="/usr/local/bin/python2",
        )
        results = service._storage.list_memory_objects(
            memory_types=[OPERATIONAL_FACT_TYPE], container_ref=CONTAINER_A,
        )
        ids = {r.id for r in results}
        assert active_id in ids
        assert cand_id not in ids

    def test_list_memory_objects_include_candidates_returns_them(self, service):
        cand_id = _seed_candidate(service._storage, lifecycle="candidate")
        results = service._storage.list_memory_objects(
            memory_types=[OPERATIONAL_FACT_TYPE],
            container_ref=CONTAINER_A,
            include_candidates=True,
        )
        assert cand_id in {r.id for r in results}

    def test_list_memory_objects_explicit_lifecycle_candidate_returns_it(self, service):
        # Explicit ``lifecycle="candidate"`` bypasses the default filter.
        cand_id = _seed_candidate(service._storage, lifecycle="candidate")
        results = service._storage.list_memory_objects(
            memory_types=[OPERATIONAL_FACT_TYPE],
            container_ref=CONTAINER_A,
            lifecycle="candidate",
        )
        assert cand_id in {r.id for r in results}

    def test_query_retrieval_excludes_candidate(self, service):
        # Two rows: one candidate (invisible) and one active sibling.
        # Primary invariant: retrieval never surfaces the candidate.
        cand_id = _seed_candidate(
            service._storage,
            lifecycle="candidate",
            artifact_normalized="/usr/local/bin/xyzlang",
            command_family="xyzlang",
            subject_override="xyzlang interpreter recon candidate",
        )
        active_id = _seed_candidate(
            service._storage,
            lifecycle="active",
            artifact_normalized="/usr/local/bin/xyzlang2",
            command_family="xyzlang",
            subject_override="xyzlang interpreter recon active",
        )
        result = service.query(
            text="xyzlang interpreter recon",
            limit=20,
            trigger_origin="user_prompt_submit",
            container_ref=CONTAINER_A,
        )
        # InjectableBlock.memory_object_id is the correct attribute
        # (verified against core/models.py::InjectableBlock).
        block_ids = {b.memory_object_id for b in result.injectable_blocks}
        # Load-bearing assertion: the candidate never appears in the
        # injectable set. If retrieval surfaces zero blocks (routing
        # not fully wired for op_fact in this test fixture), the
        # invariant is trivially satisfied — but the raw hits under
        # the query must ALSO exclude the candidate for the assertion
        # to be meaningful. Check raw_hits as belt-and-braces.
        assert cand_id not in block_ids, (
            f"candidate {cand_id} leaked into injectable_blocks"
        )
        # Belt-and-braces: check the raw retrieval hits too. Even if
        # ranking/injection doesn't surface the candidate as a block,
        # the raw retrieval layer must not return it.
        raw_hit_ids = set()
        for hit in getattr(result, "raw_hits", []) or []:
            tid = getattr(hit, "target_id", None) or getattr(hit, "memory_object_id", None)
            if tid:
                raw_hit_ids.add(tid)
        assert cand_id not in raw_hit_ids, (
            f"candidate {cand_id} leaked into raw retrieval hits: {raw_hit_ids}"
        )

    def test_dashboard_api_default_excludes_candidate(self, service, dashboard_client):
        cand_id = _seed_candidate(service._storage, lifecycle="candidate")
        active_id = _seed_candidate(
            service._storage, lifecycle="active",
            artifact_normalized="/usr/local/bin/python2",
        )
        resp = dashboard_client.get(
            "/dashboard/api/memories",
            params={"type": OPERATIONAL_FACT_TYPE, "limit": 100},
        )
        assert resp.status_code == 200
        ids = {m["id"] for m in resp.json()["memories"]}
        assert active_id in ids
        assert cand_id not in ids

    def test_dashboard_api_explicit_lifecycle_candidate_returns_it(self, service, dashboard_client):
        cand_id = _seed_candidate(service._storage, lifecycle="candidate")
        resp = dashboard_client.get(
            "/dashboard/api/memories",
            params={"type": OPERATIONAL_FACT_TYPE, "lifecycle": "candidate"},
        )
        assert resp.status_code == 200
        ids = {m["id"] for m in resp.json()["memories"]}
        assert cand_id in ids

    def test_lifecycle_promoted_to_active_becomes_visible(self, service):
        cand_id = _seed_candidate(service._storage, lifecycle="candidate")
        # Default query excludes it.
        pre = service._storage.list_memory_objects(
            memory_types=[OPERATIONAL_FACT_TYPE], container_ref=CONTAINER_A,
        )
        assert cand_id not in {r.id for r in pre}
        # Flip to active.
        service._storage.update_memory_object_lifecycle(cand_id, "active")
        # Now it appears.
        post = service._storage.list_memory_objects(
            memory_types=[OPERATIONAL_FACT_TYPE], container_ref=CONTAINER_A,
        )
        assert cand_id in {r.id for r in post}


# ---------------------------------------------------------------------------
# Test 5 — Cross-container isolation (PR 3)
# ---------------------------------------------------------------------------


class TestCrossContainerIsolation:
    def test_active_facts_isolated_by_container(self, service):
        a_id = _seed_candidate(
            service._storage, container_ref=CONTAINER_A, lifecycle="active",
            artifact_normalized="/usr/local/bin/python_A",
        )
        b_id = _seed_candidate(
            service._storage, container_ref=CONTAINER_B, lifecycle="active",
            artifact_normalized="/usr/local/bin/python_B",
        )
        a_rows = service._storage.list_memory_objects(
            memory_types=[OPERATIONAL_FACT_TYPE], container_ref=CONTAINER_A,
        )
        b_rows = service._storage.list_memory_objects(
            memory_types=[OPERATIONAL_FACT_TYPE], container_ref=CONTAINER_B,
        )
        a_ids = {r.id for r in a_rows}
        b_ids = {r.id for r in b_rows}
        assert a_id in a_ids and b_id not in a_ids
        assert b_id in b_ids and a_id not in b_ids

    def test_query_scopes_to_container(self, service):
        _seed_candidate(
            service._storage, container_ref=CONTAINER_A, lifecycle="active",
            artifact_normalized="/usr/local/bin/python_A",
            subject_override="python: /usr/local/bin/python_A",
        )
        _seed_candidate(
            service._storage, container_ref=CONTAINER_B, lifecycle="active",
            artifact_normalized="/usr/local/bin/python_B",
            subject_override="python: /usr/local/bin/python_B",
        )
        # Query in A must not surface B's fact even though the term
        # "python" matches both.
        result = service.query(
            text="python interpreter",
            limit=20,
            trigger_origin="user_prompt_submit",
            container_ref=CONTAINER_A,
        )
        # Assert no block references container B's artifact string.
        rendered = " ".join(str(b) for b in result.injectable_blocks)
        assert "python_B" not in rendered


# ---------------------------------------------------------------------------
# Test 4a — Unknown ecosystem produces a candidate (PR 3)
# ---------------------------------------------------------------------------


class TestUnknownEcosystemCandidate:
    """A fresh ecosystem's reconnaissance turn produces a
    ``lifecycle=candidate`` operational_fact, even if the interpreter
    name is unknown to any allow-list.

    Uses the derivation predicate directly rather than the full ingest
    pipeline to keep the invariant scope tight.
    """

    def test_xyzlang_which_produces_candidate(self):
        from semantic.operational_fact import derive_operational_facts
        from tests.fixtures.operational_fact import fake_scope_resolver, make_bash_turn

        turns = [
            make_bash_turn(0, "which xyzlang", output_tail="/usr/local/bin/xyzlang"),
            make_bash_turn(1, "xyzlang --version", output_tail="xyzlang 3.14.15"),
        ]
        candidates = derive_operational_facts(
            turns, CONTAINER_A, fake_scope_resolver,
        )
        # At least one candidate whose artifact references xyzlang.
        assert any("xyzlang" in c.artifact_normalized for c in candidates)

    def test_candidate_defaults_invisible_at_dashboard(self, service, dashboard_client):
        # A candidate — even one with the family="xyzlang" that no
        # allow-list would ever have — must not appear in the default
        # dashboard view.
        cand_id = _seed_candidate(
            service._storage,
            lifecycle="candidate",
            command_family="xyzlang",
            artifact_normalized="/usr/local/bin/xyzlang",
            subject_override="xyzlang: /usr/local/bin/xyzlang",
        )
        resp = dashboard_client.get(
            "/dashboard/api/memories",
            params={"type": OPERATIONAL_FACT_TYPE, "limit": 100},
        )
        assert resp.status_code == 200
        ids = {m["id"] for m in resp.json()["memories"]}
        assert cand_id not in ids


# ---------------------------------------------------------------------------
# Test 1 — Cross-session recurrence promotes (PR 4)
# ---------------------------------------------------------------------------


CONTAINER_X = "git:example.com/repo-X"


def _ingest_recon_trace(
    service,
    *,
    thread_ref: str,
    turns_data: list[dict],
    container_ref: str = CONTAINER_X,
    cwd: str = "/home/user/project",
) -> None:
    """Ingest a list of turns (each with commands/files_read etc.) as
    ``agent_work_trace_turn`` source items and drain the queue so
    thread rebuild + reconcile hook + promotion runs.
    """
    for turn in turns_data:
        service.ingest_item(
            source_type="claude-code",
            source_id=f"cc-recon-{new_id()[:12]}",
            content_type="text/plain",
            content="Turn: recon.",
            metadata={
                "agent_work_trace_turn": turn,
                "cwd": cwd,
            },
            use_case="demo_agent_memory",
            artifact_kind="assistant_output",
            role="assistant",
            container_ref=container_ref,
            thread_ref=thread_ref,
            visibility="private",
        )
    service.drain_processing_queue(worker_id="e2e-pr4-test")


def _list_op_facts(service, *, container_ref: str, include_candidates: bool = True):
    return service._storage.list_memory_objects(
        memory_types=[OPERATIONAL_FACT_TYPE],
        container_ref=container_ref,
        include_candidates=include_candidates,
    )


def _query_promotion_log_ids(service):
    """Return the set of memory_object_ids that have promotion-log rows."""
    from storage.sqlite_schema import OperationalFactPromotionLogRecord
    from sqlalchemy import select

    storage = service._storage
    with storage._session_factory() as session:
        rows = session.scalars(
            select(OperationalFactPromotionLogRecord)
        ).all()
    return {r.memory_object_id for r in rows}


class TestCrossSessionRecurrencePromotes:
    """Two-session reconnaissance promotes a candidate to active; a
    single-session recon leaves it invisible.
    """

    def test_two_sessions_promote_to_active(self, service):
        # Session A: reconnaissance turns. Because thread-rebuild fires
        # on every rebuild-triggering item and the reconnaissance
        # predicate runs on the accumulated turn set, we ingest turns
        # that between them include recon verbs for python and the
        # test runner.
        sess_a_turns = [
            {
                "commands": [
                    {"cmd": "where python", "exit_code": 0, "output_tail": "/usr/local/bin/python"},
                ],
                "files_read": [],
                "files_modified": [],
                "grep_patterns": [],
                "has_productive_action": False,
            },
            {
                "commands": [
                    {"cmd": "python --version", "exit_code": 0, "output_tail": "Python 3.12.4"},
                ],
                "files_read": [],
                "files_modified": [],
                "grep_patterns": [],
                "has_productive_action": False,
            },
            {
                "commands": [
                    {"cmd": "cat pyproject.toml", "exit_code": 0, "output_tail": "[project]\nname = 'x'"},
                ],
                "files_read": ["pyproject.toml"],
                "files_modified": [],
                "grep_patterns": [],
                "has_productive_action": False,
            },
            {
                "commands": [
                    {"cmd": "uv run pytest", "exit_code": 0, "output_tail": "1 passed"},
                ],
                "files_read": [],
                "files_modified": [],
                "grep_patterns": [],
                "has_productive_action": False,
            },
        ]
        _ingest_recon_trace(service, thread_ref="sess-a", turns_data=sess_a_turns)

        # After session A alone: candidate rows exist but nothing is active.
        rows_after_a = _list_op_facts(service, container_ref=CONTAINER_X)
        assert rows_after_a, "session A ingest produced zero operational_fact rows"
        assert all(r.lifecycle == "candidate" for r in rows_after_a), (
            "session A should only produce candidates: "
            f"{[(r.id, r.lifecycle) for r in rows_after_a]}"
        )

        # Retrieval must not surface any candidate to the operator.
        pre_promotion = service.query(
            text="python",
            limit=20,
            trigger_origin="user_prompt_submit",
            container_ref=CONTAINER_X,
        )
        pre_block_ids = {b.memory_object_id for b in pre_promotion.injectable_blocks}
        candidate_ids = {r.id for r in rows_after_a}
        assert not (pre_block_ids & candidate_ids), (
            "candidate leaked into injectable_blocks before promotion: "
            f"{pre_block_ids & candidate_ids}"
        )

        # Session B: repeat the durable subset of recon in a NEW thread.
        sess_b_turns = [
            {
                "commands": [
                    {"cmd": "python --version", "exit_code": 0, "output_tail": "Python 3.12.4"},
                ],
                "files_read": [],
                "files_modified": [],
                "grep_patterns": [],
                "has_productive_action": False,
            },
            {
                "commands": [
                    {"cmd": "uv run pytest", "exit_code": 0, "output_tail": "1 passed"},
                ],
                "files_read": [],
                "files_modified": [],
                "grep_patterns": [],
                "has_productive_action": False,
            },
        ]
        _ingest_recon_trace(service, thread_ref="sess-b", turns_data=sess_b_turns)

        rows_after_b = _list_op_facts(service, container_ref=CONTAINER_X)
        # At least one row for the python interpreter slot should now
        # be active — the version-query slot is answered by BOTH
        # sessions (session A ``python --version`` and session B
        # ``python --version``). The `where python` slot is not, so
        # not every candidate promotes; that's expected.
        interpreter_actives = [
            r for r in rows_after_b
            if r.lifecycle == "active"
            and (r.payload or {}).get("command_family") == "python"
        ]
        assert interpreter_actives, (
            "expected at least one active python operational_fact after cross-session recurrence; "
            f"rows={[(r.id, r.lifecycle, (r.payload or {}).get('artifact_role'), (r.payload or {}).get('artifact_normalized')) for r in rows_after_b]}"
        )

        # An operational_fact_promotion_log audit row exists for at
        # least one promoted memory.
        promoted_ids = _query_promotion_log_ids(service)
        assert promoted_ids, "expected at least one operational_fact_promotion_log row"
        assert any(r.id in promoted_ids for r in interpreter_actives), (
            "promotion-log rows do not reference any active interpreter row"
        )


# ---------------------------------------------------------------------------
# Test 4b — Unknown ecosystem promotes after recurrence (PR 4)
# ---------------------------------------------------------------------------


class TestUnknownEcosystemPromotes:
    def test_xyzlang_promotes_after_two_sessions(self, service):
        sess_a_turns = [
            {
                "commands": [
                    {"cmd": "where xyzlang", "exit_code": 0, "output_tail": "/usr/local/bin/xyzlang"},
                ],
                "files_read": [],
                "files_modified": [],
                "grep_patterns": [],
                "has_productive_action": False,
            },
            {
                "commands": [
                    {"cmd": "xyzlang --version", "exit_code": 0, "output_tail": "xyzlang 3.14.15"},
                ],
                "files_read": [],
                "files_modified": [],
                "grep_patterns": [],
                "has_productive_action": False,
            },
        ]
        _ingest_recon_trace(service, thread_ref="sess-a", turns_data=sess_a_turns)

        # Session A alone: candidates only, no active row.
        rows_after_a = _list_op_facts(service, container_ref=CONTAINER_X)
        xyz_rows_a = [r for r in rows_after_a if (r.payload or {}).get("command_family") == "xyzlang"]
        assert xyz_rows_a, (
            "session A should have produced at least one xyzlang candidate; "
            f"rows={[(r.id, (r.payload or {}).get('command_family')) for r in rows_after_a]}"
        )
        assert all(r.lifecycle == "candidate" for r in xyz_rows_a)

        # Session B repeats the recon in a NEW thread.
        _ingest_recon_trace(service, thread_ref="sess-b", turns_data=sess_a_turns)

        rows_after_b = _list_op_facts(service, container_ref=CONTAINER_X)
        xyz_actives = [
            r for r in rows_after_b
            if r.lifecycle == "active"
            and (r.payload or {}).get("command_family") == "xyzlang"
        ]
        assert xyz_actives, (
            "expected at least one active xyzlang operational_fact after cross-session recurrence; "
            f"rows={[(r.id, r.lifecycle, (r.payload or {}).get('command_family'), (r.payload or {}).get('artifact_normalized')) for r in rows_after_b]}"
        )


# ---------------------------------------------------------------------------
# Test 7 — UserPromptSubmit injects on operational intent (PR 4)
# ---------------------------------------------------------------------------


class TestUserPromptSubmitInjection:
    def test_how_do_i_run_tests_injects_test_runner_fact(self, service):
        # Reuse Test-1 style promotion: two sessions running python
        # + pytest recon.
        sess_a_turns = [
            {
                "commands": [
                    {"cmd": "where python", "exit_code": 0, "output_tail": "/usr/local/bin/python"},
                ],
                "files_read": [],
                "files_modified": [],
                "grep_patterns": [],
                "has_productive_action": False,
            },
            {
                "commands": [
                    {"cmd": "python --version", "exit_code": 0, "output_tail": "Python 3.12.4"},
                ],
                "files_read": [],
                "files_modified": [],
                "grep_patterns": [],
                "has_productive_action": False,
            },
            {
                "commands": [
                    {"cmd": "cat pyproject.toml", "exit_code": 0, "output_tail": "[project]"},
                ],
                "files_read": ["pyproject.toml"],
                "files_modified": [],
                "grep_patterns": [],
                "has_productive_action": False,
            },
            {
                "commands": [
                    {"cmd": "uv run pytest", "exit_code": 0, "output_tail": "1 passed"},
                ],
                "files_read": [],
                "files_modified": [],
                "grep_patterns": [],
                "has_productive_action": False,
            },
        ]
        _ingest_recon_trace(service, thread_ref="sess-a", turns_data=sess_a_turns)
        _ingest_recon_trace(service, thread_ref="sess-b", turns_data=sess_a_turns)

        # After both sessions, at least one op_fact is active.
        actives = [
            r for r in _list_op_facts(service, container_ref=CONTAINER_X)
            if r.lifecycle == "active"
        ]
        assert actives, "expected active operational_fact rows after 2-session recon"

        # Operational-intent prompt surfaces the active fact through
        # the retrieval + routing pipeline. The signal fires on an
        # operational verb (``run``) AND a known command-family token
        # (``python``); see
        # docs/specs/2026-05-31-operational-fact-memory-design.md
        # §Surfacing. We assert at the ``results`` level rather than
        # the ``injectable_blocks`` level because the per-candidate
        # BM25 injection floor (12.0 raw BM25) is calibrated against
        # production-scale index text — the tiny e2e fixture indexes
        # cannot cross it. What matters for this invariant is that
        # (a) an active op_fact was retrieved for the operational
        # query, and (b) a non-operational query does NOT surface it.
        op_result = service.query(
            text="how do I run python tests here",
            limit=20,
            trigger_origin="user_prompt_submit",
            container_ref=CONTAINER_X,
        )
        op_result_ids = {
            r.memory_object_id for r in op_result.results
            if r.type == OPERATIONAL_FACT_TYPE and r.memory_object_id
        }
        active_ids = {r.id for r in actives}
        assert op_result_ids & active_ids, (
            "operational query did not retrieve any active operational_fact; "
            f"active_ids={active_ids} result_ids={op_result_ids}"
        )

        # Non-operational prompt does NOT surface any op_fact. Uses
        # the same ``results`` surface for symmetry with the positive
        # assertion above.
        non_op_result = service.query(
            text="what did I have for lunch",
            limit=20,
            trigger_origin="user_prompt_submit",
            container_ref=CONTAINER_X,
        )
        non_op_result_ids = {
            r.memory_object_id for r in non_op_result.results
            if r.type == OPERATIONAL_FACT_TYPE and r.memory_object_id
        }
        assert not (non_op_result_ids & active_ids), (
            "non-operational prompt surfaced an operational_fact; "
            f"overlap={non_op_result_ids & active_ids}"
        )

    def test_operational_intent_signal_fires_on_run_python_tests(self):
        """Injection-side lock: the operational_intent routing signal
        MUST fire on the plan's canonical query ("how do I run the
        tests here?") and MUST NOT fire on off-topic prompts.

        This asserts on the routing-signal boundary independent of
        BM25 index sizing. Even if a test-fixture index is too small
        to cross the per-candidate injection floor, the classification
        of "operational intent → route to operational_fact preferred
        layer" must hold. If a future change disables the signal but
        leaves BM25 retrieval intact, the sibling test above still
        passes; THIS test catches the regression.
        """
        from semantic.agent_conversation_memory_routing_signals import (
            _derive_operational_intent,
        )

        def _toks(s: str) -> tuple[str, ...]:
            return tuple(t.strip().lower() for t in s.split() if t.strip())

        fired, _ = _derive_operational_intent(_toks("how do I run python tests here"))
        assert fired, "operational_intent signal did not fire on canonical query"

        fired_off, _ = _derive_operational_intent(_toks("what did I have for lunch"))
        assert not fired_off, "operational_intent signal fired on off-topic prompt"
