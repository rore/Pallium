"""Finite real-lifecycle/GC discrimination; never qualification or forced collection."""
from contextlib import contextmanager, ExitStack
import gc, importlib.metadata, importlib.util, json, os, signal, subprocess, sys, threading, time
from pathlib import Path

CASES = [(mode, repeat) for mode in ('baseline', 'lifecycle') for repeat in (1, 2)]

def heap_snapshot():
    # Linux resident pages, not maximum RSS; fixed bounded read and numeric output.
    with open('/proc/self/statm', 'rb') as handle:
        raw = handle.read(128)
    fields = raw.split()
    if len(fields) < 2 or not fields[1].isdigit():
        raise ValueError('RSS unavailable')
    return {'rss_bytes': int(fields[1]) * os.sysconf('SC_PAGE_SIZE'),
            'counts': list(gc.get_count()), 'stats': gc.get_stats()}

class GCWindow:
    """One target journey only; all Python threads, fixed numeric events."""
    def __init__(self):
        self.events = []
        self.issues = []
        self.dropped = 0
        self.callback = self.observe
        self.installed = False
        self.started = False
        self.armed = True
        self.active_collection = None
    def fault(self, name):
        if name not in self.issues:
            self.issues.append(name)
    def observe(self, phase, info):
        try:
            if phase not in ('start', 'stop'):
                self.fault('gc_phase')
                return
            identity = (threading.get_ident(), int(info['generation']))
            if phase == 'start':
                if self.active_collection is not None: self.fault('gc_nested_or_duplicate')
                self.active_collection = identity
            else:
                if self.active_collection not in (None, identity): self.fault('gc_identity_mismatch')
                self.active_collection = None
            # Construction only maintains one active identity, no event buffer use.
            if not self.armed:
                return
            if len(self.events) >= 256:
                self.dropped += 1
                self.fault('gc_overflow')
                return
            self.events.append({'phase': 0 if phase == 'start' else 1,
                'generation': int(info['generation']), 'thread': threading.get_ident(),
                'wall_ns': time.monotonic_ns(), 'thread_cpu_ns': time.thread_time_ns(),
                'process_cpu_ns': time.process_time_ns(),
                'collected': int(info.get('collected', 0)),
                'uncollectable': int(info.get('uncollectable', 0))})
        except BaseException:
            self.fault('gc_observer_fault')
    def start(self, armed=True):
        self.armed = armed
        try:
            self.policy = (gc.isenabled(), gc.get_threshold())
            self.previous = tuple(gc.callbacks)
            self.before = heap_snapshot()
            gc.callbacks.append(self.callback)
            self.installed = True
            self.started = True
        except BaseException:
            self.fault('gc_start_fault')
    def construction_finished(self):
        try: self.construction_after = heap_snapshot()
        except BaseException: self.fault('gc_construction_snapshot_fault')
    def arm(self):
        try:
            self.arm_snapshot = heap_snapshot()
            if self.active_collection is not None: self.fault('gc_active_at_arm')
            self.armed_at_ns = time.monotonic_ns()
            self.armed = True
        except BaseException:
            self.fault('gc_arm_fault')
    def stop(self):
        try:
            if not self.armed: self.fault('gc_not_armed')
            if self.active_collection is not None: self.fault('gc_active_at_stop')
            if self.installed:
                for index, callback in enumerate(gc.callbacks):
                    if callback is self.callback:
                        del gc.callbacks[index]
                        self.installed = False
                        break
                else:
                    self.fault('gc_callback_missing')
            if hasattr(self, 'armed_at_ns'): self.stopped_at_ns = time.monotonic_ns()
            if not self.started:
                self.fault('gc_not_started')
            if tuple(gc.callbacks) != getattr(self, 'previous', tuple(gc.callbacks)):
                self.fault('gc_callback_restoration')
            if getattr(self, 'policy', None) != (gc.isenabled(), gc.get_threshold()):
                self.fault('gc_policy_changed')
            self.after = heap_snapshot()
        except BaseException:
            self.fault('gc_stop_fault')
    def payload(self, records):
        opened, intervals = {}, []
        for event in self.events:
            key = (event['thread'], event['generation'])
            if event['phase'] == 0:
                if key in opened: self.fault('gc_nested_or_duplicate')
                opened[key] = event
            else:
                start = opened.pop(key, None)
                if start is None:
                    self.fault('gc_unpaired')
                    continue
                deltas = {name: event[name] - start[name] for name in
                          ('wall_ns', 'thread_cpu_ns', 'process_cpu_ns')}
                if any(value < 0 for value in deltas.values()): self.fault('gc_clock_invalid')
                intervals.append({'entered_ns': start['wall_ns'], 'returned_ns': event['wall_ns'],
                    'generation': key[1], 'thread': key[0], **deltas,
                    'collected': event['collected'], 'uncollectable': event['uncollectable']})
        if opened: self.fault('gc_unpaired')
        overlaps = []
        for record in records:
            root = next((s for s in record['spans'] if s['phase'] == 'turn'), None)
            if root is None: continue
            entered = record['anchor_monotonic_ns'] + root['entered_wall_ns']
            returned = record['anchor_monotonic_ns'] + root['returned_wall_ns']
            overlaps.append({'ordinal': record['ordinal'], 'turn_wall_ns': returned - entered,
                'collection_overlap_ns': [max(0, min(returned, i['returned_ns']) -
                    max(entered, i['entered_ns'])) for i in intervals]})
        return {'complete': not self.issues, 'issues': self.issues, 'dropped': self.dropped,
                'events': self.events, 'intervals': intervals, 'turn_overlaps': overlaps,
                'before': getattr(self, 'before', None), 'construction_after': getattr(self, 'construction_after', None),
                'arm_snapshot': getattr(self, 'arm_snapshot', None), 'armed_at_ns': getattr(self, 'armed_at_ns', None),
                'stopped_at_ns': getattr(self, 'stopped_at_ns', None), 'after': getattr(self, 'after', None),
                'scope': 'all-thread interval events armed immediately before original journey through ordinary teardown; construction counters separate, active boundary incomplete; observer-inclusive, not refcount-finalizer or runqueue/I-O duration'}

