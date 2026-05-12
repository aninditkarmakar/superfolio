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

# Safe keys for privacy: exclude amounts, NAV values, and raw payloads
_CASH_FLOW_SAFE_KEYS = frozenset(
    {"account_external_id", "dedupe_key", "source_currency", "flow_date"}
)
_DAILY_NAV_SAFE_KEYS = frozenset(
    {"account_external_id", "dedupe_key", "source_currency", "snapshot_date"}
)


def _safe_cash_flow_record(bulk: dict[str, Any]) -> dict[str, Any]:
    """Project cash flow record to safe fields only (no amounts or payloads)."""
    return {k: v for k, v in bulk.items() if k in _CASH_FLOW_SAFE_KEYS}


def _safe_daily_nav_record(bulk: dict[str, Any]) -> dict[str, Any]:
    """Project daily NAV record to safe fields only (no NAV values or payloads)."""
    return {k: v for k, v in bulk.items() if k in _DAILY_NAV_SAFE_KEYS}


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
    account_external_id: str | None = None
    skipped_other_account_cash_flow_count: int = 0
    skipped_other_account_daily_nav_count: int = 0

    @property
    def cash_flow_count(self) -> int:
        return len(self.cash_flow_records)

    @property
    def daily_nav_count(self) -> int:
        return len(self.daily_nav_records)


# NOTE: Public fields mirror FlexDryRunSummary and AccountScopedFlexAnalysisResult exactly.
# Private fields (starting with _) are internal only and not exposed in summaries.
# Keep public fields in sync when adding new public fields.
#
# Do not serialize FlexAnalysisResult with dataclasses.asdict(); it contains
# internal fields used only to derive account-scoped safe summaries.
@dataclass(frozen=True)
class FlexAnalysisResult:
    cash_flow_records: tuple[dict[str, Any], ...]
    daily_nav_records: tuple[dict[str, Any], ...]
    unsupported_cash_transaction_count: int
    accounts_seen: tuple[str, ...]
    currencies_seen: tuple[str, ...]
    cash_flow_date_range: DateRange | None
    daily_nav_date_range: DateRange | None
    duplicate_dedupe_keys: tuple[str, ...]
    account_external_id: str | None = None
    skipped_other_account_cash_flow_count: int = 0
    skipped_other_account_daily_nav_count: int = 0
    _unsupported_cash_transaction_account_ids: tuple[str, ...] = ()

    @property
    def cash_flow_count(self) -> int:
        return len(self.cash_flow_records)

    @property
    def daily_nav_count(self) -> int:
        return len(self.daily_nav_records)

    def to_dry_run_summary(self) -> FlexDryRunSummary:
        safe_cash_records = tuple(
            _safe_cash_flow_record(record) for record in self.cash_flow_records
        )
        safe_nav_records = tuple(
            _safe_daily_nav_record(record) for record in self.daily_nav_records
        )
        return FlexDryRunSummary(
            cash_flow_records=safe_cash_records,
            daily_nav_records=safe_nav_records,
            unsupported_cash_transaction_count=self.unsupported_cash_transaction_count,
            accounts_seen=self.accounts_seen,
            currencies_seen=self.currencies_seen,
            cash_flow_date_range=self.cash_flow_date_range,
            daily_nav_date_range=self.daily_nav_date_range,
            duplicate_dedupe_keys=self.duplicate_dedupe_keys,
            account_external_id=self.account_external_id,
            skipped_other_account_cash_flow_count=self.skipped_other_account_cash_flow_count,
            skipped_other_account_daily_nav_count=self.skipped_other_account_daily_nav_count,
        )

    def for_account(self, account_external_id: str) -> AccountScopedFlexAnalysisResult:
        target = account_external_id.strip()
        cash_flow_records = tuple(
            record for record in self.cash_flow_records
            if str(record["account_external_id"]) == target
        )
        daily_nav_records = tuple(
            record for record in self.daily_nav_records
            if str(record["account_external_id"]) == target
        )
        all_records = list(cash_flow_records + daily_nav_records)
        # Count unsupported cash transactions for this account only
        unsupported_count = sum(
            1 for account_id in self._unsupported_cash_transaction_account_ids
            if account_id == target
        )
        return AccountScopedFlexAnalysisResult(
            account_external_id=target,
            cash_flow_records=cash_flow_records,
            daily_nav_records=daily_nav_records,
            unsupported_cash_transaction_count=unsupported_count,
            accounts_seen=(target,) if (cash_flow_records or daily_nav_records) else (),
            currencies_seen=_sorted_unique(record["source_currency"] for record in all_records),
            cash_flow_date_range=_record_date_range(list(cash_flow_records), "flow_date"),
            daily_nav_date_range=_record_date_range(list(daily_nav_records), "snapshot_date"),
            duplicate_dedupe_keys=_duplicate_dedupe_keys(all_records),
            skipped_other_account_cash_flow_count=len(self.cash_flow_records) - len(cash_flow_records),
            skipped_other_account_daily_nav_count=len(self.daily_nav_records) - len(daily_nav_records),
        )


