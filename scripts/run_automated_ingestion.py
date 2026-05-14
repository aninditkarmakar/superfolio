#!/usr/bin/env python3
"""Script wrapper for the automated ingestion CLI."""
import sys

from portfolio_engine.automation.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
