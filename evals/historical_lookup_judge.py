"""Retrospective sampled reuse judge for the historical-lookup funnel.

Spec: docs/specs/2026-08-13-historical-lookup-measurement-contract.md
      §§ Reuse ladder, Rollup formula, Definitions

Shadow / offline. This harness NEVER affects live injection or agent output. It
reads persisted ``historical_lookup_reuse_event`` "lookup" rows (write-only
telemetry), reconstructs the surrounding session turns from ``source_items``,
and asks an LLM judge — per lookup — for four labels:

  (a) genuine_opportunity — was the retrieved history genuinely relevant?
  (b) rung-1 "incorporation" — retrieved history verifiably appears in the
      subsequent work (+ an evidence span).
  (c) rung-2 "influence" — no verbatim incorporation, but the history plausibly
      shaped the subsequent work.
  (d) direction — "user_directed" vs "agent_decided", read from the turns
      PRECEDING the lookup (a ``(thread_ref, container_ref, created_at)`` join
      over ``source_items``, the same reconstruction pattern the loader uses).

Protocol modelled on ``evals/anchor_probe/subagent_audit.py``: deterministic
seeded sampling, ``provider.generate_json``, rate accumulation, Wilson
intervals. Two differences, both intentional:

  * There is no baseline-vs-rule A/B pair to blind here — a reuse verdict is a
    single per-event label — so the A/B de-blinding step does not apply. The
    blinding we keep is the deterministic, seed-driven sample order.
  * Each seed acts as an independent RATER. The LLM cache key
    (``providers/llm/cached.py``) has NO seed slot, so identical prompts would
    collapse to one cached verdict. We fold the rater seed VALUE into the
    user_prompt as an inert trailing tag so differently-seeded runs yield
    DISTINCT cache keys (hence independent verdicts) WITHOUT biasing the
    verdict.

Per-rater rung labels are written to the append-only
``historical_lookup_reuse_label`` table via
``storage.write_historical_lookup_label_row``; the measurement loader computes
the consensus rung the rollup consumes. A double-rated subsample (two rater
seeds over the same events) yields Cohen's kappa.

Run (needs a live DB + configured LLM provider):
    python -m evals.historical_lookup_judge --db pallium.db \\
        --container-ref git:example.com/repo --seeds 0,1,2
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.models import new_id, utc_now  # noqa: E402
from evals.historical_lookup_measurement import (  # noqa: E402
    _RUNG_LADDER,
    _normalize_ts_bound,
    _wilson_95,
    load_events_from_storage,
)

# ---------------------------------------------------------------------------
# Judge prompt
# ---------------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = """\
You are auditing whether an AI agent actually REUSED information it retrieved
from its own past conversation history. You judge one history lookup at a time,
strictly from the evidence given. You have no access to any label or score.

You are given three blocks:
- CONTEXT BEFORE: the turns immediately preceding the lookup.
- RETRIEVED HISTORY: the past source excerpts the lookup surfaced to the agent.
- WORK AFTER: the agent's subsequent turns in the same session.

Decide:
1. genuine_opportunity (boolean): was the RETRIEVED HISTORY genuinely relevant
   to the task the agent was working on? false when the lookup surfaced nothing
   useful, or was empty / abandoned.
2. rung (string): the strongest supportable reuse claim —
   - "incorporation": the retrieved history verifiably appears in WORK AFTER
     (a reasoning step, an action, or the answer). Observational.
   - "influence": no verbatim incorporation, but the retrieved history plausibly
     shaped the subsequent work. Weaker, observational.
   - "none": no evidence the history was used.
3. evidence_span (string): a short verbatim quote (<=200 chars) copied from
   WORK AFTER that demonstrates the incorporation; empty string when rung is
   "none".
4. direction (string): who initiated the lookup, read from CONTEXT BEFORE —
   - "user_directed": the user explicitly asked the agent to recall or look up
     past context.
   - "agent_decided": the agent chose to consult history on its own.

