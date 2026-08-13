"""RAW / DERIVED / HYBRID retrieval + representation eval (Pallium vNext).

Continuous evaluation track — the RETRIEVAL-SIDE seams, complementary to the
derivation-side seams (extraction/coverage + source-fidelity) in
``evals/derivation_fidelity``. Offline and data-read-only.

On REAL historical lookups (from ``query_audit_log``) this eval REPLAYS each query
through the shipped retrieval stack three times at candidate level
(``target_kind="source_item"`` = RAW, ``"memory_object"`` = DERIVED, ``None`` =
HYBRID) and measures the two retrieval-time seams a shadow can honestly measure:

- **candidate-recovery** — an OBJECTIVE, judge-free derivation EVIDENCE LINK: for
  each derived object (episode), did its linked source turns enter the RAW arm and
  did the object enter the DERIVED arm? (RAW-only / DERIVED-only / both / neither).
- **representation-quality** — holding information + retrieval constant, is the
  rendered DERIVED text a correct, non-misleading answer surface FOR THIS LOOKUP vs
  the retrieved RAW turns? (query-conditioned; distinct from the source-fidelity axis
  in ``evals/derivation_fidelity``).

Context cost is compared at EQUAL token budget (a separate axis, NOT fed to the
judge) so HYBRID cannot win merely by receiving more context. Downstream/consumption
is explicitly OUT — a shadow arm is never shown to the agent. See runner.py.
"""
