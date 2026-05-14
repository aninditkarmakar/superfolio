from __future__ import annotations

import os
import unittest
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
from typing import Any

from portfolio_engine.database import (
    AccountRegistration,
    BulkIngestionSummary,
    DatabaseConfigurationError,
    IngestionRunStart,
    SuperFolioDatabase,
    connect_database,
)
from portfolio_engine.models import AccountRef, CashFlow, NavSnapshot, PortfolioCashFlow, PortfolioDailyInput, PortfolioSummary, TransferBridge


class FakeCursor:
    def __init__(
        self,
        row: tuple[Any, ...] | None = None,
        rows: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.row = row
        self.rows = [] if rows is None else rows
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class FakeConnection:
    def __init__(
        self,
        row: tuple[Any, ...] | None = None,
        rows: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.cursor_instance = FakeCursor(row, rows)
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.close_count += 1


class FailingConnection(FakeConnection):
    def __init__(self) -> None:
        super().__init__(None)

    def cursor(self) -> FakeCursor:
        raise RuntimeError("database unavailable")


class DatabaseAdapterTests(unittest.TestCase):
    def test_account_registration_is_immutable(self) -> None:
        registration = AccountRegistration(
            brokerage_code="IBKR",
            external_id="U100",
            account_type="Individual",
            base_currency="USD",
            display_name="Main account",
        )

        with self.assertRaises(FrozenInstanceError):
            registration.external_id = "U200"

    def test_ingestion_run_start_is_immutable(self) -> None:
        request = IngestionRunStart(
            brokerage_code="IBKR",
            account_external_id="U100",
            source_type="MANUAL_FILE",
            requested_start_date=date(2026, 5, 1),
            requested_end_date=date(2026, 5, 31),
            source_filename="Cash_Flows.xml",
        )

        with self.assertRaises(FrozenInstanceError):
            request.source_filename = "Daily_NAV.xml"

    def test_register_account_calls_database_function_and_commits(self) -> None:
        connection = FakeConnection(("account-uuid",))
        database = SuperFolioDatabase(connection)

        account_id = database.register_account(
            AccountRegistration(
                brokerage_code="IBKR",
                external_id="U100",
                account_type="Individual",
                base_currency="USD",
                display_name="Main account",
            )
        )

        self.assertEqual(account_id, "account-uuid")
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        self.assertEqual(
            connection.cursor_instance.executed,
            [
                (
                    "SELECT public.register_account(%s, %s, %s, %s, %s)",
                    ("IBKR", "U100", "Individual", "USD", "Main account"),
                )
            ],
        )

    def test_register_account_allows_missing_display_name(self) -> None:
        connection = FakeConnection(("account-uuid",))
        database = SuperFolioDatabase(connection)

        database.register_account(
            AccountRegistration(
                brokerage_code="IBKR",
                external_id="U100",
                account_type="Individual",
                base_currency="USD",
            )
        )

        self.assertEqual(
            connection.cursor_instance.executed[0][1],
            ("IBKR", "U100", "Individual", "USD", None),
        )

    def test_start_ingestion_run_calls_database_function(self) -> None:
        connection = FakeConnection(("run-uuid",))
        database = SuperFolioDatabase(connection)

        run_id = database.start_ingestion_run(
            IngestionRunStart(
                brokerage_code="IBKR",
                account_external_id="U100",
                source_type="MANUAL_FILE",
                requested_start_date=date(2026, 5, 1),
                requested_end_date=date(2026, 5, 31),
                source_filename="Cash_Flows.xml",
            )
        )

        self.assertEqual(run_id, "run-uuid")
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        self.assertEqual(
            connection.cursor_instance.executed,
            [
                (
                    "SELECT public.start_ingestion_run(%s, %s, %s, %s, %s, %s)",
                    (
                        "IBKR",
                        "U100",
                        "MANUAL_FILE",
                        date(2026, 5, 1),
                        date(2026, 5, 31),
                        "Cash_Flows.xml",
                    ),
                )
            ],
        )

    def test_start_ingestion_run_allows_optional_fields(self) -> None:
        connection = FakeConnection(("run-uuid",))
        database = SuperFolioDatabase(connection)

        database.start_ingestion_run(
            IngestionRunStart(
                brokerage_code="IBKR",
                account_external_id="U100",
                source_type="MANUAL_FILE",
            )
        )

        self.assertEqual(
            connection.cursor_instance.executed[0][1],
            ("IBKR", "U100", "MANUAL_FILE", None, None, None),
        )

    def test_start_ingestion_run_rolls_back_and_reraises_on_failure(self) -> None:
        connection = FailingConnection()
        database = SuperFolioDatabase(connection)

        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            database.start_ingestion_run(
                IngestionRunStart(
                    brokerage_code="IBKR",
                    account_external_id="U100",
                    source_type="MANUAL_FILE",
                )
            )

        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 1)

    def test_complete_ingestion_run_calls_database_function(self) -> None:
        connection = FakeConnection(("run-uuid",))
        database = SuperFolioDatabase(connection)

        run_id = database.complete_ingestion_run(
            ingestion_run_id="run-uuid",
            status="partially_succeeded",
            error_message="Skipped unknown accounts: U404",
        )

        self.assertEqual(run_id, "run-uuid")
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        self.assertEqual(
            connection.cursor_instance.executed,
            [
                (
                    "SELECT public.complete_ingestion_run(%s, %s, %s)",
                    ("run-uuid", "partially_succeeded", "Skipped unknown accounts: U404"),
                )
            ],
        )

    def test_complete_ingestion_run_allows_optional_error_message(self) -> None:
        connection = FakeConnection(("run-uuid",))
        database = SuperFolioDatabase(connection)

        database.complete_ingestion_run(
            ingestion_run_id="run-uuid",
            status="succeeded",
        )

        self.assertEqual(
            connection.cursor_instance.executed[0][1],
            ("run-uuid", "succeeded", None),
        )

    def test_complete_ingestion_run_rolls_back_and_reraises_on_failure(self) -> None:
        connection = FailingConnection()
        database = SuperFolioDatabase(connection)

        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            database.complete_ingestion_run(
                ingestion_run_id="run-uuid",
                status="failed",
                error_message="database unavailable",
            )

        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 1)

    def test_bulk_ingest_cash_flows_returns_summary(self) -> None:
        row = (
            2,
            1,
            1,
            0,
            0,
            ["U404"],
            [{"account_external_id": "U404", "record_status": "skipped_unknown_account"}],
        )
        connection = FakeConnection(row)
        database = SuperFolioDatabase(connection)
        records = [{"account_external_id": "U100", "dedupe_key": "cash-1"}]

        summary = database.bulk_ingest_cash_flows("run-uuid", records)

        self.assertEqual(
            summary,
            BulkIngestionSummary(
                inserted_count=2,
                duplicate_count=1,
                skipped_unknown_account_count=1,
                skipped_inactive_account_count=0,
                conflict_count=0,
                skipped_accounts=["U404"],
                record_results=[
                    {
                        "account_external_id": "U404",
                        "record_status": "skipped_unknown_account",
                    }
                ],
            ),
        )
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        self.assertEqual(
            connection.cursor_instance.executed[0][0],
            "SELECT * FROM public.bulk_ingest_cash_flows(%s, %s)",
        )
        self.assertEqual(connection.cursor_instance.executed[0][1][0], "run-uuid")

    def test_bulk_ingest_daily_nav_snapshots_returns_summary(self) -> None:
        row = (1, 0, 0, 0, 1, [], [{"record_status": "conflict_existing_snapshot"}])
        connection = FakeConnection(row)
        database = SuperFolioDatabase(connection)
        records = [{"account_external_id": "U100", "dedupe_key": "nav-1"}]

        summary = database.bulk_ingest_daily_nav_snapshots("run-uuid", records)

        self.assertEqual(summary.inserted_count, 1)
        self.assertEqual(summary.conflict_count, 1)
        self.assertEqual(summary.record_results, [{"record_status": "conflict_existing_snapshot"}])
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        self.assertEqual(
            connection.cursor_instance.executed[0][0],
            "SELECT * FROM public.bulk_ingest_daily_nav_snapshots(%s, %s)",
        )
        self.assertEqual(connection.cursor_instance.executed[0][1][0], "run-uuid")

    def test_bulk_summary_converts_null_collections_to_empty_lists(self) -> None:
        connection = FakeConnection((0, 0, 0, 0, 0, None, None))
        database = SuperFolioDatabase(connection)

        summary = database.bulk_ingest_cash_flows("run-uuid", [])

        self.assertEqual(summary.skipped_accounts, [])
        self.assertEqual(summary.record_results, [])

    def test_register_account_rolls_back_and_reraises_on_failure(self) -> None:
        connection = FailingConnection()
        database = SuperFolioDatabase(connection)

        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            database.register_account(
                AccountRegistration(
                    brokerage_code="IBKR",
                    external_id="U100",
                    account_type="Individual",
                    base_currency="USD",
                )
            )

        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 1)

    def test_database_close_closes_underlying_connection(self) -> None:
        connection = FakeConnection(("account-uuid",))
        database = SuperFolioDatabase(connection)

        database.close()

        self.assertEqual(connection.close_count, 1)

    def test_database_context_manager_closes_underlying_connection(self) -> None:
        connection = FakeConnection(("account-uuid",))

        with SuperFolioDatabase(connection) as database:
            self.assertIsInstance(database, SuperFolioDatabase)

        self.assertEqual(connection.close_count, 1)

    def test_connect_database_requires_database_url(self) -> None:
        original = os.environ.pop("DATABASE_URL", None)
        try:
            with self.assertRaisesRegex(DatabaseConfigurationError, "DATABASE_URL"):
                connect_database()
        finally:
            if original is not None:
                os.environ["DATABASE_URL"] = original

    def test_connect_database_rejects_blank_database_url(self) -> None:
        with self.assertRaisesRegex(DatabaseConfigurationError, "DATABASE_URL"):
            connect_database("   ")

    def test_public_database_adapter_imports_are_available(self) -> None:
        from portfolio_engine.database import (
            AccountRegistration,
            BulkIngestionSummary,
            DatabaseConfigurationError,
            IngestionRunStart,
            SuperFolioDatabase,
            connect_database,
        )

        self.assertIsNotNone(AccountRegistration)
        self.assertIsNotNone(BulkIngestionSummary)
        self.assertIsNotNone(DatabaseConfigurationError)
        self.assertIsNotNone(IngestionRunStart)
        self.assertIsNotNone(SuperFolioDatabase)
        self.assertIsNotNone(connect_database)

    def test_fetch_nav_snapshots_returns_ordered_models(self) -> None:
        connection = FakeConnection(
            rows=[
                (date(2026, 1, 2), Decimal("10000.00")),
                (date(2026, 1, 3), Decimal("10100.00")),
            ]
        )
        database = SuperFolioDatabase(connection)

        snapshots = database.fetch_nav_snapshots(
            brokerage_code="IBKR",
            account_external_id="U100",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        self.assertEqual(
            snapshots,
            [
                NavSnapshot(report_date=date(2026, 1, 2), total_base=Decimal("10000.00")),
                NavSnapshot(report_date=date(2026, 1, 3), total_base=Decimal("10100.00")),
            ],
        )
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("FROM daily_nav_snapshots", sql)
        self.assertIn("JOIN accounts", sql)
        self.assertIn("JOIN brokerages", sql)
        self.assertIn("ORDER BY d.snapshot_date", sql)
        self.assertEqual(
            params,
            (
                "IBKR",
                "U100",
                date(2026, 1, 1),
                date(2026, 1, 1),
                date(2026, 1, 31),
                date(2026, 1, 31),
            ),
        )

    def test_fetch_cash_flows_returns_deposit_withdrawal_models(self) -> None:
        connection = FakeConnection(
            rows=[
                (date(2026, 1, 3), Decimal("1000.00")),
                (date(2026, 1, 5), Decimal("-250.00")),
            ]
        )
        database = SuperFolioDatabase(connection)

        flows = database.fetch_cash_flows(
            brokerage_code="IBKR",
            account_external_id="U100",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        self.assertEqual(
            flows,
            [
                CashFlow(effective_date=date(2026, 1, 3), amount_base=Decimal("1000.00")),
                CashFlow(effective_date=date(2026, 1, 5), amount_base=Decimal("-250.00")),
            ],
        )
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("FROM cash_flows", sql)
        self.assertIn("c.cash_flow_type = %s", sql)
        self.assertIn("ORDER BY c.flow_date", sql)
        self.assertEqual(
            params,
            (
                "IBKR",
                "U100",
                "Deposits/Withdrawals",
                date(2026, 1, 1),
                date(2026, 1, 1),
                date(2026, 1, 31),
                date(2026, 1, 31),
            ),
        )

    def test_fetch_queries_keep_user_inputs_out_of_sql_text(self) -> None:
        connection = FakeConnection(rows=[])
        database = SuperFolioDatabase(connection)
        malicious_brokerage = "IBKR'; DROP TABLE accounts; --"
        malicious_account = "U100' OR TRUE --"

        database.fetch_nav_snapshots(
            brokerage_code=malicious_brokerage,
            account_external_id=malicious_account,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
        database.fetch_cash_flows(
            brokerage_code=malicious_brokerage,
            account_external_id=malicious_account,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        for sql, params in connection.cursor_instance.executed:
            self.assertNotIn("DROP TABLE", sql)
            self.assertNotIn("OR TRUE", sql)
            self.assertNotIn(malicious_brokerage, sql)
            self.assertNotIn(malicious_account, sql)
            self.assertIn("%s", sql)
            self.assertIn(malicious_brokerage, params)
            self.assertIn(malicious_account, params)

    def test_fetch_nav_snapshots_rolls_back_and_reraises_on_failure(self) -> None:
        connection = FailingConnection()
        database = SuperFolioDatabase(connection)

        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            database.fetch_nav_snapshots(
                brokerage_code="IBKR",
                account_external_id="U100",
            )

        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 1)

    def test_fetch_cash_flows_rolls_back_and_reraises_on_failure(self) -> None:
        connection = FailingConnection()
        database = SuperFolioDatabase(connection)

        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            database.fetch_cash_flows(
                brokerage_code="IBKR",
                account_external_id="U100",
            )

        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 1)

    def test_create_portfolio_calls_database_function(self) -> None:
        connection = FakeConnection(row=("portfolio-uuid",))
        database = SuperFolioDatabase(connection)

        portfolio_id = database.create_portfolio(
            name="All Accounts",
            reporting_currency="USD",
        )

        self.assertEqual(portfolio_id, "portfolio-uuid")
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("public.create_portfolio", sql)
        self.assertEqual(params, ("All Accounts", "USD"))
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)

    def test_attach_portfolio_account_calls_database_function(self) -> None:
        connection = FakeConnection(row=("membership-uuid",))
        database = SuperFolioDatabase(connection)

        membership_id = database.attach_portfolio_account(
            portfolio_name="All Accounts",
            brokerage_code="IBKR",
            account_external_id="U100",
        )

        self.assertEqual(membership_id, "membership-uuid")
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("public.attach_portfolio_account", sql)
        self.assertEqual(params, ("All Accounts", "IBKR", "U100"))

    def test_create_transfer_bridge_calls_database_function(self) -> None:
        connection = FakeConnection(row=("bridge-uuid",))
        database = SuperFolioDatabase(connection)

        bridge_id = database.create_portfolio_transfer_bridge(
            portfolio_name="All Accounts",
            source_brokerage_code="IBKR",
            source_account_external_id="U100",
            destination_brokerage_code="IBKR",
            destination_account_external_id="U200",
            departure_date=date(2026, 1, 2),
            arrival_date=date(2026, 1, 4),
            value=Decimal("5000.00"),
            currency="USD",
            note="relocation",
        )

        self.assertEqual(bridge_id, "bridge-uuid")
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("public.create_portfolio_transfer_bridge", sql)
        self.assertEqual(
            params,
            (
                "All Accounts",
                "IBKR",
                "U100",
                "IBKR",
                "U200",
                date(2026, 1, 2),
                date(2026, 1, 4),
                Decimal("5000.00"),
                "USD",
                "relocation",
            ),
        )

    def test_list_portfolios_maps_rows(self) -> None:
        connection = FakeConnection(
            rows=[
                ("All Accounts", "USD", True),
                ("IBKR Only", "USD", False),
            ]
        )
        database = SuperFolioDatabase(connection)

        portfolios = database.list_portfolios()

        self.assertEqual(
            portfolios,
            [
                PortfolioSummary("All Accounts", "USD", True),
                PortfolioSummary("IBKR Only", "USD", False),
            ],
        )
        sql, params = connection.cursor_instance.executed[0]
        normalized = " ".join(sql.split())
        self.assertIn("SELECT name, reporting_currency, is_active", normalized)
        self.assertEqual(params, ())

    def test_fetch_methods_allow_absent_date_filters(self) -> None:
        connection = FakeConnection(rows=[])
        database = SuperFolioDatabase(connection)

        self.assertEqual(
            database.fetch_nav_snapshots(
                brokerage_code="IBKR",
                account_external_id="U100",
            ),
            [],
        )
        self.assertEqual(
            database.fetch_cash_flows(
                brokerage_code="IBKR",
                account_external_id="U100",
            ),
            [],
        )

        self.assertEqual(connection.commit_count, 2)
        self.assertEqual(connection.rollback_count, 0)
        self.assertEqual(connection.cursor_instance.executed[0][1], ("IBKR", "U100", None, None, None, None))
        self.assertEqual(
            connection.cursor_instance.executed[1][1],
            ("IBKR", "U100", "Deposits/Withdrawals", None, None, None, None),
        )

    def test_fetch_portfolio_accounts_maps_rows_including_inactive_accounts(self) -> None:
        connection = FakeConnection(
            rows=[
                ("IBKR", "UCA", "USD", "Canada account"),
                ("IBKR", "UUS", "USD", "US account"),
            ]
        )
        database = SuperFolioDatabase(connection)

        accounts = database.fetch_portfolio_accounts("All Accounts")

        self.assertEqual(
            accounts,
            [
                AccountRef("IBKR", "UCA", "USD", "Canada account"),
                AccountRef("IBKR", "UUS", "USD", "US account"),
            ],
        )
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("public.portfolio_accounts", sql)
        self.assertIn("public.portfolios", sql)
        self.assertIn("public.accounts", sql)
        self.assertIn("public.brokerages", sql)
        self.assertNotIn("a.is_active = true", sql)
        self.assertEqual(params, ("All Accounts",))

    def test_fetch_portfolio_nav_inputs_maps_currency_aware_rows(self) -> None:
        start = date(2026, 1, 1)
        end = date(2026, 1, 31)
        connection = FakeConnection(
            rows=[
                ("IBKR", "UCA", "USD", "Canada account", date(2026, 1, 2), Decimal("100.00"), "USD"),
            ]
        )
        database = SuperFolioDatabase(connection)

        inputs = database.fetch_portfolio_nav_inputs(
            portfolio_name="All Accounts",
            start_date=start,
            end_date=end,
        )

        self.assertEqual(
            inputs,
            [
                PortfolioDailyInput(
                    AccountRef("IBKR", "UCA", "USD", "Canada account"),
                    date(2026, 1, 2),
                    Decimal("100.00"),
                    "USD",
                )
            ],
        )
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("public.portfolio_accounts", sql)
        self.assertIn("public.daily_nav_snapshots", sql)
        self.assertEqual(params, ("All Accounts", start, start, end, end))

    def test_fetch_portfolio_cash_flows_maps_rows(self) -> None:
        start = date(2026, 1, 1)
        end = date(2026, 1, 31)
        connection = FakeConnection(
            rows=[
                ("IBKR", "U100", "USD", "Main account", date(2026, 1, 5), Decimal("1000.00")),
            ]
        )
        database = SuperFolioDatabase(connection)

        flows = database.fetch_portfolio_cash_flows(
            portfolio_name="All Accounts",
            start_date=start,
            end_date=end,
        )

        self.assertEqual(
            flows,
            [
                PortfolioCashFlow(
                    AccountRef("IBKR", "U100", "USD", "Main account"),
                    date(2026, 1, 5),
                    Decimal("1000.00"),
                    "USD",
                )
            ],
        )
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("public.portfolio_accounts", sql)
        self.assertIn("public.cash_flows", sql)
        self.assertIn("c.cash_flow_type = %s", sql)
        self.assertEqual(params, ("All Accounts", "Deposits/Withdrawals", start, start, end, end))

    def test_fetch_portfolio_transfer_bridges_maps_rows(self) -> None:
        connection = FakeConnection(
            rows=[
                (
                    "IBKR", "U100", "USD", "Source account",
                    "IBKR", "U200", "CAD", "Dest account",
                    date(2026, 1, 2), date(2026, 1, 4), Decimal("5000.00"), "USD", "relocation",
                ),
            ]
        )
        database = SuperFolioDatabase(connection)

        bridges = database.fetch_portfolio_transfer_bridges("All Accounts")

        self.assertEqual(
            bridges,
            [
                TransferBridge(
                    source_account=AccountRef("IBKR", "U100", "USD", "Source account"),
                    destination_account=AccountRef("IBKR", "U200", "CAD", "Dest account"),
                    departure_date=date(2026, 1, 2),
                    arrival_date=date(2026, 1, 4),
                    value=Decimal("5000.00"),
                    currency="USD",
                    note="relocation",
                )
            ],
        )
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("public.portfolio_transfer_bridges", sql)
        self.assertIn("public.portfolios", sql)
        self.assertIn("public.accounts", sql)
        self.assertEqual(params, ("All Accounts",))


if __name__ == "__main__":
    unittest.main()
