"""Per-account ingestion helpers for automation runs."""
from __future__ import annotations

from portfolio_engine.automation.summary import build_child_summary
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
