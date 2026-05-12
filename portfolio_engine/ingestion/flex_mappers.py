"""Flex XML ingestion payload mappers and helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from portfolio_engine.flex_xml import parse_decimal, parse_flex_date


BROKERAGE_CODE = "IBKR"
DEFAULT_CASH_FLOW_TYPE = "Deposits/Withdrawals"


@dataclass
class FlexCashTransactionPayload:
    """Ingestion payload for a Flex cash transaction record."""

    account_external_id: str
    external_record_id: str | None
    dedupe_key: str
    source_report_date: str
    source_currency: str
    raw_payload: dict[str, Any]
    flow_date: str
    cash_flow_type: str
    currency: str
    amount: str
    amount_base: str
    fx_rate_to_base: str | None
    description: str | None

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


def map_cash_transaction_attributes(
    raw: dict[str, str],
) -> FlexCashTransactionPayload:
    """Map one Flex CashTransaction attribute dict to an ingestion payload."""
    account_id = require_attribute(raw, "accountId")
    report_date = require_attribute(raw, "reportDate")
    source_currency = require_attribute(raw, "currency").upper()
    amount = parse_decimal(require_attribute(raw, "amount"), field_name="amount")
    cash_flow_type = require_attribute(raw, "type")

    raw_fx_rate = optional_blank_to_none(raw.get("fxRateToBase"))
    if raw_fx_rate is None:
        fx_rate = Decimal("1")
        fx_rate_payload = None
    else:
        fx_rate = parse_decimal(raw_fx_rate, field_name="fxRateToBase")
        fx_rate_payload = decimal_to_payload(fx_rate)

    source_report_date = flex_date_to_payload(report_date)

    return FlexCashTransactionPayload(
        account_external_id=account_id,
        external_record_id=optional_blank_to_none(raw.get("transactionID")),
        dedupe_key=build_cash_transaction_dedupe_key(raw),
        source_report_date=source_report_date,
        source_currency=source_currency,
        raw_payload=dict(raw),
        flow_date=source_report_date,
        cash_flow_type=cash_flow_type,
        currency=source_currency,
        amount=decimal_to_payload(amount),
        amount_base=decimal_to_payload(amount * fx_rate),
        fx_rate_to_base=fx_rate_payload,
        description=optional_blank_to_none(raw.get("description")),
    )


def _date_to_iso(value: date | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return value


def map_cash_transactions_from_flex_xml_text(
    xml_text: str,
    *,
    cash_flow_type: str = DEFAULT_CASH_FLOW_TYPE,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
) -> list[dict[str, Any]]:
    """Map Flex CashTransaction elements in XML text to DB bulk records."""
    root = ElementTree.fromstring(xml_text)
    start_date_iso = _date_to_iso(start_date)
    end_date_iso = _date_to_iso(end_date)
    records: list[dict[str, Any]] = []

    for element in root.iter("CashTransaction"):
        raw = dict(element.attrib)
        if cash_flow_type and raw.get("type") != cash_flow_type:
            continue

        source_report_date = flex_date_to_payload(require_attribute(raw, "reportDate"))
        if not in_date_range(source_report_date, start_date_iso, end_date_iso):
            continue

        records.append(map_cash_transaction_attributes(raw).to_bulk_record())

    return records


def map_cash_transactions_from_flex_xml_file(
    path: Path,
    *,
    cash_flow_type: str = DEFAULT_CASH_FLOW_TYPE,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
) -> list[dict[str, Any]]:
    """Read a UTF-8 Flex XML file and map CashTransaction records."""
    return map_cash_transactions_from_flex_xml_text(
        path.read_text(encoding="utf-8"),
        cash_flow_type=cash_flow_type,
        start_date=start_date,
        end_date=end_date,
    )
