"""Tests for portfolio_engine.automation.targets."""
from __future__ import annotations

import unittest

from portfolio_engine.automation.targets import (
    AutomationValidationError,
    parse_account_external_ids,
    validate_target_inputs,
)


class ParseAccountExternalIdsTests(unittest.TestCase):
    def test_basic_comma_separated(self) -> None:
        result = parse_account_external_ids(" U100, ,U200,U100,, ")
        self.assertEqual(result, ("U100", "U200"))

    def test_none_returns_empty_tuple(self) -> None:
        result = parse_account_external_ids(None)
        self.assertEqual(result, ())

    def test_empty_string_returns_empty_tuple(self) -> None:
        result = parse_account_external_ids("")
        self.assertEqual(result, ())

    def test_whitespace_only_returns_empty_tuple(self) -> None:
        result = parse_account_external_ids("  , , ,  ")
        self.assertEqual(result, ())

    def test_single_id(self) -> None:
        result = parse_account_external_ids("U123")
        self.assertEqual(result, ("U123",))

    def test_deduplication_preserves_first_seen_order(self) -> None:
        result = parse_account_external_ids("C, B, A, B, C")
        self.assertEqual(result, ("C", "B", "A"))

    def test_returns_tuple(self) -> None:
        result = parse_account_external_ids("U100")
        self.assertIsInstance(result, tuple)


class ValidateTargetInputsPortfolioTests(unittest.TestCase):
    def test_portfolio_with_name_succeeds(self) -> None:
        # Should not raise
        validate_target_inputs(
            target_type="portfolio",
            portfolio_name="My Portfolio",
            account_external_ids=(),
        )

    def test_portfolio_missing_name_raises(self) -> None:
        with self.assertRaises(AutomationValidationError) as ctx:
            validate_target_inputs(
                target_type="portfolio",
                portfolio_name=None,
                account_external_ids=(),
            )
        self.assertIn(
            "target_type=portfolio requires portfolio_name",
            str(ctx.exception),
        )
        # Must not imply the account_ids constraint also failed when it didn't.
        self.assertNotIn("rejects account_external_ids", str(ctx.exception))

    def test_portfolio_both_violations_raises_compound(self) -> None:
        # Missing name AND account ids present → compound message.
        with self.assertRaises(AutomationValidationError) as ctx:
            validate_target_inputs(
                target_type="portfolio",
                portfolio_name=None,
                account_external_ids=("U100",),
            )
        self.assertIn(
            "target_type=portfolio requires portfolio_name and rejects account_external_ids",
            str(ctx.exception),
        )

    def test_portfolio_blank_name_treated_as_absent(self) -> None:
        with self.assertRaises(AutomationValidationError):
            validate_target_inputs(
                target_type="portfolio",
                portfolio_name="   ",
                account_external_ids=(),
            )

    def test_portfolio_with_account_ids_raises(self) -> None:
        with self.assertRaises(AutomationValidationError) as ctx:
            validate_target_inputs(
                target_type="portfolio",
                portfolio_name="My Portfolio",
                account_external_ids=("U100",),
            )
        self.assertIn(
            "target_type=portfolio rejects account_external_ids",
            str(ctx.exception),
        )
        # Must not imply the portfolio_name constraint also failed when it didn't.
        self.assertNotIn("requires portfolio_name", str(ctx.exception))

    def test_portfolio_target_type_normalized(self) -> None:
        # Mixed case and whitespace should normalize to "portfolio"
        validate_target_inputs(
            target_type="  PORTFOLIO  ",
            portfolio_name="P1",
            account_external_ids=(),
        )


class ValidateTargetInputsAccountsTests(unittest.TestCase):
    def test_accounts_with_ids_succeeds(self) -> None:
        validate_target_inputs(
            target_type="accounts",
            portfolio_name=None,
            account_external_ids=("U100", "U200"),
        )

    def test_accounts_missing_ids_raises(self) -> None:
        with self.assertRaises(AutomationValidationError) as ctx:
            validate_target_inputs(
                target_type="accounts",
                portfolio_name=None,
                account_external_ids=(),
            )
        self.assertIn(
            "target_type=accounts requires account_external_ids",
            str(ctx.exception),
        )
        # Must not imply the portfolio_name constraint also failed when it didn't.
        self.assertNotIn("rejects portfolio_name", str(ctx.exception))

    def test_accounts_both_violations_raises_compound(self) -> None:
        # No account ids AND portfolio name present → compound message.
        with self.assertRaises(AutomationValidationError) as ctx:
            validate_target_inputs(
                target_type="accounts",
                portfolio_name="My Portfolio",
                account_external_ids=(),
            )
        self.assertIn(
            "target_type=accounts requires account_external_ids and rejects portfolio_name",
            str(ctx.exception),
        )

    def test_accounts_with_portfolio_name_raises(self) -> None:
        with self.assertRaises(AutomationValidationError) as ctx:
            validate_target_inputs(
                target_type="accounts",
                portfolio_name="My Portfolio",
                account_external_ids=("U100",),
            )
        self.assertIn(
            "target_type=accounts rejects portfolio_name",
            str(ctx.exception),
        )
        # Must not imply the account_ids constraint also failed when it didn't.
        self.assertNotIn("requires account_external_ids", str(ctx.exception))

    def test_accounts_blank_portfolio_name_treated_as_absent(self) -> None:
        # Blank portfolio_name should be treated as absent (not a conflict)
        validate_target_inputs(
            target_type="accounts",
            portfolio_name="   ",
            account_external_ids=("U100",),
        )

    def test_accounts_target_type_normalized(self) -> None:
        validate_target_inputs(
            target_type="  ACCOUNTS  ",
            portfolio_name=None,
            account_external_ids=("U100",),
        )


class ValidateTargetInputsInvalidTypeTests(unittest.TestCase):
    def test_invalid_target_type_raises(self) -> None:
        with self.assertRaises(AutomationValidationError) as ctx:
            validate_target_inputs(
                target_type="everything",
                portfolio_name=None,
                account_external_ids=(),
            )
        # Message must include all valid target types from VALID_TARGET_TYPES.
        msg = str(ctx.exception)
        self.assertIn("target_type must be", msg)
        self.assertIn("portfolio", msg)
        self.assertIn("accounts", msg)
        # Exact string expected for the current constant.
        self.assertIn("target_type must be portfolio or accounts", msg)

    def test_empty_target_type_raises(self) -> None:
        with self.assertRaises(AutomationValidationError):
            validate_target_inputs(
                target_type="",
                portfolio_name=None,
                account_external_ids=(),
            )

    def test_blank_target_type_raises(self) -> None:
        with self.assertRaises(AutomationValidationError):
            validate_target_inputs(
                target_type="   ",
                portfolio_name=None,
                account_external_ids=(),
            )


class AutomationValidationErrorTests(unittest.TestCase):
    def test_is_value_error_subclass(self) -> None:
        err = AutomationValidationError("test message")
        self.assertIsInstance(err, ValueError)
