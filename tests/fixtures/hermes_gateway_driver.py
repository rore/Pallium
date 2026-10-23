"""Qualification-only native gateway grant; the owned helper stays alive for ancestry proof."""
from __future__ import annotations

import json
import hashlib
import importlib.machinery
import os
from pathlib import Path
import builtins
import queue
import re
import subprocess
import threading
import tempfile
import time


def prepare_private_control(env: dict, qualification_root: Path):
    """Select the native short private IPC location; do not choose the gateway TCP port."""
    if os.name == 'nt':
        env['PALLIUM_TUI_ALLOWED_CONTROL_PATHS'] = '[]'
        return []
    home = Path(env['HERMES_HOME']).resolve()
    assert home.is_relative_to(qualification_root.resolve()) and not home.is_symlink()
    home.chmod(0o700)
    runtime = Path(tempfile.mkdtemp(prefix='gw-', dir=qualification_root / 'tmp'))
    assert runtime.stat().st_uid == os.getuid() and runtime.stat().st_mode & 0o777 == 0o700
    env['XDG_RUNTIME_DIR'] = str(runtime)
    direct = home / 'gateway.sock'
    home_hash = hashlib.sha256(os.path.normcase(str(home)).encode('utf-8')).hexdigest()[:16]
    control = direct if len(str(direct).encode('utf-8')) <= 100 else runtime / ('hermes-gw-' + home_hash) / 'control.sock'
    assert len(str(control).encode('utf-8')) <= 100
    env['PALLIUM_TUI_ALLOWED_CONTROL_PATHS'] = json.dumps([str(control)])
    return [str(control)]


def install_copied_runtime_guard(python: Path, source: Path, guard: str, *, allowed_root: Path):
    """Instrument only an existing dedicated qualification venv, never a base installation."""
    import psutil

    python, source, allowed_root = python.resolve(), source.resolve(), allowed_root.resolve()
    assert python.is_relative_to(allowed_root) and source.is_relative_to(allowed_root)
    metadata = subprocess.run([str(python), '-I', '-S', '-c',
        "import json,sys,sysconfig; print(json.dumps({'version':list(sys.version_info[:2]),'prefix':sys.prefix,'base':sys.base_prefix,'site':sysconfig.get_path('purelib')}))"],
        check=True, capture_output=True, text=True, timeout=10,
        env={key: os.environ[key] for key in ('SYSTEMROOT', 'WINDIR') if key in os.environ})
    info = json.loads(metadata.stdout)
    assert info['version'] == [3, 14]
    prefix, base, site = (Path(info[key]).resolve() for key in ('prefix', 'base', 'site'))
    assert prefix != base and prefix.is_relative_to(allowed_root)
    assert python.is_relative_to(prefix) and (prefix / 'pyvenv.cfg').is_file()
    assert site.is_relative_to(prefix) and site.is_dir() and not Path(info['site']).is_symlink()
    for parent in (site, *site.parents):
        if parent.is_relative_to(prefix):
            assert not parent.is_symlink()
    for search in (source, source / 'ui-tui/scripts'):
        assert importlib.machinery.PathFinder.find_spec('sitecustomize', [str(search)]) is None
    for process in psutil.process_iter(['exe']):
        if process.info['exe']:
            assert not Path(process.info['exe']).resolve().is_relative_to(prefix), 'qualification venv still has a consumer'
    target = site / 'sitecustomize.py'
    payload = guard.encode('utf-8')
    if target.exists() or target.is_symlink():
        assert target.is_file() and not target.is_symlink() and target.stat().st_nlink == 1 and target.read_bytes() == payload
        action = 'verified-identical'
    else:
        with target.open('xb') as stream:
            assert stream.write(payload) == len(payload)
            stream.flush()
            os.fsync(stream.fileno())
        action = 'created'
    assert target.read_bytes() == payload
    return {'path': str(target), 'sha256': hashlib.sha256(payload).hexdigest(),
            'prefix': str(prefix), 'base_prefix': str(base), 'action': action}


