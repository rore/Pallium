from __future__ import annotations

from datetime import timedelta

from app.config import AppConfig
from app.worker import run_worker
from app import supervisor
from core.contracts import ProcessResult, build_source_item
from core.service import PalliumService
from retrieval.lexical import LexicalRetrievalProvider
from semantic.base import SemanticPlugin
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider
from sqlalchemy.orm import Session


class AlwaysFailPlugin(SemanticPlugin):
    name = 'always_fail'

    def process_item(self, source_item):
        raise RuntimeError('boom')


def _build_service(test_db_url: str, *, plugins: dict[str, SemanticPlugin] | None = None, default_use_case: str = 'demo_agent_memory', storage: SQLiteStorageProvider | None = None) -> PalliumService:
    storage = storage or SQLiteStorageProvider(test_db_url)
    retrieval = LexicalRetrievalProvider(storage)
    resolved_plugins = {'demo_agent_memory': DemoAgentMemoryPlugin()}
    if plugins:
        resolved_plugins.update(plugins)
    return PalliumService(storage=storage, retrieval=retrieval, semantic_plugins=resolved_plugins, default_use_case=default_use_case)


def test_run_worker_once_processes_pending_item(test_db_url: str) -> None:
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

    exit_code = run_worker(['--once', '--worker-id', 'worker-test'], config=AppConfig(storage_backend='sqlite', sqlite_url=test_db_url, default_use_case='demo_agent_memory'))
    assert exit_code == 0

    status = service.get_item_processing(ingest.source_item_id)
    assert status.processing_status == 'completed'
    assert status.memory_object_ids


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
    assert after_first.annotation_ids == []
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
    assert len(final_state.annotation_ids) == 2
    assert len(final_state.memory_object_ids) == 1
    assert len(final_state.relation_ids) == 1
    assert len(final_state.index_entry_ids) == 2



class FakeProcess:
    _next_pid = 1000

    def __init__(self, command: list[str], cwd: str | None = None) -> None:
        self.command = command
        self.cwd = cwd
        self.pid = FakeProcess._next_pid
        FakeProcess._next_pid += 1
        self.returncode = None
        self.terminated = False
        self.waited = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        self.waited = True
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def test_supervisor_blocks_reload_mode() -> None:
    assert supervisor.run_supervisor(['--reload']) == 2


def test_supervisor_starts_api_and_workers_and_terminates_them() -> None:
    started: list[FakeProcess] = []

    def popen_factory(command, cwd=None):
        process = FakeProcess(command, cwd=cwd)
        started.append(process)
        return process

    exit_code = supervisor.run_supervisor(
        ['--host', '127.0.0.1', '--port', '8010', '--workers', '2'],
        popen_factory=popen_factory,
        sleep_fn=lambda _: None,
        should_stop=lambda: True,
    )

    assert exit_code == 0
    assert len(started) == 3
    assert started[0].command[:3] == ['python', '-m', 'uvicorn'] or started[0].command[1:3] == ['-m', 'uvicorn']
    assert all(process.terminated for process in started)
    assert all(process.waited or process.returncode is not None for process in started)
