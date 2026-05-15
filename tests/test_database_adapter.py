from __future__ import annotations

import os
import unittest
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, get_type_hints

from psycopg.types.json import Jsonb

from portfolio_engine.database import (
    AccountIntegrationAssignmentSet,
    AccountRegistration,
    AutomationAccountTarget,
    AutomationConnectionTarget,
    AutomationJobAccountAdd,
    AutomationJobAccountFinalize,
    AutomationJobFinalize,
    AutomationJobStart,
    BulkIngestionSummary,
    DatabaseConfigurationError,
    IngestionRunStart,
    IntegrationConnectionCreate,
    IntegrationConnectionRecord,
    IntegrationCredentialSet,
    IntegrationFeedCreate,
    IntegrationFeedRecord,
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

    @property
    def statements(self) -> list[tuple[str, tuple[Any, ...]]]:
        return self.cursor_instance.executed

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

    def test_list_portfolio_account_external_ids_filters_by_brokerage(self) -> None:
        connection = FakeConnection(
            rows=[
                ("U11111",),
                ("U22222",),
            ]
        )
        database = SuperFolioDatabase(connection)

        external_ids = database.list_portfolio_account_external_ids(
            portfolio_name="MyPortfolio",
            brokerage_code="IBKR",
        )

        self.assertEqual(external_ids, ["U11111", "U22222"])
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("public.portfolio_accounts", sql)
        self.assertIn("public.portfolios", sql)
        self.assertIn("public.accounts", sql)
        self.assertIn("public.brokerages", sql)
        self.assertIn("b.code = %s", sql)
        self.assertIn("p.is_active = true", sql)
        self.assertIn("a.is_active = true", sql)
        self.assertIn("b.is_active = true", sql)
        self.assertEqual(params, ("MyPortfolio", "IBKR"))

    def test_fetch_portfolio_nav_inputs_maps_rows_with_date_range(self) -> None:
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


class AutomationDatabaseAdapterTests(unittest.TestCase):
    def test_automation_job_start_is_immutable(self) -> None:
        request = AutomationJobStart(
            trigger_type="manual",
            target_type="accounts",
            portfolio_id=None,
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2026, 5, 1),
            requested_end_date=date(2026, 5, 14),
        )

        with self.assertRaises(FrozenInstanceError):
            request.trigger_type = "scheduled"  # type: ignore[misc]

    def test_automation_job_finalize_is_immutable(self) -> None:
        request = AutomationJobFinalize(
            automation_job_id="job-uuid",
            status="succeeded",
        )

        with self.assertRaises(FrozenInstanceError):
            request.status = "failed"  # type: ignore[misc]

    def test_automation_account_target_is_immutable(self) -> None:
        target = AutomationAccountTarget(
            account_id="account-uuid",
            brokerage_code="IBKR",
            account_external_id="U100",
            base_currency="USD",
            display_name="Main",
        )

        with self.assertRaises(FrozenInstanceError):
            target.account_id = "other-uuid"  # type: ignore[misc]

    def test_create_automation_job_calls_database_function(self) -> None:
        connection = FakeConnection(("job-uuid",))
        database = SuperFolioDatabase(connection)

        job_id = database.create_automation_job(
            AutomationJobStart(
                trigger_type="manual",
                target_type="accounts",
                portfolio_id=None,
                integration_key="ibkr_flex_ws",
                mode="dry-run",
                requested_start_date=date(2026, 5, 1),
                requested_end_date=date(2026, 5, 14),
            )
        )

        self.assertEqual(job_id, "job-uuid")
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(
            connection.cursor_instance.executed[0],
            (
                "SELECT public.create_automation_job(%s, %s, %s, %s, %s, %s, %s)",
                ("manual", "accounts", None, "ibkr_flex_ws", "dry-run", date(2026, 5, 1), date(2026, 5, 14)),
            ),
        )

    def test_finalize_automation_job_passes_summary_json(self) -> None:
        connection = FakeConnection(("job-uuid",))
        database = SuperFolioDatabase(connection)

        result = database.finalize_automation_job(
            AutomationJobFinalize(
                automation_job_id="job-uuid",
                status="succeeded",
                summary={"account_counts": {"total": 1, "succeeded": 1, "partially_succeeded": 0, "failed": 0}},
                error_message=None,
            )
        )

        self.assertEqual(result, "job-uuid")
        sql, params = connection.cursor_instance.executed[0]
        self.assertEqual(sql, "SELECT public.finalize_automation_job(%s, %s, %s, %s)")
        self.assertEqual(params[0], "job-uuid")
        self.assertEqual(params[1], "succeeded")
        self.assertIsInstance(params[2], Jsonb)
        self.assertEqual(params[2].obj, {"account_counts": {"total": 1, "succeeded": 1, "partially_succeeded": 0, "failed": 0}})
        self.assertEqual(params[3], None)

    def test_resolve_automation_account_targets_maps_rows(self) -> None:
        connection = FakeConnection(rows=[("account-uuid", "IBKR", "U100", "USD", "Main")])
        database = SuperFolioDatabase(connection)

        accounts = database.resolve_automation_account_targets(
            brokerage_code="IBKR",
            account_external_ids=["U100"],
        )

        self.assertEqual(
            accounts,
            [AutomationAccountTarget("account-uuid", "IBKR", "U100", "USD", "Main")],
        )
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("public.resolve_automation_account_targets", sql)
        self.assertEqual(params, ("IBKR", ["U100"]))

    def test_resolve_automation_account_targets_handles_null_display_name(self) -> None:
        connection = FakeConnection(rows=[("account-uuid", "IBKR", "U100", "USD", None)])
        database = SuperFolioDatabase(connection)

        accounts = database.resolve_automation_account_targets(
            brokerage_code="IBKR",
            account_external_ids=["U100"],
        )

        self.assertIsNone(accounts[0].display_name)

    def test_add_automation_job_account_calls_database_function(self) -> None:
        connection = FakeConnection(("job-account-uuid",))
        database = SuperFolioDatabase(connection)

        job_account_id = database.add_automation_job_account(
            AutomationJobAccountAdd(
                automation_job_id="job-uuid",
                account_id="account-uuid",
            )
        )

        self.assertEqual(job_account_id, "job-account-uuid")
        self.assertEqual(connection.commit_count, 1)
        sql, params = connection.cursor_instance.executed[0]
        self.assertEqual(sql, "SELECT public.add_automation_job_account(%s, %s, %s)")
        self.assertEqual(params, ("job-uuid", "account-uuid", None))

    def test_add_automation_job_account_accepts_connection_snapshot(self) -> None:
        connection = FakeConnection(row=("child-uuid",))
        db = SuperFolioDatabase(connection)

        db.add_automation_job_account(
            AutomationJobAccountAdd(
                automation_job_id="job-uuid",
                account_id="account-uuid",
                connection_id="connection-uuid",
            )
        )

        self.assertEqual(connection.statements[0][1], ("job-uuid", "account-uuid", "connection-uuid"))

    def test_mark_automation_job_account_running_calls_database_function(self) -> None:
        connection = FakeConnection(("job-account-uuid",))
        database = SuperFolioDatabase(connection)

        result = database.mark_automation_job_account_running("job-account-uuid")

        self.assertEqual(result, "job-account-uuid")
        self.assertEqual(connection.commit_count, 1)
        sql, params = connection.cursor_instance.executed[0]
        self.assertEqual(sql, "SELECT public.mark_automation_job_account_running(%s)")
        self.assertEqual(params, ("job-account-uuid",))

    def test_finalize_automation_job_account_calls_database_function(self) -> None:
        connection = FakeConnection(("job-account-uuid",))
        database = SuperFolioDatabase(connection)

        result = database.finalize_automation_job_account(
            AutomationJobAccountFinalize(
                automation_job_account_id="job-account-uuid",
                status="succeeded",
                ingestion_run_id="run-uuid",
                summary={"inserted_count": 5},
                error_message=None,
            )
        )

        self.assertEqual(result, "job-account-uuid")
        self.assertEqual(connection.commit_count, 1)
        sql, params = connection.cursor_instance.executed[0]
        self.assertEqual(sql, "SELECT public.finalize_automation_job_account(%s, %s, %s, %s, %s)")
        self.assertEqual(params[0], "job-account-uuid")
        self.assertEqual(params[1], "succeeded")
        self.assertEqual(params[2], "run-uuid")
        self.assertIsInstance(params[3], Jsonb)
        self.assertEqual(params[3].obj, {"inserted_count": 5})
        self.assertEqual(params[4], None)

    def test_finalize_automation_job_account_allows_optional_fields(self) -> None:
        connection = FakeConnection(("job-account-uuid",))
        database = SuperFolioDatabase(connection)

        database.finalize_automation_job_account(
            AutomationJobAccountFinalize(
                automation_job_account_id="job-account-uuid",
                status="failed",
                error_message="something went wrong",
            )
        )

        _, params = connection.cursor_instance.executed[0]
        self.assertEqual(params[2], None)
        self.assertIsNone(params[3])
        self.assertEqual(params[4], "something went wrong")

    def test_resolve_automation_portfolio_accounts_maps_rows(self) -> None:
        connection = FakeConnection(
            rows=[
                ("account-uuid", "IBKR", "U100", "USD", "Main"),
                ("account-uuid2", "IBKR", "U200", "CAD", None),
            ]
        )
        database = SuperFolioDatabase(connection)

        accounts = database.resolve_automation_portfolio_accounts(
            portfolio_name="All Accounts",
            brokerage_code="IBKR",
        )

        self.assertEqual(len(accounts), 2)
        self.assertEqual(accounts[0].account_id, "account-uuid")
        self.assertEqual(accounts[0].account_external_id, "U100")
        self.assertIsNone(accounts[1].display_name)
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("public.resolve_automation_portfolio_accounts", sql)
        self.assertEqual(params, ("All Accounts", "IBKR"))

    def test_fail_stale_automation_runs_returns_count(self) -> None:
        connection = FakeConnection((3,))
        database = SuperFolioDatabase(connection)

        stale_before = datetime(2026, 5, 1, 12, 30, tzinfo=timezone.utc)

        count = database.fail_stale_automation_runs(
            stale_before=stale_before,
            error_message="timed out",
        )

        self.assertEqual(count, 3)
        self.assertEqual(connection.commit_count, 1)
        sql, params = connection.cursor_instance.executed[0]
        self.assertEqual(sql, "SELECT public.fail_stale_automation_runs(%s, %s)")
        self.assertEqual(params, (stale_before, "timed out"))

    def test_fail_stale_automation_runs_accepts_timestamp_cutoff(self) -> None:
        hints = get_type_hints(SuperFolioDatabase.fail_stale_automation_runs)

        self.assertIs(hints["stale_before"], datetime)

    # ------------------------------------------------------------------
    # Task 15: Overlap detection adapter method
    # ------------------------------------------------------------------

    def test_has_overlapping_automation_load_calls_database_function(self) -> None:
        connection = FakeConnection((True,))
        database = SuperFolioDatabase(connection)

        result = database.has_overlapping_automation_load(
            integration_key="ibkr_flex_ws",
            account_id="account-uuid",
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
            exclude_automation_job_id="job-uuid",
        )

        self.assertTrue(result)
        self.assertEqual(connection.commit_count, 1)
        sql, params = connection.cursor_instance.executed[0]
        self.assertEqual(sql, "SELECT public.has_overlapping_automation_load(%s, %s, %s, %s, %s)")
        self.assertEqual(
            params,
            ("ibkr_flex_ws", "account-uuid", date(2024, 1, 1), date(2024, 1, 31), "job-uuid"),
        )

    def test_has_overlapping_automation_load_returns_false_when_no_overlap(self) -> None:
        connection = FakeConnection((False,))
        database = SuperFolioDatabase(connection)

        result = database.has_overlapping_automation_load(
            integration_key="ibkr_flex_ws",
            account_id="account-uuid",
            requested_start_date=date(2024, 2, 1),
            requested_end_date=date(2024, 2, 28),
            exclude_automation_job_id="job-uuid",
        )

        self.assertFalse(result)

    def test_has_overlapping_automation_load_returns_bool(self) -> None:
        connection = FakeConnection((True,))
        database = SuperFolioDatabase(connection)

        result = database.has_overlapping_automation_load(
            integration_key="ibkr_flex_ws",
            account_id="account-uuid",
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
            exclude_automation_job_id="job-uuid",
        )

        self.assertIsInstance(result, bool)

    # ------------------------------------------------------------------
    # Issue 1 fix: adapter method must accept and pass exclude_automation_job_id
    # ------------------------------------------------------------------

    def test_has_overlapping_automation_load_passes_exclude_job_id_as_fifth_param(self) -> None:
        """Adapter must pass exclude_automation_job_id as the 5th SQL parameter."""
        connection = FakeConnection((False,))
        database = SuperFolioDatabase(connection)

        database.has_overlapping_automation_load(
            integration_key="ibkr_flex_ws",
            account_id="account-uuid",
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
            exclude_automation_job_id="exclude-job-uuid",
        )

        sql, params = connection.cursor_instance.executed[0]
        self.assertEqual(sql, "SELECT public.has_overlapping_automation_load(%s, %s, %s, %s, %s)")
        self.assertEqual(
            params,
            ("ibkr_flex_ws", "account-uuid", date(2024, 1, 1), date(2024, 1, 31), "exclude-job-uuid"),
        )


