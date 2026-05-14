"""CLI entrypoint for automated ingestion runs."""
from __future__ import annotations

import argparse
import contextlib
import sys
from datetime import date
from typing import Callable, Any

from portfolio_engine.automation.orchestrator import run_automation
from portfolio_engine.automation.targets import parse_account_external_ids
from portfolio_engine.automation.types import AutomationRunRequest
from portfolio_engine.database import connect_database


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_automated_ingestion",
        description="Run an automated broker data ingestion job.",
    )
    parser.add_argument(
        "--target-type",
        required=True,
        choices=["portfolio", "accounts"],
        help="Target type: 'portfolio' or 'accounts'.",
    )
    parser.add_argument(
        "--integration",
        default="ibkr_flex_ws",
        dest="integration_key",
        help="Integration key (default: ibkr_flex_ws).",
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["dry-run", "load"],
        help="Run mode: 'dry-run' or 'load'.",
    )
    parser.add_argument(
        "--start-date",
        required=True,
        help="Start date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        help="End date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--portfolio-name",
        default=None,
        help="Portfolio name (required for target-type=portfolio).",
    )
    parser.add_argument(
        "--account-external-ids",
        default=None,
        help="Comma-separated account external IDs (required for target-type=accounts).",
    )
    return parser


def _as_context_manager(obj: Any):
    """Wrap obj in a nullcontext if it is not already a context manager."""
    if hasattr(obj, "__enter__") and hasattr(obj, "__exit__"):
        return obj
    return contextlib.nullcontext(obj)


def run(
    argv: list[str] | None = None,
    *,
    stdout=sys.stdout,
    stderr=sys.stderr,
    runner: Callable = run_automation,
    database_connector: Callable = connect_database,
) -> int:
    """Parse argv, build a request, execute it, and report the result.

    Returns an exit code: 0 on success or partial success, 1 on failure or error.
    """
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        start_date = date.fromisoformat(args.start_date)
        end_date = date.fromisoformat(args.end_date)
        account_external_ids = parse_account_external_ids(args.account_external_ids)

        request = AutomationRunRequest(
            target_type=args.target_type,
            integration_key=args.integration_key,
            mode=args.mode,
            requested_start_date=start_date,
            requested_end_date=end_date,
            portfolio_name=args.portfolio_name,
            account_external_ids=account_external_ids,
        )

        db_obj = database_connector()
        with _as_context_manager(db_obj) as database:
            result = runner(request, database=database)

    except SystemExit:
        raise
    except Exception as exc:
        print(f"Error: {exc}", file=stderr)
        return 1

    print(f"Automation status: {result.status}", file=stdout)

    if result.status == "partially_succeeded":
        print(
            "WARNING: automation run only partially succeeded — some accounts may have failed.",
            file=stdout,
        )

    if result.error_message:
        print(f"Message: {result.error_message}", file=stdout)

    return 1 if result.status == "failed" else 0


def main(argv: list[str] | None = None) -> int:
    """Main entrypoint that delegates to run()."""
    return run(argv)
