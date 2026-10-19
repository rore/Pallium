"""Run bounded probes against pinned, cached Hermes source functions.

This is source-function evidence only: it does not qualify the installed host,
profile isolation, or the complete provider-admission path.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import inspect
import json
import logging
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

PINNED = {
    "tools/registry.py": "4a05aae5b4dd40bf9a104d23582d4363326ad7ce3fdac1ac249e0af04334d909",
    "hermes_cli/middleware.py": "3745ad211f365554a3c070083dc39d3ff9b6cdc93965f13d8796918433ec2328",
}
_ABSENT = object()


class SourceError(ValueError):
    pass


def _read_pinned(root: Path) -> dict[str, tuple[Path, str]]:
    sources = {}
    for relative, expected in PINNED.items():
        path = root / relative
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise SourceError(f"missing pinned source {relative}: {exc}") from exc
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            raise SourceError(f"hash mismatch for {relative}: {actual}")
        sources[relative] = (path, raw.decode("utf-8"))
    return sources


def _find(tree: ast.Module, name: str, owner: str | None = None) -> ast.AST:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == (owner or name):
            if owner is None:
                return node
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == name:
                    return member
        if owner is None and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise SourceError(f"pinned source function not found: {owner + '.' if owner else ''}{name}")


def _extract(source: str, filename: Path, name: str, namespace: dict, owner: str | None = None):
    tree = ast.parse(source, filename=str(filename))
    node = _find(tree, name, owner)
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, str(filename), "exec"), namespace)
    return namespace[name]


class _FixtureManager:
    def __init__(self):
        self._middleware = {}
        self.failures = []
        self.module_restored = []

    def _report_hook_failure(self, *args, **kwargs):
        self.failures.append((args, kwargs))


def _with_manager(manager: _FixtureManager, callback: Callable[[], Any]) -> Any:
    key = "hermes_cli.plugins"
    module = types.ModuleType(key)
    module._delivery_manager = lambda: manager
    prior = sys.modules.get(key, _ABSENT)
    sys.modules[key] = module
    try:
        return callback()
    finally:
        if prior is _ABSENT:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = prior
        manager.module_restored.append(sys.modules.get(key, _ABSENT) is prior)


def run_qualification(source_root: Path) -> dict[str, Any]:
    sources = _read_pinned(source_root)
    reg_path, reg_source = sources["tools/registry.py"]
    mid_path, mid_source = sources["hermes_cli/middleware.py"]
    registry_ns = {
        "inspect": inspect, "Callable": Callable, "Optional": Optional,
        "logger": logging.getLogger("hermes-source-probe"),
        "_bound_error_text": str,
        "tool_error": lambda message: json.dumps({"error": message}),
    }
    _extract(reg_source, reg_path, "_kwargs_accepted_by", registry_ns)
    dispatch = _extract(reg_source, reg_path, "dispatch", registry_ns, "ToolRegistry")
    middleware_ns = {
        "Any": Any, "Callable": Callable,
        "OBSERVER_SCHEMA_VERSION": "hermes.observer.v1",
        "MIDDLEWARE_SCHEMA_VERSION": "hermes.middleware.v1",
        "LLM_EXECUTION_MIDDLEWARE": "llm_execution",
    }
    _extract(mid_source, mid_path, "middleware_payload", middleware_ns)
    _extract(mid_source, mid_path, "_DownstreamExecutionError", middleware_ns)
    _extract(mid_source, mid_path, "_run_execution_chain", middleware_ns)
    run_llm = _extract(mid_source, mid_path, "run_llm_execution_middleware", middleware_ns)

    seen = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def contextual(args, session_id=None, turn_id=None):
        barrier.wait(timeout=3)
        with lock:
            seen.append((args, session_id, turn_id))
        return "ok"

    entry = types.SimpleNamespace(handler=contextual, is_async=False)

    class RegistryFixture:
        def get_entry(self, name, scope=None):
            return entry

        def _normalize_handler_result(self, name, result):
            return result

    RegistryFixture.dispatch = dispatch
    registry = RegistryFixture()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(
            registry.dispatch, "capture",
            {"session_id": "forged-session", "turn_id": "forged-turn"},
            session_id=sid, turn_id=tid,
        ) for sid, tid in (("session-A", "turn-A"), ("session-B", "turn-B"))]
        results = [future.result(timeout=5) for future in futures]
    identity_ok = results == ["ok", "ok"] and len(seen) == 2 and all(
        item in seen for item in (
            ({"session_id": "forged-session", "turn_id": "forged-turn"}, "session-A", "turn-A"),
            ({"session_id": "forged-session", "turn_id": "forged-turn"}, "session-B", "turn-B"),
        )
    )

    missing = []

    def optional_context(args, session_id=None, turn_id=None):
        missing.append((session_id, turn_id))
        return "missing" if not session_id or not turn_id else "present"

    entry.handler = optional_context
    missing_none = registry.dispatch(
        "capture", {"session_id": "forged-session", "turn_id": "forged-turn"}
    ) == "missing"
    missing_empty = registry.dispatch(
        "capture", {"session_id": "forged-session", "turn_id": "forged-turn"},
        session_id="", turn_id="",
    ) == "missing"
    missing_ok = missing_none and missing_empty and missing == [(None, None), ("", "")]

    narrow_calls = []

    def narrow(args):
        narrow_calls.append(args)
        return "narrow-ok"

    entry.handler = narrow
    narrow_ok = registry.dispatch(
        "capture", {"x": 1}, session_id="extra", turn_id="extra"
    ) == "narrow-ok" and narrow_calls == [{"x": 1}]

    scenarios = {}
    manager = _FixtureManager()

    def chain(callbacks, terminal, payload, **context):
        manager._middleware = {"llm_execution": callbacks}
        return _with_manager(
            manager, lambda: run_llm(payload, terminal, **context)
        )

    initial = {
        "prompt": "original",
        "session_id": "forged-session",
        "turn_id": "forged-turn",
    }
    observed = []
    callback_ids = []

    def observer(request, next_call, **context):
        callback_ids.append((context.get("session_id"), context.get("turn_id")))
        observed.append(dict(request))
        return next_call()

    def rewrite(request, next_call, **context):
        callback_ids.append((context.get("session_id"), context.get("turn_id")))
        return next_call({**request, "prompt": "rewritten"})

    terminal_requests = []
    forwarded = chain(
        [observer, rewrite],
        lambda request: terminal_requests.append(request) or request,
        initial, session_id="trusted-session", turn_id="trusted-turn",
    )
    scenarios["llm_execution_forward_and_rewrite"] = (
        forwarded == {**initial, "prompt": "rewritten"}
        and terminal_requests == [{**initial, "prompt": "rewritten"}]
        and observed == [initial]
        and callback_ids == [("trusted-session", "trusted-turn")] * 2
    )

    terminal_calls = []
    short = chain(
        [lambda request, **context: "short-circuit"],
        lambda request: terminal_calls.append(request), initial,
        session_id="trusted-session", turn_id="trusted-turn",
    )
    scenarios["short_circuit_skips_terminal"] = short == "short-circuit" and not terminal_calls

    def fail_terminal(request):
        raise LookupError("downstream")

    try:
        chain(
            [lambda request, next_call, **context: next_call()],
            fail_terminal, initial, session_id="trusted-session", turn_id="trusted-turn",
        )
        downstream_propagates = False
    except LookupError as exc:
        downstream_propagates = str(exc) == "downstream"
    scenarios["downstream_exception_propagates"] = downstream_propagates

    call_count = []

    def call_then_fail(request, next_call, **context):
        next_call()
        raise RuntimeError("wrapper after downstream")

    preserved = chain(
        [call_then_fail],
        lambda request: call_count.append(request) or "provider-result",
        initial, session_id="trusted-session", turn_id="trusted-turn",
    )
    scenarios["wrapper_failure_does_not_repeat_provider"] = (
        preserved == "provider-result" and len(call_count) == 1
    )
    scenarios["fixture_module_restored"] = (
        all(manager.module_restored) and len(manager.module_restored) == 4
    )

    checks = {
        "separate_trusted_session_and_turn_kwargs": identity_ok,
        "missing_none_or_empty_identity_is_not_inferred": missing_ok,
        "narrow_handler_compatibility": narrow_ok,
        **scenarios,
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "evidence_level": "source_function_probe",
        "qualified_host": False,
        "source_revision": "NousResearch/hermes-agent v0.22.2 d923a5eb487a17c0a68801bba9ef0f56c81040a8",
        "source_sha256": PINNED,
        "checks": checks,
        "failures": failures,
        "limits": [
            "does not prove profile scope",
            "does not prove full provider admission",
            "does not qualify a running Hermes host",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path, help="cached v0.22.2 source tree")
    args = parser.parse_args(argv)
    try:
        report = run_qualification(args.source_root)
    except SourceError as exc:
        print(json.dumps({"qualified_host": False, "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
