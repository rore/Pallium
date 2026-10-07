"""Temporary, exact-delivery Codex hook fault harness (never enabled by config)."""
from __future__ import annotations

import hashlib
import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import threading
import time
import types
import uuid
from typing import Any, Callable


MODES = {"claim-response-loss", "ack-precommit", "ack-response-loss", "observe"}
OBSERVE_EVENT_LIMIT = 64
OBSERVE_BYTES_LIMIT = 16 * 1024
OBSERVE_APPEND_WAIT_SECONDS = 0.05
_DELIVERY_ID = re.compile(r"relay-delivery-[0-9a-f]{32}")


def _read_manifest(path: Path, session_id: object, now: float) -> dict[str, Any] | None:
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
        expected = {"version", "mode", "session_id", "message_id", "expires_at", "state_path"}
        expiry = m.get("expires_at") if isinstance(m, dict) else None
        state_path = Path(m["state_path"]) if isinstance(m, dict) and isinstance(m.get("state_path"), str) else None
        if (not isinstance(m, dict) or set(m) != expected or m.get("version") != 1
                or m.get("mode") not in MODES
                or not _bounded_identity(m.get("session_id"))
                or not _bounded_identity(m.get("message_id"))
                or type(expiry) not in (int, float) or not math.isfinite(expiry)
                or not now < expiry <= now + 1800 or m["session_id"] != session_id
                or state_path is None or not state_path.is_absolute()
                or state_path.parent.resolve() != path.parent.resolve()
                or state_path.name != "fault-state"):
            return None
        return m
    except (OSError, ValueError, TypeError, RuntimeError):
        return None


