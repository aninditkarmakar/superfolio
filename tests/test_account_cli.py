from __future__ import annotations

import io
import unittest

from portfolio_engine.account_cli import AccountCliError, resolve_registration


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


if __name__ == "__main__":
    unittest.main()
