"""Shared domain models for portfolio calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class CashFlow:
    effective_date: date
    amount_base: Decimal


@dataclass(frozen=True)
class NavSnapshot:
    report_date: date
    total_base: Decimal


@dataclass(frozen=True)
class TwrRow:
    report_date: date
    ending_nav_base: Decimal
    net_cash_flow_base: Decimal
    period_return: Decimal | None
    cumulative_twr: Decimal
