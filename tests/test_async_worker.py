from __future__ import annotations

from datetime import timedelta
import re
import sqlite3
import threading
from subprocess import TimeoutExpired
from unittest.mock import MagicMock

from sqlalchemy.exc import OperationalError as SAOperationalError

from app.config import AppConfig
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import _vector_index_path_for_sqlite
from app.processor import run_processor
from app.worker import run_worker
from app.transient_errors import is_transient_error
from app import supervisor
from core.contracts import ProcessResult, build_source_item
from core.service import DEFAULT_PROCESSING_LEASE_SECONDS, PalliumService
from retrieval.lexical import LexicalRetrievalProvider
from semantic.base import SemanticPlugin, ThreadAggregationSemanticPlugin
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.base import ThreadProcessingScope
from storage.sqlite import SQLiteStorageProvider
from sqlalchemy.orm import Session
from core.models import MemoryObject, Relation


def _make_sa_operational_error(message: str) -> SAOperationalError:
    """Create a SQLAlchemy OperationalError wrapping a sqlite3 OperationalError."""
    return SAOperationalError("statement", {}, sqlite3.OperationalError(message))


class AlwaysFailPlugin(SemanticPlugin):
    name = 'always_fail'

    def process_item(self, source_item):
        raise RuntimeError('boom')


class BlockingThreadAggregationPlugin(ThreadAggregationSemanticPlugin):
    name = 'blocking_thread_lease'

    @property
    def thread_summary_schema_id(self) -> str:
        return 'blocking_thread_lease.thread_summary'

    @property
    def requires_visibility_context(self) -> bool:
        return True

    def __init__(self) -> None:
        self.first_build_started = threading.Event()
        self.allow_first_build_finish = threading.Event()
        self._build_lock = threading.Lock()
        self.build_calls = 0

    def process_item(self, source_item):
        decision = MemoryObject(
            type='decision',
            schema_id='blocking_thread_lease.decision',
            schema_version='v1',
            payload={'decision': source_item.content, 'source_item_id': source_item.id},
            visibility=source_item.visibility,
        )
        return ProcessResult(
            memory_objects=[decision],
            relations=[
                Relation(
                    from_kind='memory_object',
                    from_id=decision.id,
                    relation_type='supported_by',
                    to_kind='source_item',
                    to_id=source_item.id,
                )
            ],
            index_entries=[],
        )

    def supports_thread_aggregation(self, source_item) -> bool:
        return bool(source_item.container_ref and source_item.thread_ref and source_item.visibility is not None)

    def build_thread_summary(self, aggregate, conclusions):
        with self._build_lock:
            self.build_calls += 1
            build_number = self.build_calls
        if build_number == 1:
            self.first_build_started.set()
            self.allow_first_build_finish.wait(timeout=5)

        thread_summary = MemoryObject(
            type='thread_summary',
            schema_id='blocking_thread_lease.thread_summary',
            schema_version='v1',
            payload={
                'thread_ref': aggregate.thread_ref,
                'container_ref': aggregate.container_ref,
                'source_item_ids': list(aggregate.source_item_ids),
                'summary': f'{len(aggregate.source_item_ids)} items in thread scope',
            },
            visibility=aggregate.visibility,
        )
        task_checkpoint = MemoryObject(
            type='task_checkpoint',
            schema_id='blocking_thread_lease.task_checkpoint',
            schema_version='v1',
            payload={
                'thread_ref': aggregate.thread_ref,
                'container_ref': aggregate.container_ref,
                'source_item_ids': list(aggregate.source_item_ids),
                'summary': f'{len(aggregate.source_item_ids)} items checkpoint',
                'task': 'Resume same-thread work',
                'current_state': f'{len(aggregate.source_item_ids)} items processed',
                'key_findings': [item.payload.get('decision', '') for item in conclusions if item.payload.get('decision')],
                'blocker_state': '',
                'next_step': 'Continue processing',
                'evidence': list(aggregate.source_item_ids),
                'freshness_signal': 'synthetic',
            },
            visibility=aggregate.visibility,
        )
        relations = [
            Relation(
                from_kind='memory_object',
                from_id=memory_object.id,
                relation_type='supported_by',
                to_kind='source_item',
                to_id=source_item_id,
            )
            for memory_object in (thread_summary, task_checkpoint)
            for source_item_id in aggregate.source_item_ids
        ]
        return ProcessResult(
            memory_objects=[thread_summary, task_checkpoint],
            relations=relations,
            index_entries=[],
        )


