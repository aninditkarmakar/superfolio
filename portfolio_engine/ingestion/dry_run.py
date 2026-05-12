"""Dry-run analysis for manual Flex XML ingestion files."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable
from typing import Any
from xml.etree import ElementTree

from portfolio_engine.ingestion.flex_mappers import (
    DEFAULT_CASH_FLOW_TYPE,
    flex_date_to_payload,
    in_date_range,
    map_cash_transaction_attributes,
    map_daily_nav_attributes,
    require_attribute,
)


DateRange = tuple[str, str]


@dataclass(frozen=True)
class FlexDryRunSummary:
    cash_flow_records: tuple[dict[str, Any], ...]
    daily_nav_records: tuple[dict[str, Any], ...]
    unsupported_cash_transaction_count: int
    accounts_seen: tuple[str, ...]
    currencies_seen: tuple[str, ...]
    cash_flow_date_range: DateRange | None
    daily_nav_date_range: DateRange | None
    duplicate_dedupe_keys: tuple[str, ...]

    @property
    def cash_flow_count(self) -> int:
        return len(self.cash_flow_records)

    @property
    def daily_nav_count(self) -> int:
        return len(self.daily_nav_records)


def analyze_flex_xml_file(
    path: Path,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> FlexDryRunSummary:
    return analyze_flex_xml_text(
        path.read_text(encoding="utf-8"),
        start_date=start_date,
        end_date=end_date,
    )


def analyze_flex_xml_text(
    xml_text: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> FlexDryRunSummary:
    root = ElementTree.fromstring(xml_text)
    cash_flow_records: list[dict[str, Any]] = []
    daily_nav_records: list[dict[str, Any]] = []
    unsupported_cash_transaction_count = 0

    for element in root.iter("CashTransaction"):
        raw = dict(element.attrib)
        if raw.get("type") != DEFAULT_CASH_FLOW_TYPE:
            unsupported_cash_transaction_count += 1
            continue

        source_report_date = flex_date_to_payload(require_attribute(raw, "reportDate"))
        if not in_date_range(source_report_date, start_date, end_date):
            continue

        cash_flow_records.append(map_cash_transaction_attributes(raw).to_bulk_record())

    for element in root.iter("EquitySummaryByReportDateInBase"):
        raw = dict(element.attrib)
        source_report_date = flex_date_to_payload(require_attribute(raw, "reportDate"))
        if not in_date_range(source_report_date, start_date, end_date):
            continue

        daily_nav_records.append(map_daily_nav_attributes(raw).to_bulk_record())

    all_records = cash_flow_records + daily_nav_records
    return FlexDryRunSummary(
        cash_flow_records=tuple(cash_flow_records),
        daily_nav_records=tuple(daily_nav_records),
        unsupported_cash_transaction_count=unsupported_cash_transaction_count,
        accounts_seen=_sorted_unique(record["account_external_id"] for record in all_records),
        currencies_seen=_sorted_unique(record["source_currency"] for record in all_records),
        cash_flow_date_range=_record_date_range(cash_flow_records, "flow_date"),
        daily_nav_date_range=_record_date_range(daily_nav_records, "snapshot_date"),
        duplicate_dedupe_keys=_duplicate_dedupe_keys(all_records),
    )


def _sorted_unique(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values}))


def _record_date_range(records: list[dict[str, Any]], field_name: str) -> DateRange | None:
    if not records:
        return None
    dates = sorted(str(record[field_name]) for record in records)
    return dates[0], dates[-1]


def _duplicate_dedupe_keys(records: list[dict[str, Any]]) -> tuple[str, ...]:
    counts = Counter(str(record["dedupe_key"]) for record in records)
    return tuple(sorted(key for key, count in counts.items() if count > 1))
