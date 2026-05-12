from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from portfolio_engine.ingestion_cli import run


MIXED_XML = """<FlexQueryResponse>
  <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="1000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" />
  <CashTransaction accountId="U100" reportDate="20250103" dateTime="20250103;101500" currency="USD" amount="5.00" fxRateToBase="1" type="Dividend" transactionID="DIV1" />
  <EquitySummaryByReportDateInBase accountId="U100" reportDate="20250102" currency="USD" total="10000.00" />
</FlexQueryResponse>"""


class IngestionCliTests(unittest.TestCase):
    def test_dry_run_prints_privacy_safe_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Flex.xml"
            path.write_text(MIXED_XML, encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()

            exit_code = run(
                ["dry-run", str(path), "--account-external-id", "U100"],
                stdout=stdout,
                stderr=stderr,
            )

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Dry run:", output)
        self.assertIn("Cash-flow records mapped: 1", output)
        self.assertIn("Daily NAV snapshots mapped: 1", output)
        self.assertIn("Unsupported CashTransaction records skipped: 1", output)
        self.assertIn("Currencies seen: USD", output)
        self.assertIn("Duplicate dedupe keys: 0", output)
        self.assertIn("No database writes performed.", output)
        self.assertNotIn("1000.00", output)
        self.assertNotIn("10000.00", output)   # NAV total must also be suppressed
        self.assertEqual(stderr.getvalue(), "")

    def test_dry_run_date_filter_limits_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Flex.xml"
            path.write_text(MIXED_XML, encoding="utf-8")
            stdout = io.StringIO()

            exit_code = run(
                [
                    "dry-run",
                    str(path),
                    "--account-external-id",
                    "U100",
                    "--start-date",
                    "2025-01-03",
                    "--end-date",
                    "2025-01-03",
                ],
                stdout=stdout,
                stderr=io.StringIO(),
            )

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Cash-flow records mapped: 0", output)
        self.assertIn("Daily NAV snapshots mapped: 0", output)

    def test_dry_run_rejects_start_date_after_end_date(self) -> None:
        stderr = io.StringIO()

        exit_code = run(
            [
                "dry-run",
                "missing.xml",
                "--account-external-id",
                "U100",
                "--start-date",
                "2025-01-04",
                "--end-date",
                "2025-01-03",
            ],
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: --start-date must be on or before --end-date", stderr.getvalue())

    def test_dry_run_invalid_date_returns_error(self) -> None:
        stderr = io.StringIO()

        exit_code = run(
            [
                "dry-run",
                "missing.xml",
                "--account-external-id",
                "U100",
                "--start-date",
                "20250103",
            ],
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: invalid date '20250103'; expected YYYY-MM-DD", stderr.getvalue())

    def test_dry_run_missing_file_returns_error(self) -> None:
        stderr = io.StringIO()

        exit_code = run(
            ["dry-run", "missing.xml", "--account-external-id", "U100"],
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error:", stderr.getvalue())
        self.assertIn("missing.xml", stderr.getvalue())

    def test_dry_run_malformed_xml_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.xml"
            path.write_text("<FlexQueryResponse>", encoding="utf-8")
            stderr = io.StringIO()

            exit_code = run(
                ["dry-run", str(path), "--account-external-id", "U100"],
                stdout=io.StringIO(),
                stderr=stderr,
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error:", stderr.getvalue())

    def test_dry_run_duplicate_key_amount_not_in_output(self) -> None:
        """Fallback dedupe keys contain amounts; verify they are not printed."""
        xml_with_dup = """<FlexQueryResponse>
  <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="99999.99" fxRateToBase="1" type="Deposits/Withdrawals" />
  <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="99999.99" fxRateToBase="1" type="Deposits/Withdrawals" />
</FlexQueryResponse>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dup.xml"
            path.write_text(xml_with_dup, encoding="utf-8")
            stdout = io.StringIO()

            exit_code = run(
                ["dry-run", str(path), "--account-external-id", "U100"],
                stdout=stdout,
                stderr=io.StringIO(),
            )

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Duplicate dedupe keys: 1", output)
        self.assertNotIn("99999.99", output)

    def test_dry_run_requires_account_external_id(self) -> None:
        stderr = io.StringIO()

        exit_code = run(["dry-run", "Flex.xml"], stdout=io.StringIO(), stderr=stderr)

        self.assertEqual(exit_code, 1)
        self.assertIn("Error:", stderr.getvalue())
        self.assertIn("account-external-id", stderr.getvalue())

    def test_dry_run_filters_to_target_account_and_reports_skips(self) -> None:
        mixed_account_xml = """<FlexQueryResponse>
  <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="1000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" />
  <CashTransaction accountId="U200" reportDate="20250102" dateTime="20250102;091501" currency="USD" amount="2000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF2" />
  <EquitySummaryByReportDateInBase accountId="U100" reportDate="20250102" currency="USD" total="10000.00" />
  <EquitySummaryByReportDateInBase accountId="U200" reportDate="20250102" currency="USD" total="20000.00" />
</FlexQueryResponse>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Flex.xml"
            path.write_text(mixed_account_xml, encoding="utf-8")
            stdout = io.StringIO()

            exit_code = run(
                ["dry-run", str(path), "--account-external-id", "U100"],
                stdout=stdout,
                stderr=io.StringIO(),
            )

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Target account: U100", output)
        self.assertIn("Cash-flow records mapped: 1", output)
        self.assertIn("Daily NAV snapshots mapped: 1", output)
        self.assertIn("Cash-flow records skipped for other accounts: 1", output)
        self.assertIn("Daily NAV snapshots skipped for other accounts: 1", output)
        self.assertNotIn("2000.00", output)
        self.assertNotIn("20000.00", output)

    def test_script_wrapper_imports_main(self) -> None:
        import scripts.ingest_flex_file as ingest_flex_file_script

        self.assertEqual(ingest_flex_file_script.main.__module__, "portfolio_engine.ingestion_cli")


if __name__ == "__main__":
    unittest.main()
