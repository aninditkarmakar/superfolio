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


@dataclass(frozen=True)
class AccountRef:
    brokerage_code: str
    external_id: str
    base_currency: str
    display_name: str | None = None

    @property
    def label(self) -> str:
        return f"{self.brokerage_code}:{self.external_id}"


@dataclass(frozen=True)
class PortfolioSummary:
    name: str
    reporting_currency: str
    is_active: bool


@dataclass(frozen=True)
class PortfolioCashFlow:
    account: AccountRef
    effective_date: date
    amount_base: Decimal
    base_currency: str

    def __post_init__(self) -> None:
        if self.base_currency != self.account.base_currency:
            raise ValueError(
                f"cash-flow base currency {self.base_currency} does not match "
                f"account base currency {self.account.base_currency}"
            )


@dataclass(frozen=True)
class PortfolioDailyInput:
    account: AccountRef
    report_date: date
    nav_base: Decimal
    nav_currency: str

    def __post_init__(self) -> None:
        if self.nav_currency != self.account.base_currency:
            raise ValueError(
                f"NAV currency {self.nav_currency} does not match "
                f"account base currency {self.account.base_currency}"
            )


@dataclass(frozen=True)
class TransferBridge:
    source_account: AccountRef
    destination_account: AccountRef
    departure_date: date
    arrival_date: date
    value: Decimal
    currency: str
    note: str | None = None

    def __post_init__(self) -> None:
        if self.source_account == self.destination_account:
            raise ValueError("transfer bridge source and destination accounts must differ")
        if self.arrival_date < self.departure_date:
            raise ValueError("arrival_date must be on or after departure_date")
        if self.value <= 0:
            raise ValueError("transfer bridge value must be positive")


@dataclass(frozen=True)
class PortfolioTwrRow:
    report_date: date
    ending_nav_base: Decimal
    net_cash_flow_base: Decimal
    bridge_value_base: Decimal
    missing_nav_accounts: tuple[str, ...]
    period_return: Decimal | None
    cumulative_twr: Decimal