HELPER = r'''
import builtins, contextlib, io, json, os, re, runpy, sys, threading, types
from pathlib import Path
threading.Timer(300, lambda: os._exit(79)).start()
source = Path.cwd()
phase = 'run_path'
ensure_observation = {'status': 'not_reached', 'calls': 0, 'returns': 0,
                      'state': None, 'reason_code': None}
ensure_filename = None

def observe_ensure(frame, event, arg):
    try:
        if (frame.f_code.co_filename != ensure_filename
                or frame.f_code.co_name != 'ensure_gateway_runtime'):
            return
        if event == 'call':
            if ensure_observation['calls'] >= 2:
                ensure_observation['status'] = 'multiple_calls'
                return
            ensure_observation['calls'] += 1
            ensure_observation['status'] = ('observing' if ensure_observation['calls'] == 1
                                            else 'multiple_calls')
        elif event == 'return':
            if ensure_observation['returns'] >= ensure_observation['calls']:
                ensure_observation['status'] = 'observer_error'
                return
            ensure_observation['returns'] += 1
            if ensure_observation['status'] == 'multiple_calls':
                return
            if arg is None:
                ensure_observation['status'] = 'none_or_unwind'
                return
            module = sys.modules.get(frame.f_globals.get('__name__'))
            if type(module) is not types.ModuleType:
                ensure_observation['status'] = 'unexpected_return'
                return
            discovery_type = vars(module).get('GatewayDiscovery')
            if type(arg) is not discovery_type:
                ensure_observation['status'] = 'unexpected_return'
                return
            fields = object.__getattribute__(arg, '__dict__')
            if type(fields) is not dict or 'state' not in fields or 'reason_code' not in fields:
                ensure_observation['status'] = 'unexpected_return'
                return
            state, reason = fields['state'], fields['reason_code']
            ensure_observation['state'] = (state if type(state) is str and state in {
                'absent', 'starting', 'ready', 'draining', 'incompatible', 'inaccessible', 'conflict'
            } else 'unrecognized')
            ensure_observation['reason_code'] = (reason if reason is None or
                (type(reason) is str and reason in {
                    'authorization', 'runtime_exited', 'runtime_start_failed', 'deadline',
                    'control_timeout', 'invalid_control_peer', 'unsafe_control_path',
                    'unsafe_control_permissions', 'unsafe_control_pointer', 'invalid_control_pointer',
                    'unsafe_control_peer', 'profile_mismatch', 'profile_parked',
                    'invalid_runtime_state', 'runtime_protocol', 'session_authority_unavailable',
                    'update_paused'
                }) else 'unrecognized')
            ensure_observation['status'] = 'returned'
    except BaseException:
        ensure_observation['status'] = 'observer_error'

def ensure_gateway_bootstrap(bootstrap):
    global ensure_filename
    previous_profiler = sys.getprofile()
    assert previous_profiler is None, 'qualification helper already has a profiler'
    ensure_filename = str((source / 'hermes_cli/gateway_runtime.py').resolve())
    ensure_observation['status'] = 'observing'
    sys.setprofile(observe_ensure)
    try:
        return bootstrap['bootstrap'](True)
    finally:
        sys.setprofile(previous_profiler)
        if ensure_observation['status'] == 'observing':
            ensure_observation['status'] = ('no_matching_call' if ensure_observation['calls'] == 0
                                            else 'no_return')

def safe_frames(exc):
    rows = []
    frame = exc.__traceback__
    while frame is not None and len(rows) < 8:
        code = frame.tb_frame.f_code
        raw = code.co_filename
        if raw in {'<string>', '<stdin>'}:
            filename = '<helper>'
        else:
            try:
                filename = Path(raw).resolve().relative_to(source).as_posix()
            except (OSError, RuntimeError, ValueError):
                filename = None
        function = code.co_name
        if not isinstance(function, str) or not re.fullmatch(r'[A-Za-z0-9_<>.-]{1,80}', function):
            function = '<function>'
        line = frame.tb_lineno
        if (filename is not None and len(filename) <= 180
                and type(line) is int and line > 0):
            rows.append({'file': filename, 'function': function, 'line': line})
        frame = frame.tb_next
    return rows

try:
    phase = 'run_path'
    source = Path(sys.argv[1]).resolve()
    expected_sha = sys.argv[2]
    home = Path(os.environ['HERMES_HOME']).resolve()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        bootstrap = runpy.run_path(str(source / 'ui-tui/scripts/gateway_bootstrap.py'))
        phase = 'bootstrap'
        grant = ensure_gateway_bootstrap(bootstrap)
        phase = 'imports'
        from hermes_cli.gateway_runtime_discovery import query_identify
        from hermes_cli.gateway_runtime import _endpoint
        from gateway.status import get_process_start_time

    def receipt():
        global phase
        phase = 'query_identify'
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            identity = query_identify(home, timeout=5)
            phase = 'endpoint'
            discovery = _endpoint(identity, home, home)
            phase = 'identity_validation'
            assert discovery.state == 'ready' and discovery.endpoint is not None
            endpoint = discovery.endpoint
            assert endpoint.control_home == str(home)
            assert identity['hermes_home'] == str(home) and identity['code_sha'] == expected_sha
            assert type(identity['pid']) is int and identity['pid'] > 0
            assert type(identity['start_time']) is int and identity['start_time'] > 0
            assert get_process_start_time(identity['pid']) == identity['start_time']
            return {'url': endpoint.api_origin.replace('http://', 'ws://', 1) + '/api/ws',
                    'profile_id': endpoint.profile_id, 'instance_id': endpoint.instance_id,
                    'pid': identity['pid'], 'start_time': identity['start_time'],
                    'hermes_home': identity['hermes_home'], 'code_sha': identity['code_sha']}

    original = receipt()
    phase = 'grant_validation'
    assert {key: grant[key] for key in ('url', 'profile_id', 'instance_id')} == {
        key: original[key] for key in ('url', 'profile_id', 'instance_id')}
    assert isinstance(grant.get('protocols'), list) and len(grant['protocols']) == 2
    del grant
    print(json.dumps(original, sort_keys=True), flush=True)
    phase = 'command'
    for command in sys.stdin:
        if command.strip() == 'verify':
            phase = 'verify'
            current = receipt()
            phase = 'verify'
            assert current == original
            print(json.dumps(current, sort_keys=True), flush=True)
        elif command.strip() == 'close':
            break
        else:
            phase = 'command'
            raise ValueError('unknown qualification command')
except BaseException as exc:
    try:
        exception_class = type(exc)
        exception_type = (exception_class.__name__
                          if getattr(builtins, exception_class.__name__, None) is exception_class else 'Exception')
        diagnostic = {'error': 'native gateway qualification failed', 'phase': phase,
                      'exception_type': exception_type, 'frames': safe_frames(exc),
                      'ensure': dict(ensure_observation)}
        print(json.dumps(diagnostic, sort_keys=True), flush=True)
    except BaseException:
        print('{"error":"native gateway qualification failed"}', flush=True)
    finally:
        # Keep any newly spawned daemon discoverable until the owning driver cleans its tree.
        try:
            for command in sys.stdin:
                if command.strip() == 'close':
                    break
        finally:
            os._exit(78)
os._exit(0)
'''


