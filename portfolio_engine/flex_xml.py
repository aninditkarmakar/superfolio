"""IBKR Flex XML parsing adapters."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree

from .models import CashFlow, NavSnapshot


def parse_flex_date(value: str | None) -> date:
    if not value:
        raise ValueError("missing Flex date")

    return datetime.strptime(value[:8], "%Y%m%d").date()


def parse_decimal(value: str | None, *, field_name: str) -> Decimal:
    if value in (None, ""):
        return Decimal("0")

    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"invalid decimal for {field_name}: {value!r}") from error


def parse_cash_flows_from_flex_xml(
    path: Path,
    *,
    date_field: str,
    cash_flow_type: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[CashFlow]:
    root = ElementTree.parse(path).getroot()
    flows: list[CashFlow] = []

    for element in root.iter("CashTransaction"):
        transaction_type = element.attrib.get("type", "")
        if cash_flow_type and transaction_type != cash_flow_type:
            continue

        effective_date = parse_flex_date(element.attrib.get(date_field))
        if start_date and effective_date < start_date:
            continue
        if end_date and effective_date > end_date:
            continue

        amount = parse_decimal(element.attrib.get("amount"), field_name="amount")
        fx_rate = parse_decimal(element.attrib.get("fxRateToBase"), field_name="fxRateToBase")
        flows.append(CashFlow(effective_date=effective_date, amount_base=amount * fx_rate))

    return sorted(flows, key=lambda flow: flow.effective_date)


def parse_nav_snapshots_from_flex_xml(
    path: Path,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[NavSnapshot]:
    root = ElementTree.parse(path).getroot()
    snapshots: list[NavSnapshot] = []

    for element in root.iter("EquitySummaryByReportDateInBase"):
        report_date = parse_flex_date(element.attrib.get("reportDate"))
        if start_date and report_date < start_date:
            continue
        if end_date and report_date > end_date:
            continue

        snapshots.append(
            NavSnapshot(
                report_date=report_date,
                total_base=parse_decimal(element.attrib.get("total"), field_name="total"),
            )
        )

    return sorted(snapshots, key=lambda snapshot: snapshot.report_date)
