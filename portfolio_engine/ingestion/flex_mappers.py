"""Flex XML ingestion payload mappers and helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from portfolio_engine.flex_xml import parse_flex_date


BROKERAGE_CODE = "IBKR"
DEFAULT_CASH_FLOW_TYPE = "Deposits/Withdrawals"


@dataclass
class FlexCashTransactionPayload:
    """Ingestion payload for a Flex cash transaction record."""

    account_external_id: str
    external_record_id: str
    dedupe_key: str
    source_report_date: str
    source_currency: str
    raw_payload: dict[str, Any]
    flow_date: str
    cash_flow_type: str
    currency: str
    amount: str
    amount_base: str
    fx_rate_to_base: str
    description: str

    def to_bulk_record(self) -> dict[str, Any]:
        """Convert to bulk insert record."""
        return asdict(self)


@dataclass
class FlexDailyNavPayload:
    """Ingestion payload for a Flex daily NAV (EquitySummaryByReportDateInBase) record."""

    account_external_id: str
    external_record_id: str
    dedupe_key: str
    source_report_date: str
    source_currency: str
    raw_payload: dict[str, Any]
    snapshot_date: str
    base_currency: str
    nav_base: str

    def to_bulk_record(self) -> dict[str, Any]:
        """Convert to bulk insert record."""
        return asdict(self)


def flex_date_to_payload(value: str) -> str:
    """Convert Flex date string (YYYYMMDD) to ISO date string (YYYY-MM-DD)."""
    return parse_flex_date(value).isoformat()


def decimal_to_payload(value: Decimal) -> str:
    """Convert Decimal to string preserving all digits."""
    return str(value)


def require_attribute(raw: dict[str, Any], name: str) -> str:
    """Extract and validate required attribute from raw dict.

    Raises ValueError if the attribute is missing or blank.
    """
    value = raw.get(name)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        raise ValueError(f"missing required Flex attribute: {name}")
    return value


def optional_blank_to_none(value: str | None) -> str | None:
    """Convert blank strings to None."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def in_date_range(
    record_date: str, start_date: str | None, end_date: str | None
) -> bool:
    """Check if record_date falls within inclusive date range.

    Args:
        record_date: ISO date string (YYYY-MM-DD)
        start_date: Inclusive start date or None
        end_date: Inclusive end date or None

    Returns:
        True if record_date is within range.
    """
    if start_date is not None and record_date < start_date:
        return False
    if end_date is not None and record_date > end_date:
        return False
    return True


def build_cash_transaction_dedupe_key(raw: dict[str, Any]) -> str:
    """Build stable dedupe key for cash transaction.

    Prefers transactionID if available, otherwise uses fallback
    of reportDate, currency, amount, and description.
    """
    account_id = require_attribute(raw, "accountId")

    transaction_id = optional_blank_to_none(raw.get("transactionID"))
    if transaction_id:
        return f"{BROKERAGE_CODE}:{account_id}:CASH_TRANSACTION:{transaction_id}"

    report_date = require_attribute(raw, "reportDate")
    currency = require_attribute(raw, "currency")
    amount = require_attribute(raw, "amount")
    description = require_attribute(raw, "description")

    return f"{BROKERAGE_CODE}:{account_id}:CASH_TRANSACTION:{report_date}:{currency}:{amount}:{description}"


def build_daily_nav_dedupe_key(raw: dict[str, Any]) -> str:
    """Build dedupe key for daily NAV snapshot."""
    account_id = require_attribute(raw, "accountId")
    report_date = require_attribute(raw, "reportDate")

    return f"{BROKERAGE_CODE}:{account_id}:DAILY_NAV:{report_date}"
