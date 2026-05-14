from __future__ import annotations

import io
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from portfolio_engine.models import AccountRef, PortfolioDailyInput


class FakePortfolioTwrDatabase:
    def __init__(self) -> None:
        self.accounts = [
            AccountRef("IBKR", "UCA", "USD", "Canada"),
            AccountRef("IBKR", "UUS", "USD", "US"),
        ]
        self.nav_inputs = [
            PortfolioDailyInput(self.accounts[0], date(2026, 1, 1), Decimal("100"), "USD"),
            PortfolioDailyInput(self.accounts[1], date(2026, 1, 1), Decimal("0"), "USD"),
            PortfolioDailyInput(self.accounts[0], date(2026, 1, 2), Decimal("40"), "USD"),
            PortfolioDailyInput(self.accounts[1], date(2026, 1, 2), Decimal("60"), "USD"),
        ]
        self.cash_flows = []
        self.bridges = []
        self.close_count = 0

    def __enter__(self) -> "FakePortfolioTwrDatabase":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self.close_count += 1

    def fetch_portfolio_accounts(self, portfolio_name: str):
        return self.accounts

    def fetch_portfolio_nav_inputs(self, *, portfolio_name: str, start_date: date | None, end_date: date | None):
        return self.nav_inputs

    def fetch_portfolio_cash_flows(self, *, portfolio_name: str, start_date: date | None, end_date: date | None):
        return self.cash_flows

    def fetch_portfolio_transfer_bridges(self, portfolio_name: str):
        return self.bridges


class FakeFactory:
    def __init__(self, database: FakePortfolioTwrDatabase) -> None:
        self.database = database

    def __call__(self, database_url: str | None = None) -> FakePortfolioTwrDatabase:
        return self.database


class PortfolioDbTwrCliTests(unittest.TestCase):
    def test_run_calculates_portfolio_twr_and_prints_summary(self) -> None:
        from portfolio_engine.portfolio_db_twr import run

        database = FakePortfolioTwrDatabase()
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run(
            ["--portfolio-name", "All Accounts", "--reporting-currency", "USD"],
            database_connector=FakeFactory(database),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Portfolio: All Accounts", output)
        self.assertIn("Reporting currency: USD", output)
        self.assertIn("Member accounts: 2", output)
        self.assertIn("NAV rows: 4", output)
        self.assertIn("Return periods: 1", output)
        self.assertIn("TWR: 0.000000%", output)
        self.assertEqual(stderr.getvalue(), "")

    def test_run_writes_optional_daily_csv(self) -> None:
        from portfolio_engine.portfolio_db_twr import run

        database = FakePortfolioTwrDatabase()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "portfolio.csv"
            exit_code = run(
                [
                    "--portfolio-name", "All Accounts",
                    "--reporting-currency", "USD",
                    "--daily-output", str(output_path),
                ],
                database_connector=FakeFactory(database),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.exists())
            self.assertIn("bridge_value_base", output_path.read_text())

    def test_script_wrapper_imports_main(self) -> None:
        import scripts.calculate_portfolio_twr_from_db as script

        self.assertEqual(script.main.__module__, "portfolio_engine.portfolio_db_twr")


if __name__ == "__main__":
    unittest.main()