def gateway_target(value):
    """Accept the native literal endpoint, without aliases, normalization or credentials."""
    import re

    match = re.fullmatch(r'ws://127\.0\.0\.1:([1-9][0-9]{0,4})/api/ws', value or '')
    assert match and int(match[1]) <= 65535, 'unexpected native gateway endpoint'
    return '127.0.0.1', int(match[1])


def validate_canonical_gateway(receipt, ui_driver_identity, *, home, revision, python, python_base):
    """Validate a sibling client's grant without adopting the original driver's processes."""
    import math
    import psutil
    import socket

    assert type(receipt) is dict and set(receipt) == {
        'url', 'profile_id', 'instance_id', 'pid', 'start_time', 'hermes_home', 'code_sha',
        'owner_birthtime', 'owner_exe', 'helper_identity'}, 'invalid canonical gateway receipt'
    assert type(ui_driver_identity) is dict and set(ui_driver_identity) == {
        'pid', 'birthtime', 'exe', 'launcher_pid', 'launcher_birthtime', 'launcher_exe',
        'parent_pid', 'parent_birthtime', 'parent_exe'}, 'invalid original UI driver identity'
    assert type(receipt['url']) is str, 'invalid canonical gateway URL'
    target = gateway_target(receipt['url'])
    assert receipt['hermes_home'] == str(Path(home).resolve()), 'canonical gateway home changed'
    assert type(revision) is str and re.fullmatch(r'[0-9a-f]{40}', revision)
    assert receipt['code_sha'] == revision, 'canonical gateway revision changed'
    for key in ('profile_id', 'instance_id'):
        value = receipt[key]
        assert type(value) is str and value and value == value.strip() and not any(
            ord(char) < 32 for char in value), 'invalid canonical gateway ' + key
    assert type(receipt['start_time']) is int and receipt['start_time'] > 0
    allowed = {str(Path(python).resolve()), str(Path(python).with_name('pythonw.exe').resolve()),
               str(Path(python_base).resolve())}

    def identity(pid, birth, exe):
        assert type(pid) is int and pid > 0, 'invalid canonical process PID'
        assert type(birth) in (int, float) and math.isfinite(birth) and birth > 0, (
            'invalid canonical process birthtime')
        assert type(exe) is str and str(Path(exe).resolve()) == exe and exe in allowed, (
            'unexpected canonical process executable')
        return pid, birth, exe

    ui = identity(ui_driver_identity['pid'], ui_driver_identity['birthtime'], ui_driver_identity['exe'])
    for prefix in ('launcher_', 'parent_'):
        assert type(ui_driver_identity[prefix + 'pid']) is int and ui_driver_identity[prefix + 'pid'] > 0
        birth = ui_driver_identity[prefix + 'birthtime']
        assert type(birth) in (int, float) and math.isfinite(birth) and birth > 0
        assert type(ui_driver_identity[prefix + 'exe']) is str and ui_driver_identity[prefix + 'exe']
    helper = receipt['helper_identity']
    assert type(helper) in (list, tuple) and len(helper) == 3, 'invalid gateway helper identity'
    helper = identity(*helper)
    owner = identity(receipt['pid'], receipt['owner_birthtime'], receipt['owner_exe'])
    assert len({ui[0], helper[0], owner[0]}) == 3, 'canonical process identities overlap'

    def current(process):
        return process.pid, process.create_time(), str(Path(process.exe()).resolve())

    ui_process, helper_process, owner_process = (psutil.Process(row[0]) for row in (ui, helper, owner))
    assert current(ui_process) == ui and current(helper_process) == helper and current(owner_process) == owner, (
        'canonical process identity changed')
    launcher = identity(ui_driver_identity['launcher_pid'], ui_driver_identity['launcher_birthtime'],
                        ui_driver_identity['launcher_exe'])
    assert current(psutil.Process(launcher[0])) == launcher, 'original UI launcher identity changed'
    assert launcher == ui or launcher in [current(process) for process in ui_process.parents()], (
        'original UI is not owned by its retained launcher')
    assert ui in [current(process) for process in helper_process.parents()], 'gateway helper is not owned by original UI'
    assert helper in [current(process) for process in owner_process.parents()], 'gateway owner is not owned by helper'
    assert any(connection.family == socket.AF_INET and connection.type == socket.SOCK_STREAM
               and connection.status == psutil.CONN_LISTEN
               and (connection.laddr.ip, connection.laddr.port) == target
               for connection in owner_process.net_connections(kind='tcp')), 'gateway owner does not own exact listener'
    return target


