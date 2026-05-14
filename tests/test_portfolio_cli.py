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
        self.assertEqual(database.close_count, 1)

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
        self.assertEqual(database.close_count, 1)

    def test_list_portfolios(self) -> None:
        from portfolio_engine.portfolio_cli import run

        database = FakePortfolioDatabase()
        stdout = io.StringIO()

        exit_code = run(
            ["list"],
            database_connector=FakeFactory(database),
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("All Accounts\tUSD\tTrue", stdout.getvalue())
        self.assertEqual(database.close_count, 1)

    def test_show_portfolio_accounts(self) -> None:
        from portfolio_engine.portfolio_cli import run

        database = FakePortfolioDatabase()
        stdout = io.StringIO()

        exit_code = run(
            ["show", "--portfolio-name", "All Accounts"],
            database_connector=FakeFactory(database),
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("IBKR:U100\tUSD\tMain", stdout.getvalue())
        self.assertEqual(database.close_count, 1)

    def test_create_bridge(self) -> None:
        from portfolio_engine.portfolio_cli import run

        database = FakePortfolioDatabase()
        stdout = io.StringIO()

        exit_code = run(
            [
                "create-bridge",
                "--portfolio-name", "All Accounts",
                "--source-brokerage-code", "IBKR",
                "--source-account-external-id", "U100",
                "--destination-brokerage-code", "IBKR",
                "--destination-account-external-id", "U200",
                "--departure-date", "2024-01-15",
                "--arrival-date", "2024-01-20",
                "--value", "50000.00",
                "--currency", "USD",
            ],
            database_connector=FakeFactory(database),
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("Created transfer bridge: bridge-uuid", stdout.getvalue())
        self.assertEqual(len(database.bridges), 1)
        bridge_kwargs = database.bridges[0]
        self.assertEqual(bridge_kwargs["portfolio_name"], "All Accounts")
        self.assertEqual(bridge_kwargs["source_brokerage_code"], "IBKR")
        self.assertEqual(bridge_kwargs["source_account_external_id"], "U100")
        self.assertEqual(bridge_kwargs["destination_brokerage_code"], "IBKR")
        self.assertEqual(bridge_kwargs["destination_account_external_id"], "U200")
        self.assertEqual(bridge_kwargs["departure_date"], date(2024, 1, 15))
        self.assertEqual(bridge_kwargs["arrival_date"], date(2024, 1, 20))
        self.assertEqual(bridge_kwargs["value"], Decimal("50000.00"))
        self.assertEqual(bridge_kwargs["currency"], "USD")
        self.assertIsNone(bridge_kwargs["note"])
        self.assertEqual(database.close_count, 1)

    def test_list_bridges(self) -> None:
        from portfolio_engine.portfolio_cli import run

        source = AccountRef("IBKR", "U100", "USD", "Source Account")
        destination = AccountRef("IBKR", "U200", "USD", "Dest Account")
        bridge = TransferBridge(
            source_account=source,
            destination_account=destination,
            departure_date=date(2024, 1, 15),
            arrival_date=date(2024, 1, 20),
            value=Decimal("50000.00"),
            currency="USD",
            note="Transfer note",
        )
        database = FakePortfolioDatabase()
        database.transfer_bridges = [bridge]
        stdout = io.StringIO()

        exit_code = run(
            ["list-bridges", "--portfolio-name", "All Accounts"],
            database_connector=FakeFactory(database),
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("IBKR:U100->IBKR:U200", output)
        self.assertIn("2024-01-15..2024-01-20", output)
        self.assertIn("50000.00 USD", output)
        self.assertIn("Transfer note", output)
        self.assertEqual(database.close_count, 1)

    def test_database_error_returns_one_and_closes(self) -> None:
        from portfolio_engine.portfolio_cli import run

        database = FakePortfolioDatabase()

        def _raise() -> list:
            raise RuntimeError("boom")

        database.list_portfolios = _raise  # type: ignore[method-assign]
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run(
            ["list"],
            database_connector=FakeFactory(database),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: boom", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(database.close_count, 1)

    def test_create_bridge_rejects_invalid_decimal_before_database_call(self) -> None:
        from portfolio_engine.portfolio_cli import run

        database = FakePortfolioDatabase()
        factory = FakeFactory(database)
        stderr = io.StringIO()

        with self.assertRaises(SystemExit) as cm:
            run(
                [
                    "create-bridge",
                    "--portfolio-name", "All Accounts",
                    "--source-brokerage-code", "IBKR",
                    "--source-account-external-id", "U100",
                    "--destination-brokerage-code", "IBKR",
                    "--destination-account-external-id", "U200",
                    "--departure-date", "2024-01-15",
                    "--arrival-date", "2024-01-20",
                    "--value", "notadecimal",
                    "--currency", "USD",
                ],
                database_connector=factory,
                stdout=io.StringIO(),
                stderr=stderr,
            )

        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(database.close_count, 0)
        self.assertEqual(factory.database_urls, [])
        self.assertIn("invalid decimal value", stderr.getvalue())

    def test_create_bridge_rejects_non_finite_decimal_before_database_call(self) -> None:
        from portfolio_engine.portfolio_cli import run

        base_args = [
            "create-bridge",
            "--portfolio-name", "All Accounts",
            "--source-brokerage-code", "IBKR",
            "--source-account-external-id", "U100",
            "--destination-brokerage-code", "IBKR",
            "--destination-account-external-id", "U200",
            "--departure-date", "2024-01-15",
            "--arrival-date", "2024-01-20",
            "--currency", "USD",
        ]
        # "-Infinity" must be passed as "--value=-Infinity" (equals form) because
        # argparse would otherwise treat the leading dash as a flag prefix.
        cases = [
            ("Inf", ["--value", "Inf"]),
            ("Infinity", ["--value", "Infinity"]),
            ("-Infinity", ["--value=-Infinity"]),
        ]
        for label, value_args in cases:
            with self.subTest(value=label):
                database = FakePortfolioDatabase()
                factory = FakeFactory(database)
                stderr = io.StringIO()

                with self.assertRaises(SystemExit) as cm:
                    run(
                        [*base_args, *value_args],
                        database_connector=factory,
                        stdout=io.StringIO(),
                        stderr=stderr,
                    )

                self.assertEqual(cm.exception.code, 2, f"Expected exit code 2 for {label!r}")
                self.assertEqual(database.close_count, 0, f"DB should not be opened for {label!r}")
                self.assertEqual(factory.database_urls, [], f"Factory should not be called for {label!r}")
                self.assertIn("invalid decimal value", stderr.getvalue(), f"stderr missing message for {label!r}")

    def test_database_url_is_forwarded(self) -> None:
        from portfolio_engine.portfolio_cli import run

        database = FakePortfolioDatabase()
        factory = FakeFactory(database)

        exit_code = run(
            ["--database-url", "postgresql://example", "list"],
            database_connector=factory,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(factory.database_urls, ["postgresql://example"])

    def test_script_wrapper_imports_main(self) -> None:
        import scripts.manage_portfolio as manage_portfolio_script

        self.assertEqual(manage_portfolio_script.main.__module__, "portfolio_engine.portfolio_cli")


if __name__ == "__main__":
    unittest.main()