Do not invent quotes; evidence_span must be copied verbatim from WORK AFTER or
be empty. Return the JSON schema.
"""

JUDGE_SCHEMA = (
    '{"genuine_opportunity":"boolean","rung":"string",'
    '"evidence_span":"string","direction":"string"}'
)

#: Rungs the judge may assign (rung-3 "downstream" is controlled-only, never
#: claimable from passive logs — see the measurement contract). "none" maps to a
#: NULL label (event contributes to no rung).
_JUDGE_RUNGS = frozenset({"incorporation", "influence"})
_DIRECTIONS = frozenset({"user_directed", "agent_decided"})

#: Minimum judge-vs-gold Cohen's kappa below which the reuse KPI is presented as
#: UNCALIBRATED. 0.60 is a PROJECT-DEFINED minimum agreement threshold (it sits
#: just below the Landis & Koch "substantial" boundary of 0.61, used only as a
#: rough reference point — not a claim that 0.60 IS "substantial"). The repo
#: already requires >=3 rater seeds + a consensus rule because single-seed judge
#: verdicts carry ~20pp variance (docs/context/validation.md); calibration raises
#: that bar from self-consistency to CORRECTNESS — the judge's consensus must
#: reach this agreement with a human-labelled gold set before rung rates are
#: shown as confident. Point estimate on a small gold fixture; see the fixture's
#: honesty_limitations (wide CI, single-author synthetic labels).
GOLD_KAPPA_THRESHOLD = 0.6


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class LookupContext:
    """Everything the judge needs about one persisted lookup event."""

    lookup_event_id: str
    session_id: str
    container_ref: str | None
    created_at: str
    exposed: list[dict[str, Any]]
    retrieved_texts: list[str]
    before_turns: list[tuple[str, str]]  # (role, content)
    after_turns: list[tuple[str, str]]

    @property
    def is_abandoned(self) -> bool:
        """A lookup that exposed nothing (empty / abandoned)."""
        return not self.exposed


@dataclass
class RaterLabel:
    lookup_event_id: str
    rater_seed: str
    rung: str | None
    genuine_opportunity: bool
    direction: str
    evidence_span: str
    rationale: str
    failed: bool = False


@dataclass
class JudgeReport:
    n_lookups: int
    n_sampled: int
    n_abandoned: int
    seeds: list[int]
    sample_seed: int
    labels: list[RaterLabel] = field(default_factory=list)
    consensus_rung: dict[str, str | None] = field(default_factory=dict)
    consensus_direction: dict[str, str] = field(default_factory=dict)
    genuine_opportunities: int = 0
    user_directed: int = 0
    agent_decided: int = 0
    kappa: float | None = None
    kappa_pair: tuple[str, str] | None = None
    kappa_n: int = 0
    n_judge_failures: int = 0
    rung_rates: dict[str, Any] = field(default_factory=dict)
    # Judge-vs-gold calibration (populated only when run_judge is given
    # gold_labels). gold_kappa is Cohen's kappa between the per-event CONSENSUS
    # rung and the human gold rung, over the events present in gold_labels;
    # calibrated is gold_kappa >= GOLD_KAPPA_THRESHOLD. None when uncomputed.
    gold_kappa: float | None = None
    gold_kappa_n: int = 0
    calibrated: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": "docs/specs/2026-08-13-historical-lookup-measurement-contract.md",
            "n_lookups": self.n_lookups,
            "n_sampled": self.n_sampled,
            "n_abandoned": self.n_abandoned,
            "seeds": self.seeds,
            "sample_seed": self.sample_seed,
            "genuine_opportunities": self.genuine_opportunities,
            "direction_split": {
                "user_directed": self.user_directed,
                "agent_decided": self.agent_decided,
            },
            "cohens_kappa": {
                "kappa": self.kappa,
                "rater_pair": list(self.kappa_pair) if self.kappa_pair else None,
                "n_double_rated": self.kappa_n,
            },
            "judge_vs_gold": {
                "kappa": self.gold_kappa,
                "n": self.gold_kappa_n,
                "threshold": GOLD_KAPPA_THRESHOLD,
                "calibrated": self.calibrated,
                "categories": ["incorporation", "influence", "none"],
            },
            "rung_rates": self.rung_rates,
            "n_labels_written": len(self.labels),
            "n_judge_failures": self.n_judge_failures,
        }


# ---------------------------------------------------------------------------
# Excerpting + prompt building
# ---------------------------------------------------------------------------


def _excerpt(text: str, n: int = 600) -> str:
    return (text or "").replace("\n", " ").strip()[:n]


def _render_turns(turns: list[tuple[str, str]], *, per: int = 300) -> str:
    if not turns:
        return "(none)"
    return "\n".join(f"- {role or '?'}: {_excerpt(content, per)}" for role, content in turns)


def _render_history(texts: list[str], *, per: int = 400) -> str:
    if not texts:
        return "(nothing retrieved — abandoned/empty lookup)"
    return "\n".join(f"- {_excerpt(t, per)}" for t in texts)


def _build_user_prompt(ctx: LookupContext, seed_value: int) -> str:
    """Build the blinded judge prompt for one lookup under one rater seed.

    The trailing ``[reviewer pass #N]`` tag carries the rater seed VALUE (not the
    enumerate ordinal). It is INERT — it carries no verdict signal — but it makes
    the prompt (and therefore the disk cache key) unique per rater seed VALUE, so
    differently-seeded runs (e.g. ``0,1,2`` vs ``5,6,7``) produce independent
    verdicts instead of collapsing onto one cached response. See module docstring.
    """
    body = (
        "CONTEXT BEFORE:\n"
        f"{_render_turns(ctx.before_turns)}\n\n"
        "RETRIEVED HISTORY:\n"
        f"{_render_history(ctx.retrieved_texts)}\n\n"
        "WORK AFTER:\n"
        f"{_render_turns(ctx.after_turns)}\n\n"
        "Judge this lookup and respond with the JSON schema."
    )
    # Inert trailing tag — defeats the seedless LLM cache key without biasing.
    return f"{body}\n\n[reviewer pass #{seed_value}]"


# ---------------------------------------------------------------------------
# Storage reads (raw sqlite3, mirrors the measurement loader)
# ---------------------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _load_lookup_contexts(
    conn: sqlite3.Connection,
    *,
    eligible_set: set[str],
    container_ref: str | None,
    since: str | None,
    until: str | None,
    before_turns: int,
    after_turns: int,
) -> list[LookupContext]:
    """Load full lookup contexts for eligible sessions from the live DB."""
    if not _table_exists(conn, "historical_lookup_reuse_event"):
        return []
    where = ["event_type = 'lookup'"]
    params: list[Any] = []
    if container_ref is not None:
        where.append("container_ref = ?")
        params.append(container_ref)
    if since is not None:
        where.append("created_at >= ?")
        params.append(since)
    if until is not None:
        where.append("created_at <= ?")
        params.append(until)
    sql = (
        "SELECT id, session_id, container_ref, created_at, exposed_json "
        "FROM historical_lookup_reuse_event WHERE " + " AND ".join(where)
        + " ORDER BY created_at, id"
    )
    rows = conn.execute(sql, params).fetchall()

    contexts: list[LookupContext] = []
    for r in rows:
        session_id = r["session_id"]
        if session_id not in eligible_set:
            continue
        try:
            exposed = json.loads(r["exposed_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            exposed = []
        retrieved = _retrieved_texts(conn, exposed)
        before, after = _session_turns_around(
            conn,
            session_id=session_id,
            container_ref=r["container_ref"],
            pivot=r["created_at"],
            before_n=before_turns,
            after_n=after_turns,
        )
        contexts.append(
            LookupContext(
                lookup_event_id=r["id"],
                session_id=session_id,
                container_ref=r["container_ref"],
                created_at=r["created_at"],
                exposed=exposed if isinstance(exposed, list) else [],
                retrieved_texts=retrieved,
                before_turns=before,
                after_turns=after,
            )
        )
    return contexts


def _retrieved_texts(conn: sqlite3.Connection, exposed: Any) -> list[str]:
    if not isinstance(exposed, list) or not exposed:
        return []
    ids = [e.get("source_item_id") for e in exposed if isinstance(e, dict) and e.get("source_item_id")]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id, content FROM source_items WHERE id IN ({placeholders}) "
        "AND forgotten_at IS NULL",
        ids,
    ).fetchall()
    by_id = {row["id"]: row["content"] for row in rows}
    # Preserve the exposed order (rank order).
    return [by_id[i] for i in ids if i in by_id]


def _session_turns_around(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    container_ref: str | None,
    pivot: str | None,
    before_n: int,
    after_n: int,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Reconstruct turns before/after ``pivot`` in one session.

    ``(thread_ref, container_ref, created_at)`` ordering join over
    ``source_items`` — the same reconstruction pattern as the eligibility
    loader. Forgotten turns are excluded.
    """
    where = ["thread_ref = ?", "forgotten_at IS NULL"]
    params: list[Any] = [session_id]
    if container_ref is not None:
        where.append("container_ref = ?")
        params.append(container_ref)
    rows = conn.execute(
        "SELECT role, content, created_at FROM source_items WHERE "
        + " AND ".join(where)
        + " ORDER BY created_at, id",
        params,
    ).fetchall()
    before: list[tuple[str, str]] = []
    after: list[tuple[str, str]] = []
    for row in rows:
        created = row["created_at"]
        turn = (row["role"], row["content"] or "")
        if created is None:
            # Unknown-time turn: cannot be placed relative to the pivot. Dropping
            # it avoids misreading a pre-lookup turn as subsequent work (a false
            # rung-1 "incorporation").
            continue
        if pivot is not None and created < pivot:
            before.append(turn)
        else:
            after.append(turn)
    # Keep the turns nearest the lookup on each side.
    return before[-before_n:], after[:after_n]