class IntegrationConnectionAdapterTests(unittest.TestCase):
    def test_create_integration_connection_calls_function(self) -> None:
        connection = FakeConnection(row=("connection-uuid",))
        db = SuperFolioDatabase(connection)

        result = db.create_integration_connection(
            IntegrationConnectionCreate(
                integration_key="ibkr_flex_ws",
                brokerage_code="IBKR",
                name="IBKR Personal",
            )
        )

        self.assertEqual(result, "connection-uuid")
        self.assertIn("public.create_integration_connection", connection.statements[0][0])
        self.assertEqual(connection.statements[0][1], ("ibkr_flex_ws", "IBKR", "IBKR Personal"))

    def test_set_integration_credential_passes_ciphertext(self) -> None:
        connection = FakeConnection(row=("credential-uuid",))
        db = SuperFolioDatabase(connection)

        result = db.set_integration_credential(
            IntegrationCredentialSet(
                connection_id="connection-uuid",
                credential_name="flex_token",
                ciphertext=b"ciphertext",
                encryption_key_id="v1",
                encryption_version=1,
            )
        )

        self.assertEqual(result, "credential-uuid")
        self.assertIn("public.set_integration_credential", connection.statements[0][0])
        self.assertEqual(
            connection.statements[0][1],
            ("connection-uuid", "flex_token", b"ciphertext", "v1", 1),
        )

    def test_create_integration_feed_calls_function(self) -> None:
        connection = FakeConnection(row=("feed-uuid",))
        db = SuperFolioDatabase(connection)

        result = db.create_integration_feed(
            IntegrationFeedCreate(
                connection_id="connection-uuid",
                feed_key="ibkr_cash_flows",
                display_name="Cash Flows",
            )
        )

        self.assertEqual(result, "feed-uuid")
        self.assertIn("public.create_integration_feed", connection.statements[0][0])
        self.assertEqual(
            connection.statements[0][1],
            ("connection-uuid", "ibkr_cash_flows", "Cash Flows"),
        )

    def test_create_integration_feed_allows_null_display_name(self) -> None:
        connection = FakeConnection(row=("feed-uuid",))
        db = SuperFolioDatabase(connection)

        db.create_integration_feed(
            IntegrationFeedCreate(
                connection_id="connection-uuid",
                feed_key="ibkr_cash_flows",
            )
        )

        self.assertIsNone(connection.statements[0][1][2])

    def test_set_account_integration_assignment_calls_function(self) -> None:
        connection = FakeConnection(row=("account-uuid",))
        db = SuperFolioDatabase(connection)

        result = db.set_account_integration_assignment(
            AccountIntegrationAssignmentSet(
                brokerage_code="IBKR",
                account_external_id="U100",
                connection_id="connection-uuid",
            )
        )

        self.assertEqual(result, "account-uuid")
        self.assertIn("public.set_account_integration_assignment", connection.statements[0][0])
        self.assertEqual(
            connection.statements[0][1],
            ("IBKR", "U100", "connection-uuid"),
        )

    def test_validate_account_integration_assignments_returns_list(self) -> None:
        connection = FakeConnection(rows=[("U101",), ("U102",)])
        db = SuperFolioDatabase(connection)

        result = db.validate_account_integration_assignments(
            target_type="portfolio",
            portfolio_name="All Accounts",
            brokerage_code="IBKR",
            account_external_ids=[],
        )

        self.assertEqual(result, ["U101", "U102"])
        self.assertIn("public.validate_account_integration_assignments", connection.statements[0][0])
        self.assertEqual(
            connection.statements[0][1],
            ("portfolio", "All Accounts", "IBKR", []),
        )

    def test_validate_account_integration_assignments_accounts_target(self) -> None:
        connection = FakeConnection(rows=[("U200",)])
        db = SuperFolioDatabase(connection)

        result = db.validate_account_integration_assignments(
            target_type="accounts",
            portfolio_name=None,
            brokerage_code="IBKR",
            account_external_ids=["U100", "U200"],
        )

        self.assertEqual(result, ["U200"])
        self.assertEqual(
            connection.statements[0][1],
            ("accounts", None, "IBKR", ["U100", "U200"]),
        )

    def test_list_integration_connections_maps_rows(self) -> None:
        from datetime import timezone
        now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        connection = FakeConnection(rows=[
            ("conn-uuid", "ibkr_flex_ws", "IBKR", "IBKR Personal", True, now, now),
        ])
        db = SuperFolioDatabase(connection)

        results = db.list_integration_connections()

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], IntegrationConnectionRecord)
        self.assertEqual(results[0].id, "conn-uuid")
        self.assertEqual(results[0].integration_key, "ibkr_flex_ws")
        self.assertEqual(results[0].brokerage_code, "IBKR")
        self.assertEqual(results[0].name, "IBKR Personal")
        self.assertTrue(results[0].is_active)
        self.assertIn("public.list_integration_connections", connection.statements[0][0])

    def test_list_integration_connections_returns_empty_list(self) -> None:
        connection = FakeConnection(rows=[])
        db = SuperFolioDatabase(connection)

        results = db.list_integration_connections()

        self.assertEqual(results, [])

    def test_list_integration_feeds_maps_rows(self) -> None:
        from datetime import timezone
        now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        connection = FakeConnection(rows=[
            ("feed-uuid", "conn-uuid", "cash_flows", "Cash Flows", True, now, now),
        ])
        db = SuperFolioDatabase(connection)

        results = db.list_integration_feeds("conn-uuid")

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], IntegrationFeedRecord)
        self.assertEqual(results[0].id, "feed-uuid")
        self.assertEqual(results[0].connection_id, "conn-uuid")
        self.assertEqual(results[0].feed_key, "cash_flows")
        self.assertEqual(results[0].display_name, "Cash Flows")
        self.assertTrue(results[0].is_active)
        self.assertIn("public.list_integration_feeds", connection.statements[0][0])
        self.assertEqual(connection.statements[0][1], ("conn-uuid",))

    def test_list_integration_feeds_allows_null_display_name(self) -> None:
        from datetime import timezone
        now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        connection = FakeConnection(rows=[
            ("feed-uuid", "conn-uuid", "cash_flows", None, True, now, now),
        ])
        db = SuperFolioDatabase(connection)

        results = db.list_integration_feeds("conn-uuid")

        self.assertIsNone(results[0].display_name)

    def test_integration_connection_create_is_immutable(self) -> None:
        request = IntegrationConnectionCreate(
            integration_key="ibkr_flex_ws",
            brokerage_code="IBKR",
            name="IBKR Personal",
        )

        with self.assertRaises(FrozenInstanceError):
            request.name = "Other"  # type: ignore[misc]

    def test_integration_credential_set_is_immutable(self) -> None:
        request = IntegrationCredentialSet(
            connection_id="conn-uuid",
            credential_name="flex_token",
            ciphertext=b"secret",
            encryption_key_id="v1",
            encryption_version=1,
        )

        with self.assertRaises(FrozenInstanceError):
            request.ciphertext = b"other"  # type: ignore[misc]

    def test_integration_feed_create_is_immutable(self) -> None:
        request = IntegrationFeedCreate(
            connection_id="conn-uuid",
            feed_key="cash_flows",
        )

        with self.assertRaises(FrozenInstanceError):
            request.feed_key = "nav"  # type: ignore[misc]

    def test_account_integration_assignment_set_is_immutable(self) -> None:
        request = AccountIntegrationAssignmentSet(
            brokerage_code="IBKR",
            account_external_id="U100",
            connection_id="conn-uuid",
        )

        with self.assertRaises(FrozenInstanceError):
            request.connection_id = "other-uuid"  # type: ignore[misc]


