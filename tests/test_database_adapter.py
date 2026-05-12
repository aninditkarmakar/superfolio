from __future__ import annotations

import os
import unittest
from dataclasses import FrozenInstanceError
from datetime import date
from typing import Any

from portfolio_engine.database import (
    AccountRegistration,
    BulkIngestionSummary,
    DatabaseConfigurationError,
    IngestionRunStart,
    SuperFolioDatabase,
    connect_database,
)


class FakeCursor:
    def __init__(self, row: tuple[Any, ...] | None = None) -> None:
        self.row = row
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row


class FakeConnection:
    def __init__(self, row: tuple[Any, ...] | None = None) -> None:
        self.cursor_instance = FakeCursor(row)
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
                    "SELECT public.start_ingestion_run(%s, %s, %s, %s, %s)",
                    (
                        "IBKR",
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
                source_type="MANUAL_FILE",
            )
        )

        self.assertEqual(
            connection.cursor_instance.executed[0][1],
            ("IBKR", "MANUAL_FILE", None, None, None),
        )

    def test_start_ingestion_run_rolls_back_and_reraises_on_failure(self) -> None:
        connection = FailingConnection()
        database = SuperFolioDatabase(connection)

        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            database.start_ingestion_run(
                IngestionRunStart(
                    brokerage_code="IBKR",
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



if __name__ == "__main__":
    unittest.main()
