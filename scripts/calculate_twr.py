#!/usr/bin/env python3
"""CLI for calculating Time-Weighted Return from IBKR Flex XML files."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from portfolio_engine.csv_export import write_daily_twr_csv
from portfolio_engine.flex_xml import (
    parse_cash_flows_from_flex_xml,
    parse_nav_snapshots_from_flex_xml,
)
from portfolio_engine.twr import align_flows_to_nav_dates, calculate_twr


DEFAULT_CASH_FLOWS = Path("scratch/Cash_Flows.xml")
DEFAULT_DAILY_NAV = Path("scratch/Daily_NAV.xml")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate daily linked TWR from IBKR Flex cash-flow and daily NAV XML."
    )
    parser.add_argument(
        "--cash-flows",
        type=Path,
        default=DEFAULT_CASH_FLOWS,
        help=f"Cash-flow Flex XML path. Default: {DEFAULT_CASH_FLOWS}",
    )
    parser.add_argument(
        "--daily-nav",
        type=Path,
        default=DEFAULT_DAILY_NAV,
        help=f"Daily NAV Flex XML path. Default: {DEFAULT_DAILY_NAV}",
    )
    parser.add_argument(
        "--flow-date-field",
        choices=("reportDate", "dateTime", "settleDate", "availableForTradingDate"),
        default="reportDate",
        help="CashTransaction date attribute used to align flows to NAV dates.",
    )
    parser.add_argument(
        "--flow-timing",
        choices=("end", "start"),
        default="start",
        help=(
            "Daily return convention. 'end' uses (ending NAV - flow) / beginning NAV - 1. "
            "'start' uses ending NAV / (beginning NAV + flow) - 1."
        ),
    )
    parser.add_argument(
        "--cash-flow-type",
        default="Deposits/Withdrawals",
        help="CashTransaction type to include. Use an empty string to include all types.",
    )
    parser.add_argument("--start-date", type=parse_iso_date, help="Optional YYYY-MM-DD start date.")
    parser.add_argument("--end-date", type=parse_iso_date, help="Optional YYYY-MM-DD end date.")
    parser.add_argument(
        "--daily-output",
        type=Path,
        help="Optional CSV path for daily NAV, cash-flow, period-return, and cumulative-TWR rows.",
    )
    return parser.parse_args()


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}; expected YYYY-MM-DD") from error


def format_percent(value: Decimal) -> str:
    return f"{value * Decimal('100'):.6f}%"


def main() -> None:
    args = parse_args()
    snapshots = parse_nav_snapshots_from_flex_xml(
        args.daily_nav,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    if not snapshots:
        raise SystemExit("No NAV snapshots found for the selected date range.")

    flows = parse_cash_flows_from_flex_xml(
        args.cash_flows,
        date_field=args.flow_date_field,
        cash_flow_type=args.cash_flow_type,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    flows_by_date, dropped_flow_count = align_flows_to_nav_dates(
        flows, [snapshot.report_date for snapshot in snapshots]
    )
    rows = calculate_twr(snapshots, flows_by_date, flow_timing=args.flow_timing)

    completed_rows = [row for row in rows if row.period_return is not None]
    final_row = rows[-1]

    print(f"NAV snapshots: {len(snapshots)}")
    print(f"Cash-flow records: {len(flows)}")
    print(f"Return periods: {len(completed_rows)}")
    print(f"Date range: {snapshots[0].report_date.isoformat()} to {snapshots[-1].report_date.isoformat()}")
    print(f"Cash-flow date field: {args.flow_date_field}")
    print(f"Cash-flow timing: {args.flow_timing}")
    if dropped_flow_count:
        print(f"Warning: dropped {dropped_flow_count} cash flow(s) after the final NAV date.")
    print(f"TWR: {format_percent(final_row.cumulative_twr)}")

    if args.daily_output:
        write_daily_twr_csv(args.daily_output, rows)
        print(f"Daily output written to {args.daily_output}")


if __name__ == "__main__":
    main()