def cleanup_subject(child):
    """Only this start_new_session child's exact owned group, including survivors."""
    def exists():
        try:
            os.killpg(child.pid, 0)
            return True
        except ProcessLookupError:
            return False
    result = {'term_sent': False, 'kill_sent': False, 'remaining': True}
    for native_signal, label in ((signal.SIGTERM, 'term_sent'), (signal.SIGKILL, 'kill_sent')):
        if not exists(): break
        try:
            os.killpg(child.pid, native_signal)
            result[label] = True
        except ProcessLookupError:
            break
        deadline = time.monotonic() + 5
        while exists() and time.monotonic() < deadline:
            child.poll()  # Reap the owned leader as well as checking its group.
            time.sleep(.01)  # Outside every measured journey, cleanup only.
    child.poll()
    result['remaining'] = exists()
    return result

def evidence_status(directory):
    summary = {'complete': False, 'timing_complete': False, 'gc_complete': False,
               'conditioning_complete': False, 'issues': []}
    try:
        reports = []
        for mode, repeat in CASES:
            file = directory / f'{mode}-{repeat}.json'
            if file.stat().st_size > 1_000_000: raise ValueError('oversize')
            report = json.loads(file.read_text(encoding='utf-8'))
            if (report['mode'], report['repeat']) != (mode, repeat): raise ValueError('identity')
            reports.append(report)
        runtime = json.loads((directory / 'runtime.json').read_text(encoding='utf-8'))
        process = json.loads((directory / 'process.json').read_text(encoding='utf-8'))
        if runtime['platform'] != 'linux' or not runtime['python'].startswith('3.12.') or not runtime['source'] or not runtime['distributions']: raise ValueError('runtime')
        if len(process['subjects']) != 4 or any(s['exit_code'] != 0 or s['timed_out'] or s['remaining'] for s in process['subjects']): raise ValueError('subjects')
        summary['timing_complete'] = all(r['third_is_exact_claim'] and not r['unexpected_observer_issues'] and not r['unexpected_capture_issues'] and r['capture']['seen'] == 3 and r['capture']['dropped'] == 0 and r['teardown_error_type'] is None for r in reports)
        summary['conditioning_complete'] = all(r['conditioning']['completed'] == (16 if r['mode'] == 'lifecycle' else 0) and not r['conditioning']['cap_exceeded'] for r in reports)
        summary['gc_complete'] = all(r['gc']['complete'] and r['gc']['dropped'] == 0 for r in reports)
        summary['resource_complete'] = all(r['capture']['complete'] for r in reports)
        summary['original_all_pass'] = all(r['original_assertions_passed'] for r in reports)
        summary['collection_observed'] = any(r['gc']['intervals'] for r in reports)
        summary['slow_turn_gc_overlap'] = any(o['turn_wall_ns'] >= 100_000_000 and any(o['collection_overlap_ns']) for r in reports for o in r['gc']['turn_overlaps'])
        summary['complete'] = all(summary[k] for k in ('timing_complete', 'conditioning_complete', 'gc_complete'))
        if not summary['complete']: summary['issues'] = ['incomplete_evidence']
    except Exception:
        summary['issues'] = ['missing_malformed_or_failed_evidence']
    (directory / 'evidence-status.json').write_text(json.dumps(summary, sort_keys=True), encoding='utf-8')
    return 0 if summary['complete'] else 1

