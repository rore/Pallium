"""Scenario 7 — Two unrelated prior errors superficially match; Pallium injects neither.

See docs/specs/2026-07-01-narrow-target-claude-code-in-pallium-repo.md#scenario-7
"""

from __future__ import annotations

from ._shared import ScenarioResult, incomplete

SCENARIO_ID = "07-unrelated-prior-errors-no-injection"


def run() -> ScenarioResult:
    """Container has two prior investigation memories sharing a surface term
    ("timeout") with different root subjects. New query mildly matches by
    surface but is unrelated. Correct behavior: inject neither.

    Negative scenario — specificity contributor. Directly tests the
    topical-similarity failure mode named in the abstention spec.

    Placeholder: fixture wiring lands in Week 2.
    """
    return incomplete(
        SCENARIO_ID,
        reason="two-unrelated-investigation fixture + non-injection assertion not wired",
    )


if __name__ == "__main__":
    import json
    result = run()
    print(json.dumps(result.to_dict(), indent=2))
