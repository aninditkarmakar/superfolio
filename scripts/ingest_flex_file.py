#!/usr/bin/env python3
"""CLI for manual Flex XML ingestion workflows."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from portfolio_engine.ingestion_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