def verify_canonical_gateway_identity(receipt, *, home, timeout):
    """Bind an already-owned receipt to current native private-control discovery."""
    from hermes_cli.gateway_runtime_discovery import query_identify
    from hermes_cli.gateway_runtime import _endpoint
    from gateway.status import get_process_start_time

    identity = query_identify(home, timeout=timeout)
    assert type(identity) is dict and type(identity.get('pid')) is int and type(identity.get('start_time')) is int, (
        'invalid canonical gateway native identity')
    discovery = _endpoint(identity, home, home)
    assert discovery.state == 'ready' and discovery.endpoint is not None, 'canonical gateway is not ready'
    endpoint = discovery.endpoint
    assert endpoint.control_home == str(home), 'canonical gateway control home changed'
    keys = ('pid', 'start_time', 'hermes_home', 'code_sha')
    assert {key: identity[key] for key in keys} == {key: receipt[key] for key in keys}, (
        'canonical gateway native identity changed')
    assert get_process_start_time(receipt['pid']) == receipt['start_time'], 'canonical gateway start time changed'
    assert (endpoint.profile_id, endpoint.instance_id,
            endpoint.api_origin.replace('http://', 'ws://', 1) + '/api/ws') == (
                receipt['profile_id'], receipt['instance_id'], receipt['url']), (
                    'canonical gateway native endpoint changed')


def gateway_guard_witness(path: Path, receipt: dict, guard: dict):
    if not path.exists():
        return []
    matching = [row for line in path.read_text(encoding='utf-8').splitlines()
                if (row := json.loads(line))['pid'] == receipt['pid']
                and row['birthtime'] == receipt['owner_birthtime']]
    assert all(row['path'] == guard['path'] and row['sha256'] == guard['sha256']
               and row['socket_guard_active'] is True for row in matching), matching
    return matching