# ---------------------------------------------------------------------------
# Judge invocation
# ---------------------------------------------------------------------------


def _coerce_rung(raw: Any) -> str | None:
    value = str(raw or "").strip().lower()
    return value if value in _JUDGE_RUNGS else None


def _coerce_direction(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    return value if value in _DIRECTIONS else "agent_decided"


def _coerce_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"true", "yes", "1"}


def _judge_once(provider, ctx: LookupContext, *, rater_seed: str, seed_value: int) -> RaterLabel:
    user_prompt = _build_user_prompt(ctx, seed_value)
    failed = False
    try:
        response = provider.generate_json(
            system_prompt=JUDGE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema_description=JUDGE_SCHEMA,
        )
        parsed = response.parsed_json or {}
        genuine = _coerce_bool(parsed.get("genuine_opportunity", False))
        rung = _coerce_rung(parsed.get("rung")) if genuine else None
        direction = _coerce_direction(parsed.get("direction"))
        evidence = str(parsed.get("evidence_span", ""))[:300]
        rationale = f"genuine={genuine} rung={rung} dir={direction}"
    except Exception as exc:  # noqa: BLE001 — a judge error must not abort the run
        # A provider failure is NOT a "no reuse" verdict: mark it failed so it is
        # neither persisted nor folded into consensus / kappa (which would bias
        # both downward). Rationale is a short error CODE — never repr(exc), which
        # could embed prompt / endpoint fragments.
        failed = True
        genuine, rung, direction, evidence = False, None, "agent_decided", ""
        rationale = f"[judge error: {type(exc).__name__}]"
    return RaterLabel(
        lookup_event_id=ctx.lookup_event_id,
        rater_seed=rater_seed,
        rung=rung,
        genuine_opportunity=genuine,
        direction=direction,
        evidence_span=evidence,
        rationale=rationale,
        failed=failed,
    )