if __name__ == '__main__':
    import hashlib, tempfile
    directory = Path(sys.argv[2]).resolve(); directory.mkdir(parents=True, exist_ok=True)
    if sys.argv[1] == '--status': raise SystemExit(evidence_status(directory))
    assert sys.platform == 'linux' and sys.version_info[:2] == (3, 12)
    if sys.argv[1] == '--run':
        subjects, active, cleanup_done = [], None, False
        def terminate_supervisor(_signal, _frame):
            raise SystemExit(143)
        previous_term = signal.signal(signal.SIGTERM, terminate_supervisor)
        try:
            for mode, repeat in CASES:
                record = {'mode': mode, 'repeat': repeat, 'pid': None, 'exit_code': None, 'timed_out': False, 'remaining': True}
                subjects.append(record)
                cleanup_done = False
                with (directory / f'{mode}-{repeat}.stdout').open('wb') as out, (directory / f'{mode}-{repeat}.stderr').open('wb') as err:
                    active = subprocess.Popen([sys.executable, '-B', __file__, '--trial', str(directory), mode, str(repeat)], stdout=out, stderr=err, start_new_session=True)
                    record['pid'] = active.pid
                    try: active.wait(timeout=120)
                    except subprocess.TimeoutExpired: record['timed_out'] = True
                    finally:
                        try:
                            record.update(cleanup_subject(active))
                            cleanup_done = True
                        finally: record['exit_code'] = active.poll()
                    active = None
                if record['timed_out'] or record['exit_code'] or record['remaining']: break
        finally:
            # Includes outer timeout/SIGTERM, readiness errors and ordinary exceptions.
            try:
                if active is not None and not cleanup_done:
                    try: subjects[-1].update(cleanup_subject(active))
                    finally: subjects[-1]['exit_code'] = active.poll()
            finally:
                signal.signal(signal.SIGTERM, previous_term)
                (directory / 'process.json').write_text(json.dumps({'subjects': subjects, 'scope': 'four fresh owned groups, native group-existence check after bounded TERM/KILL; no broad process enumeration'}, sort_keys=True))
        raise SystemExit(0 if len(subjects) == 4 and all(s['exit_code'] == 0 and not s['timed_out'] and not s['remaining'] for s in subjects) else 1)
    assert sys.argv[1] == '--trial'
    mode, repeat = sys.argv[3], int(sys.argv[4]); assert (mode, repeat) in CASES
    os.environ['PALLIUM_FOCUSED_EVIDENCE'] = str(directory)
    private_temp = Path(tempfile.mkdtemp(prefix='pallium-gc-', dir=os.environ.get('RUNNER_TEMP')))
    assert Path.cwd().resolve() not in private_temp.resolve().parents
    consumed = ('scripts/relay_claim_focused_repro.py', 'scripts/relay_claim_acquisition_diagnostic.py', 'tests/test_agent_relay_hooks.py', 'tests/conftest.py', 'core/service.py', 'core/processing.py', 'core/relay.py', 'storage/sqlite.py', 'storage/sqlite_queue.py', 'storage/sqlite_relay.py', 'app/main.py', 'app/config.py', 'pyproject.toml', '.github/workflows/ci.yml')
    process = {'pid': os.getpid(), 'mode': mode, 'repeat': repeat, 'pytest_temp': str(private_temp / 'p'), 'source': {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in consumed}, 'affinity': sorted(os.sched_getaffinity(0)), 'nice': os.getpriority(os.PRIO_PROCESS, 0), 'scope': 'observed only; no affinity, priority or GC policy changes'}
    (directory / f'process-{mode}-{repeat}.json').write_text(json.dumps(process, sort_keys=True))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import pytest
    exit_code = 2
    try: exit_code = pytest.main([f'{__file__}::test_focused_original_http[{mode}-{repeat}]', '-q', '-x', '-n', '0', '-p', 'no:cacheprovider', '--basetemp', str(private_temp / 'p'), '--junitxml', str(directory / f'junit-{mode}-{repeat}.xml')])
    finally: (directory / f'result-{mode}-{repeat}.json').write_text(json.dumps({'exit_code': int(exit_code), 'pid': os.getpid(), 'scope': 'original assertions retained separately; not qualification'}))
    raise SystemExit(exit_code)

