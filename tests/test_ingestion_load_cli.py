from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from typing import Any

from portfolio_engine.database import BulkIngestionSummary, IngestionRunStart
from portfolio_engine.ingestion_cli import run


MIXED_XML = """<FlexQueryResponse>
  <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="1000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" />
  <CashTransaction accountId="U100" reportDate="20250103" dateTime="20250103;101500" currency="USD" amount="5.00" fxRateToBase="1" type="Dividend" transactionID="DIV1" />
  <EquitySummaryByReportDateInBase accountId="U100" reportDate="20250102" currency="USD" total="10000.00" />
</FlexQueryResponse>"""


def summary(
    *,
    inserted: int = 0,
    duplicate: int = 0,
    unknown: int = 0,
    inactive: int = 0,
    conflicts: int = 0,
    skipped_accounts: list[str] | None = None,
) -> BulkIngestionSummary:
    return BulkIngestionSummary(
        inserted_count=inserted,
        duplicate_count=duplicate,
        skipped_unknown_account_count=unknown,
        skipped_inactive_account_count=inactive,
        conflict_count=conflicts,
        skipped_accounts=skipped_accounts or [],
        record_results=[],
    )


class FakeDatabase:
    def __init__(self) -> None:
        self.started: list[IngestionRunStart] = []
        self.completed: list[tuple[str, str, str | None]] = []
        self.cash_records: list[list[dict[str, Any]]] = []
        self.nav_records: list[list[dict[str, Any]]] = []
        self.cash_summary = summary(inserted=1)
        self.nav_summary = summary(inserted=1)
        self.closed = False

    def __enter__(self) -> "FakeDatabase":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.closed = True

    def start_ingestion_run(self, request: IngestionRunStart) -> str:
        self.started.append(request)
        return "run-123"

    def bulk_ingest_cash_flows(
        self, ingestion_run_id: str, records: list[dict[str, Any]]
    ) -> BulkIngestionSummary:
        self.cash_records.append(records)
        return self.cash_summary

    def bulk_ingest_daily_nav_snapshots(
        self, ingestion_run_id: str, records: list[dict[str, Any]]
    ) -> BulkIngestionSummary:
        self.nav_records.append(records)
        return self.nav_summary

    def complete_ingestion_run(
        self, *, ingestion_run_id: str, status: str, error_message: str | None = None
    ) -> str:
        self.completed.append((ingestion_run_id, status, error_message))
        return ingestion_run_id


class Connector:
    def __init__(self, database: FakeDatabase | None = None) -> None:
        self.database = database or FakeDatabase()
        self.urls: list[str | None] = []

    def __call__(self, database_url: str | None = None) -> FakeDatabase:
        self.urls.append(database_url)
        return self.database


