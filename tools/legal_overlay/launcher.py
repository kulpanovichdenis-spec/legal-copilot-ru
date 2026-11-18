#!/usr/bin/env python3
"""Absolute-path launcher for harnesses that do not start in the repository."""

from __future__ import annotations

import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from tools.legal_overlay.mcp_server import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
