"""Scenario 1 — Don't repeat a previously-failed command.

See docs/specs/2026-07-01-narrow-target-claude-code-in-pallium-repo.md#scenario-1
"""

from __future__ import annotations

from ._shared import ScenarioResult, incomplete

SCENARIO_ID = "01-repeat-failed-command"


def run() -> ScenarioResult:
    """Session A fails `uv sync` on Windows; Session B must be warned before retrying.

    Placeholder: fixture wiring lands in Week 2.
    """
    return incomplete(
        SCENARIO_ID,
        reason="Session A ingest fixture + Session B trigger-turn replay not wired",
    )


if __name__ == "__main__":
    import json
    result = run()
    print(json.dumps(result.to_dict(), indent=2))
