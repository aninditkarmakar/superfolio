"""Tests for the automation CLI entrypoint."""
from __future__ import annotations

import unittest
from io import StringIO

from portfolio_engine.automation.cli import run


def _result(status: str):
    """Build a minimal automation result object."""
    return type("Result", (), {"status": status, "summary": {}, "error_message": None})()


class AutomationCliTests(unittest.TestCase):
    def test_accounts_target_parses_and_runs(self) -> None:
        calls = []

        def fake_runner(request, database):
            calls.append(request)
            return type("Result", (), {"status": "succeeded", "summary": {}, "error_message": None})()

        stdout = StringIO()
        exit_code = run(
            [
                "--target-type", "accounts",
                "--integration", "ibkr_flex_ws",
                "--mode", "dry-run",
                "--start-date", "2026-05-01",
                "--end-date", "2026-05-14",
                "--account-external-ids", "U100,,U200",
            ],
            stdout=stdout,
            runner=fake_runner,
            database_connector=lambda: object(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls[0].account_external_ids, ("U100", "U200"))
        self.assertIn("Automation status: succeeded", stdout.getvalue())

    def test_partial_status_exits_zero_with_warning(self) -> None:
        def fake_runner(request, database):
            return type("Result", (), {"status": "partially_succeeded", "summary": {}, "error_message": None})()

        stdout = StringIO()
        exit_code = run(
            [
                "--target-type", "accounts",
                "--integration", "ibkr_flex_ws",
                "--mode", "dry-run",
                "--start-date", "2026-05-01",
                "--end-date", "2026-05-14",
                "--account-external-ids", "U100",
            ],
            stdout=stdout,
            runner=fake_runner,
            database_connector=lambda: object(),
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("WARNING", stdout.getvalue())

    def test_failed_status_exits_one(self) -> None:
        def fake_runner(request, database):
            return type("Result", (), {"status": "failed", "summary": {}, "error_message": "bad"})()

        stdout = StringIO()
        exit_code = run(
            [
                "--target-type", "accounts",
                "--integration", "ibkr_flex_ws",
                "--mode", "dry-run",
                "--start-date", "2026-05-01",
                "--end-date", "2026-05-14",
                "--account-external-ids", "U100",
            ],
            stdout=stdout,
            runner=fake_runner,
            database_connector=lambda: object(),
        )

        self.assertEqual(exit_code, 1)

    def test_error_message_printed_on_failure(self) -> None:
        def fake_runner(request, database):
            return type("Result", (), {"status": "failed", "summary": {}, "error_message": "bad thing happened"})()

        stdout = StringIO()
        exit_code = run(
            [
                "--target-type", "accounts",
                "--integration", "ibkr_flex_ws",
                "--mode", "dry-run",
                "--start-date", "2026-05-01",
                "--end-date", "2026-05-14",
                "--account-external-ids", "U100",
            ],
            stdout=stdout,
            runner=fake_runner,
            database_connector=lambda: object(),
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Message: bad thing happened", stdout.getvalue())

    def test_runtime_exception_writes_to_stderr_and_exits_one(self) -> None:
        def fake_runner(request, database):
            raise RuntimeError("unexpected crash")

        stderr = StringIO()
        exit_code = run(
            [
                "--target-type", "accounts",
                "--integration", "ibkr_flex_ws",
                "--mode", "dry-run",
                "--start-date", "2026-05-01",
                "--end-date", "2026-05-14",
                "--account-external-ids", "U100",
            ],
            stderr=stderr,
            runner=fake_runner,
            database_connector=lambda: object(),
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error:", stderr.getvalue())
        self.assertIn("unexpected crash", stderr.getvalue())

    def test_portfolio_target_parses_and_runs(self) -> None:
        calls = []

        def fake_runner(request, database):
            calls.append(request)
            return type("Result", (), {"status": "succeeded", "summary": {}, "error_message": None})()

        stdout = StringIO()
        exit_code = run(
            [
                "--target-type", "portfolio",
                "--integration", "ibkr_flex_ws",
                "--mode", "load",
                "--start-date", "2026-05-01",
                "--end-date", "2026-05-14",
                "--portfolio-name", "MyPortfolio",
            ],
            stdout=stdout,
            runner=fake_runner,
            database_connector=lambda: object(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls[0].portfolio_name, "MyPortfolio")
        self.assertEqual(calls[0].target_type, "portfolio")

    def test_default_integration_is_ibkr_flex_ws(self) -> None:
        calls = []

        def fake_runner(request, database):
            calls.append(request)
            return type("Result", (), {"status": "succeeded", "summary": {}, "error_message": None})()

        run(
            [
                "--target-type", "accounts",
                "--mode", "dry-run",
                "--start-date", "2026-05-01",
                "--end-date", "2026-05-14",
                "--account-external-ids", "U100",
            ],
            runner=fake_runner,
            database_connector=lambda: object(),
        )

        self.assertEqual(calls[0].integration_key, "ibkr_flex_ws")

    def test_database_context_manager_is_used(self) -> None:
        """Verify that a context-manager database connector is entered/exited."""
        entered = []
        exited = []

        class FakeDB:
            def __enter__(self):
                entered.append(True)
                return self

            def __exit__(self, *args):
                exited.append(True)

        def fake_runner(request, database):
            return type("Result", (), {"status": "succeeded", "summary": {}, "error_message": None})()

        run(
            [
                "--target-type", "accounts",
                "--integration", "ibkr_flex_ws",
                "--mode", "dry-run",
                "--start-date", "2026-05-01",
                "--end-date", "2026-05-14",
                "--account-external-ids", "U100",
            ],
            runner=fake_runner,
            database_connector=FakeDB,
        )

        self.assertEqual(entered, [True])
        self.assertEqual(exited, [True])

    def test_automation_cli_does_not_require_connection_input(self) -> None:
        stdout = StringIO()

        exit_code = run(
            [
                "--target-type", "accounts",
                "--integration", "ibkr_flex_ws",
                "--mode", "dry-run",
                "--start-date", "2026-05-01",
                "--end-date", "2026-05-14",
                "--account-external-ids", "U100",
            ],
            stdout=stdout,
            runner=lambda request, database: _result("succeeded"),
            database_connector=lambda: object(),
        )

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
