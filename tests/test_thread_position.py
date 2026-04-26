from app.config import AppConfig
from app.main import create_app
from core.models import SourceItem
from storage.vector_index import VectorIndexConfig

def _config(db_url: str) -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=db_url,
        default_use_case="demo_agent_memory",
        vector_index=VectorIndexConfig(enabled=False),
    )

def _make_item(source_id, *, thread_ref=None, container_ref="container-a"):
    return SourceItem(
        source_type="chat_message",
        source_id=source_id,
        content_type="text/plain",
        content="test content",
        role="user",
        artifact_kind="message",
        container_ref=container_ref,
        thread_ref=thread_ref,
        visibility="private",
    )

def _find(storage, source_id):
    item = storage.find_source_item("chat_message", source_id)
    assert item is not None, f"source_id={source_id!r} not found"
    return item

class TestThreadPositionAtIngest:
    def test_first_item_in_thread_gets_position_1(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("msg-1", thread_ref="thread-a"))
        item = _find(storage, "msg-1")
        assert item.thread_position == 1

    def test_second_item_in_thread_gets_position_2(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("msg-1", thread_ref="thread-a"))
        storage.create_source_item(_make_item("msg-2", thread_ref="thread-a"))
        item = _find(storage, "msg-2")
        assert item.thread_position == 2

    def test_different_threads_get_independent_positions(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("a-1", thread_ref="thread-a"))
        storage.create_source_item(_make_item("b-1", thread_ref="thread-b"))
        storage.create_source_item(_make_item("a-2", thread_ref="thread-a"))

        assert _find(storage, "a-1").thread_position == 1
        assert _find(storage, "b-1").thread_position == 1
        assert _find(storage, "a-2").thread_position == 2

    def test_threadless_item_gets_position_1(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("no-thread", thread_ref=None))
        item = _find(storage, "no-thread")
        assert item.thread_position == 1

    def test_different_containers_get_independent_positions(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("c1-1", thread_ref="thread-a", container_ref="container-1"))
        storage.create_source_item(_make_item("c2-1", thread_ref="thread-a", container_ref="container-2"))

        assert _find(storage, "c1-1").thread_position == 1
        assert _find(storage, "c2-1").thread_position == 1
