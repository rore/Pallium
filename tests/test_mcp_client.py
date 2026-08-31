"""Tests for MCP HTTP client wrapping Pallium REST API."""

from __future__ import annotations

import json
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("mcp", reason="mcp[cli] not installed")

from app.mcp.client import PalliumMcpClient
from app.mcp.context import PalliumContext


@pytest.fixture()
def ctx() -> PalliumContext:
    return PalliumContext(
        base_url="http://localhost:8000",
        container_ref="test-container",
        thread_ref="test-thread",
        actor_ref="test-actor",
        agent_ref="test-agent",
        visibility="container",
    )


def _mock_response(status_code: int = 200, json_data: dict | list | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = json.dumps(json_data or {})
    resp.raise_for_status = MagicMock()
    return resp


class TestQuery:
    @pytest.mark.asyncio
    async def test_query_sends_scope_from_context(self, ctx: PalliumContext) -> None:
        mock_resp = _mock_response(json_data={"results": [], "should_inject": False, "decision_reason": "no_relevant_memory", "injectable_blocks": []})
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.query("test query", limit=3)

            mock_post.assert_called_once()
            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
            assert payload["text"] == "test query"
            assert payload["limit"] == 3
            assert payload["container_ref"] == "test-container"
            assert payload["thread_ref"] == "test-thread"
            assert payload["actor_ref"] == "test-actor"
            assert payload["visibility"] == "container"

    @pytest.mark.asyncio
    async def test_query_omits_none_scope_fields(self) -> None:
        ctx = PalliumContext(base_url="http://localhost:8000")
        mock_resp = _mock_response(json_data={"results": [], "should_inject": False, "decision_reason": "no_relevant_memory", "injectable_blocks": []})
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.query("test query")

            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
            assert "container_ref" not in payload
            assert "thread_ref" not in payload
            assert "actor_ref" not in payload
            assert "visibility" not in payload

    @pytest.mark.asyncio
    async def test_query_returns_raw_json(self, ctx: PalliumContext) -> None:
        expected = {"results": [{"score": 0.9}], "should_inject": True, "decision_reason": "carry_forward_available", "injectable_blocks": []}
        mock_resp = _mock_response(json_data=expected)
        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            client = PalliumMcpClient(ctx)
            result = await client.query("test")
            assert result == expected


class TestQueryDebug:
    @pytest.mark.asyncio
    async def test_query_debug_hits_debug_endpoint(self, ctx: PalliumContext) -> None:
        mock_resp = _mock_response(json_data={"results": [], "should_inject": False, "decision_reason": "no_relevant_memory", "injectable_blocks": [], "trace": {}})
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.query_debug("test")

            url = mock_post.call_args.args[0] if mock_post.call_args.args else mock_post.call_args.kwargs.get("url", "")
            assert "/query/debug" in str(url)

    @pytest.mark.asyncio
    async def test_query_debug_omits_limit(self, ctx: PalliumContext) -> None:
        """query_debug intentionally omits limit — uses API default (5)."""
        mock_resp = _mock_response(json_data={"results": [], "should_inject": False, "decision_reason": "no_relevant_memory", "trace": {}})
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.query_debug("test")

            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
            assert "limit" not in payload


class TestIngest:
    @pytest.mark.asyncio
    async def test_ingest_sends_single_item_array(self, ctx: PalliumContext) -> None:
        mock_resp = _mock_response(json_data=[{"source_item_id": "si-123", "processing_status": "pending", "memory_object_ids": [], "relation_ids": [], "index_entry_ids": [], "processing_attempts": 0, "processing_error": None}])
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.ingest(
                content="Remember this decision",
                source_type="agent_artifact",
                source_id="test-123",
                artifact_kind="assistant_output",
                role="assistant",
            )

            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
            assert isinstance(payload, list)
            assert len(payload) == 1
            item = payload[0]
            assert item["content"] == "Remember this decision"
            assert item["source_type"] == "agent_artifact"
            assert item["source_id"] == "test-123"
            assert item["content_type"] == "text/plain"
            assert item["artifact_kind"] == "assistant_output"
            assert item["role"] == "assistant"
            assert item["container_ref"] == "test-container"

    @pytest.mark.asyncio
    async def test_ingest_omits_none_optional_fields(self, ctx: PalliumContext) -> None:
        """artifact_kind and role should be omitted when None, not sent as null."""
        mock_resp = _mock_response(json_data=[{"source_item_id": "si-123", "processing_status": "pending", "memory_object_ids": [], "relation_ids": [], "index_entry_ids": [], "processing_attempts": 0}])
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.ingest(content="test", source_type="agent_artifact", source_id="x")

            item = mock_post.call_args.kwargs.get("json")[0]
            assert "artifact_kind" not in item
            assert "role" not in item

    @pytest.mark.asyncio
    async def test_ingest_generates_source_id_when_none(self, ctx: PalliumContext) -> None:
        """When source_id is None, client auto-generates an mcp-prefixed ID."""
        mock_resp = _mock_response(json_data=[{"source_item_id": "si-123", "processing_status": "pending", "memory_object_ids": [], "relation_ids": [], "index_entry_ids": [], "processing_attempts": 0}])
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.ingest(content="test", source_type="agent_artifact")

            item = mock_post.call_args.kwargs.get("json")[0]
            assert item["source_id"].startswith("mcp-")
            assert len(item["source_id"]) == 16  # "mcp-" + 12 hex chars

    @pytest.mark.asyncio
    async def test_ingest_returns_first_item_response(self, ctx: PalliumContext) -> None:
        resp_data = [{"source_item_id": "si-abc", "processing_status": "pending", "memory_object_ids": [], "relation_ids": [], "index_entry_ids": [], "processing_attempts": 0}]
        mock_resp = _mock_response(json_data=resp_data)
        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            client = PalliumMcpClient(ctx)
            result = await client.ingest(content="test", source_type="agent_artifact", source_id="x")
            assert result == resp_data[0]


class TestConnectionError:
    @pytest.mark.asyncio
    async def test_connection_error_returns_error_dict(self, ctx: PalliumContext) -> None:
        with patch("httpx.AsyncClient.post", side_effect=Exception("Connection refused")):
            client = PalliumMcpClient(ctx)
            result = await client.query("test")
            assert "error" in result
            assert "Connection refused" in result["error"]

class TestExplicitMemoryCreation:
    @staticmethod
    def _payload(mock_post):
        return mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "kwargs", "endpoint"),
        [
            ("remember_memory", {"text": "fact", "type": "decision"}, "/memory/remember"),
            ("supersede_memory", {"new_text": "replacement", "supersedes_id": "old-id"}, "/memory/supersede"),
            ("record_outcome", {"procedure_id": "procedure-id", "outcome": "success"}, "/memory/record-outcome"),
        ],
    )
    async def test_creation_forwards_complete_canonical_provenance(
        self, ctx: PalliumContext, method: str, kwargs: dict, endpoint: str
    ) -> None:
        mock_resp = _mock_response(json_data={"ok": True})
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            await getattr(PalliumMcpClient(ctx), method)(**kwargs)

        url = mock_post.call_args.args[0]
        payload = self._payload(mock_post)
        assert str(url).endswith(endpoint)
        assert {key: payload[key] for key in (
            "container_ref", "actor_ref", "thread_ref", "agent_ref", "visibility"
        )} == {
            "container_ref": "test-container",
            "actor_ref": "test-actor",
            "thread_ref": "test-thread",
            "agent_ref": "test-agent",
            "visibility": "container",
        }
