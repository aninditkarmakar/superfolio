"""CSV export helpers for portfolio calculation outputs."""

from __future__ import annotations

import csv
from pathlib import Path

from .models import PortfolioTwrRow, TwrRow


def write_daily_twr_csv(path: Path, rows: list[TwrRow]) -> None:
    with path.open("w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            [
                "date",
                "ending_nav_base",
                "net_cash_flow_base",
                "period_return",
                "cumulative_twr",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.report_date.isoformat(),
                    row.ending_nav_base,
                    row.net_cash_flow_base,
                    "" if row.period_return is None else row.period_return,
                    row.cumulative_twr,
                ]
            )


def write_portfolio_daily_twr_csv(path: Path, rows: list[PortfolioTwrRow]) -> None:
    with path.open("w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            [
                "date",
                "ending_nav_base",
                "net_cash_flow_base",
                "bridge_value_base",
                "missing_nav_accounts",
                "period_return",
                "cumulative_twr",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.report_date.isoformat(),
                    row.ending_nav_base,
                    row.net_cash_flow_base,
                    row.bridge_value_base,
                    ";".join(row.missing_nav_accounts),
                    "" if row.period_return is None else row.period_return,
                    row.cumulative_twr,
                ]
            )
