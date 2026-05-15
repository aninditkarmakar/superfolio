from __future__ import annotations

import unittest
from io import StringIO
from cryptography.fernet import Fernet

from portfolio_engine.automation.connection_cli import run


class ConnectionCliTests(unittest.TestCase):
    def test_create_connection_calls_database(self) -> None:
        calls = []

        class FakeDatabase:
            def create_integration_connection(self, request):
                calls.append(request)
                return "connection-uuid"

        stdout = StringIO()
        code = run(
            ["create", "--integration", "ibkr_flex_ws", "--brokerage-code", "IBKR", "--name", "IBKR Personal"],
            stdout=stdout,
            database_connector=lambda: FakeDatabase(),
            environ={"SUPERFOLIO_CREDENTIAL_MASTER_KEY": Fernet.generate_key().decode("ascii")},
        )

        self.assertEqual(code, 0)
        self.assertEqual(calls[0].name, "IBKR Personal")
        self.assertIn("connection-uuid", stdout.getvalue())

    def test_set_credential_encrypts_plaintext(self) -> None:
        captured = []

        class FakeDatabase:
            def set_integration_credential(self, request):
                captured.append(request)
                return "credential-uuid"

        code = run(
            [
                "set-credential",
                "--connection-id", "connection-uuid",
                "--credential-name", "flex_token",
                "--value-from-env", "MY_TOKEN",
            ],
            stdout=StringIO(),
            database_connector=lambda: FakeDatabase(),
            environ={
                "SUPERFOLIO_CREDENTIAL_MASTER_KEY": Fernet.generate_key().decode("ascii"),
                "MY_TOKEN": "plain-token",
            },
        )

        self.assertEqual(code, 0)
        self.assertNotEqual(captured[0].ciphertext, b"plain-token")
        self.assertNotIn(b"plain-token", captured[0].ciphertext)

    def test_create_connection_sets_integration_and_brokerage(self) -> None:
        calls = []

        class FakeDatabase:
            def create_integration_connection(self, request):
                calls.append(request)
                return "uuid-123"

        code = run(
            ["create", "--integration", "ibkr_flex_ws", "--brokerage-code", "IBKR", "--name", "Test"],
            stdout=StringIO(),
            database_connector=lambda: FakeDatabase(),
            environ={"SUPERFOLIO_CREDENTIAL_MASTER_KEY": Fernet.generate_key().decode("ascii")},
        )

        self.assertEqual(code, 0)
        self.assertEqual(calls[0].integration_key, "ibkr_flex_ws")
        self.assertEqual(calls[0].brokerage_code, "IBKR")

    def test_set_credential_prints_credential_id(self) -> None:
        class FakeDatabase:
            def set_integration_credential(self, request):
                return "cred-uuid"

        stdout = StringIO()
        code = run(
            [
                "set-credential",
                "--connection-id", "conn-id",
                "--credential-name", "flex_token",
                "--value-from-env", "MY_SECRET",
            ],
            stdout=stdout,
            database_connector=lambda: FakeDatabase(),
            environ={
                "SUPERFOLIO_CREDENTIAL_MASTER_KEY": Fernet.generate_key().decode("ascii"),
                "MY_SECRET": "secret",
            },
        )

        self.assertEqual(code, 0)
        self.assertIn("cred-uuid", stdout.getvalue())

    def test_set_credential_does_not_print_plaintext(self) -> None:
        class FakeDatabase:
            def set_integration_credential(self, request):
                return "cred-uuid"

        stdout = StringIO()
        stderr = StringIO()
        run(
            [
                "set-credential",
                "--connection-id", "conn-id",
                "--credential-name", "flex_token",
                "--value-from-env", "MY_SUPER_SECRET",
            ],
            stdout=stdout,
            stderr=stderr,
            database_connector=lambda: FakeDatabase(),
            environ={
                "SUPERFOLIO_CREDENTIAL_MASTER_KEY": Fernet.generate_key().decode("ascii"),
                "MY_SUPER_SECRET": "my-super-secret-token",
            },
        )

        combined = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn("my-super-secret-token", combined)

    def test_set_credential_missing_master_key_returns_1(self) -> None:
        class FakeDatabase:
            def set_integration_credential(self, request):
                return "cred-uuid"

        stderr = StringIO()
        code = run(
            [
                "set-credential",
                "--connection-id", "conn-id",
                "--credential-name", "flex_token",
                "--value-from-env", "MY_SECRET",
            ],
            stdout=StringIO(),
            stderr=stderr,
            database_connector=lambda: FakeDatabase(),
            environ={"MY_SECRET": "secret"},
        )

        self.assertEqual(code, 1)
        self.assertIn("master key", stderr.getvalue().lower())

    def test_set_credential_stores_encryption_key_id_and_version(self) -> None:
        captured = []

        class FakeDatabase:
            def set_integration_credential(self, request):
                captured.append(request)
                return "cred-uuid"

        run(
            [
                "set-credential",
                "--connection-id", "conn-id",
                "--credential-name", "flex_token",
                "--value-from-env", "MY_SECRET",
            ],
            stdout=StringIO(),
            database_connector=lambda: FakeDatabase(),
            environ={
                "SUPERFOLIO_CREDENTIAL_MASTER_KEY": Fernet.generate_key().decode("ascii"),
                "MY_SECRET": "secret",
            },
        )

        self.assertEqual(captured[0].encryption_key_id, "v1")
        self.assertEqual(captured[0].encryption_version, 1)

    def test_add_feed_calls_database(self) -> None:
        calls = []

        class FakeDatabase:
            def create_integration_feed(self, request):
                calls.append(request)
                return "feed-uuid"

        stdout = StringIO()
        code = run(
            ["add-feed", "--connection-id", "conn-id", "--feed-key", "flex_cash_flows"],
            stdout=stdout,
            database_connector=lambda: FakeDatabase(),
            environ={},
        )

        self.assertEqual(code, 0)
        self.assertEqual(calls[0].connection_id, "conn-id")
        self.assertEqual(calls[0].feed_key, "flex_cash_flows")
        self.assertIn("feed-uuid", stdout.getvalue())

    def test_add_feed_with_display_name(self) -> None:
        calls = []

        class FakeDatabase:
            def create_integration_feed(self, request):
                calls.append(request)
                return "feed-uuid"

        code = run(
            ["add-feed", "--connection-id", "conn-id", "--feed-key", "flex_cash_flows", "--display-name", "Cash Flows"],
            stdout=StringIO(),
            database_connector=lambda: FakeDatabase(),
            environ={},
        )

        self.assertEqual(code, 0)
        self.assertEqual(calls[0].display_name, "Cash Flows")

    def test_assign_account_calls_database(self) -> None:
        calls = []

        class FakeDatabase:
            def set_account_integration_assignment(self, request):
                calls.append(request)
                return "assignment-id"

        stdout = StringIO()
        code = run(
            [
                "assign-account",
                "--connection-id", "conn-id",
                "--brokerage-code", "IBKR",
                "--account-external-id", "U12345",
            ],
            stdout=stdout,
            database_connector=lambda: FakeDatabase(),
            environ={},
        )

        self.assertEqual(code, 0)
        self.assertEqual(calls[0].connection_id, "conn-id")
        self.assertEqual(calls[0].brokerage_code, "IBKR")
        self.assertEqual(calls[0].account_external_id, "U12345")
        self.assertIn("assignment-id", stdout.getvalue())

    def test_assign_accounts_assigns_each_account(self) -> None:
        calls = []

        class FakeDatabase:
            def set_account_integration_assignment(self, request):
                calls.append(request)
                return "assignment-id"

        code = run(
            [
                "assign-accounts",
                "--connection-id", "conn-id",
                "--brokerage-code", "IBKR",
                "--account-external-id", "U11111",
                "--account-external-id", "U22222",
            ],
            stdout=StringIO(),
            database_connector=lambda: FakeDatabase(),
            environ={},
        )

        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)
        external_ids = {c.account_external_id for c in calls}
        self.assertIn("U11111", external_ids)
        self.assertIn("U22222", external_ids)

    def test_validate_assignments_returns_0_when_no_missing(self) -> None:
        class FakeDatabase:
            def validate_account_integration_assignments(self, *, target_type, portfolio_name, brokerage_code, account_external_ids):
                return []

        stdout = StringIO()
        code = run(
            [
                "validate-assignments",
                "--target-type", "account_list",
                "--brokerage-code", "IBKR",
                "--account-external-id", "U12345",
            ],
            stdout=stdout,
            database_connector=lambda: FakeDatabase(),
            environ={},
        )

        self.assertEqual(code, 0)

    def test_validate_assignments_returns_1_when_missing(self) -> None:
        class FakeDatabase:
            def validate_account_integration_assignments(self, *, target_type, portfolio_name, brokerage_code, account_external_ids):
                return ["U99999"]

        stderr = StringIO()
        code = run(
            [
                "validate-assignments",
                "--target-type", "account_list",
                "--brokerage-code", "IBKR",
                "--account-external-id", "U99999",
            ],
            stdout=StringIO(),
            stderr=stderr,
            database_connector=lambda: FakeDatabase(),
            environ={},
        )

        self.assertEqual(code, 1)
        self.assertIn("U99999", stderr.getvalue())

    def test_assign_portfolio_calls_validate(self) -> None:
        calls = []

        class FakeDatabase:
            def validate_account_integration_assignments(self, *, target_type, portfolio_name, brokerage_code, account_external_ids):
                calls.append((target_type, portfolio_name, brokerage_code, account_external_ids))
                return []

        stdout = StringIO()
        code = run(
            [
                "assign-portfolio",
                "--portfolio-name", "MyPortfolio",
                "--brokerage-code", "IBKR",
            ],
            stdout=stdout,
            database_connector=lambda: FakeDatabase(),
            environ={},
        )

        self.assertEqual(code, 0)
        self.assertEqual(calls[0][0], "portfolio")
        self.assertEqual(calls[0][1], "MyPortfolio")
        self.assertEqual(calls[0][2], "IBKR")

    def test_list_connections_calls_database(self) -> None:
        from datetime import datetime, timezone

        class FakeDatabase:
            def list_integration_connections(self):
                from portfolio_engine.database import IntegrationConnectionRecord
                return [
                    IntegrationConnectionRecord(
                        id="conn-uuid",
                        integration_key="ibkr_flex_ws",
                        brokerage_code="IBKR",
                        name="Personal",
                        is_active=True,
                        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    )
                ]

        stdout = StringIO()
        code = run(
            ["list-connections"],
            stdout=stdout,
            database_connector=lambda: FakeDatabase(),
            environ={},
        )

        self.assertEqual(code, 0)
        output = stdout.getvalue()
        self.assertIn("conn-uuid", output)
        self.assertIn("ibkr_flex_ws", output)

    def test_list_feeds_calls_database(self) -> None:
        from datetime import datetime, timezone

        class FakeDatabase:
            def list_integration_feeds(self, connection_id):
                from portfolio_engine.database import IntegrationFeedRecord
                return [
                    IntegrationFeedRecord(
                        id="feed-uuid",
                        connection_id=connection_id,
                        feed_key="flex_cash_flows",
                        display_name="Cash Flows",
                        is_active=True,
                        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    )
                ]

        stdout = StringIO()
        code = run(
            ["list-feeds", "--connection-id", "conn-uuid"],
            stdout=stdout,
            database_connector=lambda: FakeDatabase(),
            environ={},
        )

        self.assertEqual(code, 0)
        output = stdout.getvalue()
        self.assertIn("feed-uuid", output)
        self.assertIn("flex_cash_flows", output)

    def test_unknown_command_returns_1(self) -> None:
        stderr = StringIO()
        code = run(
            ["unknown-command"],
            stdout=StringIO(),
            stderr=stderr,
            database_connector=lambda: None,
            environ={},
        )

        self.assertEqual(code, 1)

    def test_set_credential_rejects_value_flag(self) -> None:
        """--value must not be accepted; only --value-from-env is allowed."""
        class FakeDatabase:
            def set_integration_credential(self, request):
                return "cred-uuid"

        stderr = StringIO()
        code = run(
            [
                "set-credential",
                "--connection-id", "conn-id",
                "--credential-name", "flex_token",
                "--value", "some-plaintext",
            ],
            stdout=StringIO(),
            stderr=stderr,
            database_connector=lambda: FakeDatabase(),
            environ={"SUPERFOLIO_CREDENTIAL_MASTER_KEY": Fernet.generate_key().decode("ascii")},
        )

        self.assertEqual(code, 1)

    def test_set_credential_missing_value_env_var_returns_1(self) -> None:
        """Return 1 with actionable error when the named env var is absent."""
        class FakeDatabase:
            def set_integration_credential(self, request):
                return "cred-uuid"

        stderr = StringIO()
        code = run(
            [
                "set-credential",
                "--connection-id", "conn-id",
                "--credential-name", "flex_token",
                "--value-from-env", "MISSING_VAR",
            ],
            stdout=StringIO(),
            stderr=stderr,
            database_connector=lambda: FakeDatabase(),
            environ={"SUPERFOLIO_CREDENTIAL_MASTER_KEY": Fernet.generate_key().decode("ascii")},
        )

        self.assertEqual(code, 1)
        err = stderr.getvalue()
        self.assertIn("MISSING_VAR", err)

    def test_set_credential_blank_value_env_var_returns_1(self) -> None:
        """Return 1 with actionable error when the named env var is blank."""
        class FakeDatabase:
            def set_integration_credential(self, request):
                return "cred-uuid"

        stderr = StringIO()
        code = run(
            [
                "set-credential",
                "--connection-id", "conn-id",
                "--credential-name", "flex_token",
                "--value-from-env", "BLANK_VAR",
            ],
            stdout=StringIO(),
            stderr=stderr,
            database_connector=lambda: FakeDatabase(),
            environ={
                "SUPERFOLIO_CREDENTIAL_MASTER_KEY": Fernet.generate_key().decode("ascii"),
                "BLANK_VAR": "",
            },
        )

        self.assertEqual(code, 1)
        err = stderr.getvalue()
        self.assertIn("BLANK_VAR", err)

    def test_assign_accounts_partial_failure_identifies_account(self) -> None:
        """When the second account fails, stderr identifies that account and exit code is 1."""
        assigned = []

        class FakeDatabase:
            def set_account_integration_assignment(self, request):
                if request.account_external_id == "U22222":
                    raise RuntimeError("db error")
                assigned.append(request.account_external_id)
                return "assignment-id"

        stdout = StringIO()
        stderr = StringIO()
        code = run(
            [
                "assign-accounts",
                "--connection-id", "conn-id",
                "--brokerage-code", "IBKR",
                "--account-external-id", "U11111",
                "--account-external-id", "U22222",
            ],
            stdout=stdout,
            stderr=stderr,
            database_connector=lambda: FakeDatabase(),
            environ={},
        )

        self.assertEqual(code, 1)
        # First account was assigned successfully
        self.assertIn("U11111", assigned)
        # Stderr identifies the failing account
        self.assertIn("U22222", stderr.getvalue())
        # Stderr does not contain raw exception message
        self.assertNotIn("db error", stderr.getvalue())
        class FakeDatabase:
            def create_integration_connection(self, request):
                raise RuntimeError("connection string: postgresql://user:secret@host/db")

        stderr = StringIO()
        code = run(
            ["create", "--integration", "ibkr_flex_ws", "--brokerage-code", "IBKR", "--name", "Test"],
            stdout=StringIO(),
            stderr=stderr,
            database_connector=lambda: FakeDatabase(),
            environ={"SUPERFOLIO_CREDENTIAL_MASTER_KEY": Fernet.generate_key().decode("ascii")},
        )

        self.assertEqual(code, 1)
        err = stderr.getvalue()
        self.assertTrue(len(err) > 0)
        # Should not expose raw connection string details
        self.assertNotIn("postgresql://", err)


if __name__ == "__main__":
    unittest.main()