import pytest
from tests.conftest import test_db_url, isolated_claude_wake_state
from tests.conftest import client as native_client
from tests.test_agent_relay_hooks import isolated_hook_state
from tests.test_agent_relay_hooks import test_codex_exact_wake_real_http_response_delay_is_bounded_and_traceable as journey
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('_focused_original_recorder', ROOT / 'scripts/relay_claim_acquisition_diagnostic.py')
observer = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(observer)
assert importlib.metadata.version('sqlalchemy') == observer.EXPECTED_SQLALCHEMY

@pytest.fixture
def observed_client(test_db_url, monkeypatch, request, tmp_path):
    mode, repeat = request.node.callspec.params['mode'], request.node.callspec.params['repeat']
    receipt = {'mode': mode, 'repeat': repeat, 'original_assertions_passed': False,
               'conditioning': {'completed': 0, 'cap_exceeded': False, 'snapshots': []}}
    request.node._focused_receipt = receipt
    capture, window = observer.Capture(0), GCWindow()
    native_error = None
    try:
        initial = heap_snapshot(); receipt['conditioning']['initial'] = initial
        for index in range(16 if mode == 'lifecycle' else 0):
            database = tmp_path / f'conditioning-{index}.db'
            with monkeypatch.context() as setup:
                with contextmanager(native_client.__wrapped__)(f'sqlite:///{database}', setup) as http:
                    response = http.post('/relay/turn', json={'runtime': 'codex', 'session_ref': 'gc-conditioning', 'container_ref': 'git:example/conditioning'})
                    assert response.status_code == 200, 'conditioning registration refused'
                    health = http.get('/health')
                    # Native shared fixture deliberately does not enter lifespan.
                    assert health.status_code == 503 and health.json()['status'] == 'initializing', 'conditioning read contract failed'
            del http, response, health, setup
            snapshot = heap_snapshot()
            receipt['conditioning']['completed'] += 1
            receipt['conditioning']['snapshots'].append(snapshot)
            if snapshot['rss_bytes'] - initial['rss_bytes'] > 256 * 1024 * 1024:
                receipt['conditioning']['cap_exceeded'] = True
                raise AssertionError('conditioning observed RSS growth cap exceeded')
        window.start(armed=False)
        try:
            with ExitStack() as observation:
                with contextmanager(native_client.__wrapped__)(test_db_url, monkeypatch) as client:
                    window.construction_finished()
                    observer.install(capture, observation, client.app.state.pallium_service._storage)
                    observer.install_http(capture, observation, client)
                    assert not capture.issues
                    yield client, capture, observation, window
        finally:
            window.stop()
            after = getattr(window, 'after', None)
            if after is not None and after['rss_bytes'] - initial['rss_bytes'] > 256 * 1024 * 1024:
                receipt['conditioning']['cap_exceeded'] = True
                window.fault('observed_rss_cap')
    finally:
        native_error = sys.exc_info()[0]
        receipt['teardown_error_type'] = None if native_error is None else native_error.__name__
        if native_error is not None: capture.failed = True
        try:
            payload = capture.payload(); receipt['capture'] = payload
            receipt['gc'] = window.payload(payload['records'])
            receipt['unexpected_observer_issues'] = [x for r in payload['records'] for x in r['issues'] if x != 'resource_unsupported']
            resource_only = all(set(r['issues']) <= {'resource_unsupported'} for r in payload['records'])
            receipt['unexpected_capture_issues'] = [x for x in payload['issues'] if not (x == 'incomplete_turn' and resource_only)]
            directory = Path(os.environ['PALLIUM_FOCUSED_EVIDENCE'])
            (directory / f'{mode}-{repeat}.json').write_text(json.dumps(receipt, sort_keys=True), encoding='utf-8')
            if native_error is None:
                assert not receipt['unexpected_observer_issues'] and not receipt['unexpected_capture_issues']
                assert not receipt['gc']['issues'] and payload['dropped'] == 0 and payload['seen'] <= 3
        except BaseException:
            if native_error is None: raise
            print('lifecycle evidence emission failed during original error', file=sys.stderr)

