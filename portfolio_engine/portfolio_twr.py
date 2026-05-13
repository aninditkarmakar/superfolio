"""Portfolio-level TWR aggregation."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

from .models import (
    AccountRef,
    CashFlow,
    NavSnapshot,
    PortfolioCashFlow,
    PortfolioDailyInput,
    PortfolioTwrRow,
    TransferBridge,
)
from .twr import align_flows_to_nav_dates, calculate_twr


class PortfolioTwrError(RuntimeError):
    """Raised when portfolio TWR inputs are invalid."""


def calculate_portfolio_twr(
    *,
    reporting_currency: str,
    accounts: list[AccountRef],
    nav_inputs: list[PortfolioDailyInput],
    cash_flows: list[PortfolioCashFlow],
    transfer_bridges: list[TransferBridge],
    flow_timing: str = "start",
) -> list[PortfolioTwrRow]:
    if not accounts:
        raise PortfolioTwrError("Portfolio has no member accounts.")

    normalized_reporting_currency = reporting_currency.upper()
    for account in accounts:
        if account.base_currency.upper() != normalized_reporting_currency:
            raise PortfolioTwrError(
                f"Account {account.label} base currency {account.base_currency} "
                f"does not match portfolio reporting currency {normalized_reporting_currency}."
            )

    account_labels = tuple(account.label for account in accounts)
    account_label_set = set(account_labels)

    nav_by_date_account: dict[date, dict[str, Decimal]] = defaultdict(dict)
    for nav in nav_inputs:
        if nav.nav_currency.upper() != normalized_reporting_currency:
            raise PortfolioTwrError(
                f"NAV currency {nav.nav_currency} for {nav.account.label} does not match "
                f"portfolio reporting currency {normalized_reporting_currency}."
            )
        if nav.account.label not in account_label_set:
            raise PortfolioTwrError(f"NAV input account {nav.account.label} is not a member of the portfolio.")
        if nav.account.label in nav_by_date_account[nav.report_date]:
            raise PortfolioTwrError(
                f"Duplicate NAV input for {nav.account.label} on {nav.report_date}."
            )
        nav_by_date_account[nav.report_date][nav.account.label] = nav.nav_base

    if not nav_by_date_account:
        raise PortfolioTwrError("No NAV snapshots found for the selected portfolio and date range.")

    aligned_flow_inputs: list[CashFlow] = []
    for flow in cash_flows:
        if flow.base_currency.upper() != normalized_reporting_currency:
            raise PortfolioTwrError(
                f"Cash-flow currency {flow.base_currency} for {flow.account.label} does not match "
                f"portfolio reporting currency {normalized_reporting_currency}."
            )
        if flow.account.label not in account_label_set:
            raise PortfolioTwrError(
                f"Cash-flow account {flow.account.label} is not a member of the portfolio."
            )
        aligned_flow_inputs.append(CashFlow(flow.effective_date, flow.amount_base))

    bridge_value_by_date: defaultdict[date, Decimal] = defaultdict(Decimal)
    nav_dates = sorted(nav_by_date_account)
    flows_by_date, dropped_flow_count = align_flows_to_nav_dates(aligned_flow_inputs, nav_dates)
    if dropped_flow_count:
        raise PortfolioTwrError(
            f"{dropped_flow_count} cash-flow record(s) fell outside the NAV date range."
        )
    for bridge in transfer_bridges:
        if bridge.currency.upper() != normalized_reporting_currency:
            raise PortfolioTwrError(
                f"Bridge currency {bridge.currency} does not match portfolio reporting currency "
                f"{normalized_reporting_currency}."
            )
        if bridge.source_account.label not in account_label_set:
            raise PortfolioTwrError(
                f"Bridge source account {bridge.source_account.label} is not a member of the portfolio."
            )
        if bridge.destination_account.label not in account_label_set:
            raise PortfolioTwrError(
                f"Bridge destination account {bridge.destination_account.label} is not a member of the portfolio."
            )
        for nav_date in nav_dates:
            if bridge.departure_date < nav_date < bridge.arrival_date:
                bridge_value_by_date[nav_date] += bridge.value

    portfolio_snapshots: list[NavSnapshot] = []
    missing_by_date: dict[date, tuple[str, ...]] = {}
    bridge_by_date: dict[date, Decimal] = {}

    for nav_date in nav_dates:
        account_navs = nav_by_date_account[nav_date]
        missing = tuple(label for label in account_labels if label not in account_navs)
        missing_by_date[nav_date] = missing
        bridge_value = bridge_value_by_date.get(nav_date, Decimal("0"))
        bridge_by_date[nav_date] = bridge_value
        total_nav = sum(account_navs.values(), Decimal("0")) + bridge_value
        portfolio_snapshots.append(NavSnapshot(report_date=nav_date, total_base=total_nav))

    twr_rows = calculate_twr(
        portfolio_snapshots,
        flows_by_date,
        flow_timing=flow_timing,
    )

    return [
        PortfolioTwrRow(
            report_date=row.report_date,
            ending_nav_base=row.ending_nav_base,
            net_cash_flow_base=row.net_cash_flow_base,
            bridge_value_base=bridge_by_date[row.report_date],
            missing_nav_accounts=missing_by_date[row.report_date],
            period_return=row.period_return,
            cumulative_twr=row.cumulative_twr,
        )
        for row in twr_rows
    ]


def missing_nav_counts(rows: list[PortfolioTwrRow]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(row.missing_nav_accounts)
    return counts