# ---------------------------------------------------------------------------
# Consensus + statistics
# ---------------------------------------------------------------------------


def _consensus_rung_from_labels(rungs: list[str | None]) -> str | None:
    """Plurality; tie -> most conservative (lowest-ladder) rung. Mirrors the
    measurement loader's ``_consensus_rung`` rule so the harness report matches
    what the rollup will later derive from the persisted labels."""
    counts: dict[str, int] = {}
    for rung in rungs:
        if rung in _RUNG_LADDER:
            counts[rung] = counts.get(rung, 0) + 1
    if not counts:
        return None
    top = max(counts.values())
    for rung in _RUNG_LADDER:  # ascending strength -> first tie is conservative
        if counts.get(rung, 0) == top:
            return rung
    return None


def _consensus_direction_from_labels(directions: list[str]) -> str:
    """Plurality; tie -> "agent_decided" (the conservative default: only claim
    user-directed when raters agree it was)."""
    counts: dict[str, int] = {}
    for direction in directions:
        counts[direction] = counts.get(direction, 0) + 1
    if not counts:
        return "agent_decided"
    top = max(counts.values())
    if counts.get("user_directed", 0) == top and counts.get("agent_decided", 0) != top:
        return "user_directed"
    return "agent_decided"


def cohens_kappa(labels_a: list[str], labels_b: list[str]) -> float | None:
    """Cohen's kappa for two raters over the same items.

    Returns None when the vectors are empty or of unequal length. When both
    raters place every item in a single shared category (degenerate, expected
    agreement == 1) returns 1.0 by convention.
    """
    if not labels_a or len(labels_a) != len(labels_b):
        return None
    n = len(labels_a)
    categories = set(labels_a) | set(labels_b)
    po = sum(1 for a, b in zip(labels_a, labels_b) if a == b) / n
    pe = 0.0
    for cat in categories:
        pa = sum(1 for a in labels_a if a == cat) / n
        pb = sum(1 for b in labels_b if b == cat) / n
        pe += pa * pb
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1.0 - pe)


