from __future__ import annotations

import unittest
from xml.etree import ElementTree

from portfolio_engine.ingestion.dry_run import (
    analyze_flex_xml_file_for_ingestion,
    analyze_flex_xml_text,
    analyze_flex_xml_text_for_ingestion,
    FlexAnalysisResult,
    FlexDryRunSummary,
)


MIXED_XML = """<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement>
      <CashTransactions>
        <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="1000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" description="Synthetic deposit" />
        <CashTransaction accountId="U100" reportDate="20250103" dateTime="20250103;101500" currency="USD" amount="5.00" fxRateToBase="1" type="Broker Interest Paid" transactionID="INT1" description="Unsupported interest" />
      </CashTransactions>
      <EquitySummaryInBase>
        <EquitySummaryByReportDateInBase accountId="U100" reportDate="20250102" currency="USD" total="10000.00" />
        <EquitySummaryByReportDateInBase accountId="U200" reportDate="20250103" currency="CAD" total="20000.00" />
      </EquitySummaryInBase>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""

MIXED_ACCOUNT_XML = """<FlexQueryResponse>
  <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="1000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" />
  <CashTransaction accountId="U200" reportDate="20250102" dateTime="20250102;091501" currency="USD" amount="2000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF2" />
  <EquitySummaryByReportDateInBase accountId="U100" reportDate="20250102" currency="USD" total="10000.00" />
  <EquitySummaryByReportDateInBase accountId="U200" reportDate="20250102" currency="USD" total="20000.00" />