class TestRelay:
    @pytest.mark.asyncio
    async def test_receive_fences_candidate_before_returning_it(self, ctx: PalliumContext) -> None:
        candidate = {
            "delivery_id": "d-1", "claim_token": "claim", "envelope_digest": "a" * 64,
            "protocol_version": "batch_v2_candidate", "payload": "handoff",
        }
        turn = _mock_response(json_data={"deliveries": [candidate], "remaining_count": 0, "has_more": False})
        publication = _mock_response(json_data={"delivery_id": "d-1"})
        with patch("httpx.AsyncClient.post", side_effect=[turn, publication]) as post:
            result = await PalliumMcpClient(ctx).relay_receive("codex", "target")
        assert result["deliveries"][0]["envelope_digest"] == candidate["envelope_digest"]
        assert "claim_token" not in result["deliveries"][0]
        assert "payload" not in result["deliveries"][0]
        assert "payload" not in result["deliveries"][0]
        assert post.call_count == 2
        assert post.call_args_list[1].args[0].endswith("/relay/deliveries/publication")
        assert post.call_args_list[1].kwargs["json"]["claim_token"] == "claim"
    @pytest.mark.asyncio
    async def test_receive_stops_at_the_first_candidate_publication_refusal(self, ctx: PalliumContext) -> None:
        candidates = [
            {"delivery_id": f"d-{index}", "claim_token": f"claim-{index}", "envelope_digest": "a" * 64,
             "protocol_version": "batch_v2_candidate", "envelope": "envelope", "receipt": f"receipt-{index}"}
            for index in range(2)
        ]
        turn = _mock_response(json_data={"deliveries": candidates, "remaining_count": 0, "has_more": False})
        refusal = _mock_response(status_code=409, json_data={"detail": "refused"})
        refusal.raise_for_status.side_effect = httpx.HTTPStatusError("refused", request=MagicMock(), response=refusal)
        with patch("httpx.AsyncClient.post", side_effect=[turn, refusal]) as post:
            result = await PalliumMcpClient(ctx).relay_receive("codex", "target")
        assert result["deliveries"] == []
        assert result["remaining_count"] == 2
        assert result["has_more"] is True
        assert post.call_count == 2

    @pytest.mark.asyncio
    async def test_receive_reserves_final_json_budget_before_publication(self, ctx: PalliumContext) -> None:
        candidate = {
            "delivery_id": "d-1", "message_id": "m-1", "claim_token": "claim", "receipt": "receipt",
            "envelope_digest": "a" * 64, "claim_generation": 1,
            "protocol_version": "batch_v2_candidate", "payload": "hello", "envelope": "hello" * 80,
        }
        turn = _mock_response(json_data={"session": {"runtime": "codex", "session_ref": "target"}, "deliveries": [candidate], "remaining_count": 0, "has_more": False})
        publication = _mock_response(json_data={"delivery_id": "d-1"})
        with patch("httpx.AsyncClient.post", side_effect=[turn, publication]) as post:
            result = await PalliumMcpClient(ctx).relay_receive("codex", "target", max_chars=1000)
        assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) <= 1000
        assert post.call_args_list[0].kwargs["json"]["max_chars"] == 744
        assert "claim_token" not in result["deliveries"][0]
        assert "payload" not in result["deliveries"][0]

    @pytest.mark.asyncio
    async def test_recipients_forwards_unicode_runtime_and_scope(self, ctx: PalliumContext) -> None:
        response = _mock_response(json_data={"sessions": []})
        with patch("httpx.AsyncClient.get", return_value=response) as mock_get:
            result = await PalliumMcpClient(ctx).relay_recipients(runtime="קלוד", include_inactive=True)
        assert result == {"sessions": []}
        assert mock_get.call_args.kwargs["params"] == {
            "container_ref": "test-container",
            "actor_ref": "test-actor",
            "runtime": "קלוד",
            "include_inactive": True,
        }

    @pytest.mark.asyncio
    async def test_send_preserves_unicode_and_omits_optional_fields(self, ctx: PalliumContext) -> None:
        response = _mock_response(json_data={"message_id": "m-1"})
        with patch("httpx.AsyncClient.post", return_value=response) as mock_post:
            result = await PalliumMcpClient(ctx).relay_send(
                message="הודעה → 你好",
                recipient="codex:@review",
                sender_runtime="codex",
                sender_session_ref="session-1",
            )
        assert result == {"message_id": "m-1"}
        payload = mock_post.call_args.kwargs["json"]
        assert payload == {
            "payload": "הודעה → 你好",
            "recipient": "codex:@review",
            "sender_runtime": "codex",
            "sender_session_ref": "session-1",
            "container_ref": "test-container",
            "actor_ref": "test-actor",
        }

    @pytest.mark.asyncio
    async def test_send_forwards_optional_reply_expiry_and_id(self, ctx: PalliumContext) -> None:
        response = _mock_response(json_data={"message_id": "m-2"})
        with patch("httpx.AsyncClient.post", return_value=response) as mock_post:
            await PalliumMcpClient(ctx).relay_send(
                message="reply",
                recipient="codex:session-1",
                sender_runtime="codex",
                sender_session_ref="session-2",
                expires_in_seconds=60,
                in_reply_to="m-1",
                message_id="m-2",
            )
        payload = mock_post.call_args.kwargs["json"]
        assert payload["expires_in_seconds"] == 60
        assert payload["in_reply_to"] == "m-1"
        assert payload["message_id"] == "m-2"

    @pytest.mark.asyncio
    async def test_reply_uses_delivery_and_scope_only(self, ctx: PalliumContext) -> None:
        response = _mock_response(json_data={"message_id": "reply-1"})
        with patch("httpx.AsyncClient.post", return_value=response) as mock_post:
            result = await PalliumMcpClient(ctx).relay_reply(
                delivery_id="delivery-1", message="ack ✓", expires_in_seconds=60
            )
        assert result == {"message_id": "reply-1"}
        assert mock_post.call_args.args[0].endswith("/relay/replies")
        assert mock_post.call_args.kwargs["json"] == {
            "delivery_id": "delivery-1",
            "payload": "ack ✓",
            "expires_in_seconds": 60,
            "container_ref": "test-container",
            "actor_ref": "test-actor",
        }

    @pytest.mark.asyncio
    async def test_status_gets_scoped_message(self, ctx: PalliumContext) -> None:
        response = _mock_response(json_data={"message_id": "m-1", "state": "delivered"})
        with patch("httpx.AsyncClient.get", return_value=response) as mock_get:
            result = await PalliumMcpClient(ctx).relay_status("m-1")
        assert result["state"] == "delivered"
        assert mock_get.call_args.kwargs["params"] == {
            "container_ref": "test-container",
            "actor_ref": "test-actor",
        }

    @pytest.mark.asyncio
    async def test_relay_connection_error_is_visible(self, ctx: PalliumContext) -> None:
        with patch("httpx.AsyncClient.get", side_effect=Exception("relay unavailable")):
            result = await PalliumMcpClient(ctx).relay_recipients()
        assert result["error"] == "relay unavailable"
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "kwargs"),
        [
            ("relay_send", {"message": "handoff", "recipient": "codex:session-1", "sender_runtime": "codex", "sender_session_ref": "sender"}),
            ("relay_reply", {"delivery_id": "delivery-1", "message": "ack"}),
        ],
    )
    async def test_relay_busy_error_remains_retryable_for_send_and_reply(self, ctx: PalliumContext, method: str, kwargs: dict) -> None:
        body = {"detail": {"code": "relay_busy", "retryable": True}}
        response = _mock_response(status_code=503, json_data=body)
        response.raise_for_status.side_effect = httpx.HTTPStatusError("busy", request=MagicMock(), response=response)
        with patch("httpx.AsyncClient.post", return_value=response):
            result = await getattr(PalliumMcpClient(ctx), method)(**kwargs)
        assert result["detail"] == body
    @pytest.mark.asyncio
    async def test_name_omits_optional_alias_and_replace_flag(self, ctx: PalliumContext) -> None:
        response = _mock_response(json_data={"session_ref": "session-1"})
        with patch("httpx.AsyncClient.post", return_value=response) as mock_post:
            await PalliumMcpClient(ctx).relay_name(
                alias=None, current_runtime="codex", current_session_ref="session-1"
            )
        assert mock_post.call_args.kwargs["json"] == {
            "runtime": "codex",
            "session_ref": "session-1",
            "container_ref": "test-container",
            "actor_ref": "test-actor",
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "kwargs"),
        [
            ("relay_send", {"message": "x", "recipient": "codex:target", "sender_runtime": "codex", "sender_session_ref": "s", "request_id": "key"}),
            ("relay_reply", {"delivery_id": "d", "message": "x", "request_id": "key"}),
        ],
    )
    async def test_keyed_relay_mcp_operations_fail_closed_without_post(self, ctx: PalliumContext, method: str, kwargs: dict) -> None:
        with patch("httpx.AsyncClient.post") as post:
            result = await getattr(PalliumMcpClient(ctx), method)(**kwargs)
        assert "coordinated API activation" in result["error"]
        post.assert_not_called()