"""Database-backed Time-Weighted Return CLI."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Callable, NoReturn, Protocol, TextIO

from .csv_export import write_daily_twr_csv
from .database import connect_database
from .models import CashFlow, NavSnapshot, TwrRow
from .twr import align_flows_to_nav_dates, calculate_twr

DEPOSIT_WITHDRAWAL_CASH_FLOW_TYPE = "Deposits/Withdrawals"


class DatabaseTwrCliError(RuntimeError):
    """Raised for user-facing CLI errors in the database TWR workflow."""


class TwrDatabase(Protocol):
    def __enter__(self) -> "TwrDatabase": ...
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def fetch_nav_snapshots(
        self,
        *,
        brokerage_code: str,
        account_external_id: str,
        start_date: date | None,
        end_date: date | None,
    ) -> list[NavSnapshot]: ...

    def fetch_cash_flows(
        self,
        *,
        brokerage_code: str,
        account_external_id: str,
        start_date: date | None,
        end_date: date | None,
    ) -> list[CashFlow]: ...


DatabaseConnector = Callable[[str | None], TwrDatabase]


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise DatabaseTwrCliError(message)


def build_parser() -> _ArgumentParser:
    parser = _ArgumentParser(
        description="Calculate daily linked TWR from SuperFolio database data."
    )
    parser.add_argument("--brokerage-code", required=True)
    parser.add_argument("--account-external-id", required=True)
    parser.add_argument("--database-url", default=None)
    parser.add_argument(
        "--flow-timing",
        choices=["end", "start"],
        default="start",
    )
    parser.add_argument("--start-date", type=_parse_iso_date, default=None)
    parser.add_argument("--end-date", type=_parse_iso_date, default=None)
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
            _validate_date_range(args.start_date, args.end_date)

        with database_connector(args.database_url) as db:
            snapshots = db.fetch_nav_snapshots(
                brokerage_code=args.brokerage_code,
                account_external_id=args.account_external_id,
                start_date=args.start_date,
                end_date=args.end_date,
            )
            if not snapshots:
                raise DatabaseTwrCliError(
                    "No NAV snapshots found for the selected account and date range."
                )

            flows = db.fetch_cash_flows(
                brokerage_code=args.brokerage_code,
                account_external_id=args.account_external_id,
                start_date=args.start_date,
                end_date=args.end_date,
            )

        nav_dates = [s.report_date for s in snapshots]
        flows_by_date, dropped_flow_count = align_flows_to_nav_dates(flows, nav_dates)
        rows = calculate_twr(snapshots, flows_by_date, flow_timing=args.flow_timing)

        if args.daily_output is not None:
            write_daily_twr_csv(args.daily_output, rows)

        _print_summary(
            rows,
            brokerage_code=args.brokerage_code,
            account_external_id=args.account_external_id,
            snapshots=snapshots,
            flows=flows,
            flow_timing=args.flow_timing,
            dropped_flow_count=dropped_flow_count,
            daily_output=args.daily_output,
            stdout=stdout,
        )
        return 0

    except Exception as error:
        stderr.write(f"Error: {error}\n")
        return 1


def main(argv: list[str] | None = None) -> int:
    return run(argv)


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise DatabaseTwrCliError(
            f"invalid date '{value}': expected YYYY-MM-DD format"
        )


def _validate_date_range(start: date, end: date) -> None:
    if start > end:
        raise DatabaseTwrCliError("--start-date must be on or before --end-date")


def _format_percent(value: Decimal) -> str:
    return f"{value * Decimal('100'):.6f}%"


def _print_summary(
    rows: list[TwrRow],
    *,
    brokerage_code: str,
    account_external_id: str,
    snapshots: list[NavSnapshot],
    flows: list[CashFlow],
    flow_timing: str,
    dropped_flow_count: int,
    daily_output: Path | None,
    stdout: TextIO,
) -> None:
    completed_rows = [r for r in rows if r.period_return is not None]
    first_date = snapshots[0].report_date
    last_date = snapshots[-1].report_date
    final_twr = rows[-1].cumulative_twr if rows else Decimal("0")

    stdout.write(f"Brokerage: {brokerage_code}\n")
    stdout.write(f"Account: {account_external_id}\n")
    stdout.write(f"NAV snapshots: {len(snapshots)}\n")
    stdout.write(f"Cash-flow records: {len(flows)}\n")
    stdout.write(f"Return periods: {len(completed_rows)}\n")
    stdout.write(f"Date range: {first_date} to {last_date}\n")
    stdout.write(f"Cash-flow type: {DEPOSIT_WITHDRAWAL_CASH_FLOW_TYPE}\n")
    stdout.write(f"Cash-flow timing: {flow_timing}\n")
    if dropped_flow_count:
        stdout.write(
            f"Warning: {dropped_flow_count} cash-flow record(s) fell outside the NAV date range and were dropped.\n"
        )
    stdout.write(f"TWR: {_format_percent(final_twr)}\n")
    if daily_output is not None:
        stdout.write(f"Daily output written to {daily_output}\n")