def _bounded_identity(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 128 and all(
        ord(char) >= 0x20 and ord(char) != 0x7f for char in value
    )


def _create_once(path: Path, metadata: dict[str, Any]) -> bool:
    """O_EXCL claim independent of common.py's per-session lock."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(metadata, stream, separators=(",", ":"))
        return True
    except (OSError, TypeError, ValueError):
        return False


def _record(path: Path, event: str, mode: str, delivery_id: str | None = None,
            lease_expires_at: str | None = None) -> bool:
    # A private append-only metadata ledger; never includes payload or claim token.
    try:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": event, "mode": mode,
                "delivery_id": delivery_id, "lease_expires_at": lease_expires_at,
                "at": time.time()}, separators=(",", ":")) + "\n")
        return True
    except (OSError, TypeError, ValueError):
        return False


def _append_observation(path: Path, snapshot: bytes) -> bool:
    try:
        with path.open("ab") as stream:
            return stream.write(snapshot) == len(snapshot) and (stream.flush() is None)
    except (OSError, ValueError):
        return False


def _result_class(value: object) -> str:
    if value is None:
        return "none"
    return "dict" if isinstance(value, dict) else "other"


class _Observation:
    def __init__(self, module: Any, manifest: dict[str, Any], evidence: Path):
        name = Path(str(getattr(module, "__file__", ""))).name
        self.hook = {"session_start.py": "session_start",
                     "user_prompt_submit.py": "user_prompt_submit"}.get(name, "unknown")
        self.message_id = manifest["message_id"]
        self.evidence = evidence
        self.events: list[dict[str, Any]] = []
        self.size = 0
        self.overflow = False
        self.target_seen = False
        self.delivery_id: str | None = None
        self.formatted = False
        self.assignments: list[tuple[Any, str, Any, Any]] = []
        self.finished = False
        self.restore_failed = False

    def event(self, stage: str, outcome: str, *, target: bool | None = None,
              delivery_id: str | None = None, elapsed: int | None = None) -> None:
        try:
            item = {"event": "codex_relay_observation", "hook": self.hook,
                    "stage": stage, "outcome": outcome, "target_present": target,
                    "delivery_id": delivery_id, "elapsed_ms": elapsed,
                    "at": time.time()}
            size = len(json.dumps(item, separators=(",", ":")).encode("utf-8")) + 1
            if (len(self.events) >= OBSERVE_EVENT_LIMIT
                    or self.size + size > OBSERVE_BYTES_LIMIT):
                self.overflow = True
                return
            self.events.append(item)
            self.size += size
        except Exception:
            self.overflow = True

    def target_in(self, value: object) -> bool:
        try:
            return bool(self.delivery_id) and isinstance(value, list) and any(
                isinstance(item, dict) and item.get("message_id") == self.message_id
                and item.get("delivery_id") == self.delivery_id for item in value
            )
        except Exception:
            return False

    def observed_response(self, response: object) -> bool:
        found = False
        try:
            deliveries = response.get("deliveries") if isinstance(response, dict) else None
            if isinstance(deliveries, list):
                for item in deliveries:
                    if isinstance(item, dict) and item.get("message_id") == self.message_id:
                        found = True
                        value = item.get("delivery_id")
                        if isinstance(value, str) and _DELIVERY_ID.fullmatch(value):
                            self.delivery_id = value
                        break
        except Exception:
            return False
        self.target_seen = self.target_seen or found
        return found

    def patch(self, obj: Any, attr: str, replacement: Any) -> None:
        old = getattr(obj, attr)
        self.assignments.append((obj, attr, old, replacement))
        setattr(obj, attr, replacement)

    def restore(self) -> bool:
        ok = True
        for obj, attr, old, _replacement in reversed(self.assignments):
            try:
                setattr(obj, attr, old)
            except Exception:
                ok = False
        self.restore_failed = self.restore_failed or not ok
        self.assignments.clear()
        return ok

    def finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        try:
            restored = self.restore()
        except Exception:
            restored = False
        self.event("observer_finished", "captured" if restored and not self.restore_failed and not self.overflow
                   else "incomplete", target=self.target_seen,
                   delivery_id=self.delivery_id)
        try:
            snapshot = b"".join(
                json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
                for item in self.events
            )
            if len(snapshot) > OBSERVE_BYTES_LIMIT:
                return
            done = threading.Event()
            def append() -> None:
                try:
                    _append_observation(self.evidence, snapshot)
                except BaseException:
                    pass
                finally:
                    done.set()
            worker = threading.Thread(
                target=append,
                name="codex-relay-observer-ledger", daemon=True,
            )
            worker.start()
            done.wait(OBSERVE_APPEND_WAIT_SECONDS)
        except Exception:
            pass


def _wrap_observer(module: Any, manifest_file: Path,
                   evidence_file: Path) -> Callable[[], None]:
    common = module._common
    old_turn = module.relay_turn
    observer: _Observation | None = None

    def turn(runtime: str, session_id: object, *args: Any, **kwargs: Any) -> Any:
        nonlocal observer
        m = _read_manifest(manifest_file, session_id, time.time())
        if m is None or m["mode"] != "observe" or observer is not None:
            return old_turn(runtime, session_id, *args, **kwargs)
        used = Path(m["state_path"] + ".used")
        if not _create_once(used, {"mode": "observe", "message_id": m["message_id"]}):
            return old_turn(runtime, session_id, *args, **kwargs)

        try:
            obs = _Observation(module, m, evidence_file)
        except Exception:
            return old_turn(runtime, session_id, *args, **kwargs)
        observer = obs
        # The wrapper itself is also part of the transactional patch set so the
        # original alias is restored before any evidence append is attempted.
        obs.assignments.append((module, "relay_turn", old_turn, turn))
        started = time.monotonic()
        try:
            old_request = common.relay_request
            old_writer = common._write_session_state_locked
            old_format = module.format_relay
            old_emit_context = module.emit_context
            old_ack = module.acknowledge_relay
            old_common_emit = common.emit_utf8
            old_module_emit = getattr(module, "emit_utf8", None)

            def observe_request(original: Callable[..., Any]) -> Callable[..., Any]:
                def request(method: str, path: str, body: Any, *a: Any, **kw: Any) -> Any:
                    began = time.monotonic()
                    try:
                        response = original(method, path, body, *a, **kw)
                    except BaseException:
                        if method == "POST" and path == "/relay/turn":
                            obs.event("relay_response", "exception", target=False,
                                      elapsed=min(60000, int((time.monotonic() - began) * 1000)))
                        raise
                    if method == "POST" and path == "/relay/turn":
                        target = obs.observed_response(response)
                        obs.event("relay_response", _result_class(response), target=target,
                                  delivery_id=obs.delivery_id if target else None,
                                  elapsed=min(60000, int((time.monotonic() - began) * 1000)))
                    return response
                return request

            def state_writer(session: str, state: dict[str, Any]) -> bool:
                if session != session_id:
                    return old_writer(session, state)
                obs.event("state_write_before", "called", target=obs.target_seen,
                          delivery_id=obs.delivery_id)
                began = time.monotonic()
                try:
                    result = old_writer(session, state)
                except BaseException:
                    obs.event("state_write_after", "exception", target=obs.target_seen,
                              delivery_id=obs.delivery_id,
                              elapsed=min(60000, int((time.monotonic() - began) * 1000)))
                    raise
                obs.event("state_write_after", "true" if result is True else "false",
                          target=obs.target_seen, delivery_id=obs.delivery_id,
                          elapsed=min(60000, int((time.monotonic() - began) * 1000)))
                return result

            def format_relay(deliveries: Any, *a: Any, **kw: Any) -> Any:
                target = obs.target_in(deliveries) and obs.target_seen
                began = time.monotonic()
                try:
                    result = old_format(deliveries, *a, **kw)
                except BaseException:
                    obs.event("format_relay", "exception", target=target,
                              delivery_id=obs.delivery_id if target else None,
                              elapsed=min(60000, int((time.monotonic() - began) * 1000)))
                    raise
                try:
                    rendered = result[1] if isinstance(result, tuple) and len(result) > 1 else None
                    obs.formatted = obs.target_in(rendered) and obs.target_seen
                except Exception:
                    obs.formatted = False
                obs.event("format_relay", _result_class(result), target=obs.formatted,
                          delivery_id=obs.delivery_id if obs.formatted else None,
                          elapsed=min(60000, int((time.monotonic() - began) * 1000)))
                return result

            def emit_context(text: str, event_name: str) -> Any:
                began = time.monotonic()
                try:
                    result = old_emit_context(text, event_name)
                except BaseException:
                    obs.event("emit_context", "exception", target=obs.formatted,
                              delivery_id=obs.delivery_id if obs.formatted else None,
                              elapsed=min(60000, int((time.monotonic() - began) * 1000)))
                    raise
                obs.event("emit_context", _result_class(result), target=obs.formatted,
                          delivery_id=obs.delivery_id if obs.formatted else None,
                          elapsed=min(60000, int((time.monotonic() - began) * 1000)))
                return result

            def wrap_utf8(original: Callable[..., Any]) -> Callable[..., Any]:
                def emit_utf8(*args: Any, **kwargs: Any) -> Any:
                    began = time.monotonic()
                    try:
                        result = original(*args, **kwargs)
                    except BaseException:
                        obs.event("emit_utf8", "exception", target=obs.formatted,
                                  delivery_id=obs.delivery_id if obs.formatted else None,
                                  elapsed=min(60000, int((time.monotonic() - began) * 1000)))
                        raise
                    obs.event("emit_utf8", "true" if result is True else "false",
                              target=obs.formatted,
                              delivery_id=obs.delivery_id if obs.formatted else None,
                              elapsed=min(60000, int((time.monotonic() - began) * 1000)))
                    return result
                return emit_utf8

            def acknowledge(deliveries: list[dict], *, container_ref: str) -> Any:
                try:
                    target = bool(obs.delivery_id) and isinstance(deliveries, list) and any(
                        isinstance(item, dict) and item.get("delivery_id") == obs.delivery_id
                        and item.get("message_id") == obs.message_id for item in deliveries
                    )
                except Exception:
                    target = False
                began = time.monotonic()
                try:
                    result = old_ack(deliveries, container_ref=container_ref)
                except BaseException:
                    obs.event("acknowledge_relay", "exception", target=target,
                              delivery_id=obs.delivery_id if target else None,
                              elapsed=min(60000, int((time.monotonic() - began) * 1000)))
                    raise
                try:
                    confirmed = target and isinstance(result, list) and any(
                        isinstance(item, dict) and item.get("delivery_id") == obs.delivery_id
                        and item.get("message_id") == obs.message_id for item in result
                    )
                except Exception:
                    confirmed = False
                obs.event("acknowledge_relay", "confirmed" if confirmed else "returned",
                          target=target, delivery_id=obs.delivery_id if target else None,
                          elapsed=min(60000, int((time.monotonic() - began) * 1000)))
                return result

            # Prepare every wrapper before the first assignment; finish() restores
            # even a partial assignment if an unusual module rejects a patch.
            explicit_request = kwargs.get("request")
            request_override = observe_request(explicit_request) if callable(explicit_request) else None
            if request_override is None:
                obs.patch(common, "relay_request", observe_request(old_request))
            obs.patch(common, "_write_session_state_locked", state_writer)
            obs.patch(common, "emit_utf8", wrap_utf8(old_common_emit))
            obs.patch(module, "format_relay", format_relay)
            obs.patch(module, "emit_context", emit_context)
            obs.patch(module, "acknowledge_relay", acknowledge)
            if old_module_emit is not None:
                obs.patch(module, "emit_utf8", wrap_utf8(old_module_emit))
            if request_override is not None:
                kwargs["request"] = request_override
            obs.event("relay_turn", "started", elapsed=min(60000, int((time.monotonic() - started) * 1000)))
        except BaseException:
            obs.event("relay_turn", "observer_setup_failed", target=False)
            if not obs.restore():
                obs.restore_failed = True
            try:
                return old_turn(runtime, session_id, *args, **kwargs)
            finally:
                obs.finish()

        try:
            result = old_turn(runtime, session_id, *args, **kwargs)
        except BaseException:
            obs.event("relay_turn", "exception", target=obs.target_seen,
                      delivery_id=obs.delivery_id,
                      elapsed=min(60000, int((time.monotonic() - started) * 1000)))
            raise
        obs.event("relay_turn", _result_class(result),
                  target=obs.target_seen, delivery_id=obs.delivery_id,
                  elapsed=min(60000, int((time.monotonic() - started) * 1000)))
        return result

    module.relay_turn = turn

    def undo() -> None:
        if observer is not None:
            observer.finish()
        try:
            module.relay_turn = old_turn
        except Exception:
            pass

    return undo


def wrap_hook(module: Any, manifest_path: str | Path,
              evidence_path: str | Path) -> Callable[[], None]:
    """Wrap module globals; return a finally-safe undo function."""
    try:
        raw = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raw = None
    if isinstance(raw, dict) and raw.get("mode") == "observe":
        return _wrap_observer(module, Path(manifest_path), Path(evidence_path))
    old_turn, old_ack = module.relay_turn, module.acknowledge_relay
    common = module._common
    old_request = common.relay_request
    manifest_file, evidence_file = Path(manifest_path), Path(evidence_path)
    reservation_suffix = ".used"

    def turn(runtime: str, session_id: object, *args: Any, **kwargs: Any) -> Any:
        module._pallium_fault_session_id = session_id
        m = _read_manifest(manifest_file, session_id, time.time())
        request = kwargs.get("request")
        if m is None or not callable(request):
            return old_turn(runtime, session_id, *args, **kwargs)

        def forwarded(method: str, path: str, body: Any, **options: Any) -> Any:
            response = request(method, path, body, **options)
            if (m["mode"] == "claim-response-loss" and method == "POST"
                    and path == "/relay/turn" and isinstance(response, dict)):
                deliveries = response.get("deliveries")
                for d in deliveries if isinstance(deliveries, list) else ():
                    if isinstance(d, dict) and d.get("message_id") == m["message_id"]:
                        used = Path(m["state_path"] + reservation_suffix)
                        if _create_once(used, {"mode": m["mode"],
                                "message_id": m["message_id"],
                                "delivery_id": d.get("delivery_id"),
                                "lease_expires_at": d.get("lease_expires_at")}):
                            if _record(evidence_file, "response_dropped", m["mode"],
                                       d.get("delivery_id"), d.get("lease_expires_at")):
                                return None
            return response

        kwargs["request"] = forwarded
        result = old_turn(runtime, session_id, *args, **kwargs)
        if isinstance(result, dict) and m["mode"] in {"ack-precommit", "ack-response-loss"}:
            for d in result.get("deliveries", []):
                if isinstance(d, dict) and d.get("message_id") == m["message_id"]:
                    binding = Path(m["state_path"] + ".binding")
                    _create_once(binding, {"message_id": m["message_id"],
                        "delivery_id": d.get("delivery_id"),
                        "lease_expires_at": d.get("lease_expires_at")})
        return result

    def ack(deliveries: list[dict], *, container_ref: str) -> list[dict]:
        # Scope is obtained from the actual hook's Relay turn state, not prompt text.
        session_id = getattr(module, "_pallium_fault_session_id", None)
        m = _read_manifest(manifest_file, session_id, time.time())
        if m is None or m["mode"] == "claim-response-loss":
            return old_ack(deliveries, container_ref=container_ref)
        try:
            binding = json.loads(Path(m["state_path"] + ".binding").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return old_ack(deliveries, container_ref=container_ref)
        target = binding.get("delivery_id")
        if (not _bounded_identity(target) or not target.startswith("relay-delivery-")
                or len(target) != 47 or binding.get("message_id") != m["message_id"]
                or not any(isinstance(d, dict) and d.get("delivery_id") == target
                           and d.get("message_id") == m["message_id"] for d in deliveries)):
            return old_ack(deliveries, container_ref=container_ref)
        used = Path(m["state_path"] + reservation_suffix)
        if not _create_once(used, {"mode": m["mode"], "delivery_id": target,
                                   "message_id": m["message_id"]}):
            return old_ack(deliveries, container_ref=container_ref)

        def request(method: str, path: str, body: Any, **options: Any) -> Any:
            if (method == "POST" and path == "/relay/deliveries/ack"
                    and isinstance(body, dict) and body.get("delivery_id") == target):
                if m["mode"] == "ack-precommit":
                    if _record(evidence_file, "request_suppressed", m["mode"], target):
                        return None
                    return old_request(method, path, body, **options)
                response = old_request(method, path, body, **options)
                if (isinstance(response, dict) and response.get("delivery_id") == target
                        and response.get("state") == "delivered"
                        and type(response.get("already_delivered")) is bool
                        and _record(evidence_file, "response_dropped", m["mode"], target)):
                    return None
                return response
            return old_request(method, path, body, **options)

        common.relay_request = request
        try:
            return old_ack(deliveries, container_ref=container_ref)
        finally:
            common.relay_request = old_request

    module.relay_turn, module.acknowledge_relay = turn, ack

    def undo() -> None:
        module.relay_turn, module.acknowledge_relay = old_turn, old_ack
        common.relay_request = old_request
    return undo


def run_backed_up_hook(source: str | Path, manifest: str | Path,
                       evidence: str | Path, *, original_path: str | Path | None = None) -> None:
    """Execute backup bytes with original __file__/argv/stdin; always unpatch."""
    backup = Path(source).resolve()
    original = Path(original_path).resolve() if original_path else backup
    code = backup.read_bytes()
    module = types.ModuleType("_codex_hook")
    module.__file__ = str(original)
    exec(compile(code, str(original), "exec"), module.__dict__, module.__dict__)
    # Suppress the source's __main__ stanza during setup; main sees the normal
    # script name and is invoked exactly once below.
    module.__name__ = "__main__"
    try:
        undo = wrap_hook(module, manifest, evidence)
    except Exception:
        module.__name__ = "__main__"
        module.main()
        return
    try:
        module.main()
    finally:
        undo()


def execute_target(target: str | Path, backup: str | Path,
                   manifest: str | Path, evidence: str | Path) -> None:
    """Use the installed target's path while executing retained original bytes."""
    run_backed_up_hook(backup, manifest, evidence, original_path=target)


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


HOOK_NAMES = ("session_start.py", "user_prompt_submit.py")
INSTALL_RECORD = ".relay-fault-install.json"
FAULT_MANIFEST = ".relay-fault-manifest.json"
EVIDENCE_FILE = ".relay-fault-evidence.jsonl"


def _atomic_write(path: Path, content: bytes, *, expected_hash: str | None = None) -> None:
    if expected_hash is not None and sha256(path) != expected_hash:
        raise RuntimeError("target changed; refusing atomic replacement")
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if expected_hash is not None and sha256(path) != expected_hash:
            raise RuntimeError("target changed; refusing atomic replacement")
        os.replace(temp, path)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _config_hash(path: Path) -> str | None:
    return sha256(path) if path.is_file() else None


def _shim(target: Path, backup: Path, helper: Path, manifest: Path, evidence: Path) -> bytes:
    # Import failure alone falls back to the retained original bytes. Once
    # execute_target begins, no exception path replays the hook.
    code = f'''import importlib.util\nfrom pathlib import Path\nT={str(target)!r}; B={str(backup)!r}; H={str(helper)!r}\nM={str(manifest)!r}; E={str(evidence)!r}\ns=importlib.util.spec_from_file_location("_codex_fault_helper", H)\ntry:\n m=importlib.util.module_from_spec(s); s.loader.exec_module(m)\nexcept Exception:\n n={{"__file__":T,"__name__":"_codex_hook"}}\n exec(compile(Path(B).read_bytes(), T, "exec"), n, n)\n n["__name__"]="__main__"; n["main"]()\nelse:\n m.execute_target(T, B, M, E)\n'''
    return code.encode("utf-8")


def _validate_install_root(root: Path, helper: Path) -> None:
    expected = helper.parent.parent / "integrations" / "codex" / "hooks"
    if (not root.is_absolute() or not helper.is_absolute()
            or root.name != "hooks" or root.parent.name != "codex"
            or root.parent.parent.name != "integrations"
            or ".codex" in root.parts or "worktrees" in root.parts
            or root != expected):
        raise ValueError("supply the absolute stable installed integrations/codex/hooks directory")


def _validate_control_dir(path: str | Path) -> Path:
    control = Path(path)
    if not control.is_absolute() or not control.is_dir() or control.is_symlink():
        raise ValueError("control-dir must be an existing absolute operator-provisioned private directory")
    info = control.stat()
    if getattr(info, "st_file_attributes", 0) & 0x400 or control.resolve() != control.absolute():
        raise ValueError("control-dir must not be a symlink or reparse point")
    return control.resolve()


def install_hooks(hooks_dir: str | Path, control_dir: str | Path,
                  helper_path: str | Path, *,
                  mode: str, session_id: str, message_id: str,
                  expires_in: int, config_path: str | Path) -> None:
    root, helper, config = Path(hooks_dir).resolve(), Path(helper_path).resolve(), Path(config_path).resolve()
    control = _validate_control_dir(control_dir)
    _validate_install_root(root, helper)
    if mode not in MODES or not _bounded_identity(session_id) or not _bounded_identity(message_id):
        raise ValueError("invalid mode or exact recipient/message identity")
    if type(expires_in) is not int or not 1 <= expires_in <= 1800:
        raise ValueError("fault expiry must be 1..1800 seconds")
    targets = [root / name for name in HOOK_NAMES]
    record_path = control / INSTALL_RECORD
    manifest_path, evidence_path = control / FAULT_MANIFEST, control / EVIDENCE_FILE
    if any(path.exists() for path in (record_path, manifest_path, evidence_path,
                                      control / "fault-state", control / "fault-state.used",
                                      control / "fault-state.binding")):
        raise FileExistsError("fault harness files already exist; inspect and restore explicitly")
    for target in targets:
        if target.is_symlink() or not target.is_file():
            raise ValueError("both named installed hook files must be regular files")
    backups = [control / (target.name + ".relay-fault-backup") for target in targets]
    if any(path.exists() for path in backups):
        raise FileExistsError("a retained hook backup already exists")
    fault = {"version": 1, "mode": mode, "session_id": session_id,
             "message_id": message_id, "expires_at": time.time() + expires_in,
             "state_path": str((control / "fault-state").resolve())}
    record = {"version": 1, "config_path": str(config), "helper": str(helper),
              "config_sha256": _config_hash(config), "targets": []}
    originals = [target.read_bytes() for target in targets]
    try:
        for target, backup, original in zip(targets, backups, originals):
            _atomic_write(backup, original)
        for target, backup in zip(targets, backups):
            shim = _shim(target, backup, helper, manifest_path, evidence_path)
            record["targets"].append({"target": str(target), "backup": str(backup),
                "original_sha256": hashlib.sha256(originals[len(record["targets"])]).hexdigest(),
                "shim_sha256": hashlib.sha256(shim).hexdigest()})
        _atomic_write(record_path, json.dumps(record, separators=(",", ":")).encode())
        _atomic_write(manifest_path, json.dumps(fault, separators=(",", ":")).encode())
        for entry in record["targets"]:
            target = Path(entry["target"])
            backup = Path(entry["backup"])
            if sha256(target) != entry["original_sha256"]:
                raise RuntimeError("hook changed during install; refusing to replace it")
            _atomic_write(target, _shim(target, backup, helper, manifest_path, evidence_path),
                          expected_hash=entry["original_sha256"])
    except BaseException:
        # Roll back only targets that still contain this exact generated shim.
        for entry in record["targets"]:
            target, backup = Path(entry["target"]), Path(entry["backup"])
            if target.is_file() and sha256(target) == entry["shim_sha256"] and sha256(backup) == entry["original_sha256"]:
                _atomic_write(target, backup.read_bytes())
        raise


def restore_hooks(hooks_dir: str | Path, control_dir: str | Path) -> None:
    root = Path(hooks_dir).resolve()
    control = _validate_control_dir(control_dir)
    if root.name != "hooks" or root.parent.name != "codex" or root.parent.parent.name != "integrations":
        raise ValueError("restore requires the exact installed integrations/codex/hooks directory")
    record_path = control / INSTALL_RECORD
    record = json.loads(record_path.read_text(encoding="utf-8"))
    helper = Path(record["helper"]).resolve()
    _validate_install_root(root, helper)
    config = Path(record["config_path"])
    if _config_hash(config) != record["config_sha256"]:
        raise RuntimeError("Codex hooks configuration changed; no target restored")
    entries = record.get("targets")
    if not isinstance(entries, list) or [Path(e["target"]).name for e in entries] != list(HOOK_NAMES):
        raise ValueError("invalid two-hook install record")
    for entry in entries:
        target, backup = Path(entry["target"]), Path(entry["backup"])
        if (target.parent != root or backup.parent != control
                or backup.name != target.name + ".relay-fault-backup"
                or sha256(target) not in {entry["shim_sha256"], entry["original_sha256"]}
                or sha256(backup) != entry["original_sha256"]):
            raise RuntimeError("hook or backup changed; no target restored")
    for entry in entries:
        target = Path(entry["target"])
        if sha256(target) == entry["shim_sha256"]:
            if sha256(target) != entry["shim_sha256"]:
                raise RuntimeError("hook changed during restore; refusing to replace it")
            _atomic_write(target, Path(entry["backup"]).read_bytes(),
                          expected_hash=entry["shim_sha256"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    install = sub.add_parser("install", help="install exact-session temporary wrappers; never changes hooks.json")
    install.add_argument("--hooks-dir", required=True)
    install.add_argument("--control-dir", required=True,
                         help="existing private-ACL directory; ACL is an operator precondition")
    install.add_argument("--mode", choices=sorted(MODES), required=True)
    install.add_argument("--session-id", required=True)
    install.add_argument("--message-id", required=True)
    install.add_argument("--expires-in", type=int, required=True)
    restore = sub.add_parser("restore", help="restore only untouched generated wrappers")
    restore.add_argument("--hooks-dir", required=True)
    restore.add_argument("--control-dir", required=True,
                         help="same existing private-ACL directory used for install")
    args = parser.parse_args()
    try:
        if args.command == "install":
            helper = Path(__file__).resolve()
            root = Path(args.hooks_dir).resolve()
            config = Path.home() / ".codex" / "hooks.json"
            install_hooks(root, args.control_dir, helper, mode=args.mode, session_id=args.session_id,
                          message_id=args.message_id, expires_in=args.expires_in,
                          config_path=config)
        else:
            restore_hooks(args.hooks_dir, args.control_dir)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"relay fault harness: {type(exc).__name__}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