_GATEWAY_ERROR_PHASES = frozenset({
    'run_path', 'bootstrap', 'imports', 'query_identify', 'endpoint',
    'identity_validation', 'grant_validation', 'verify', 'command',
})
_GATEWAY_ERROR_STATES = frozenset({
    'absent', 'starting', 'ready', 'draining', 'incompatible', 'inaccessible', 'conflict',
})
_GATEWAY_ERROR_REASONS = frozenset({
    'authorization', 'runtime_exited', 'runtime_start_failed', 'deadline', 'control_timeout',
    'invalid_control_peer', 'unsafe_control_path', 'unsafe_control_permissions',
    'unsafe_control_pointer', 'invalid_control_pointer', 'unsafe_control_peer',
    'profile_mismatch', 'profile_parked', 'invalid_runtime_state', 'runtime_protocol',
    'session_authority_unavailable', 'update_paused',
})
_GATEWAY_ENSURE_STATUSES = frozenset({
    'not_reached', 'observing', 'returned', 'none_or_unwind', 'unexpected_return', 'multiple_calls',
    'no_matching_call', 'no_return', 'observer_error',
})
_BUILTIN_EXCEPTION_NAMES = frozenset(
    name for name in dir(builtins)
    if isinstance(getattr(builtins, name), type)
    and issubclass(getattr(builtins, name), BaseException)
)


def _valid_gateway_error(result):
    if (type(result) is not dict
            or set(result) != {'error', 'phase', 'exception_type', 'frames', 'ensure'}
            or result.get('error') != 'native gateway qualification failed'):
        return False
    phase, exception_type = result.get('phase'), result.get('exception_type')
    if (type(phase) is not str or phase not in _GATEWAY_ERROR_PHASES
            or type(exception_type) is not str
            or exception_type not in (_BUILTIN_EXCEPTION_NAMES | {'Exception'})):
        return False
    frames = result.get('frames')
    if type(frames) is not list or not 1 <= len(frames) <= 8:
        return False
    for frame in frames:
        if type(frame) is not dict or set(frame) != {'file', 'function', 'line'}:
            return False
        filename, function, line = frame['file'], frame['function'], frame['line']
        if (not isinstance(filename, str) or not filename or len(filename) > 180
                or not isinstance(function, str) or not re.fullmatch(r'[A-Za-z0-9_<>.-]{1,80}', function)
                or type(line) is not int or line <= 0):
            return False
        if filename != '<helper>' and (
                filename.startswith(('/', '\\')) or '\\' in filename or ':' in filename
                or any(part in {'', '.', '..'} for part in filename.split('/'))
                or any(ord(char) < 32 for char in filename)):
            return False
    ensure = result.get('ensure')
    if (type(ensure) is not dict
            or set(ensure) != {'status', 'calls', 'returns', 'state', 'reason_code'}
            or type(ensure.get('status')) is not str
            or ensure['status'] not in _GATEWAY_ENSURE_STATUSES
            or type(ensure.get('calls')) is not int or not 0 <= ensure['calls'] <= 2
            or type(ensure.get('returns')) is not int or not 0 <= ensure['returns'] <= ensure['calls']):
        return False
    state, reason = ensure.get('state'), ensure.get('reason_code')
    if (state is not None and (type(state) is not str or state not in (_GATEWAY_ERROR_STATES | {'unrecognized'}))):
        return False
    if (reason is not None
            and (type(reason) is not str or reason not in (_GATEWAY_ERROR_REASONS | {'unrecognized'}))):
        return False
    return True


