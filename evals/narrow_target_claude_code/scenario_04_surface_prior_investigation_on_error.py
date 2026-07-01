"""Scenario 4 — Surface a prior investigation when the same error class reappears.

# measures: injection-precision

See docs/specs/2026-07-01-narrow-target-claude-code-in-pallium-repo.md#scenario-4
"""

from __future__ import annotations

from ._shared import ScenarioResult, incomplete

SCENARIO_ID = "04-surface-prior-investigation-on-error"


def run() -> ScenarioResult:
    """investigation_outcome from Session A must fire on Session B's error via
    PostToolUse-failure trigger — and only then.

    Placeholder: fixture wiring lands in Week 2.
    """
    return incomplete(
        SCENARIO_ID,
        reason="investigation_outcome fixture + PostToolUse-failure trigger replay not wired",
    )


if __name__ == "__main__":
    import json
    result = run()
    print(json.dumps(result.to_dict(), indent=2))