def _build_service(
    test_db_url: str,
    *,
    plugins: dict[str, SemanticPlugin] | None = None,
    default_use_case: str = 'demo_agent_memory',
    storage: SQLiteStorageProvider | None = None,
    retention_enabled: bool = False,
    retention_lease_seconds: int = 300,
    retention_batch_size: int = 200,
) -> PalliumService:
    storage = storage or SQLiteStorageProvider(test_db_url)
    retrieval = LexicalRetrievalProvider(storage)
    resolved_plugins = {'demo_agent_memory': DemoAgentMemoryPlugin()}
    if plugins:
        resolved_plugins.update(plugins)
    return PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins=resolved_plugins,
        default_use_case=default_use_case,
        retention_enabled=retention_enabled,
        retention_lease_seconds=retention_lease_seconds,
        retention_batch_size=retention_batch_size,
    )


def test_run_worker_once_processes_pending_item(test_db_url: str, capsys) -> None:
    service = _build_service(test_db_url)
    ingest = service.ingest_item(
        source_type='decision_note',
        source_id='worker-demo-1',
        content_type='text/plain',
        content='Decision: use item event time for reservation ordering to avoid duplicate holds.',
        metadata=None,
        use_case='demo_agent_memory',
        artifact_kind='assistant_output',
        role='assistant',
    )
    assert ingest.processing_status == 'pending'

    exit_code = run_worker(['--once', '--worker-id', 'worker-test'], config=AppConfig(storage_backend='sqlite', sqlite_url=test_db_url, default_use_case='demo_agent_memory', vector_index=VectorIndexConfig(index_path=_vector_index_path_for_sqlite(test_db_url))))
    assert exit_code == 0

    status = service.get_item_processing(ingest.source_item_id)
    assert status.processing_status == 'completed'
    assert status.memory_object_ids

    runtime_output = capsys.readouterr().out
    assert re.search(r'^\d{4}-\d{2}-\d{2}T.+ \[processor\] worker_id=worker-test source_item=', runtime_output, re.MULTILINE)


def test_run_worker_uses_processing_summary_path(test_db_url: str, monkeypatch) -> None:
    service = _build_service(test_db_url)
    service.ingest_item(
        source_type='decision_note',
        source_id='worker-summary-1',
        content_type='text/plain',
        content='Decision: summary path should avoid full processing hydration.',
        metadata=None,
        use_case='demo_agent_memory',
        artifact_kind='assistant_output',
        role='assistant',
    )

    def fail_if_full_processing_used(_source_item_id: str):
        raise AssertionError('worker should not call full processing hydration')

    service._processor._get_item_processing = fail_if_full_processing_used
    monkeypatch.setattr('app.worker.build_service', lambda config, **_kw: service)

    exit_code = run_worker(
        ['--once', '--worker-id', 'worker-summary-test'],
        config=AppConfig(
            storage_backend='sqlite',
            sqlite_url=test_db_url,
            default_use_case='demo_agent_memory',
            vector_index=VectorIndexConfig(index_path=_vector_index_path_for_sqlite(test_db_url)),
        ),
        install_signal_handlers=False,
    )

    assert exit_code == 0


def test_run_worker_stops_cleanly_when_stop_is_requested(test_db_url: str) -> None:
    exit_code = run_worker(
        ['--worker-id', 'worker-stop-test'],
        config=AppConfig(storage_backend='sqlite', sqlite_url=test_db_url, default_use_case='demo_agent_memory', vector_index=VectorIndexConfig(index_path=_vector_index_path_for_sqlite(test_db_url))),
        sleep_fn=lambda _: None,
        should_stop=lambda: True,
        install_signal_handlers=False,
    )

    assert exit_code == 0


