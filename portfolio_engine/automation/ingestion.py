"""Per-account ingestion helpers for automation runs."""
from __future__ import annotations

from datetime import date
from typing import Any

from portfolio_engine.automation.summary import build_child_summary
from portfolio_engine.database import BulkIngestionSummary, IngestionRunStart
from portfolio_engine.ingestion.dry_run import analyze_flex_xml_text_for_ingestion


def dry_run_payload(
    xml_text: str,
    *,
    account_external_id: str,
    start_date: str,
    end_date: str,
) -> dict[str, object]:
    """Analyze a broker XML payload for dry-run and return a child summary dict.

    Parses the XML, filters records to the given account, and builds a child
    summary with supported counts and skipped-other-account counts.  No data
    is written to the database.
    """
    result = analyze_flex_xml_text_for_ingestion(
        xml_text, start_date=start_date, end_date=end_date
    )
    analysis = result.for_account(account_external_id)
    return build_child_summary(
        cash_supported=analysis.cash_flow_count,
        nav_supported=analysis.daily_nav_count,
        cash_skipped_other_account=analysis.skipped_other_account_cash_flow_count,
        nav_skipped_other_account=analysis.skipped_other_account_daily_nav_count,
    )


def load_payload(
    xml_text: str,
    *,
    database: Any,
    brokerage_code: str,
    account_external_id: str,
    source_type: str,
    source_name: str | None,
    start_date: str,
    end_date: str,
) -> tuple[str, str, dict[str, object], str | None]:
    """Parse and ingest a broker XML payload for one account.

    Returns (ingestion_run_id, status, child_summary, error_message).
    """
    result = analyze_flex_xml_text_for_ingestion(
        xml_text, start_date=start_date, end_date=end_date
    )
    analysis = result.for_account(account_external_id)

    ingestion_run_id = database.start_ingestion_run(
        IngestionRunStart(
            brokerage_code=brokerage_code,
            account_external_id=account_external_id,
            source_type=source_type,
            requested_start_date=date.fromisoformat(start_date),
            requested_end_date=date.fromisoformat(end_date),
            source_filename=source_name,
        )
    )

    cash_summary = _empty_bulk_summary()
    nav_summary = _empty_bulk_summary()
    if analysis.cash_flow_records:
        cash_summary = database.bulk_ingest_cash_flows(
            ingestion_run_id, list(analysis.cash_flow_records)
        )
    if analysis.daily_nav_records:
        nav_summary = database.bulk_ingest_daily_nav_snapshots(
            ingestion_run_id, list(analysis.daily_nav_records)
        )

    status = _derive_ingestion_status(cash_summary, nav_summary)
    message: str | None = (
        "skipped accounts or conflicts require review"
        if status == "partially_succeeded"
        else None
    )

    database.complete_ingestion_run(
        ingestion_run_id=ingestion_run_id,
        status=status,
        error_message=message,
    )

    child_summary = build_child_summary(
        cash_supported=analysis.cash_flow_count,
        cash_inserted=cash_summary.inserted_count,
        cash_duplicates=cash_summary.duplicate_count,
        cash_skipped_unknown_account=cash_summary.skipped_unknown_account_count,
        cash_skipped_inactive_account=cash_summary.skipped_inactive_account_count,
        cash_skipped_other_account=analysis.skipped_other_account_cash_flow_count,
        cash_conflicts=cash_summary.conflict_count,
        nav_supported=analysis.daily_nav_count,
        nav_inserted=nav_summary.inserted_count,
        nav_duplicates=nav_summary.duplicate_count,
        nav_skipped_unknown_account=nav_summary.skipped_unknown_account_count,
        nav_skipped_inactive_account=nav_summary.skipped_inactive_account_count,
        nav_skipped_other_account=analysis.skipped_other_account_daily_nav_count,
        nav_conflicts=nav_summary.conflict_count,
    )

    return ingestion_run_id, status, child_summary, message


def _empty_bulk_summary() -> BulkIngestionSummary:
    return BulkIngestionSummary(
        inserted_count=0,
        duplicate_count=0,
        skipped_unknown_account_count=0,
        skipped_inactive_account_count=0,
        conflict_count=0,
        skipped_accounts=[],
        record_results=[],
    )


def _derive_ingestion_status(
    cash_summary: BulkIngestionSummary,
    nav_summary: BulkIngestionSummary,
) -> str:
    """Return 'partially_succeeded' if any skips or conflicts exist, else 'succeeded'."""
    if _has_partial_conditions(cash_summary) or _has_partial_conditions(nav_summary):
        return "partially_succeeded"
    return "succeeded"


def _has_partial_conditions(summary: BulkIngestionSummary) -> bool:
    return (
        summary.skipped_unknown_account_count > 0
        or summary.skipped_inactive_account_count > 0
        or summary.conflict_count > 0
    )
