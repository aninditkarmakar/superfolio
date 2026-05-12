from __future__ import annotations

import os
import unittest
from dataclasses import FrozenInstanceError
from typing import Any

from portfolio_engine.database import (
    AccountRegistration,
    DatabaseConfigurationError,
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


if __name__ == "__main__":
    unittest.main()
