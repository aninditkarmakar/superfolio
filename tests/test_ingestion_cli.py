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

            exit_code = run(["dry-run", str(path)], stdout=stdout, stderr=stderr)

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Dry run:", output)
        self.assertIn("Cash-flow records mapped: 1", output)
        self.assertIn("Daily NAV snapshots mapped: 1", output)
        self.assertIn("Unsupported CashTransaction records skipped: 1", output)
        self.assertIn("Accounts seen: U100", output)
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
                ["dry-run", str(path), "--start-date", "2025-01-03", "--end-date", "2025-01-03"],
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
            ["dry-run", "missing.xml", "--start-date", "2025-01-04", "--end-date", "2025-01-03"],
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: --start-date must be on or before --end-date", stderr.getvalue())

    def test_dry_run_invalid_date_returns_error(self) -> None:
        stderr = io.StringIO()

        exit_code = run(
            ["dry-run", "missing.xml", "--start-date", "20250103"],
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: invalid date '20250103'; expected YYYY-MM-DD", stderr.getvalue())

    def test_dry_run_missing_file_returns_error(self) -> None:
        stderr = io.StringIO()

        exit_code = run(["dry-run", "missing.xml"], stdout=io.StringIO(), stderr=stderr)

        self.assertEqual(exit_code, 1)
        self.assertIn("Error:", stderr.getvalue())
        self.assertIn("missing.xml", stderr.getvalue())

    def test_dry_run_malformed_xml_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.xml"
            path.write_text("<FlexQueryResponse>", encoding="utf-8")
            stderr = io.StringIO()

            exit_code = run(["dry-run", str(path)], stdout=io.StringIO(), stderr=stderr)

        self.assertEqual(exit_code, 1)
        self.assertIn("Error:", stderr.getvalue())

    def test_script_wrapper_imports_main(self) -> None:
        import scripts.ingest_flex_file as ingest_flex_file_script

        self.assertEqual(ingest_flex_file_script.main.__module__, "portfolio_engine.ingestion_cli")


if __name__ == "__main__":
    unittest.main()
