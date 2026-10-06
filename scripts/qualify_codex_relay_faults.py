"""Temporary, exact-delivery Codex hook fault harness (never enabled by config)."""
from __future__ import annotations

import hashlib
import argparse
import json
import math
import os
from pathlib import Path
import sys
import time
import types
import uuid
from typing import Any, Callable


MODES = {"claim-response-loss", "ack-precommit", "ack-response-loss"}


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


def wrap_hook(module: Any, manifest_path: str | Path,
              evidence_path: str | Path) -> Callable[[], None]:
    """Wrap module globals; return a finally-safe undo function."""
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
                return None if _record(evidence_file, "response_dropped", m["mode"], target) else response
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


def install_hooks(hooks_dir: str | Path, helper_path: str | Path, *,
                  mode: str, session_id: str, message_id: str,
                  expires_in: int, config_path: str | Path) -> None:
    root, helper, config = Path(hooks_dir).resolve(), Path(helper_path).resolve(), Path(config_path).resolve()
    _validate_install_root(root, helper)
    if mode not in MODES or not _bounded_identity(session_id) or not _bounded_identity(message_id):
        raise ValueError("invalid mode or exact recipient/message identity")
    if type(expires_in) is not int or not 1 <= expires_in <= 1800:
        raise ValueError("fault expiry must be 1..1800 seconds")
    targets = [root / name for name in HOOK_NAMES]
    record_path = root / INSTALL_RECORD
    manifest_path, evidence_path = root / FAULT_MANIFEST, root / EVIDENCE_FILE
    if any(path.exists() for path in (record_path, manifest_path, evidence_path,
                                      root / "fault-state", root / "fault-state.used",
                                      root / "fault-state.binding")):
        raise FileExistsError("fault harness files already exist; inspect and restore explicitly")
    for target in targets:
        if target.is_symlink() or not target.is_file():
            raise ValueError("both named installed hook files must be regular files")
    backups = [target.with_name(target.name + ".relay-fault-backup") for target in targets]
    if any(path.exists() for path in backups):
        raise FileExistsError("a retained hook backup already exists")
    fault = {"version": 1, "mode": mode, "session_id": session_id,
             "message_id": message_id, "expires_at": time.time() + expires_in,
             "state_path": str((root / "fault-state").resolve())}
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


def restore_hooks(hooks_dir: str | Path) -> None:
    root = Path(hooks_dir).resolve()
    if root.name != "hooks" or root.parent.name != "codex" or root.parent.parent.name != "integrations":
        raise ValueError("restore requires the exact installed integrations/codex/hooks directory")
    record_path = root / INSTALL_RECORD
    record = json.loads(record_path.read_text(encoding="utf-8"))
    config = Path(record["config_path"])
    if _config_hash(config) != record["config_sha256"]:
        raise RuntimeError("Codex hooks configuration changed; no target restored")
    entries = record.get("targets")
    if not isinstance(entries, list) or [Path(e["target"]).name for e in entries] != list(HOOK_NAMES):
        raise ValueError("invalid two-hook install record")
    for entry in entries:
        target, backup = Path(entry["target"]), Path(entry["backup"])
        if (target.parent != root or backup.parent != root
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
    install.add_argument("--mode", choices=sorted(MODES), required=True)
    install.add_argument("--session-id", required=True)
    install.add_argument("--message-id", required=True)
    install.add_argument("--expires-in", type=int, required=True)
    restore = sub.add_parser("restore", help="restore only untouched generated wrappers")
    restore.add_argument("--hooks-dir", required=True)
    args = parser.parse_args()
    try:
        if args.command == "install":
            helper = Path(__file__).resolve()
            root = Path(args.hooks_dir).resolve()
            config = Path.home() / ".codex" / "hooks.json"
            install_hooks(root, helper, mode=args.mode, session_id=args.session_id,
                          message_id=args.message_id, expires_in=args.expires_in,
                          config_path=config)
        else:
            restore_hooks(args.hooks_dir)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"relay fault harness: {type(exc).__name__}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