def test_run_processor_once_processes_pending_item(test_db_url: str, capsys) -> None:
    service = _build_service(test_db_url)
    ingest = service.ingest_item(
        source_type='decision_note',
        source_id='processor-demo-1',
        content_type='text/plain',
        content='Decision: use item event time for reservation ordering to avoid duplicate holds.',
        metadata=None,
        use_case='demo_agent_memory',
        artifact_kind='assistant_output',
        role='assistant',
    )
    assert ingest.processing_status == 'pending'

    exit_code = run_processor(['--once', '--processor-id', 'processor-test'], config=AppConfig(storage_backend='sqlite', sqlite_url=test_db_url, default_use_case='demo_agent_memory', vector_index=VectorIndexConfig(index_path=_vector_index_path_for_sqlite(test_db_url))))
    assert exit_code == 0

    status = service.get_item_processing(ingest.source_item_id)
    assert status.processing_status == 'completed'
    assert status.memory_object_ids

    runtime_output = capsys.readouterr().out
    assert re.search(r'^\d{4}-\d{2}-\d{2}T.+ \[processor\] worker_id=processor-test source_item=', runtime_output, re.MULTILINE)


def test_worker_failure_updates_attempts_and_allows_reclaim(test_db_url: str) -> None:
    service = _build_service(test_db_url, plugins={'always_fail': AlwaysFailPlugin()}, default_use_case='always_fail')
    ingest = service.ingest_item(
        source_type='decision_note',
        source_id='worker-fail-1',
        content_type='text/plain',
        content='Decision: use item event time for reservation ordering to avoid duplicate holds.',
        metadata=None,
        use_case='always_fail',
    )
    assert ingest.processing_status == 'pending'

    storage = service._storage
    first_claim = storage.claim_next_source_item(worker_id='worker-a', lease_seconds=60, max_attempts=2)
    assert first_claim is not None
    service._process_source_item(first_claim, max_attempts=2)

    after_first = storage.get_source_item(first_claim.id)
    assert after_first.processing_status == 'pending'
    assert after_first.processing_attempts == 1
    assert after_first.processing_error == 'boom'
    assert after_first.processing_next_attempt_at is not None

    second_claim = storage.claim_next_source_item(
        worker_id='worker-b',
        lease_seconds=60,
        max_attempts=2,
        now=after_first.processing_next_attempt_at + timedelta(seconds=1),
    )
    assert second_claim is not None
    service._process_source_item(second_claim, max_attempts=2)

    final_state = storage.get_source_item(first_claim.id)
    assert final_state.processing_status == 'failed'
    assert final_state.processing_attempts == 2
    assert final_state.processing_error == 'boom'


