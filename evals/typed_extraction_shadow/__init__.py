"""Typed-extraction shadow — comparison eval.

W5 PR 4. Joins ``memory_objects_shadow`` rows against live
``memory_objects`` rows and the rated-injection corpus
(``memory_feedback``) to produce per-type precision / recall / drift
metrics.

Report shape and metric definitions are documented in
``docs/specs/2026-07-01-milestone-shaped-memory-contract.md`` §W5.
"""
