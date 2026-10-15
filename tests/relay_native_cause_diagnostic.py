"""Temporary PR312 native-refusal capture, enabled only by its diagnostic lane."""
from contextlib import contextmanager
from functools import wraps
import inspect
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

from core.errors import ImmediateTransactionBusyError


_SQLITE_NAMES = frozenset(name for name in vars(sqlite3) if name.startswith("SQLITE_"))
_TARGETS = {
    "test_http_claim_correlation_uses_fresh_identity_and_preserves_authority":
        ("initialize", "change", "commit_before"),
    "test_accepted_mcp_worker_recovers_pending_http_wake_after_service_replacement":
        ("reserve", "busy_stage", "register"),
}


def _error_details(error):
    pending, seen, chain = [("root", error)], set(), []
    while pending and len(chain) < 8:
        relation, current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        name = type(current).__name__
        code = getattr(current, "sqlite_errorcode", None)
        sqlite_name = getattr(current, "sqlite_errorname", None)
        chain.append({
            "relation": relation,
            "type": name if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,63}", name) else "unknown",
            "sqlite_errorcode": code if type(code) is int and 0 <= code < 2**31 else None,
            "sqlite_errorname": sqlite_name if type(sqlite_name) is str and sqlite_name in _SQLITE_NAMES else None,
        })
        for attribute in ("__cause__", "orig", "__context__"):
            child = getattr(current, attribute, None)
            if isinstance(child, BaseException) and id(child) not in seen:
                pending.append((attribute, child))
    stage = getattr(error, "acquisition_stage", None)
    return {
        "acquisition_stage": stage if type(stage) is str and stage in ImmediateTransactionBusyError.ACQUISITION_STAGES else "unknown",
        "chain": chain,
        "chain_truncated": any(id(item) not in seen for _, item in pending),
        "sqlite_error_observed": any(item["sqlite_errorcode"] is not None for item in chain),
    }


def _emit(directory, operation, receipt):
    try:
        encoded = json.dumps(receipt, sort_keys=True)
        temporary = Path(directory) / f"{operation}.tmp"
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(Path(directory) / f"{operation}.json")
        print("pallium_native_cause " + encoded, file=sys.stderr)
    except Exception:
        # Diagnostic I/O must never replace a native result or the original failure.
        pass


@contextmanager
def _capture(directory, operation, arguments):
    relay = arguments["relay_store"][0] if operation == "initialize" else arguments["http_wake"][1]
    attribute = "codex_wake_initialize" if operation == "initialize" else "codex_wake_transition"
    original = getattr(relay, attribute)
    receipt = {"preparation": "ready", "target_state": "started", "outcome": None,
               "outcome_scope": "test_body_before_fixture_teardown",
               "operation": operation, "started": 0, "returned": 0, "failed": 0,
               "errors": [], "dropped_errors": 0}
    _emit(directory, operation, receipt)

    def observed(*args, **kwargs):
        if operation == "reserve" and (not args or args[0] != "reserve"):
            return original(*args, **kwargs)
        receipt["started"] += 1
        try:
            result = original(*args, **kwargs)
        except BaseException as error:
            receipt["failed"] += 1
            try:
                if len(receipt["errors"]) < 8:
                    receipt["errors"].append(_error_details(error))
                else:
                    receipt["dropped_errors"] += 1
                _emit(directory, operation, receipt)
            except Exception:
                pass
            raise
        receipt["returned"] += 1
        return result

    with arguments["monkeypatch"].context() as patch:
        patch.setattr(relay, attribute, observed)
        try:
            yield
        except BaseException:
            receipt["outcome"] = "failed"
            raise
        else:
            receipt["outcome"] = "passed"
        finally:
            receipt["target_state"] = "completed"
            _emit(directory, operation, receipt)


def capture_native_cause(test):
    operation, parameter, value = _TARGETS[test.__name__]

    def capture(arguments):
        directory = os.environ.get("PALLIUM_PR312_NATIVE_CAUSE_DIR")
        return _capture(directory, operation, arguments) if directory and arguments.get(parameter) == value else None

    if inspect.iscoroutinefunction(test):
        @wraps(test)
        async def asynchronous(*args, **kwargs):
            context = capture(kwargs)
            if context is None:
                return await test(*args, **kwargs)
            with context:
                return await test(*args, **kwargs)
        return asynchronous

    @wraps(test)
    def synchronous(*args, **kwargs):
        context = capture(kwargs)
        if context is None:
            return test(*args, **kwargs)
        with context:
            return test(*args, **kwargs)
    return synchronous
