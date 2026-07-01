"""Scenario 5 — Preserve an architectural decision made in-conversation.

See docs/specs/2026-07-01-narrow-target-claude-code-in-pallium-repo.md#scenario-5
"""

from __future__ import annotations

from ._shared import ScenarioResult, incomplete

SCENARIO_ID = "05-preserve-architectural-decision"


def run() -> ScenarioResult:
    """decision memory from Session A must surface (proactively, gated on score)
    when Session B considers the ruled-out approach.

    Placeholder: fixture wiring lands in Week 2.
    """
    return incomplete(
        SCENARIO_ID,
        reason="decision-memory fixture + related-topic Session B trigger replay not wired",
    )


if __name__ == "__main__":
    import json
    result = run()
    print(json.dumps(result.to_dict(), indent=2))