class AutomationConnectionTargetResolutionTests(unittest.TestCase):
    def test_resolve_automation_targets_with_connections_maps_nullable_connection(self) -> None:
        connection = FakeConnection(rows=[
            ("account-1", "IBKR", "U100", "USD", "Taxable", "connection-1", "IBKR Personal"),
            ("account-2", "IBKR", "U200", "USD", "IRA", None, None),
        ])
        db = SuperFolioDatabase(connection)

        results = db.resolve_automation_targets_with_connections(
            target_type="accounts",
            portfolio_name=None,
            brokerage_code="IBKR",
            account_external_ids=["U100", "U200"],
        )

        self.assertEqual(results[0].connection_id, "connection-1")
        self.assertIsNone(results[1].connection_id)

    def test_resolve_automation_targets_with_connections_maps_all_fields(self) -> None:
        connection = FakeConnection(rows=[
            ("account-1", "IBKR", "U100", "USD", "Taxable", "connection-1", "IBKR Personal"),
        ])
        db = SuperFolioDatabase(connection)

        results = db.resolve_automation_targets_with_connections(
            target_type="accounts",
            portfolio_name=None,
            brokerage_code="IBKR",
            account_external_ids=["U100"],
        )

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertIsInstance(result, AutomationConnectionTarget)
        self.assertEqual(result.account_id, "account-1")
        self.assertEqual(result.brokerage_code, "IBKR")
        self.assertEqual(result.account_external_id, "U100")
        self.assertEqual(result.base_currency, "USD")
        self.assertEqual(result.display_name, "Taxable")
        self.assertEqual(result.connection_id, "connection-1")
        self.assertEqual(result.connection_name, "IBKR Personal")

    def test_resolve_automation_targets_with_connections_null_display_name(self) -> None:
        connection = FakeConnection(rows=[
            ("account-1", "IBKR", "U100", "USD", None, None, None),
        ])
        db = SuperFolioDatabase(connection)

        results = db.resolve_automation_targets_with_connections(
            target_type="accounts",
            portfolio_name=None,
            brokerage_code="IBKR",
            account_external_ids=["U100"],
        )

        self.assertIsNone(results[0].display_name)
        self.assertIsNone(results[0].connection_id)
        self.assertIsNone(results[0].connection_name)

    def test_resolve_automation_targets_with_connections_calls_db_function(self) -> None:
        connection = FakeConnection(rows=[])
        db = SuperFolioDatabase(connection)

        db.resolve_automation_targets_with_connections(
            target_type="portfolio",
            portfolio_name="My Portfolio",
            brokerage_code="IBKR",
            account_external_ids=[],
        )

        sql, params = connection.statements[0]
        self.assertIn("public.resolve_automation_targets_with_connections", sql)
        self.assertEqual(params, ("portfolio", "My Portfolio", "IBKR", []))

    def test_resolve_automation_targets_with_connections_returns_empty_list(self) -> None:
        connection = FakeConnection(rows=[])
        db = SuperFolioDatabase(connection)

        results = db.resolve_automation_targets_with_connections(
            target_type="accounts",
            portfolio_name=None,
            brokerage_code="IBKR",
            account_external_ids=["U999"],
        )

        self.assertEqual(results, [])

    def test_automation_connection_target_is_immutable(self) -> None:
        target = AutomationConnectionTarget(
            account_id="account-1",
            brokerage_code="IBKR",
            account_external_id="U100",
            base_currency="USD",
            display_name="Taxable",
            connection_id="connection-1",
            connection_name="IBKR Personal",
        )

        with self.assertRaises(FrozenInstanceError):
            target.connection_id = "other"  # type: ignore[misc]


