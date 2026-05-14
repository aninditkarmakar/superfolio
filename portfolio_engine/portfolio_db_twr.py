"""Database-backed portfolio Time-Weighted Return CLI."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Callable, Protocol, TextIO

from .csv_export import write_portfolio_daily_twr_csv
from .database import connect_database
from .models import AccountRef, PortfolioCashFlow, PortfolioDailyInput, PortfolioTwrRow, TransferBridge
from .portfolio_twr import calculate_portfolio_twr, missing_nav_counts


class PortfolioTwrDatabase(Protocol):
    def __enter__(self) -> "PortfolioTwrDatabase": ...
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def fetch_portfolio_accounts(self, portfolio_name: str) -> list[AccountRef]: ...

    def fetch_portfolio_nav_inputs(
        self,
        *,
        portfolio_name: str,
        start_date: date | None,
        end_date: date | None,
    ) -> list[PortfolioDailyInput]: ...

    def fetch_portfolio_cash_flows(
        self,
        *,
        portfolio_name: str,
        start_date: date | None,
        end_date: date | None,
    ) -> list[PortfolioCashFlow]: ...

    def fetch_portfolio_transfer_bridges(self, portfolio_name: str) -> list[TransferBridge]: ...


DatabaseConnector = Callable[[str | None], PortfolioTwrDatabase]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calculate daily linked TWR for a SuperFolio portfolio."
    )
    parser.add_argument("--portfolio-name", required=True)
    parser.add_argument("--reporting-currency", required=True)
    parser.add_argument("--database-url", default=None)
    parser.add_argument(
        "--flow-timing",
        choices=["end", "start"],
        default="start",
    )
    parser.add_argument("--start-date", type=date.fromisoformat, default=None)
    parser.add_argument("--end-date", type=date.fromisoformat, default=None)
    parser.add_argument("--daily-output", type=Path, default=None)
    return parser


def run(
    argv: list[str] | None = None,
    *,
    database_connector: DatabaseConnector = connect_database,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    try:
        parser = build_parser()
        args = parser.parse_args(argv)

        if args.start_date is not None and args.end_date is not None:
            if args.start_date > args.end_date:
                raise ValueError("--start-date must be on or before --end-date")

        with database_connector(args.database_url) as db:
            accounts = db.fetch_portfolio_accounts(args.portfolio_name)
            nav_inputs = db.fetch_portfolio_nav_inputs(
                portfolio_name=args.portfolio_name,
                start_date=args.start_date,
                end_date=args.end_date,
            )
            cash_flows = db.fetch_portfolio_cash_flows(
                portfolio_name=args.portfolio_name,
                start_date=args.start_date,
                end_date=args.end_date,
            )
            bridges = db.fetch_portfolio_transfer_bridges(args.portfolio_name)

        rows = calculate_portfolio_twr(
            reporting_currency=args.reporting_currency,
            accounts=accounts,
            nav_inputs=nav_inputs,
            cash_flows=cash_flows,
            transfer_bridges=bridges,
            flow_timing=args.flow_timing,
        )

        if args.daily_output is not None:
            write_portfolio_daily_twr_csv(args.daily_output, rows)

        _print_summary(
            rows,
            portfolio_name=args.portfolio_name,
            reporting_currency=args.reporting_currency,
            accounts=accounts,
            nav_inputs=nav_inputs,
            cash_flows=cash_flows,
            bridges=bridges,
            daily_output=args.daily_output,
            stdout=stdout,
        )
        return 0

    except SystemExit:
        raise
    except Exception as error:
        stderr.write(f"Error: {error}\n")
        return 1


def _print_summary(
    rows: list[PortfolioTwrRow],
    *,
    portfolio_name: str,
    reporting_currency: str,
    accounts: list[AccountRef],
    nav_inputs: list[PortfolioDailyInput],
    cash_flows: list[PortfolioCashFlow],
    bridges: list[TransferBridge],
    daily_output: Path | None,
    stdout: TextIO,
) -> None:
    completed_rows = [r for r in rows if r.period_return is not None]
    final_twr = rows[-1].cumulative_twr if rows else Decimal("0")

    stdout.write(f"Portfolio: {portfolio_name}\n")
    stdout.write(f"Reporting currency: {reporting_currency}\n")
    stdout.write(f"Member accounts: {len(accounts)}\n")
    stdout.write(f"NAV rows: {len(nav_inputs)}\n")
    stdout.write(f"Cash-flow records: {len(cash_flows)}\n")
    stdout.write(f"Transfer bridges: {len(bridges)}\n")
    stdout.write(f"Return periods: {len(completed_rows)}\n")

    if rows:
        stdout.write(f"Date range: {rows[0].report_date} to {rows[-1].report_date}\n")

    warnings = missing_nav_counts(rows)
    if warnings:
        stdout.write("Missing NAV warnings:\n")
        for label in sorted(warnings):
            stdout.write(f"  {label}: {warnings[label]}\n")

    stdout.write(f"TWR: {final_twr * Decimal('100'):.6f}%\n")

    if daily_output is not None:
        stdout.write(f"Daily output written to {daily_output}\n")


def main(argv: list[str] | None = None) -> int:
    return run(argv)
