from __future__ import annotations

import json
from collections import defaultdict
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest


@pytest.fixture()
def pallium_asgi_app(test_db_url: str):
    from app.config import AppConfig
    from app.main import create_app
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES

    app = create_app(AppConfig(
        storage_backend="sqlite",
        sqlite_url=test_db_url,
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    ))
    app.state._lifespan_complete = True
    return app

def _mcp(payload: dict):
    return [SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))], {}


class _ReplayMcp:
    """Small stateful MCP double; response shape matches call_tool."""

    def __init__(self, searches: dict[str, list[list[dict]]], sources: dict[str, list[str]]) -> None:
        self.searches = searches
        self.sources = sources
        self.calls: list[tuple[str, dict]] = []
        self.failures: dict[tuple[str, str, int], int] = defaultdict(int)
        self.stale_searches: dict[str, int] = defaultdict(int)
        self.stale_sources: dict[str, int] = defaultdict(int)
        self.revisions = {source: "r1" for source in sources}

    async def __call__(self, name: str, arguments: dict):
        self.calls.append((name, deepcopy(arguments)))
        if name == "pallium_search_history":
            query = arguments["query"]
            if self.stale_searches[query]:
                self.stale_searches[query] -= 1
                return _mcp({"error_kind": "stale_result_revision"})
            pages = self.searches[query]
            offset = arguments.get("result_offset", 0)
            results = pages[min(offset, len(pages) - 1)]
            next_offset = offset + 1 if offset + 1 < len(pages) else None
            return _mcp({
                "results": results,
                "lookup_event_id": f"lookup:{query}:{offset}",
                "result_revision": f"search:{query}:r1",
                "result_offset": offset,
                "total_count": sum(map(len, pages)),
                "has_more": next_offset is not None,
                "next_offset": next_offset,
            })

        source = arguments["source_item_id"]
        offset = arguments.get("content_offset", 0)
        failure_key = ("expand", source, offset)
        if self.failures[failure_key]:
            self.failures[failure_key] -= 1
            raise ConnectionError("injected delivery failure")
        if self.stale_sources[source]:
            self.stale_sources[source] -= 1
            return _mcp({"error_kind": "stale_content_revision"})
        chunks = self.sources[source]
        starts: list[int] = []
        cursor = 0
        for chunk in chunks:
            starts.append(cursor)
            cursor += len(chunk)
        index = starts.index(offset) if offset in starts else len(chunks)
        content = chunks[index] if index < len(chunks) else ""
        next_offset = starts[index + 1] if index + 1 < len(chunks) else None
        return _mcp({
            "items": [{"is_anchor": True, "content": content}],
            "parent_lookup_id": arguments["parent_lookup_id"],
            "content_revision": self.revisions[source],
            "content_offset": offset,
            "content_total_chars": cursor,
            "has_more": next_offset is not None,
            "next_offset": next_offset,
        })


def _args() -> dict:
    return {"container_ref": "c", "thread_ref": "reader", "visibility": "private", "limit": 2}


@pytest.mark.asyncio
async def test_ledger_continues_partial_source_across_repair_without_gap_or_duplicate() -> None:
    from evals.history_pull_decision.replay import run_navigation_replay

    tool = _ReplayMcp(
        {"q1": [[{"source_item_id": "s"}]], "q2": [[{"source_item_id": "s"}]]},
        {"s": ["A界", '😀"\\', "B", "C"]},
    )
    tool.failures[("expand", "s", 2)] = 3
    expected = 'A界😀"\\BC'
    report = await run_navigation_replay(
        tool, queries=["q1", "q2"], search_arguments=_args(),
        required_evidence=[expected], policy="ledger", max_chars=256,
    )

    expansion = [args for name, args in tool.calls if name == "pallium_expand_source"]
    failed = [args for args in expansion if args.get("content_offset") == 2][:3]
    assert len(failed) == 3 and failed[0] == failed[1] == failed[2]
    assert [a.get("content_offset", 0) for a in expansion][-3:] == [2, 5, 6]
    assert report["required_evidence_recovered"] is True
    assert report["returned_characters"] == len(expected)
    assert report["candidate_occurrences"] == 2
    assert report["unique_candidates"] == 1
    assert report["exact_repeat_candidates"] == 1
    assert report["repeated_delivered_expansion_pages"] == 0


