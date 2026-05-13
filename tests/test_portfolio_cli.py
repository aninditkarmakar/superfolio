from __future__ import annotations

import io
import unittest
from datetime import date
from decimal import Decimal

from portfolio_engine.models import AccountRef, PortfolioSummary, TransferBridge


class FakePortfolioDatabase:
    def __init__(self) -> None:
        self.close_count = 0
        self.created: list[tuple[str, str]] = []
        self.attached: list[tuple[str, str, str]] = []
        self.bridges: list[dict] = []
        self.portfolios = [PortfolioSummary("All Accounts", "USD", True)]
        self.accounts = [AccountRef("IBKR", "U100", "USD", "Main")]
        self.transfer_bridges: list[TransferBridge] = []

    def __enter__(self) -> "FakePortfolioDatabase":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self.close_count += 1

    def create_portfolio(self, *, name: str, reporting_currency: str) -> str:
        self.created.append((name, reporting_currency))
        return "portfolio-uuid"

    def attach_portfolio_account(self, *, portfolio_name: str, brokerage_code: str, account_external_id: str) -> str:
        self.attached.append((portfolio_name, brokerage_code, account_external_id))
        return "membership-uuid"

    def list_portfolios(self) -> list[PortfolioSummary]:
        return self.portfolios

    def fetch_portfolio_accounts(self, portfolio_name: str) -> list[AccountRef]:
        return self.accounts

    def create_portfolio_transfer_bridge(self, **kwargs: object) -> str:
        self.bridges.append(kwargs)
        return "bridge-uuid"

    def fetch_portfolio_transfer_bridges(self, portfolio_name: str) -> list[TransferBridge]:
        return self.transfer_bridges


class FakeFactory:
    def __init__(self, database: FakePortfolioDatabase) -> None:
        self.database = database
        self.database_urls: list[str | None] = []

    def __call__(self, database_url: str | None = None) -> FakePortfolioDatabase:
        self.database_urls.append(database_url)
        return self.database


class PortfolioCliTests(unittest.TestCase):
    def test_create_portfolio(self) -> None:
        from portfolio_engine.portfolio_cli import run

        database = FakePortfolioDatabase()
        stdout = io.StringIO()

        exit_code = run(
            ["create", "--name", "All Accounts", "--reporting-currency", "USD"],
            database_connector=FakeFactory(database),
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(database.created, [("All Accounts", "USD")])
        self.assertIn("Created portfolio: portfolio-uuid", stdout.getvalue())

    def test_attach_account(self) -> None:
        from portfolio_engine.portfolio_cli import run

        database = FakePortfolioDatabase()

        exit_code = run(
            ["attach-account", "--portfolio-name", "All Accounts", "--brokerage-code", "IBKR", "--account-external-id", "U100"],
            database_connector=FakeFactory(database),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(database.attached, [("All Accounts", "IBKR", "U100")])

    def test_script_wrapper_imports_main(self) -> None:
        import scripts.manage_portfolio as manage_portfolio_script

        self.assertEqual(manage_portfolio_script.main.__module__, "portfolio_engine.portfolio_cli")


if __name__ == "__main__":
    unittest.main()
