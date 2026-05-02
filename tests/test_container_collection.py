from app.config import AppConfig
from app.main import create_app
from core.models import SourceItem
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES

def _config(db_url: str) -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=db_url,
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    )

def _make_item(source_id, content, *, thread_ref=None, container_ref="container-a"):
    return SourceItem(
        source_type="chat_message",
        source_id=source_id,
        content_type="text/plain",
        content=content,
        role="user",
        artifact_kind="message",
        container_ref=container_ref,
        thread_ref=thread_ref,
        visibility="private",
        processing_status="completed",
    )

class TestListTopLevelMessages:
    def test_collects_first_item_per_thread_ref(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        for i in range(3):
            storage.create_source_item(_make_item(f"thread-a-{i}", f"msg {i}", thread_ref="thread-a"))
        storage.create_source_item(_make_item("thread-b-0", "singleton", thread_ref="thread-b"))

        items = storage.list_top_level_messages_for_container("container-a")
        source_ids = {item.source_id for item in items}
        assert "thread-a-0" in source_ids
        assert "thread-b-0" in source_ids
        assert "thread-a-1" not in source_ids
        assert "thread-a-2" not in source_ids
        assert len(items) == 2

    def test_collects_threadless_items(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("no-thread-1", "threadless msg", thread_ref=None))
        storage.create_source_item(_make_item("with-thread-1", "threaded msg", thread_ref="thread-a"))

        items = storage.list_top_level_messages_for_container("container-a")
        source_ids = {item.source_id for item in items}
        assert "no-thread-1" in source_ids
        assert "with-thread-1" in source_ids
        assert len(items) == 2

    def test_watermark_filters_old_items(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("old-1", "old message", thread_ref="thread-old"))
        storage.create_source_item(_make_item("new-1", "new message", thread_ref="thread-new"))

        all_items = storage.list_top_level_messages_for_container("container-a")
        watermark = min(item.created_at for item in all_items)

        filtered = storage.list_top_level_messages_for_container(
            "container-a", after_created_at=watermark,
        )
        assert len(filtered) == 1
        assert filtered[0].source_id == "new-1"

    def test_max_items_limits_results(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        for i in range(10):
            storage.create_source_item(_make_item(f"msg-{i}", f"message {i}", thread_ref=f"thread-{i}"))

        items = storage.list_top_level_messages_for_container("container-a", max_items=3)
        assert len(items) == 3
        # Should be the 3 most recent, returned in ascending order
        source_ids = [item.source_id for item in items]
        assert source_ids == ["msg-7", "msg-8", "msg-9"]

    def test_different_container_excluded(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("other-1", "other container", thread_ref="t-1", container_ref="container-b"))
        storage.create_source_item(_make_item("mine-1", "my container", thread_ref="t-2", container_ref="container-a"))

        items = storage.list_top_level_messages_for_container("container-a")
        assert len(items) == 1
        assert items[0].source_id == "mine-1"
