"""Assert collector bounds, paired spans and cleanup without running an application test."""
import hashlib
import inspect
import sqlite3
import sys
from pathlib import Path

import yaml
import registration_probe as probe
from gc_overlap_helpers import _make_gc_overlap_observer, _remove_exact_gc_observer

root = Path(__file__).resolve().parent
assert hashlib.sha256((root / "retained_recorder.py").read_bytes()).hexdigest() == "f556fbc5ddbb4096f3bf65663f995c729d84b8fddefec8f1f48d2e3f5cc0b2fa"
workflow = yaml.safe_load((root.parent / "workflows/ci.yml").read_text())
assert set(workflow.get("on", workflow.get(True))) == {"workflow_dispatch"}
assert len(workflow["jobs"]) == 1
job = workflow["jobs"]["registration-observation"]
assert job["runs-on"] == "ubuntu-24.04" and job["timeout-minutes"] == 5
command = next(s["run"] for s in job["steps"] if s.get("name") == "Observe one exact original parameter once")
assert command.count(probe.TARGET) == 1 and "-n 0" in command and "120s python -m pytest" in command
assert "--kill-after=10s" in command and 'exit "$status"' in command

callbacks = [lambda *_: None]
observer, events, starts, status = _make_gc_overlap_observer(probe.time, max_events=2)
callbacks.append(observer)
observer("start", {"generation": 1}); observer("stop", {"generation": 1})
observer("stop", {"generation": 1})
assert len(events) == 2 and status["dropped"] and status["unmatched"] and not starts
assert _remove_exact_gc_observer(callbacks, observer) and len(callbacks) == 1

# Same fixed phase shape, real in-memory SQLite; no app fixtures, deadline or clock edits.
def acquire_phase(name, operation):
    return operation()
probe.PHASE_CODE = acquire_phase.__code__
probe.recorder.PYTHON_CALLS[probe.PHASE_CODE] = "acquire_phase"
connection = sqlite3.connect(":memory:")
cursor = connection.cursor()
dialect = probe.recorder.DefaultDialect()
probe.recorder.add_callable("dialect_execute", type(dialect).do_execute)
try:
    previous = sys.getprofile()
    assert probe.capture(lambda: acquire_phase("setup_pragma", lambda: dialect.do_execute(cursor, "PRAGMA busy_timeout=50", ()))) is None
    assert sys.getprofile() is previous and probe.REPORT["profile_restored"]
    assert probe.REPORT["callback_removed"] and probe.REPORT["callbacks_preserved"]
    assert probe.REPORT["gc_policy_unchanged"] and not probe.recorder.STACK
    assert any(s["label"] == "cursor_execute" and s["category"] == "busy_timeout" for s in probe.recorder.STATE["spans"])
    try:
        probe.capture(lambda: (_ for _ in ()).throw(ValueError("sentinel")))
    except ValueError:
        pass
    else:
        raise AssertionError("caller exception suppressed")
    assert sys.getprofile() is previous and probe.REPORT["callback_removed"]
finally:
    connection.close()
print("Observer control and workflow scope assertions passed; no application observation executed.")