class IngestionLoadCliTests(unittest.TestCase):
    def write_xml(self, xml_text: str = MIXED_XML) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "Flex.xml"
        path.write_text(xml_text, encoding="utf-8")
        return directory, path

    def test_load_requires_brokerage_code(self) -> None:
        stderr = io.StringIO()

        exit_code = run(["load", "Flex.xml"], stdout=io.StringIO(), stderr=stderr)

        self.assertEqual(exit_code, 1)
        self.assertIn("Error:", stderr.getvalue())
        self.assertIn("brokerage-code", stderr.getvalue())

    def test_load_passes_database_url_override_to_connector(self) -> None:
        connector = Connector()
        directory, path = self.write_xml()
        self.addCleanup(directory.cleanup)

        exit_code = run(
            [
                "load",
                str(path),
                "--brokerage-code",
                "IBKR",
                "--database-url",
                "postgresql://example",
            ],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            database_connector=connector,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(connector.urls, ["postgresql://example"])

    def test_load_mixed_file_starts_one_run_and_bulk_loads_both_types(self) -> None:
        database = FakeDatabase()
        connector = Connector(database)
        directory, path = self.write_xml()
        self.addCleanup(directory.cleanup)
        stdout = io.StringIO()

        exit_code = run(
            [
                "load",
                str(path),
                "--brokerage-code",
                "IBKR",
                "--start-date",
                "2025-01-01",
                "--end-date",
                "2025-01-31",
            ],
            stdout=stdout,
            stderr=io.StringIO(),
            database_connector=connector,
        )

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(database.started), 1)
        self.assertEqual(database.started[0].brokerage_code, "IBKR")
        self.assertEqual(database.started[0].source_type, "manual_file")
        self.assertEqual(database.started[0].source_filename, "Flex.xml")
        self.assertEqual(database.started[0].requested_start_date.isoformat(), "2025-01-01")
        self.assertEqual(database.started[0].requested_end_date.isoformat(), "2025-01-31")
        self.assertEqual(len(database.cash_records), 1)
        self.assertEqual(len(database.nav_records), 1)
        self.assertEqual(database.cash_records[0][0]["amount"], "1000.00")
        self.assertEqual(database.nav_records[0][0]["nav_base"], "10000.00")
        self.assertEqual(database.completed, [("run-123", "succeeded", None)])
        self.assertIn("Load:", output)
        self.assertIn("Ingestion run: run-123", output)
        self.assertIn("Cash-flow results: inserted=1 duplicate=0 skipped_unknown=0 skipped_inactive=0 conflicts=0", output)
        self.assertIn("Daily NAV results: inserted=1 duplicate=0 skipped_unknown=0 skipped_inactive=0 conflicts=0", output)
        self.assertIn("Final status: succeeded", output)
        self.assertNotIn("1000.00", output)
        self.assertNotIn("10000.00", output)

    def test_load_skips_empty_categories_without_bulk_calls(self) -> None:
        nav_only_xml = """<FlexQueryResponse>
  <EquitySummaryByReportDateInBase accountId="U100" reportDate="20250102" currency="USD" total="10000.00" />
</FlexQueryResponse>"""
        database = FakeDatabase()
        connector = Connector(database)
        directory, path = self.write_xml(nav_only_xml)
        self.addCleanup(directory.cleanup)

        exit_code = run(
            ["load", str(path), "--brokerage-code", "IBKR"],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            database_connector=connector,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(database.cash_records, [])
        self.assertEqual(len(database.nav_records), 1)

    def test_load_marks_unknown_inactive_or_conflict_results_partially_succeeded(self) -> None:
        database = FakeDatabase()
        database.cash_summary = summary(unknown=1, skipped_accounts=["U404"])
        database.nav_summary = summary(conflicts=1)
        connector = Connector(database)
        directory, path = self.write_xml()
        self.addCleanup(directory.cleanup)
        stdout = io.StringIO()

        exit_code = run(
            ["load", str(path), "--brokerage-code", "IBKR"],
            stdout=stdout,
            stderr=io.StringIO(),
            database_connector=connector,
        )

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            database.completed,
            [("run-123", "partially_succeeded", "skipped accounts or conflicts require review")],
        )
        self.assertIn("Skipped accounts: U404", output)
        self.assertIn("Final status: partially_succeeded", output)
        self.assertIn("Message: skipped accounts or conflicts require review", output)

    def test_load_duplicate_only_results_are_succeeded(self) -> None:
        database = FakeDatabase()
        database.cash_summary = summary(duplicate=1)
        database.nav_summary = summary(duplicate=1)
        connector = Connector(database)
        directory, path = self.write_xml()
        self.addCleanup(directory.cleanup)

        exit_code = run(
            ["load", str(path), "--brokerage-code", "IBKR"],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            database_connector=connector,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(database.completed, [("run-123", "succeeded", None)])

    def test_load_failure_after_run_start_marks_run_failed(self) -> None:
        class FailingBulkDatabase(FakeDatabase):
            def bulk_ingest_cash_flows(
                self, ingestion_run_id: str, records: list[dict[str, Any]]
            ) -> BulkIngestionSummary:
                raise RuntimeError("bulk cash failed")

        database = FailingBulkDatabase()
        connector = Connector(database)
        directory, path = self.write_xml()
        self.addCleanup(directory.cleanup)
        stderr = io.StringIO()

        exit_code = run(
            ["load", str(path), "--brokerage-code", "IBKR"],
            stdout=io.StringIO(),
            stderr=stderr,
            database_connector=connector,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: bulk cash failed", stderr.getvalue())
        self.assertEqual(database.completed, [("run-123", "failed", "bulk cash failed")])

    def test_load_reports_failed_finalization_error_too(self) -> None:
        class FailingFinalizeDatabase(FakeDatabase):
            def bulk_ingest_cash_flows(
                self, ingestion_run_id: str, records: list[dict[str, Any]]
            ) -> BulkIngestionSummary:
                raise RuntimeError("bulk cash failed")

            def complete_ingestion_run(
                self,
                *,
                ingestion_run_id: str,
                status: str,
                error_message: str | None = None,
            ) -> str:
                raise RuntimeError("completion failed")

        database = FailingFinalizeDatabase()
        connector = Connector(database)
        directory, path = self.write_xml()
        self.addCleanup(directory.cleanup)
        stderr = io.StringIO()

        exit_code = run(
            ["load", str(path), "--brokerage-code", "IBKR"],
            stdout=io.StringIO(),
            stderr=stderr,
            database_connector=connector,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("bulk cash failed", stderr.getvalue())
        self.assertIn("failed to mark ingestion run failed: completion failed", stderr.getvalue())

    def test_load_output_never_prints_fallback_dedupe_key_amount_or_raw_payload(self) -> None:
        xml = """<FlexQueryResponse>
  <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="99999.99" fxRateToBase="1" type="Deposits/Withdrawals" />
  <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="99999.99" fxRateToBase="1" type="Deposits/Withdrawals" />
  <EquitySummaryByReportDateInBase accountId="U100" reportDate="20250102" currency="USD" total="88888.88" />
</FlexQueryResponse>"""
        database = FakeDatabase()
        connector = Connector(database)
        directory, path = self.write_xml(xml)
        self.addCleanup(directory.cleanup)
        stdout = io.StringIO()

        exit_code = run(
            ["load", str(path), "--brokerage-code", "IBKR"],
            stdout=stdout,
            stderr=io.StringIO(),
            database_connector=connector,
        )

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertNotIn("99999.99", output)
        self.assertNotIn("88888.88", output)
        self.assertNotIn("raw_payload", output)
        self.assertNotIn("dedupe_key", output)
