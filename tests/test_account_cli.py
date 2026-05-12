from __future__ import annotations

import io
import unittest

from portfolio_engine.account_cli import AccountCliError, resolve_registration
from portfolio_engine.database import AccountRegistration


class AccountCliResolutionTests(unittest.TestCase):
    def test_all_parameters_supplied_resolve_without_prompting(self) -> None:
        registration = resolve_registration(
            brokerage_code=" IBKR ",
            external_id=" U100 ",
            account_type=" Individual ",
            base_currency=" USD ",
            display_name=" Main account ",
            stdin=io.StringIO("unused\n"),
            stdout=io.StringIO(),
            interactive=True,
        )

        self.assertEqual(registration.brokerage_code, "IBKR")
        self.assertEqual(registration.external_id, "U100")
        self.assertEqual(registration.account_type, "Individual")
        self.assertEqual(registration.base_currency, "USD")
        self.assertEqual(registration.display_name, "Main account")

    def test_missing_required_parameter_prompts_when_interactive(self) -> None:
        stdout = io.StringIO()

        registration = resolve_registration(
            brokerage_code="IBKR",
            external_id=None,
            account_type="Individual",
            base_currency="USD",
            display_name="Main account",
            stdin=io.StringIO("U100\n"),
            stdout=stdout,
            interactive=True,
        )

        self.assertEqual(registration.external_id, "U100")
        self.assertIn("External ID", stdout.getvalue())

    def test_missing_display_name_prompts_and_empty_answer_becomes_none(self) -> None:
        stdout = io.StringIO()

        registration = resolve_registration(
            brokerage_code="IBKR",
            external_id="U100",
            account_type="Individual",
            base_currency="USD",
            display_name=None,
            stdin=io.StringIO("\n"),
            stdout=stdout,
            interactive=True,
        )

        self.assertIsNone(registration.display_name)
        self.assertIn("Display name", stdout.getvalue())

    def test_blank_required_prompt_response_reprompts_until_non_blank(self) -> None:
        stdout = io.StringIO()

        registration = resolve_registration(
            brokerage_code="IBKR",
            external_id=None,
            account_type="Individual",
            base_currency="USD",
            display_name=None,
            stdin=io.StringIO("   \nU100\n\n"),
            stdout=stdout,
            interactive=True,
        )

        self.assertEqual(registration.external_id, "U100")
        self.assertIn("value is required", stdout.getvalue())

    def test_missing_required_parameters_fail_when_non_interactive(self) -> None:
        with self.assertRaisesRegex(
            AccountCliError,
            "Missing required option\\(s\\): --external-id, --base-currency",
        ):
            resolve_registration(
                brokerage_code="IBKR",
                external_id=None,
                account_type="Individual",
                base_currency=" ",
                display_name=None,
                stdin=io.StringIO(""),
                stdout=io.StringIO(),
                interactive=False,
            )


class FakeDatabase:
    def __init__(self, account_id: str = "account-uuid", error: Exception | None = None) -> None:
        self.account_id = account_id
        self.error = error
        self.registrations: list[AccountRegistration] = []
        self.close_count = 0

    def __enter__(self) -> "FakeDatabase":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self.close_count += 1

    def register_account(self, registration: AccountRegistration) -> str:
        if self.error is not None:
            raise self.error
        self.registrations.append(registration)
        return self.account_id


class FakeDatabaseFactory:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database
        self.database_urls: list[str | None] = []

    def __call__(self, database_url: str | None = None) -> FakeDatabase:
        self.database_urls.append(database_url)
        return self.database


class AccountCliRunTests(unittest.TestCase):
    def test_run_registers_account_and_prints_success(self) -> None:
        database = FakeDatabase()
        factory = FakeDatabaseFactory(database)
        stdout = io.StringIO()
        stderr = io.StringIO()

        from portfolio_engine.account_cli import run

        exit_code = run(
            [
                "--brokerage-code", "IBKR",
                "--external-id", "U100",
                "--account-type", "Individual",
                "--base-currency", "USD",
                "--display-name", "Main account",
                "--database-url", "postgresql://example",
            ],
            adapter_factory=factory,
            stdin=io.StringIO(""),
            stdout=stdout,
            stderr=stderr,
            interactive=False,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(factory.database_urls, ["postgresql://example"])
        self.assertEqual(
            database.registrations,
            [
                AccountRegistration(
                    brokerage_code="IBKR",
                    external_id="U100",
                    account_type="Individual",
                    base_currency="USD",
                    display_name="Main account",
                )
            ],
        )
        self.assertEqual(database.close_count, 1)
        self.assertIn("Registered account: account-uuid", stdout.getvalue())
        self.assertIn("External ID: U100", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_run_fails_before_database_call_when_required_flags_missing(self) -> None:
        database = FakeDatabase()
        factory = FakeDatabaseFactory(database)
        stderr = io.StringIO()

        from portfolio_engine.account_cli import run

        exit_code = run(
            ["--brokerage-code", "IBKR", "--account-type", "Individual"],
            adapter_factory=factory,
            stdin=io.StringIO(""),
            stdout=io.StringIO(),
            stderr=stderr,
            interactive=False,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(factory.database_urls, [])
        self.assertIn("Error: Missing required option(s): --external-id, --base-currency", stderr.getvalue())

    def test_run_prints_database_error_and_returns_nonzero(self) -> None:
        database = FakeDatabase(error=RuntimeError("unknown brokerage code"))
        factory = FakeDatabaseFactory(database)
        stderr = io.StringIO()

        from portfolio_engine.account_cli import run

        exit_code = run(
            [
                "--brokerage-code", "UNKNOWN",
                "--external-id", "U100",
                "--account-type", "Individual",
                "--base-currency", "USD",
            ],
            adapter_factory=factory,
            stdin=io.StringIO(""),
            stdout=io.StringIO(),
            stderr=stderr,
            interactive=False,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: unknown brokerage code", stderr.getvalue())

    def test_script_wrapper_imports_main(self) -> None:
        import scripts.register_account as register_account_script

        self.assertEqual(register_account_script.main.__module__, "portfolio_engine.account_cli")


if __name__ == "__main__":
    unittest.main()