@dataclass(frozen=True)
class AccountScopedFlexAnalysisResult:
    account_external_id: str
    cash_flow_records: tuple[dict[str, Any], ...]
    daily_nav_records: tuple[dict[str, Any], ...]
    unsupported_cash_transaction_count: int
    accounts_seen: tuple[str, ...]
    currencies_seen: tuple[str, ...]
    cash_flow_date_range: DateRange | None
    daily_nav_date_range: DateRange | None
    duplicate_dedupe_keys: tuple[str, ...]
    skipped_other_account_cash_flow_count: int
    skipped_other_account_daily_nav_count: int

    @property
    def cash_flow_count(self) -> int:
        return len(self.cash_flow_records)

    @property
    def daily_nav_count(self) -> int:
        return len(self.daily_nav_records)

    def to_dry_run_summary(self) -> FlexDryRunSummary:
        return FlexDryRunSummary(
            cash_flow_records=tuple(_safe_cash_flow_record(record) for record in self.cash_flow_records),
            daily_nav_records=tuple(_safe_daily_nav_record(record) for record in self.daily_nav_records),
            unsupported_cash_transaction_count=self.unsupported_cash_transaction_count,
            accounts_seen=self.accounts_seen,
            currencies_seen=self.currencies_seen,
            cash_flow_date_range=self.cash_flow_date_range,
            daily_nav_date_range=self.daily_nav_date_range,
            duplicate_dedupe_keys=self.duplicate_dedupe_keys,
            account_external_id=self.account_external_id,
            skipped_other_account_cash_flow_count=self.skipped_other_account_cash_flow_count,
            skipped_other_account_daily_nav_count=self.skipped_other_account_daily_nav_count,
        )


def analyze_flex_xml_file(
    path: Path,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    account_external_id: str | None = None,
) -> FlexDryRunSummary:
    result = analyze_flex_xml_file_for_ingestion(
        path,
        start_date=start_date,
        end_date=end_date,
    )
    if account_external_id is not None:
        return result.for_account(account_external_id).to_dry_run_summary()
    return result.to_dry_run_summary()


def analyze_flex_xml_file_for_ingestion(
    path: Path,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> FlexAnalysisResult:
    return analyze_flex_xml_text_for_ingestion(
        path.read_text(encoding="utf-8"),
        start_date=start_date,
        end_date=end_date,
    )


def analyze_flex_xml_text(
    xml_text: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    account_external_id: str | None = None,
) -> FlexDryRunSummary:
    result = analyze_flex_xml_text_for_ingestion(
        xml_text,
        start_date=start_date,
        end_date=end_date,
    )
    if account_external_id is not None:
        return result.for_account(account_external_id).to_dry_run_summary()
    return result.to_dry_run_summary()


def analyze_flex_xml_text_for_ingestion(
    xml_text: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> FlexAnalysisResult:
    root = ElementTree.fromstring(xml_text)
    cash_flow_records: list[dict[str, Any]] = []
    daily_nav_records: list[dict[str, Any]] = []
    unsupported_cash_transaction_count = 0
    unsupported_account_ids: list[str] = []

    # Single XML walk to process both cash transactions and daily NAV records
    for element in root.iter():
        if element.tag == "CashTransaction":
            raw = dict(element.attrib)
            if raw.get("type") != DEFAULT_CASH_FLOW_TYPE:
                unsupported_cash_transaction_count += 1
                unsupported_account_ids.append(raw.get("accountId", ""))
                continue

            source_report_date = flex_date_to_payload(
                require_attribute(raw, "reportDate")
            )
            if not in_date_range(source_report_date, start_date, end_date):
                continue

            cash_flow_records.append(map_cash_transaction_attributes(raw).to_bulk_record())

        elif element.tag == "EquitySummaryByReportDateInBase":
            raw = dict(element.attrib)
            source_report_date = flex_date_to_payload(
                require_attribute(raw, "reportDate")
            )
            if not in_date_range(source_report_date, start_date, end_date):
                continue

            daily_nav_records.append(map_daily_nav_attributes(raw).to_bulk_record())

    all_records = cash_flow_records + daily_nav_records
    return FlexAnalysisResult(
        cash_flow_records=tuple(cash_flow_records),
        daily_nav_records=tuple(daily_nav_records),
        unsupported_cash_transaction_count=unsupported_cash_transaction_count,
        accounts_seen=_sorted_unique(record["account_external_id"] for record in all_records),
        currencies_seen=_sorted_unique(record["source_currency"] for record in all_records),
        cash_flow_date_range=_record_date_range(cash_flow_records, "flow_date"),
        daily_nav_date_range=_record_date_range(daily_nav_records, "snapshot_date"),
        duplicate_dedupe_keys=_duplicate_dedupe_keys(all_records),
        _unsupported_cash_transaction_account_ids=tuple(unsupported_account_ids),
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
