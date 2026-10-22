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
import builtins, contextlib, io, json, os, re, runpy, sys, threading
from pathlib import Path
threading.Timer(300, lambda: os._exit(79)).start()
source = Path.cwd()
phase = 'run_path'

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
        grant = bootstrap['bootstrap'](True)
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
                      'exception_type': exception_type, 'frames': safe_frames(exc)}
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
_BUILTIN_EXCEPTION_NAMES = frozenset(
    name for name in dir(builtins)
    if isinstance(getattr(builtins, name), type)
    and issubclass(getattr(builtins, name), BaseException)
)


def _valid_gateway_error(result):
    if (type(result) is not dict
            or set(result) != {'error', 'phase', 'exception_type', 'frames'}
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
    return True


class OwnedGateway:
    def __init__(self, python: Path, source: Path, env: dict, artifacts: Path, tree, revision: str):
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

        threading.Thread(target=read, daemon=True).start()
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
        assert Path(owner.exe()).resolve() in {python.resolve(), python.with_name('pythonw.exe').resolve()}
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

    def verify_and_release(self):
        self.proc.stdin.write('verify\n')
        self.proc.stdin.flush()
        assert self.receive() == self.receipt, 'native TUI changed its gateway owner'
        owner = self.tree.psutil.Process(self.owner_identity[0])
        assert (owner.pid, owner.create_time(), str(Path(owner.exe()).resolve())) == self.owner_identity
        self.save('gateway-after.json')
        self.proc.stdin.write('close\n')
        self.proc.stdin.flush()
        assert self.proc.wait(timeout=5) == 0, 'native gateway qualification helper did not exit normally'
        self.proc.stdin.close()
        self.proc.stdout.close()
