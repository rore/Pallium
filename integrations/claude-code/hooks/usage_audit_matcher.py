from __future__ import annotations

import sys
from pathlib import Path

# Temporary compatibility path until Stop-local audit code is removed.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.usage_audit_matcher import *  # noqa: F401,F403
