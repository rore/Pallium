"""Scenario 2 — Recall the Python-on-Windows constraint before it bites.

See docs/specs/2026-07-01-narrow-target-claude-code-in-pallium-repo.md#scenario-2
"""

from __future__ import annotations

from ._shared import ScenarioResult, incomplete

SCENARIO_ID = "02-recall-python-on-windows-constraint"


def run() -> ScenarioResult:
    """Constraint from ~/.claude/CLAUDE.md must reach the agent before `uv venv`.

    Placeholder: fixture wiring lands in Week 2.
    """
    return incomplete(
        SCENARIO_ID,
        reason="constraint-surfacing pre-venv trigger not wired",
    )


if __name__ == "__main__":
    import json
    result = run()
    print(json.dumps(result.to_dict(), indent=2))