class ActiveConnectionCredentialsTests(unittest.TestCase):
    """Tests for SuperFolioDatabase.list_active_connection_credentials (Task 11)."""

    def test_list_active_connection_credentials_maps_rows(self) -> None:
        connection = FakeConnection(rows=[
            ("flex_token", b"\xde\xad\xbe\xef"),
            ("feed:cash:query_id", b"\xca\xfe\xba\xbe"),
        ])
        db = SuperFolioDatabase(connection)

        result = db.list_active_connection_credentials("conn-uuid")

        self.assertEqual(result, {
            "flex_token": b"\xde\xad\xbe\xef",
            "feed:cash:query_id": b"\xca\xfe\xba\xbe",
        })

    def test_list_active_connection_credentials_calls_db_function(self) -> None:
        connection = FakeConnection(rows=[])
        db = SuperFolioDatabase(connection)

        db.list_active_connection_credentials("conn-uuid")

        sql, params = connection.statements[0]
        self.assertIn("public.list_active_connection_credentials", sql)
        self.assertEqual(params, ("conn-uuid",))

    def test_list_active_connection_credentials_returns_empty_dict(self) -> None:
        connection = FakeConnection(rows=[])
        db = SuperFolioDatabase(connection)

        result = db.list_active_connection_credentials("conn-uuid")

        self.assertEqual(result, {})

    def test_list_active_connection_credentials_bytes_values(self) -> None:
        connection = FakeConnection(rows=[
            ("flex_token", b"some-ciphertext"),
        ])
        db = SuperFolioDatabase(connection)

        result = db.list_active_connection_credentials("conn-uuid")

        self.assertIsInstance(result["flex_token"], bytes)


