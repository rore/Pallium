"""Run the shared released Hermes TUI caller journey inside the root-proven Linux namespace."""
from __future__ import annotations

import os
import sys

import pytest

from tests.test_hermes_tui_native_e2e import test_released_hermes_actual_ui_journey as _shared_journey


pytestmark = [pytest.mark.slow, pytest.mark.skipif(sys.platform != "linux", reason="Linux namespace qualification only")]


@pytest.mark.parametrize("memory_enabled", [False, True], ids=["memory-off", "memory-on"])
def test_released_hermes_tui_in_linux_namespace(client, tmp_path, memory_enabled):
    root = os.environ.get("PALLIUM_LINUX_QUALIFICATION_ROOT")
    manifest = os.environ.get("PALLIUM_LINUX_QUALIFICATION_MANIFEST")
    if not root and not manifest:
        pytest.skip("root-proven Linux Hermes qualification namespace is not configured")
    _shared_journey(client, tmp_path, memory_enabled, "tui",
                    "custom" if memory_enabled else "openai-api")