def _rung_category(rung: str | None) -> str:
    """Map a rung (possibly None) to a kappa category string."""
    return rung if rung in _RUNG_LADDER else "none"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_judge(
    db_path: Path | str,
    *,
    provider,
    storage=None,
    container_ref: str | None = None,
    since: str | None = None,
    until: str | None = None,
    eligibility_n: int = 50,
    sample_size: int = 50,
    seeds: list[int] | None = None,
    sample_seed: int = 0,
    before_turns: int = 3,
    after_turns: int = 4,
    write_labels: bool = True,
    gold_labels: dict[str, str | None] | None = None,
) -> JudgeReport:
    """Run the retrospective reuse judge and (optionally) persist rung labels.

    Shadow/offline: reads the write-only event table + source_items, never
    touches the injection path. Each seed in ``seeds`` acts as an independent
    rater over the SAME sampled events (sampling is fixed by ``sample_seed``),
    so the report can compute both a per-event consensus rung and Cohen's kappa
    on the double-rated subsample.

    ``gold_labels`` (optional): a ``{lookup_event_id -> gold_rung}`` map of
    human labels (gold_rung in {"incorporation", "influence", "none"}, or None
    treated as "none"). When supplied, the report also carries judge-vs-gold
    Cohen's kappa (the per-event CONSENSUS rung vs the gold rung, over the
    events present in the map) and a ``calibrated`` verdict against
    ``GOLD_KAPPA_THRESHOLD``. This measures judge CORRECTNESS, not just
    inter-seed stability. It does not change the rubric, the sampling, or the
    persisted labels.
    """
    seeds = seeds if seeds is not None else [0, 1, 2]
    since_norm = _normalize_ts_bound(since)
    until_norm = _normalize_ts_bound(until)

    eligible, _events = load_events_from_storage(
        db_path,
        container_ref=container_ref,
        since=since,
        until=until,
        eligibility_n=eligibility_n,
    )
    eligible_set = set(eligible)

    contexts: list[LookupContext] = []
    path = Path(db_path)
    if path.exists():
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        try:
            if _table_exists(conn, "source_items"):
                contexts = _load_lookup_contexts(
                    conn,
                    eligible_set=eligible_set,
                    container_ref=container_ref,
                    since=since_norm,
                    until=until_norm,
                    before_turns=before_turns,
                    after_turns=after_turns,
                )
        finally:
            conn.close()

    n_lookups = len(contexts)
    n_abandoned = sum(1 for c in contexts if c.is_abandoned)

    # Deterministic shared sample — every rater judges the same events.
    sampled = list(contexts)
    random.Random(sample_seed).shuffle(sampled)
    if sample_size is not None and sample_size >= 0:
        sampled = sampled[:sample_size]

    report = JudgeReport(
        n_lookups=n_lookups,
        n_sampled=len(sampled),
        n_abandoned=n_abandoned,
        seeds=list(seeds),
        sample_seed=sample_seed,
    )
    if not sampled:
        # Empty / abandoned window — empty-safe, no crash.
        report.rung_rates = _empty_rung_rates()
        return report

    if storage is None and write_labels:
        from storage.sqlite import SQLiteStorageProvider

        storage = SQLiteStorageProvider(f"sqlite:///{path}")

    # Per-event rater labels, keyed for consensus + kappa. Failed judge calls
    # are excluded here (and from persistence) so they bias neither consensus
    # nor kappa; they are tallied separately as n_judge_failures.
    per_event: dict[str, list[RaterLabel]] = {c.lookup_event_id: [] for c in sampled}
    n_judge_failures = 0
    for seed in seeds:
        rater_seed = str(seed)
        for ctx in sampled:
            label = _judge_once(
                provider, ctx, rater_seed=rater_seed, seed_value=seed
            )
            if label.failed:
                n_judge_failures += 1
                continue
            report.labels.append(label)
            per_event[ctx.lookup_event_id].append(label)
            if write_labels and storage is not None:
                storage.write_historical_lookup_label_row(
                    {
                        "id": new_id(),
                        "lookup_event_id": label.lookup_event_id,
                        "rater_seed": label.rater_seed,
                        "rung": label.rung,
                        "rationale": label.rationale,
                        "created_at": utc_now(),
                    }
                )
    report.n_judge_failures = n_judge_failures

    # Consensus per event.
    for event_id, labels in per_event.items():
        report.consensus_rung[event_id] = _consensus_rung_from_labels(
            [lbl.rung for lbl in labels]
        )
        report.consensus_direction[event_id] = _consensus_direction_from_labels(
            [lbl.direction for lbl in labels]
        )

    report.genuine_opportunities = sum(
        1
        for labels in per_event.values()
        if sum(1 for lbl in labels if lbl.genuine_opportunity) * 2 >= len(labels)
    )
    report.user_directed = sum(
        1 for d in report.consensus_direction.values() if d == "user_directed"
    )
    report.agent_decided = sum(
        1 for d in report.consensus_direction.values() if d == "agent_decided"
    )

    # Cohen's kappa on the first two rater seeds (the double-rated subsample:
    # the shared sample every rater judged).
    if len(seeds) >= 2:
        seed_a, seed_b = str(seeds[0]), str(seeds[1])
        vec_a: list[str] = []
        vec_b: list[str] = []
        for ctx in sampled:
            labels = {lbl.rater_seed: lbl for lbl in per_event[ctx.lookup_event_id]}
            if seed_a in labels and seed_b in labels:
                vec_a.append(_rung_category(labels[seed_a].rung))
                vec_b.append(_rung_category(labels[seed_b].rung))
        report.kappa = cohens_kappa(vec_a, vec_b)
        report.kappa_pair = (seed_a, seed_b)
        report.kappa_n = len(vec_a)

    # Judge-vs-gold calibration: compare the per-event CONSENSUS rung against
    # the human gold rung over the events present in gold_labels. Reuses the
    # same cohens_kappa + _rung_category machinery as the seed-vs-seed kappa, so
    # both agreement numbers are computed identically (only the second rater
    # differs: gold instead of another seed).
    if gold_labels:
        judge_vec: list[str] = []
        gold_vec: list[str] = []
        for ctx in sampled:
            if ctx.lookup_event_id not in gold_labels:
                continue
            # Exclude events with NO successful judge label (every rater call
            # failed): their consensus is None, which _rung_category would map to
            # the "none" category and silently bias gold_kappa/gold_kappa_n. An
            # all-failed event is missing data, not a "none" verdict.
            if not per_event.get(ctx.lookup_event_id):
                continue
            judge_vec.append(_rung_category(report.consensus_rung.get(ctx.lookup_event_id)))
            gold_vec.append(_rung_category(gold_labels.get(ctx.lookup_event_id)))
        report.gold_kappa = cohens_kappa(judge_vec, gold_vec)
        report.gold_kappa_n = len(judge_vec)
        report.calibrated = (
            report.gold_kappa is not None
            and report.gold_kappa >= GOLD_KAPPA_THRESHOLD
        )

    report.rung_rates = _rung_rates_from_consensus(
        report.consensus_rung, denominator=len(sampled)
    )
    return report


