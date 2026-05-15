from __future__ import annotations

import unittest

from portfolio_engine.automation.fetch_errors import (
    ALLOWED_BROKER_FETCH_CATEGORIES,
    BrokerFetchError,
    safe_fetch_error_category,
)


class BrokerFetchErrorTests(unittest.TestCase):
    def test_allowed_categories_include_ibkr_categories(self) -> None:
        self.assertIn("ibkr_auth_failed", ALLOWED_BROKER_FETCH_CATEGORIES)
        self.assertIn("ibkr_invalid_query", ALLOWED_BROKER_FETCH_CATEGORIES)
        self.assertIn("ibkr_pacing_limit", ALLOWED_BROKER_FETCH_CATEGORIES)
        self.assertIn("ibkr_report_not_ready", ALLOWED_BROKER_FETCH_CATEGORIES)
        self.assertIn("ibkr_fetch_failed", ALLOWED_BROKER_FETCH_CATEGORIES)

    def test_broker_fetch_error_stores_category_and_sanitized_message_source(self) -> None:
        exc = BrokerFetchError("ibkr_auth_failed", "Token has expired.")

        self.assertEqual(exc.category, "ibkr_auth_failed")
        self.assertEqual(str(exc), "Token has expired.")

    def test_safe_fetch_error_category_allows_known_category(self) -> None:
        exc = BrokerFetchError("ibkr_pacing_limit", "Too many requests.")

        self.assertEqual(safe_fetch_error_category(exc), "ibkr_pacing_limit")

    def test_safe_fetch_error_category_falls_back_for_unknown_category(self) -> None:
        exc = BrokerFetchError("new_future_category", "New future error.")

        self.assertEqual(safe_fetch_error_category(exc), "feed_fetch_failed")

    def test_safe_fetch_error_category_falls_back_for_non_fetch_exception(self) -> None:
        self.assertEqual(safe_fetch_error_category(RuntimeError("boom")), "feed_fetch_failed")


if __name__ == "__main__":
    unittest.main()