@pytest.mark.asyncio
async def test_page_specific_lookup_lineage_and_more_than_two_result_pages() -> None:
    from evals.history_pull_decision.replay import run_navigation_replay

    tool = _ReplayMcp(
        {"q": [[{"source_item_id": "a"}], [{"source_item_id": "b"}], [{"source_item_id": "c"}]]},
        {"a": ["A"], "b": ["B"], "c": ["C"]},
    )
    report = await run_navigation_replay(
        tool, queries=["q"], search_arguments=_args(), required_evidence=["A", "B", "C"],
        policy="ledger", max_chars=256,
    )

    parents = {
        args["source_item_id"]: args["parent_lookup_id"]
        for name, args in tool.calls if name == "pallium_expand_source"
    }
    assert parents == {"a": "lookup:q:0", "b": "lookup:q:1", "c": "lookup:q:2"}
    assert report["search_result_pages"] == 3
    assert report["required_evidence_recovered"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("first", "second", "second_revision", "expected_offsets", "required"),
    [
        (["same"], ["same"], "r1", [0, 4], "same"),
        (["old!"], ["new!"], "r2", [0, 4, 0], "new!"),
        ([""], [""], "r1", [0, 0], ""),
        ([""], ["new"], "r2", [0, 0], "new"),
    ],
    ids=["unchanged", "equal-length-change", "empty-empty", "empty-nonempty"],
)
async def test_completed_source_terminal_revalidation(
    first: list[str], second: list[str], second_revision: str,
    expected_offsets: list[int], required: str,
) -> None:
    from evals.history_pull_decision.replay import run_navigation_replay

    tool = _ReplayMcp(
        {"q1": [[{"source_item_id": "s"}]], "q2": [[{"source_item_id": "s"}]]},
        {"s": first},
    )
    search_count = 0

    async def mutate_between_queries(name: str, arguments: dict):
        nonlocal search_count
        if name == "pallium_search_history":
            search_count += 1
            if search_count == 2:
                tool.sources["s"] = second
                tool.revisions["s"] = second_revision
        return await tool(name, arguments)

    report = await run_navigation_replay(
        mutate_between_queries, queries=["q1", "q2"], search_arguments=_args(),
        required_evidence=[required] if required else [], policy="ledger", max_chars=256,
    )
    offsets = [
        args.get("content_offset", 0)
        for name, args in tool.calls if name == "pallium_expand_source"
    ]
    assert offsets == expected_offsets
    assert report["required_evidence_recovered"] is True
    assert report["repeated_delivered_expansion_pages"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["transport", "stale-search", "stale-content"])
async def test_retry_and_stale_budgets_stop_after_initial_plus_two(failure: str) -> None:
    from evals.history_pull_decision.replay import run_navigation_replay

    tool = _ReplayMcp({"q": [[{"source_item_id": "s"}]]}, {"s": ["evidence"]})
    if failure == "transport":
        tool.failures[("expand", "s", 0)] = 99
    elif failure == "stale-search":
        tool.stale_searches["q"] = 99
    else:
        tool.stale_sources["s"] = 99
    report = await run_navigation_replay(
        tool, queries=["q"], search_arguments=_args(), required_evidence=["evidence"],
        policy="ledger", max_chars=256,
    )
    relevant = [
        args for name, args in tool.calls
        if (failure == "stale-search" and name == "pallium_search_history")
        or (failure != "stale-search" and name == "pallium_expand_source")
    ]
    assert len(relevant) == 3
    assert relevant[0] == relevant[1] == relevant[2]
    assert report["required_evidence_recovered"] is False