class ActiveIntegrationFeedsTests(unittest.TestCase):
    """Tests for SuperFolioDatabase.list_active_integration_feeds (Task 11)."""

    def test_list_active_integration_feeds_maps_rows(self) -> None:
        from datetime import timezone
        now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        connection = FakeConnection(rows=[
            ("feed-uuid", "conn-uuid", "cash_flows", "Cash Flows", True, now, now),
        ])
        db = SuperFolioDatabase(connection)

        results = db.list_active_integration_feeds("conn-uuid")

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], IntegrationFeedRecord)
        self.assertEqual(results[0].id, "feed-uuid")
        self.assertEqual(results[0].connection_id, "conn-uuid")
        self.assertEqual(results[0].feed_key, "cash_flows")
        self.assertEqual(results[0].display_name, "Cash Flows")
        self.assertTrue(results[0].is_active)

    def test_list_active_integration_feeds_calls_db_function(self) -> None:
        connection = FakeConnection(rows=[])
        db = SuperFolioDatabase(connection)

        db.list_active_integration_feeds("conn-uuid")

        sql, params = connection.statements[0]
        self.assertIn("public.list_active_integration_feeds", sql)
        self.assertEqual(params, ("conn-uuid",))

    def test_list_active_integration_feeds_returns_empty_list(self) -> None:
        connection = FakeConnection(rows=[])
        db = SuperFolioDatabase(connection)

        result = db.list_active_integration_feeds("conn-uuid")

        self.assertEqual(result, [])

    def test_list_active_integration_feeds_allows_null_display_name(self) -> None:
        from datetime import timezone
        now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        connection = FakeConnection(rows=[
            ("feed-uuid", "conn-uuid", "daily", None, True, now, now),
        ])
        db = SuperFolioDatabase(connection)

        results = db.list_active_integration_feeds("conn-uuid")

        self.assertIsNone(results[0].display_name)


if __name__ == "__main__":
    unittest.main()