@pytest.mark.parametrize('mode,repeat', CASES)
def test_focused_original_http(observed_client, monkeypatch, tmp_path, capsys, request, mode, repeat):
    client, capture, observation, window = observed_client
    receipt = request.node._focused_receipt
    storage = client.app.state.pallium_service._storage
    native_turn = storage.relay_turn
    entries = 0
    def observe_exact(*args, **kwargs):
        nonlocal entries
        entries += 1
        if entries == 3:
            receipt['third_is_exact_claim'] = (kwargs.get('runtime') == 'codex' and kwargs.get('session_ref') == 'target-session' and kwargs.get('container_ref') == 'git:example/repo' and isinstance(kwargs.get('exact_delivery_id'), str) and kwargs['exact_delivery_id'].startswith('relay-delivery-'))
        return native_turn(*args, **kwargs)
    capture.patch(observation, storage, 'relay_turn', observe_exact)
    receipt['journey_entered_ns'] = time.monotonic_ns()
    try:
        window.arm()
        journey(client, monkeypatch, tmp_path, capsys, 2.2, False, 'claimed', False, False)
        receipt['original_assertions_passed'] = True
    except AssertionError as exc:
        tb = exc.__traceback__
        while tb.tb_next: tb = tb.tb_next
        receipt['original_failure'] = {'file': Path(tb.tb_frame.f_code.co_filename).name, 'line': tb.tb_lineno, 'type': 'AssertionError'}
        capture.failed = True
    except BaseException as exc:
        receipt['unexpected_journey_error_type'] = type(exc).__name__; capture.failed = True
        raise
    finally:
        receipt['journey_returned_ns'] = time.monotonic_ns()
        stages = tmp_path / 'delayed-http-stages.json'
        if stages.exists(): receipt['original_stages'] = json.loads(stages.read_text(encoding='utf-8'))
