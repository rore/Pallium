"""Extract a static fixture from the live DB to lock the pre-PR-3
noise as a regression pin.

Usage (one-shot; the resulting JSON goes into tests/fixtures/):

    python scripts/extract_live_corpus_fixture.py \
        --db C:/Users/I347041/.pallium/data/pallium.db \
        --out tests/fixtures/live_corpus_pre_pr3_2026_07_02.json

For each active operational_fact row, look up its provenance
(evidence[0].source_item_id → source_items.metadata_json → the
agent_work_trace_turn payload) and emit a compact record with the
originating cmd / output_tail / files_read.

This isn't intended to run in CI — it's a one-shot at redesign time.
The resulting fixture is committed and consumed by
``tests/test_operational_fact_live_corpus_replay.py`` to prove PR 3
rejects the noise that produced the 218 legacy rows.

Anonymization: paths under user directories are lightly redacted
(replace ``C:/Users/<user>/`` with ``C:/Users/USER/``). Anything
already redacted by the ingest-time redactor is left alone.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path


_USER_RE = re.compile(
    r"(?:[a-zA-Z]:[\\/]+|/[a-zA-Z]/)Users[\\/]+[^\\/'\"\s]+[\\/]+",
    re.IGNORECASE,
)
# Second-pass anonymizer for bare user identifiers (SAP IDs, LDAP
# handles) that survive the path-shape regex — e.g. in ``ls -la`` output
# where the owner column shows the username on its own. Add known
# identifiers here; defense-in-depth against fixture PII leaks.
_BARE_USER_TOKENS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bI347041\b"),
)


def _anonymize(text: str) -> str:
    if not text:
        return text
    out = _USER_RE.sub("C:/Users/USER/", text)
    for pat in _BARE_USER_TOKENS:
        out = pat.sub("USER", out)
    return out


def _assert_anonymized(text: str, source_desc: str) -> None:
    """Fail-fast guard: no known PII may survive anonymization.

    A defensive check — if the regexes miss a shape, the fixture must
    not silently ship. Extend this list when new PII shapes are found.
    """
    if not text:
        return
    for pat in _BARE_USER_TOKENS:
        if pat.search(text):
            raise RuntimeError(
                f"anonymization miss: {pat.pattern} survived in {source_desc}"
            )


def _extract_turn(conn: sqlite3.Connection, source_item_id: str) -> dict | None:
    row = conn.execute(
        "SELECT metadata_json FROM source_items WHERE id = ?",
        (source_item_id,),
    ).fetchone()
    if not row or not row[0]:
        return None
    try:
        meta = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    turn = meta.get("agent_work_trace_turn")
    if not isinstance(turn, dict):
        return None
    cmds = []
    for cmd in turn.get("commands") or []:
        cmds.append({
            "cmd": _anonymize(cmd.get("cmd", "")),
            "exit_code": cmd.get("exit_code", 0),
            "output_tail": _anonymize(cmd.get("output_tail", ""))[:400],
        })
    return {
        "commands": cmds,
        "files_read": [_anonymize(p) for p in (turn.get("files_read") or [])][:20],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    rows = conn.execute(
        "SELECT id, payload_json, container_ref "
        "FROM memory_objects "
        "WHERE type = 'operational_fact' "
        "  AND lifecycle = 'active' "
        "  AND is_soft_deleted = 0"
    ).fetchall()

    entries: list[dict] = []
    for i, (mid, payload_json, container_ref) in enumerate(rows):
        try:
            payload = json.loads(payload_json)
        except (TypeError, ValueError):
            continue
        evidence = payload.get("evidence") or []
        if not evidence:
            continue
        source_id = evidence[0].get("source_item_id")
        if not source_id:
            continue
        turn = _extract_turn(conn, source_id)
        if not turn:
            continue
        entries.append({
            "turn_index": i,
            "memory_id_hint": mid[:12],
            "container_ref": container_ref,
            "legacy_family": payload.get("command_family"),
            "legacy_role": payload.get("artifact_role"),
            "legacy_artifact_normalized": _anonymize(
                payload.get("artifact_normalized") or ""
            ),
            "commands": turn["commands"],
            "files_read": turn["files_read"],
        })

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Final guard: scan the serialized JSON for known-PII shapes that
    # survived per-field anonymization. Fail fast rather than commit.
    serialized = json.dumps(entries, indent=2)
    _assert_anonymized(serialized, source_desc=str(out_path))
    out_path.write_text(serialized, encoding="utf-8")
    print(f"extracted {len(entries)} entries -> {out_path}")


if __name__ == "__main__":
    main()