</FlexQueryResponse>"""


class FlexDryRunTests(unittest.TestCase):
    def test_mixed_xml_maps_supported_cash_and_nav_records(self) -> None:
        summary = analyze_flex_xml_text(MIXED_XML)

        self.assertEqual(summary.cash_flow_count, 1)
        self.assertEqual(summary.daily_nav_count, 2)
        self.assertEqual(summary.unsupported_cash_transaction_count, 1)
        self.assertEqual(summary.accounts_seen, ("U100", "U200"))
        self.assertEqual(summary.currencies_seen, ("CAD", "USD"))
        self.assertEqual(summary.cash_flow_date_range, ("2025-01-02", "2025-01-02"))
        self.assertEqual(summary.daily_nav_date_range, ("2025-01-02", "2025-01-03"))
        self.assertEqual(summary.duplicate_dedupe_keys, ())

    def test_date_filter_applies_to_supported_record_types(self) -> None:
        summary = analyze_flex_xml_text(
            MIXED_XML,
            start_date="2025-01-03",
            end_date="2025-01-03",
        )

        self.assertEqual(summary.cash_flow_count, 0)
        self.assertEqual(summary.daily_nav_count, 1)
        self.assertEqual(summary.unsupported_cash_transaction_count, 1)
        self.assertEqual(summary.currencies_seen, ("CAD",))
        self.assertEqual(summary.accounts_seen, ("U200",))
        self.assertIsNone(summary.cash_flow_date_range)
        self.assertEqual(summary.daily_nav_date_range, ("2025-01-03", "2025-01-03"))

    def test_duplicate_dedupe_keys_within_file_are_detected(self) -> None:
        xml = """<FlexQueryResponse>
          <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="1000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" />
          <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="1000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" />
        </FlexQueryResponse>"""

        summary = analyze_flex_xml_text(xml)

        self.assertEqual(summary.cash_flow_count, 2)
        self.assertEqual(
            summary.duplicate_dedupe_keys,
            ("IBKR:U100:CASH_TRANSACTION:CF1",),
        )

    def test_malformed_xml_raises_parse_error(self) -> None:
        with self.assertRaises(ElementTree.ParseError):
            analyze_flex_xml_text("<FlexQueryResponse>")

    def test_missing_required_attribute_in_supported_record_raises_value_error(self) -> None:
        xml = """<FlexQueryResponse>
          <CashTransaction accountId="U100" reportDate="20250102" currency="USD" amount="1000.00" type="Deposits/Withdrawals" />
        </FlexQueryResponse>"""

        with self.assertRaisesRegex(ValueError, "missing required Flex attribute: dateTime"):
            analyze_flex_xml_text(xml)

    def test_missing_attributes_in_unsupported_cash_transaction_do_not_fail(self) -> None:
        xml = """<FlexQueryResponse>
          <CashTransaction type="Dividend" />
        </FlexQueryResponse>"""

        summary = analyze_flex_xml_text(xml)

        self.assertEqual(summary.cash_flow_count, 0)
        self.assertEqual(summary.unsupported_cash_transaction_count, 1)

    def test_ingestion_analysis_keeps_full_records_for_load(self) -> None:
        analysis = analyze_flex_xml_text_for_ingestion(MIXED_XML)

        self.assertEqual(analysis.cash_flow_count, 1)
        self.assertEqual(analysis.daily_nav_count, 2)
        self.assertEqual(analysis.cash_flow_records[0]["amount"], "1000.00")
        self.assertEqual(analysis.cash_flow_records[0]["raw_payload"]["amount"], "1000.00")
        self.assertEqual(analysis.daily_nav_records[0]["nav_base"], "10000.00")
        self.assertEqual(analysis.daily_nav_records[0]["raw_payload"]["total"], "10000.00")

    def test_dry_run_summary_stays_sanitized_after_full_analysis_refactor(self) -> None:
        summary = analyze_flex_xml_text(MIXED_XML)

        self.assertNotIn("amount", summary.cash_flow_records[0])
        self.assertNotIn("amount_base", summary.cash_flow_records[0])
        self.assertNotIn("raw_payload", summary.cash_flow_records[0])
        self.assertNotIn("nav_base", summary.daily_nav_records[0])
        self.assertNotIn("raw_payload", summary.daily_nav_records[0])

    def test_analysis_result_and_dry_run_summary_have_same_fields(self) -> None:
        import dataclasses

        result_fields = {f.name for f in dataclasses.fields(FlexAnalysisResult)}
        summary_fields = {f.name for f in dataclasses.fields(FlexDryRunSummary)}
        self.assertEqual(result_fields, summary_fields)

    def test_analyze_flex_xml_file_for_ingestion_reads_file(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(
            suffix=".xml", mode="w", encoding="utf-8", delete=False
        ) as f:
            f.write(MIXED_XML)
            tmp_path = Path(f.name)

        try:
            analysis = analyze_flex_xml_file_for_ingestion(tmp_path)
            self.assertEqual(analysis.cash_flow_count, 1)
            self.assertEqual(analysis.daily_nav_count, 2)
            self.assertEqual(analysis.cash_flow_records[0]["amount"], "1000.00")
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_analysis_filters_to_target_account(self) -> None:
        analysis = analyze_flex_xml_text_for_ingestion(MIXED_ACCOUNT_XML)

        scoped = analysis.for_account("U100")

        self.assertEqual(scoped.account_external_id, "U100")
        self.assertEqual(scoped.cash_flow_count, 1)
        self.assertEqual(scoped.daily_nav_count, 1)
        self.assertEqual(scoped.cash_flow_records[0]["account_external_id"], "U100")
        self.assertEqual(scoped.daily_nav_records[0]["account_external_id"], "U100")
        self.assertEqual(scoped.skipped_other_account_cash_flow_count, 1)
        self.assertEqual(scoped.skipped_other_account_daily_nav_count, 1)

    def test_account_scoped_dry_run_summary_is_sanitized(self) -> None:
        summary = analyze_flex_xml_text(
            MIXED_ACCOUNT_XML,
            account_external_id="U100",
        )

        self.assertEqual(summary.account_external_id, "U100")
        self.assertEqual(summary.cash_flow_count, 1)
        self.assertEqual(summary.daily_nav_count, 1)
        self.assertEqual(summary.skipped_other_account_cash_flow_count, 1)
        self.assertEqual(summary.skipped_other_account_daily_nav_count, 1)
        self.assertNotIn("amount", summary.cash_flow_records[0])
        self.assertNotIn("nav_base", summary.daily_nav_records[0])
        self.assertNotIn("2000.00", str(summary.cash_flow_records))
        self.assertNotIn("20000.00", str(summary.daily_nav_records))


if __name__ == "__main__":
    unittest.main()
