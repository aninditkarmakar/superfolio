"""Time-weighted return calculations."""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import date
from decimal import Decimal

from .models import CashFlow, NavSnapshot, TwrRow


def align_flows_to_nav_dates(
    flows: list[CashFlow], nav_dates: list[date]
) -> tuple[dict[date, Decimal], int]:
    flows_by_date: defaultdict[date, Decimal] = defaultdict(Decimal)
    dropped_flow_count = 0

    for flow in flows:
        nav_index = bisect_left(nav_dates, flow.effective_date)
        if nav_index == len(nav_dates):
            dropped_flow_count += 1
            continue

        flows_by_date[nav_dates[nav_index]] += flow.amount_base

    return dict(flows_by_date), dropped_flow_count


def calculate_twr(
    snapshots: list[NavSnapshot],
    flows_by_date: dict[date, Decimal],
    *,
    flow_timing: str = "start",
) -> list[TwrRow]:
    rows: list[TwrRow] = []
    cumulative_factor = Decimal("1")
    previous_nav: Decimal | None = None

    for snapshot in snapshots:
        net_flow = flows_by_date.get(snapshot.report_date, Decimal("0"))
        period_return: Decimal | None = None

        if previous_nav is not None and previous_nav != 0:
            if flow_timing == "end":
                period_return = (snapshot.total_base - net_flow) / previous_nav - Decimal("1")
            else:
                denominator = previous_nav + net_flow
                if denominator != 0:
                    period_return = snapshot.total_base / denominator - Decimal("1")

        if period_return is not None:
            cumulative_factor *= Decimal("1") + period_return

        rows.append(
            TwrRow(
                report_date=snapshot.report_date,
                ending_nav_base=snapshot.total_base,
                net_cash_flow_base=net_flow,
                period_return=period_return,
                cumulative_twr=cumulative_factor - Decimal("1"),
            )
        )
        previous_nav = snapshot.total_base

    return rows
