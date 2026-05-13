from __future__ import annotations

import io
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from portfolio_engine.models import CashFlow, NavSnapshot


class FakeDatabase:
    def __init__(
        self,
        snapshots: list[NavSnapshot] | None = None,
        flows: list[CashFlow] | None = None,
        nav_error: Exception | None = None,
        flow_error: Exception | None = None,
    ) -> None:
        self.snapshots: list[NavSnapshot] = snapshots if snapshots is not None else []
        self.flows: list[CashFlow] = flows if flows is not None else []
        self.nav_error: Exception | None = nav_error
        self.flow_error: Exception | None = flow_error
        self.close_count: int = 0
        self.nav_calls: list[dict] = []
        self.flow_calls: list[dict] = []

    def __enter__(self) -> "FakeDatabase":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self.close_count += 1

    def fetch_nav_snapshots(
        self,
        brokerage_code: str,
        account_external_id: str,
        start_date: date,
        end_date: date,
    ) -> list[NavSnapshot]:
        if self.nav_error is not None:
            raise self.nav_error
        self.nav_calls.append(
            {
                "brokerage_code": brokerage_code,
                "account_external_id": account_external_id,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return self.snapshots

    def fetch_cash_flows(
        self,
        brokerage_code: str,
        account_external_id: str,
        start_date: date,
        end_date: date,
    ) -> list[CashFlow]:
        if self.flow_error is not None:
            raise self.flow_error
        self.flow_calls.append(
            {
                "brokerage_code": brokerage_code,
                "account_external_id": account_external_id,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return self.flows


class FakeDatabaseConnector:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database
        self.database_urls: list[str | None] = []

    def __call__(self, database_url: str | None = None) -> FakeDatabase:
        self.database_urls.append(database_url)
        return self.database


class DatabaseTwrCliTests(unittest.TestCase):
    def test_run_calculates_twr_from_database_and_prints_summary(self) -> None:
        from portfolio_engine.db_twr import run

        snapshots = [
            NavSnapshot(report_date=date(2026, 1, 2), total_base=Decimal("10000")),
            NavSnapshot(report_date=date(2026, 1, 3), total_base=Decimal("11100")),
        ]
        flows = [
            CashFlow(effective_date=date(2026, 1, 3), amount_base=Decimal("1000")),
        ]
        database = FakeDatabase(snapshots=snapshots, flows=flows)
        connector = FakeDatabaseConnector(database)
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run(
            [
                "--brokerage-code", "IBKR",
                "--account-external-id", "U100",
                "--database-url", "postgresql://example",
                "--start-date", "2026-01-02",
                "--end-date", "2026-01-03",
            ],
            database_connector=connector,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(connector.database_urls, ["postgresql://example"])
        self.assertEqual(database.close_count, 1)
        self.assertEqual(len(database.nav_calls), 1)
        self.assertEqual(
            database.nav_calls[0],
            {
                "brokerage_code": "IBKR",
                "account_external_id": "U100",
                "start_date": date(2026, 1, 2),
                "end_date": date(2026, 1, 3),
            },
        )
        self.assertEqual(len(database.flow_calls), 1)
        self.assertEqual(
            database.flow_calls[0],
            {
                "brokerage_code": "IBKR",
                "account_external_id": "U100",
                "start_date": date(2026, 1, 2),
                "end_date": date(2026, 1, 3),
            },
        )
        output = stdout.getvalue()
        self.assertIn("Brokerage", output)
        self.assertIn("Account", output)
        self.assertIn("NAV snapshots: 2", output)
        self.assertIn("Cash-flow records: 1", output)
        self.assertIn("Return periods: 1", output)
        self.assertIn("Date range: 2026-01-02 to 2026-01-03", output)
        self.assertIn("Cash-flow type: Deposits/Withdrawals", output)
        self.assertIn("Cash-flow timing: start", output)
        self.assertIn("TWR: 0.909091%", output)
        self.assertEqual(stderr.getvalue(), "")

    def test_run_allows_no_cash_flows(self) -> None:
        from portfolio_engine.db_twr import run

        snapshots = [
            NavSnapshot(report_date=date(2026, 1, 2), total_base=Decimal("10000")),
            NavSnapshot(report_date=date(2026, 1, 3), total_base=Decimal("10100")),
        ]
        database = FakeDatabase(snapshots=snapshots, flows=[])
        connector = FakeDatabaseConnector(database)
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run(
            [
                "--brokerage-code", "IBKR",
                "--account-external-id", "U100",
                "--start-date", "2026-01-02",
                "--end-date", "2026-01-03",
            ],
            database_connector=connector,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Cash-flow records: 0", output)
        self.assertIn("TWR: 1.000000%", output)

    def test_run_fails_when_no_nav_snapshots_are_found(self) -> None:
        from portfolio_engine.db_twr import run

        database = FakeDatabase(snapshots=[], flows=[])
        connector = FakeDatabaseConnector(database)
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run(
            [
                "--brokerage-code", "IBKR",
                "--account-external-id", "U100",
                "--start-date", "2026-01-02",
                "--end-date", "2026-01-03",
            ],
            database_connector=connector,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn(
            "Error: No NAV snapshots found for the selected account and date range",
            stderr.getvalue(),
        )

    def test_run_rejects_start_date_after_end_date(self) -> None:
        from portfolio_engine.db_twr import run

        database = FakeDatabase()
        connector = FakeDatabaseConnector(database)
        stderr = io.StringIO()

        exit_code = run(
            [
                "--brokerage-code", "IBKR",
                "--account-external-id", "U100",
                "--start-date", "2026-02-01",
                "--end-date", "2026-01-31",
            ],
            database_connector=connector,
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: --start-date must be on or before --end-date", stderr.getvalue())

    def test_run_prints_nav_database_errors(self) -> None:
        from portfolio_engine.db_twr import run

        database = FakeDatabase(nav_error=RuntimeError("database unavailable"))
        connector = FakeDatabaseConnector(database)
        stderr = io.StringIO()

        exit_code = run(
            [
                "--brokerage-code", "IBKR",
                "--account-external-id", "U100",
                "--start-date", "2026-01-02",
                "--end-date", "2026-01-03",
            ],
            database_connector=connector,
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: database unavailable", stderr.getvalue())

    def test_run_prints_cash_flow_database_errors(self) -> None:
        from portfolio_engine.db_twr import run

        snapshots = [
            NavSnapshot(report_date=date(2026, 1, 2), total_base=Decimal("10000")),
            NavSnapshot(report_date=date(2026, 1, 3), total_base=Decimal("10100")),
        ]
        database = FakeDatabase(
            snapshots=snapshots,
            flow_error=RuntimeError("cash flow query failed"),
        )
        connector = FakeDatabaseConnector(database)
        stderr = io.StringIO()

        exit_code = run(
            [
                "--brokerage-code", "IBKR",
                "--account-external-id", "U100",
                "--start-date", "2026-01-02",
                "--end-date", "2026-01-03",
            ],
            database_connector=connector,
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: cash flow query failed", stderr.getvalue())

    def test_run_writes_daily_output_csv(self) -> None:
        from portfolio_engine.db_twr import run

        snapshots = [
            NavSnapshot(report_date=date(2026, 1, 2), total_base=Decimal("10000")),
            NavSnapshot(report_date=date(2026, 1, 3), total_base=Decimal("10100")),
        ]
        database = FakeDatabase(snapshots=snapshots, flows=[])
        connector = FakeDatabaseConnector(database)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "daily.csv"

            exit_code = run(
                [
                    "--brokerage-code", "IBKR",
                    "--account-external-id", "U100",
                    "--start-date", "2026-01-02",
                    "--end-date", "2026-01-03",
                    "--daily-output", str(csv_path),
                ],
                database_connector=connector,
                stdout=stdout,
                stderr=stderr,
            )

            self.assertEqual(exit_code, 0)
            self.assertIn("Daily output written to", stdout.getvalue())

            csv_content = csv_path.read_text()
            lines = csv_content.strip().splitlines()
            self.assertEqual(
                lines[0],
                "date,ending_nav_base,net_cash_flow_base,period_return,cumulative_twr",
            )
            self.assertEqual(lines[1], "2026-01-02,10000.00,0,,0")
            self.assertEqual(lines[2], "2026-01-03,10100.00,0,0.01,0.01")

    def test_script_wrapper_imports_main(self) -> None:
        import scripts.calculate_twr_from_db as calculate_twr_script

        self.assertEqual(
            calculate_twr_script.main.__module__, "portfolio_engine.db_twr"
        )


if __name__ == "__main__":
    unittest.main()