class OwnedGateway:
    def __init__(self, python: Path, source: Path, env: dict, artifacts: Path, tree, revision: str,
                 *, python_base: Path, python_base_sha256: str):
        assert type(python_base_sha256) is str and re.fullmatch(
            r'[0-9a-fA-F]{64}', python_base_sha256), 'explicit base Python SHA-256 is required'
        base_path = Path(python_base)
        assert base_path.is_absolute(), 'pinned base Python path must be absolute'
        assert base_path.is_file() and not base_path.is_symlink(), 'pinned base Python must be a regular file'
        current = base_path
        while current != current.parent:
            assert not current.is_symlink() and not (hasattr(current, 'is_junction') and current.is_junction()), \
                'pinned base Python path must not contain an alias'
            current = current.parent
        python_base = base_path.resolve(strict=True)
        assert python_base == base_path, 'pinned base Python path must be canonical'
        assert hashlib.sha256(python_base.read_bytes()).hexdigest().lower() == python_base_sha256.lower(), \
            'pinned base Python identity changed'
        self.tree, self.artifacts = tree, artifacts
        self.replies = queue.Queue()
        self.proc = subprocess.Popen([str(python), '-c', HELPER, str(source), revision],
                                     env=env, cwd=source, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, encoding='utf-8')
        helper = tree.psutil.Process(self.proc.pid)
        self.helper_identity = (helper.pid, helper.create_time(), str(Path(helper.exe()).resolve()))
        tree.record(helper)

        def read():
            while True:
                line = self.proc.stdout.readline(65537)
                if not line or len(line) > 65536:
                    self.replies.put(None)
                    return
                try:
                    self.replies.put(json.loads(line))
                except (ValueError, TypeError):
                    self.replies.put(None)
                    return

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        receipt = self.receive()
        assert type(receipt.get('pid')) is int and receipt['pid'] > 0
        owner = tree.psutil.Process(receipt['pid'])
        # A matching private profile is identity; this live parent chain proves ownership.
        assert any((p.pid, p.create_time(), str(Path(p.exe()).resolve())) == self.helper_identity
                   for p in owner.parents()), 'gateway is not a child of this owned bootstrap'
        tree.record(owner)
        self.owner_identity = (owner.pid, owner.create_time(), str(Path(owner.exe()).resolve()))
        self.receipt = receipt
        gateway_target(receipt.get('url'))
        assert receipt['hermes_home'] == str(Path(env['HERMES_HOME']).resolve())
        assert receipt['code_sha'] == revision
        assert Path(owner.exe()).resolve() in {
            python.resolve(), python.with_name('pythonw.exe').resolve(), python_base,
        }
        assert all(isinstance(receipt.get(key), str) and receipt[key] for key in ('profile_id', 'instance_id'))
        self.save('gateway-before.json')

    def receive(self):
        try:
            result = self.replies.get(timeout=65)
        except queue.Empty:
            raise AssertionError('native gateway qualification helper timed out') from None
        if type(result) is dict and 'error' in result:
            if _valid_gateway_error(result):
                with (self.artifacts / 'gateway-error.json').open('x', encoding='utf-8') as stream:
                    json.dump(result, stream, sort_keys=True, indent=2)
                ensure = result['ensure']
                if (result['phase'] == 'bootstrap' and ensure['status'] == 'returned'
                        and ensure['calls'] == 1 and ensure['returns'] == 1
                        and ensure['state'] == 'draining' and ensure['reason_code'] is None):
                    # Let the observed native draining teardown progress before owner-tree cleanup.
                    try:
                        time.sleep(30)
                    except BaseException:
                        pass
            raise AssertionError('native gateway qualification helper failed') from None
        if (type(result) is not dict or set(result) != {
                'url', 'profile_id', 'instance_id', 'pid', 'start_time', 'hermes_home', 'code_sha'}):
            raise AssertionError('native gateway qualification helper returned invalid receipt') from None
        return result

    def save(self, name):
        with (self.artifacts / name).open('x', encoding='utf-8') as stream:
            json.dump({**self.receipt, 'owner_birthtime': self.owner_identity[1],
                       'owner_exe': self.owner_identity[2], 'helper_identity': self.helper_identity},
                      stream, sort_keys=True, indent=2)

    def verify(self):
        self.proc.stdin.write('verify\n')
        self.proc.stdin.flush()
        assert self.receive() == self.receipt, 'native TUI changed its gateway owner'
        owner = self.tree.psutil.Process(self.owner_identity[0])
        assert (owner.pid, owner.create_time(), str(Path(owner.exe()).resolve())) == self.owner_identity
        self.save('gateway-after.json')

    def release(self):
        self.proc.stdin.write('close\n')
        self.proc.stdin.flush()
        assert self.proc.wait(timeout=5) == 0, 'native gateway qualification helper did not exit normally'

    def close_pipes(self):
        self.reader.join(5)
        if self.reader.is_alive():
            raise RuntimeError('native gateway qualification reader remained alive after owned cleanup')
        try:
            self.proc.stdin.close()
        finally:
            self.proc.stdout.close()