@pytest.mark.asyncio
async def test_query_repairs_are_bounded_to_two_after_initial_query() -> None:
    from evals.history_pull_decision.replay import run_navigation_replay

    tool = _ReplayMcp({q: [[]] for q in ("q0", "q1", "q2", "q3")}, {})
    report = await run_navigation_replay(
        tool, queries=["q0", "q1", "q2", "q3"], search_arguments=_args(),
        required_evidence=["never found"], policy="ledger", max_chars=256,
    )
    assert report["searches"] == 3
    assert [args["query"] for name, args in tool.calls if name == "pallium_search_history"] == [
        "q0", "q1", "q2"
    ]
    assert report["required_evidence_recovered"] is False


@pytest.mark.slow
@pytest.mark.asyncio
async def test_navigation_replay_compares_restart_and_ledger_over_real_mcp(
    pallium_asgi_app, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mcp.server import create_server
    from evals.history_pull_decision.replay import compare_navigation_policies

    container = "git:example/navigation-replay"
    query = "anonymized evidence marker"
    tail_evidence = 'required Ω界😀 "quoted" \\ tail evidence'
    body = "".join(
        f"segment-{index:03d}: distinct continuation text 界😀 \\\"\n"
        for index in range(120)
    )
    raw = f"{query}\n{body}{tail_evidence}"
    seed_transport = httpx.ASGITransport(app=pallium_asgi_app)
    real_async_client = httpx.AsyncClient
    async with real_async_client(
        transport=seed_transport, base_url="http://testserver",
    ) as http:
        response = await http.post("/items", json=[{
            "source_type": "chat_message", "source_id": "navigation-replay-source",
            "content_type": "text/plain", "content": raw, "artifact_kind": "message",
            "role": "user", "actor_ref": "Replay Operator", "container_ref": container,
            "thread_ref": "history:source", "visibility": "private",
        }])
        assert response.status_code == 200, response.text
    pallium_asgi_app.state.pallium_service.drain_processing_queue(worker_id="navigation-replay")

    class FailingAsgiTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.inner = httpx.ASGITransport(app=pallium_asgi_app)
            self.failures_remaining = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/source/") and self.failures_remaining:
                self.failures_remaining -= 1
                raise httpx.ConnectError("injected MCP transport failure", request=request)
            return await self.inner.handle_async_request(request)

    transport = FailingAsgiTransport()

    def asgi_client(*args, **kwargs):
        kwargs.update(transport=transport, base_url="http://testserver")
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("app.mcp.client.httpx.AsyncClient", asgi_client)
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://testserver")
    server = create_server()
    searches_started = 0
    failed_arms: set[int] = set()

    async def call_tool(name: str, arguments: dict):
        nonlocal searches_started
        if name == "pallium_search_history" and arguments.get("result_offset", 0) == 0:
            searches_started += 1
        arm = (searches_started - 1) // 2
        if (
            name == "pallium_expand_source"
            and arguments.get("content_offset", 0) > 0
            and arm not in failed_arms
        ):
            failed_arms.add(arm)
            # Exhaust initial + two identical retries inside the real MCP client
            # envelope. Query repair must then resume the ledger's unread page.
            transport.failures_remaining = 3
        return await server.call_tool(name, arguments)

    reports = await compare_navigation_policies(
        call_tool, queries=[query, query],
        search_arguments={
            "container_ref": container, "thread_ref": "history:reader",
            "actor_ref": "Replay Operator", "visibility": "private", "limit": 5,
        },
        required_evidence=[raw], max_chars=600,
    )
    baseline, ledger = reports["restart"], reports["ledger"]
    assert baseline["required_evidence_recovered"] is ledger["required_evidence_recovered"] is True
    assert baseline["recovered_required_evidence"] == ledger["recovered_required_evidence"] == [raw]
    assert baseline["measurement_layer"] == ledger["measurement_layer"] == "navigation/presentation"
    assert ledger["returned_characters"] == len(raw)
    assert ledger["repeated_delivered_expansion_pages"] == 0
    assert baseline["repeated_delivered_expansion_pages"] > 0
    assert ledger["returned_characters"] < baseline["returned_characters"]
    assert ledger["expansion_attempts"] < baseline["expansion_attempts"]
    assert ledger["exact_repeat_candidates"] == baseline["exact_repeat_candidates"] >= 1