def _empty_rung_rates() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for rung in _RUNG_LADDER:
        out[rung] = {
            "numerator": 0,
            "denominator": 0,
            "reuse_per_100": None,
            "wilson_95": {"low": None, "high": None},
            "note": "n/a (0 sampled)",
        }
    return out


def _rung_rates_from_consensus(
    consensus: dict[str, str | None], *, denominator: int
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for rung in _RUNG_LADDER:
        numerator = sum(1 for r in consensus.values() if r == rung)
        entry: dict[str, Any] = {"numerator": numerator, "denominator": denominator}
        if denominator == 0:
            entry["reuse_per_100"] = None
            entry["wilson_95"] = {"low": None, "high": None}
            entry["note"] = "n/a (0 sampled)"
        else:
            low, high = _wilson_95(numerator, denominator)
            entry["reuse_per_100"] = 100.0 * numerator / denominator
            entry["wilson_95"] = {"low": 100.0 * low, "high": 100.0 * high}
        out[rung] = entry
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_seeds(raw: str) -> list[int]:
    seeds = [int(part.strip()) for part in raw.split(",") if part.strip()]
    if len(seeds) < 3:
        raise argparse.ArgumentTypeError(
            "at least 3 rater seeds are required (e.g. --seeds 0,1,2)"
        )
    if len(set(seeds)) != len(seeds):
        raise argparse.ArgumentTypeError("rater seeds must be distinct")
    return seeds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Retrospective sampled reuse judge for the historical-lookup "
            "funnel. Writes per-rater rung labels to the append-only labels "
            "table; the measurement rollup consumes the consensus."
        )
    )
    parser.add_argument("--db", type=Path, required=True, help="Path to pallium.db")
    parser.add_argument("--container-ref", default=None)
    parser.add_argument("--since", default=None)
    parser.add_argument("--until", default=None)
    parser.add_argument("--eligibility-n", type=int, default=50)
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument(
        "--seeds",
        type=_parse_seeds,
        default=[0, 1, 2],
        help="Comma-separated rater seeds; >=3 required (default: 0,1,2).",
    )
    parser.add_argument("--sample-seed", type=int, default=0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Reconstruct + sample contexts but skip the LLM calls and writes.",
    )
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--no-eval-cache", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.dry_run:
        provider = _NullProvider()
        write_labels = False
    else:
        from app.config import AppConfig
        from evals.eval_common import build_eval_providers

        config = AppConfig.from_env()
        _main_provider, provider = build_eval_providers(
            config, cache_dir=args.cache_dir, no_eval_cache=args.no_eval_cache
        )
        write_labels = True

    report = run_judge(
        args.db,
        provider=provider,
        container_ref=args.container_ref,
        since=args.since,
        until=args.until,
        eligibility_n=args.eligibility_n,
        sample_size=args.sample_size,
        seeds=args.seeds,
        sample_seed=args.sample_seed,
        write_labels=write_labels,
    )

    serialised = json.dumps(report.to_dict(), indent=2, sort_keys=True, default=str)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialised, encoding="utf-8")
        print(f"Wrote judge report -> {args.output}", file=sys.stderr)
    print(serialised)
    return 0


class _NullProvider:
    """No-op provider for --dry-run: returns a 'none' verdict without a call."""

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str):
        from providers.llm.base import LLMJsonResponse

        payload = {
            "genuine_opportunity": False,
            "rung": "none",
            "evidence_span": "",
            "direction": "agent_decided",
        }
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


if __name__ == "__main__":
    raise SystemExit(main())
