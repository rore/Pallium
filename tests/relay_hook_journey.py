"""Actual hook journey shared by threaded and independent-process E2E callers."""
import importlib.util
import json
import sys
import time
from pathlib import Path


def hook_claim_emit_ack(common, index, message, scope, phases, emissions):
    began = time.perf_counter()
    delivery = message["deliveries"][0]
    claimed = common.relay_turn(
        "codex", f"mixed-target-{index}", scope["container_ref"],
        max_chars=1000, wake_delivery_id=delivery["delivery_id"],
    )
    phases.append({"index": index, "phase": "hook_claim",
                   "seconds": time.perf_counter() - began,
                   "status": "returned" if claimed is not None else "refused"})
    assert claimed is not None, (index, "hook claim refused")
    claimed_delivery, = claimed["deliveries"]
    assert claimed_delivery["delivery_id"] == delivery["delivery_id"]
    assert claimed_delivery["message_id"] == message["message_id"]
    assert claimed_delivery["attempts"] == 1
    rendered, emitted = common.format_relay(claimed["deliveries"])
    assert emitted == [claimed_delivery]
    assert f"message_id: {message['message_id']}" in rendered
    assert f"delivery_id: {delivery['delivery_id']}" in rendered
    emissions[index] = (message["message_id"], delivery["delivery_id"])
    began = time.perf_counter()
    confirmed = common.acknowledge_relay(emitted, container_ref=scope["container_ref"])
    phases.append({"index": index, "phase": "hook_ack",
                   "seconds": time.perf_counter() - began,
                   "status": "confirmed" if confirmed == emitted else "refused"})
    assert confirmed == emitted, (index, "hook ACK refused")


def main():
    index, directory = int(sys.argv[1]), Path(sys.argv[2])
    spec = importlib.util.spec_from_file_location("isolated_hook_common", sys.argv[3])
    common = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = common
    spec.loader.exec_module(common)
    common.PALLIUM_BASE_URL = sys.argv[4]
    common.SESSIONS_DIR, common.STATE_DIR = Path(sys.argv[5]), Path(sys.argv[6])
    assert common.hook_deadline() is None
    (directory / f"{index}.ready").write_text("ready", encoding="utf-8")
    assignment_path = directory / f"{index}.assignment.json"
    while not assignment_path.exists():
        time.sleep(.005)
    read_errors = {"count": 0, "first": None}
    while True:
        try:
            assignment_text = assignment_path.read_text(encoding="utf-8")
        except PermissionError as error:
            read_errors["count"] += 1
            if read_errors["first"] is None:
                read_errors["first"] = {"error_type": type(error).__name__,
                    "errno": error.errno, "winerror": getattr(error, "winerror", None)}
                print(json.dumps(read_errors), file=sys.stderr, flush=True)
            time.sleep(.005)
        else:
            break
    assignment = json.loads(assignment_text)
    (directory / f"{index}.assignment-ready").write_text(json.dumps(read_errors), encoding="utf-8")
    while not (directory / "release.json").exists():
        time.sleep(.005)
    phases, emissions = [], {}
    result = {"index": index, "entered": time.perf_counter(),
              "phases": phases, "emissions": emissions, "assignment_read_errors": read_errors}
    try:
        hook_claim_emit_ack(common, index, assignment["message"], assignment["scope"], phases, emissions)
        result["success"] = True
    except BaseException as error:
        result.update(success=False, error_type=type(error).__name__, error=str(error))
    finally:
        result["finished"] = time.perf_counter()
        target = directory / f"{index}.result.json"
        pending = target.with_suffix(".tmp")
        pending.write_text(json.dumps(result), encoding="utf-8")
        pending.replace(target)


if __name__ == "__main__":
    main()