def test_storage_claim_is_single_winner_and_expired_lease_is_reclaimable(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    source_item = build_source_item(
        source_type='chat_message',
        source_id='claim-test-1',
        content_type='text/plain',
        content='Decision: use item event time for reservation ordering.',
        metadata=None,
        use_case='demo_agent_memory',
    )
    storage.create_source_item(source_item)

    first = storage.claim_next_source_item(worker_id='worker-a', lease_seconds=30, max_attempts=3)
    second = storage.claim_next_source_item(worker_id='worker-b', lease_seconds=30, max_attempts=3)
    assert first is not None
    assert second is None

    reclaimed = storage.claim_next_source_item(
        worker_id='worker-b',
        lease_seconds=30,
        max_attempts=3,
        now=first.processing_claimed_at + timedelta(seconds=31),
    )
    assert reclaimed is not None
    assert reclaimed.processing_attempts == 2

class FailingCommitStorageProvider(SQLiteStorageProvider):
    def __init__(self, database_url: str) -> None:
        super().__init__(database_url)
        self.fail_commit_once = True

    def _after_commit_processed_source_item_persist(
        self,
        session: Session,
        *,
        source_item_id: str,
        result: ProcessResult,
        supersession_pairs: list[tuple[str, str]],
    ) -> None:
        if self.fail_commit_once:
            self.fail_commit_once = False
            raise RuntimeError('commit boom')


def test_transactional_commit_rolls_back_partial_processing_and_retry_stays_clean(test_db_url: str) -> None:
    storage = FailingCommitStorageProvider(test_db_url)
    service = _build_service(test_db_url, storage=storage)
    ingest = service.ingest_item(
        source_type='decision_note',
        source_id='worker-commit-fail-1',
        content_type='text/plain',
        content='Decision: use item event time for reservation ordering to avoid duplicate holds.',
        metadata=None,
        use_case='demo_agent_memory',
        artifact_kind='assistant_output',
        role='assistant',
    )
    assert ingest.processing_status == 'pending'

    claimed = storage.claim_next_source_item(worker_id='worker-a', lease_seconds=60, max_attempts=2)
    assert claimed is not None
    service._process_source_item(claimed, max_attempts=2)

    after_first = service.get_item_processing(ingest.source_item_id)
    assert after_first.processing_status == 'pending'
    assert after_first.processing_attempts == 1
    assert after_first.processing_error == 'commit boom'
    assert after_first.memory_object_ids == []
    assert after_first.relation_ids == []
    assert len(after_first.index_entry_ids) == 1

    reclaimed = storage.claim_next_source_item(
        worker_id='worker-b',
        lease_seconds=60,
        max_attempts=2,
        now=storage.get_source_item(ingest.source_item_id).processing_next_attempt_at + timedelta(seconds=1),
    )
    assert reclaimed is not None
    service._process_source_item(reclaimed, max_attempts=2)

    final_state = service.get_item_processing(ingest.source_item_id)
    assert final_state.processing_status == 'completed'
    assert final_state.processing_attempts == 2
    assert final_state.processing_error is None
    assert len(final_state.memory_object_ids) == 1
    assert len(final_state.relation_ids) == 1
    assert len(final_state.index_entry_ids) == 2  # source_item content + memory lexical



class FakeProcess:
    _next_pid = 1000

    def __init__(self, command: list[str], cwd: str | None = None) -> None:
        self.command = command
        self.cwd = cwd
        self.pid = FakeProcess._next_pid
        FakeProcess._next_pid += 1
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.waited = False
        self.wait_timeout = False
        self.ignore_terminate = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        if not self.ignore_terminate:
            self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        self.waited = True
        if self.wait_timeout and self.returncode is None:
            raise TimeoutExpired(self.command, timeout)
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def test_supervisor_blocks_reload_mode() -> None:
    assert supervisor.run_supervisor(['--reload']) == 2


def test_supervisor_starts_api_and_processors_and_terminates_them(capsys) -> None:
    started: list[FakeProcess] = []

    def popen_factory(command, cwd=None):
        process = FakeProcess(command, cwd=cwd)
        started.append(process)
        return process

    exit_code = supervisor.run_supervisor(
        ['--host', '127.0.0.1', '--port', '8010', '--processors', '2'],
        popen_factory=popen_factory,
        sleep_fn=lambda _: None,
        should_stop=lambda: True,
    )

    assert exit_code == 0
    assert len(started) == 4
    assert started[0].command[:4] == ['python', '-m', 'app.run', 'serve'] or started[0].command[1:4] == ['-m', 'app.run', 'serve']
    assert any('app.cleaner' in process.command for process in started)
    assert all(process.terminated for process in started)
    assert all(process.waited or process.returncode is not None for process in started)

    supervisor_output = capsys.readouterr().out
    assert re.search(r'^\d{4}-\d{2}-\d{2}T.+ \[supervisor\] started api pid=', supervisor_output, re.MULTILINE)



def test_supervisor_can_disable_cleaners_explicitly(capsys) -> None:
    started: list[FakeProcess] = []

    def popen_factory(command, cwd=None):
        process = FakeProcess(command, cwd=cwd)
        started.append(process)
        return process

    exit_code = supervisor.run_supervisor(
        ['--host', '127.0.0.1', '--port', '8010', '--processors', '1', '--cleaners', '0'],
        popen_factory=popen_factory,
        sleep_fn=lambda _: None,
        should_stop=lambda: True,
    )

    assert exit_code == 0
    assert len(started) == 2
    assert all('app.cleaner' not in process.command for process in started)

    supervisor_output = capsys.readouterr().out
    assert re.search(r'^\d{4}-\d{2}-\d{2}T.+ \[supervisor\] started processor pid=', supervisor_output, re.MULTILINE)


def test_supervisor_kills_process_that_ignores_terminate(capsys) -> None:
    started: list[FakeProcess] = []

    def popen_factory(command, cwd=None):
        process = FakeProcess(command, cwd=cwd)
        if 'app.cleaner' in process.command:
            process.wait_timeout = True
            process.ignore_terminate = True
        started.append(process)
        return process

    exit_code = supervisor.run_supervisor(
        ['--host', '127.0.0.1', '--port', '8010', '--processors', '1'],
        popen_factory=popen_factory,
        sleep_fn=lambda _: None,
        should_stop=lambda: True,
    )

    assert exit_code == 0
    cleaner = next(process for process in started if 'app.cleaner' in process.command)
    assert cleaner.terminated is True
    assert cleaner.killed is True
    captured = capsys.readouterr()
    assert 'forcing process shutdown' in captured.err


def test_thread_processing_lease_is_single_winner_and_expired_lease_is_reclaimable(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    source_item = build_source_item(
        source_type='chat_message',
        source_id='thread-lease-seed',
        content_type='text/plain',
        content='seed item',
        metadata=None,
        use_case='blocking_thread_lease',
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-same-scope',
        visibility="public",
    )
    storage.create_source_item(source_item)
    scope = ThreadProcessingScope(
        scope_key='thread-scope::lease-test',
        use_case='blocking_thread_lease',
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-same-scope',
        visibility="public",
    )
    storage.commit_processed_source_item(
        source_item_id=source_item.id,
        result=ProcessResult(memory_objects=[], relations=[], index_entries=[]),
        thread_rebuild_scope=scope,
    )

    first = storage.claim_thread_processing_scope(scope=scope, worker_id='worker-a', lease_seconds=30)
    assert first is not None

    second = storage.claim_thread_processing_scope(scope=scope, worker_id='worker-b', lease_seconds=30)
    assert second is None

    reclaimed = storage.claim_next_thread_processing_scope(
        worker_id='worker-b',
        lease_seconds=30,
        now=first.processing_claimed_at + timedelta(seconds=31),
    )
    assert reclaimed is not None
    assert reclaimed.scope_key == scope.scope_key


def test_two_workers_same_thread_leave_single_active_thread_memory_after_deferred_rebuild(test_db_url: str) -> None:
    plugin = BlockingThreadAggregationPlugin()
    service = _build_service(
        test_db_url,
        plugins={'blocking_thread_lease': plugin},
        default_use_case='blocking_thread_lease',
    )
    plugin.allow_first_build_finish.set()
    visibility = "public"
    first_ingest = service.ingest_item(
        source_type='assistant_artifact',
        source_id='same-thread-worker-1',
        content_type='text/plain',
        content='Decision: first same-thread worker item.',
        metadata=None,
        use_case='blocking_thread_lease',
        artifact_kind='assistant_output',
        role='assistant',
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-concurrency',
        visibility="public",
    )
    second_ingest = service.ingest_item(
        source_type='assistant_artifact',
        source_id='same-thread-worker-2',
        content_type='text/plain',
        content='Decision: second same-thread worker item.',
        metadata=None,
        use_case='blocking_thread_lease',
        artifact_kind='assistant_output',
        role='assistant',
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-concurrency',
        visibility="public",
    )

    # Process both items -- thread rebuild is decoupled, so items complete
    # without triggering rebuilds. Both create thread processing scopes.
    service.drain_processing_queue(worker_id='deferred-rebuild-test')

    first_status = service.get_item_processing(first_ingest.source_item_id)
    second_status = service.get_item_processing(second_ingest.source_item_id)
    assert first_status.processing_status == 'completed'
    assert second_status.processing_status == 'completed'

    # Thread rebuild coalesces: only one rebuild runs for both items.
    assert plugin.build_calls == 1

    storage = service._storage
    thread_items = storage.list_source_items_for_thread('chat:library-help', 'chat:library-help:thread-concurrency')
    thread_memory = {
        memory.id: memory
        for item in thread_items
        for memory in storage.list_memory_objects_for_source_item(item.id)
        if memory.type in {'thread_summary', 'task_checkpoint'}
    }
    active_summaries = [memory for memory in thread_memory.values() if memory.type == 'thread_summary' and memory.lifecycle == 'active']

    assert len(active_summaries) == 1


def test_thread_rebuild_loop_exits_after_max_iterations(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    retrieval = LexicalRetrievalProvider(storage)

    class AlwaysPendingPlugin(ThreadAggregationSemanticPlugin):
        name = 'always_pending'

        @property
        def thread_summary_schema_id(self) -> str:
            return 'always_pending.thread_summary'

        @property
        def requires_visibility_context(self) -> bool:
            return True

        def process_item(self, source_item):
            return ProcessResult(memory_objects=[], relations=[], index_entries=[])

        def supports_thread_aggregation(self, source_item) -> bool:
            return True

        def build_thread_summary(self, aggregate, conclusions):
            return None, {}

    plugin = AlwaysPendingPlugin()
    service = PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins={'always_pending': plugin},
        default_use_case='always_pending',
    )

    source_item = build_source_item(
        source_type='chat_message',
        source_id='iteration-limit-msg-1',
        content_type='text/plain',
        content='Test iteration limit.',
        metadata=None,
        container_ref='chat:iteration-limit',
        thread_ref='chat:iteration-limit:thread-1',
        visibility="public",
        use_case='always_pending',
    )
    storage.create_source_item(source_item)
    result = service.process_next_source_item(worker_id='iteration-test')
    assert result is not None

    # Patch complete_thread_processing_scope to always report pending
    iteration_count = [0]
    original_complete = storage.complete_thread_processing_scope

    def always_pending_complete(**kwargs):
        iteration_count[0] += 1
        original_complete(**kwargs)
        return True

    storage.complete_thread_processing_scope = always_pending_complete

    lease = storage.claim_next_thread_processing_scope(worker_id='iteration-test', lease_seconds=300)
    if lease is not None:
        service._process_thread_rebuild_lease(lease, worker_id='iteration-test', lease_seconds=300)

    assert iteration_count[0] <= service._MAX_THREAD_REBUILD_ITERATIONS


def test_run_worker_logs_failure_details(monkeypatch, test_db_url: str, capsys) -> None:
    service = _build_service(
        test_db_url,
        plugins={"always_fail": AlwaysFailPlugin()},
        default_use_case="always_fail",
    )
    ingest = service.ingest_item(
        source_type="decision_note",
        source_id="worker-log-fail-1",
        content_type="text/plain",
        content="Decision: fail once for logging coverage.",
        metadata=None,
        use_case="always_fail",
    )
    assert ingest.processing_status == "pending"

    monkeypatch.setattr("app.worker.build_service", lambda config, **_kw: service)

    exit_code = run_worker(
        ["--once", "--worker-id", "worker-log-test", "--max-attempts", "1"],
        config=AppConfig(
            storage_backend="sqlite",
            sqlite_url=test_db_url,
            default_use_case="always_fail",
            vector_index=VectorIndexConfig(enabled=False),
        ),
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "status=failed" in output
    assert "failure_category=" in output
    assert "processing_error=boom" in output


# ── Transient SQLite error handling ───────────────────────────────────


def testis_transient_error_recognizes_known_errors() -> None:
    # Raw sqlite3 errors
    assert is_transient_error(sqlite3.OperationalError("disk I/O error"))
    assert is_transient_error(sqlite3.OperationalError("database is locked"))
    assert is_transient_error(sqlite3.OperationalError("database table is locked"))
    assert is_transient_error(sqlite3.OperationalError("unable to open database file"))
    # SQLAlchemy-wrapped errors (what actually propagates from storage)
    assert is_transient_error(_make_sa_operational_error("disk I/O error"))
    assert is_transient_error(_make_sa_operational_error("database is locked"))


def testis_transient_error_rejects_non_transient() -> None:
    assert not is_transient_error(sqlite3.OperationalError("no such table: foo"))
    assert not is_transient_error(_make_sa_operational_error("no such table: foo"))
    assert not is_transient_error(RuntimeError("disk I/O error"))
    assert not is_transient_error(ValueError("something"))


def test_worker_retries_on_transient_sqlite_error_then_recovers(monkeypatch, test_db_url: str, capsys) -> None:
    service = _build_service(test_db_url)
    ingest = service.ingest_item(
        source_type="decision_note",
        source_id="worker-transient-1",
        content_type="text/plain",
        content="Decision: test transient error recovery.",
        metadata=None,
        use_case="demo_agent_memory",
        artifact_kind="assistant_output",
        role="assistant",
    )

    call_count = [0]
    original_process = service.process_next_source_item

    def failing_then_working(**kwargs):
        call_count[0] += 1
        if call_count[0] <= 2:
            raise _make_sa_operational_error("disk I/O error")
        return original_process(**kwargs)

    service.process_next_source_item = failing_then_working
    monkeypatch.setattr("app.worker.build_service", lambda config, **_kw: service)

    sleep_durations: list[float] = []
    original_sleep = lambda d: sleep_durations.append(d)

    exit_code = run_worker(
        ["--once", "--worker-id", "worker-transient-test"],
        config=AppConfig(
            storage_backend="sqlite",
            sqlite_url=test_db_url,
            default_use_case="demo_agent_memory",
            vector_index=VectorIndexConfig(index_path=_vector_index_path_for_sqlite(test_db_url)),
        ),
        sleep_fn=original_sleep,
        install_signal_handlers=False,
    )

    assert exit_code == 0
    assert call_count[0] == 3  # 2 failures + 1 success
    assert len(sleep_durations) == 2  # backed off twice
    assert sleep_durations[0] == 1.0  # first backoff
    assert sleep_durations[1] == 2.0  # second backoff (exponential)

    status = service.get_item_processing(ingest.source_item_id)
    assert status.processing_status == "completed"

    captured = capsys.readouterr()
    assert "transient_error" in captured.err


def test_worker_gives_up_after_max_consecutive_transient_errors(monkeypatch, test_db_url: str, capsys) -> None:
    service = _build_service(test_db_url)
    service.ingest_item(
        source_type="decision_note",
        source_id="worker-transient-max-1",
        content_type="text/plain",
        content="Decision: test max transient errors.",
        metadata=None,
        use_case="demo_agent_memory",
    )

    def always_fail(**kwargs):
        raise _make_sa_operational_error("database is locked")

    service.process_next_source_item = always_fail
    monkeypatch.setattr("app.worker.build_service", lambda config, **_kw: service)

    exit_code = run_worker(
        ["--worker-id", "worker-transient-max-test"],
        config=AppConfig(
            storage_backend="sqlite",
            sqlite_url=test_db_url,
            default_use_case="demo_agent_memory",
            vector_index=VectorIndexConfig(enabled=False),
        ),
        sleep_fn=lambda _: None,
        install_signal_handlers=False,
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "giving up" in captured.err


def test_worker_non_transient_sqlite_error_still_crashes(monkeypatch, test_db_url: str) -> None:
    service = _build_service(test_db_url)
    service.ingest_item(
        source_type="decision_note",
        source_id="worker-nontransient-1",
        content_type="text/plain",
        content="Decision: test non-transient error.",
        metadata=None,
        use_case="demo_agent_memory",
    )

    def raise_non_transient(**kwargs):
        raise _make_sa_operational_error("no such table: source_items")

    service.process_next_source_item = raise_non_transient
    monkeypatch.setattr("app.worker.build_service", lambda config, **_kw: service)

    import pytest
    with pytest.raises(SAOperationalError, match="no such table"):
        run_worker(
            ["--once", "--worker-id", "worker-nontransient-test"],
            config=AppConfig(
                storage_backend="sqlite",
                sqlite_url=test_db_url,
                default_use_case="demo_agent_memory",
                vector_index=VectorIndexConfig(enabled=False),
            ),
            sleep_fn=lambda _: None,
            install_signal_handlers=False,
        )


# ── Supervisor restart behavior ───────────────────────────────────────


def test_supervisor_restarts_crashed_processor(capsys) -> None:
    started: list[FakeProcess] = []
    poll_count = [0]

    def popen_factory(command, cwd=None):
        process = FakeProcess(command, cwd=cwd)
        started.append(process)
        return process

    def sleep_fn(_):
        poll_count[0] += 1
        # On first poll, crash the first processor
        if poll_count[0] == 1:
            for proc in started:
                if 'app.processor' in proc.command:
                    proc.returncode = 1
                    break
        # On third poll, stop
        if poll_count[0] >= 3:
            return

    exit_code = supervisor.run_supervisor(
        ['--host', '127.0.0.1', '--port', '8010', '--processors', '1', '--cleaners', '0'],
        popen_factory=popen_factory,
        sleep_fn=sleep_fn,
        should_stop=lambda: poll_count[0] >= 3,
    )

    assert exit_code == 0
    # Should have started: api + processor + restarted processor = 3
    assert len(started) == 3
    assert any('app.processor' in p.command for p in started[2:])  # restart

    captured = capsys.readouterr()
    assert "restarted" in captured.out


def test_supervisor_shuts_down_on_rapid_crashes(capsys) -> None:
    started: list[FakeProcess] = []
    poll_count = [0]

    def popen_factory(command, cwd=None):
        process = FakeProcess(command, cwd=cwd)
        # Make every processor crash immediately
        if 'app.processor' in command:
            process.returncode = 1
        started.append(process)
        return process

    def sleep_fn(_):
        poll_count[0] += 1

    # Use a fixed clock so all restarts are within the rapid-restart window
    exit_code = supervisor.run_supervisor(
        ['--host', '127.0.0.1', '--port', '8010', '--processors', '1', '--cleaners', '0'],
        popen_factory=popen_factory,
        sleep_fn=sleep_fn,
        clock=lambda: 0.0,  # time never advances
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "crashed" in captured.err
    # api(1) + processor(1) + 3 restarts = 5
    processor_starts = [p for p in started if 'app.processor' in p.command]
    assert len(processor_starts) == 4  # original + 3 restarts


def test_supervisor_api_exit_is_always_fatal(capsys) -> None:
    started: list[FakeProcess] = []
    poll_count = [0]

    def popen_factory(command, cwd=None):
        process = FakeProcess(command, cwd=cwd)
        started.append(process)
        return process

    def sleep_fn(_):
        poll_count[0] += 1
        if poll_count[0] == 1:
            # Crash the API server
            started[0].returncode = 2

    exit_code = supervisor.run_supervisor(
        ['--host', '127.0.0.1', '--port', '8010', '--processors', '1', '--cleaners', '0'],
        popen_factory=popen_factory,
        sleep_fn=sleep_fn,
    )

    assert exit_code == 2
    # No restarts should have happened — only original api + processor
    assert len(started) == 2


# ── Supervisor snapshot integration ──────────────────────────────────


def test_supervisor_spawns_snapshot_worker_when_enabled(capsys, tmp_path, monkeypatch) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        f'[snapshot]\nenabled = true\nsnapshot_path = "{snapshot_dir.as_posix()}"\ninterval_seconds = 60\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))

    started: list[FakeProcess] = []
    def popen_factory(command, cwd=None):
        process = FakeProcess(command, cwd=cwd)
        started.append(process)
        return process

    exit_code = supervisor.run_supervisor(
        ['--host', '127.0.0.1', '--port', '8099', '--processors', '1', '--cleaners', '0'],
        popen_factory=popen_factory,
        sleep_fn=lambda _: None,
        should_stop=lambda: True,
    )

    assert exit_code == 0
    snapshot_processes = [p for p in started if 'app.snapshot' in ' '.join(str(c) for c in p.command)]
    assert len(snapshot_processes) == 1
    assert all(p.terminated for p in started)

    supervisor_output = capsys.readouterr().out
    assert "started snapshot pid=" in supervisor_output


def test_supervisor_does_not_spawn_snapshot_when_disabled(capsys, tmp_path, monkeypatch) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))

    started: list[FakeProcess] = []
    def popen_factory(command, cwd=None):
        process = FakeProcess(command, cwd=cwd)
        started.append(process)
        return process

    exit_code = supervisor.run_supervisor(
        ['--host', '127.0.0.1', '--port', '8099', '--processors', '1', '--cleaners', '0'],
        popen_factory=popen_factory,
        sleep_fn=lambda _: None,
        should_stop=lambda: True,
    )

    assert exit_code == 0
    snapshot_processes = [p for p in started if 'app.snapshot' in ' '.join(str(c) for c in p.command)]
    assert len(snapshot_processes) == 0
