from __future__ import annotations

import unittest

from portfolio_engine.automation.summary import (
    COUNT_KEYS,
    RECORD_TYPES,
    build_child_summary,
    build_parent_summary,
    empty_record_counts,
)
from portfolio_engine.automation.sanitization import sanitize_error_message


class EmptyRecordCountsTests(unittest.TestCase):
    def test_shape_has_all_record_types(self) -> None:
        counts = empty_record_counts()
        for rt in RECORD_TYPES:
            self.assertIn(rt, counts)

    def test_shape_has_all_count_keys(self) -> None:
        counts = empty_record_counts()
        for rt in RECORD_TYPES:
            for key in COUNT_KEYS:
                self.assertIn(key, counts[rt])

    def test_cash_flows_supported_is_zero(self) -> None:
        counts = empty_record_counts()
        self.assertEqual(counts["cash_flows"]["supported"], 0)

    def test_cash_flows_skipped_other_account_is_zero(self) -> None:
        counts = empty_record_counts()
        self.assertEqual(counts["cash_flows"]["skipped_other_account"], 0)

    def test_daily_nav_snapshots_conflicts_is_zero(self) -> None:
        counts = empty_record_counts()
        self.assertEqual(counts["daily_nav_snapshots"]["conflicts"], 0)

    def test_returns_fresh_object_each_call(self) -> None:
        a = empty_record_counts()
        b = empty_record_counts()
        a["cash_flows"]["supported"] = 99
        self.assertEqual(b["cash_flows"]["supported"], 0)


class BuildChildSummaryTests(unittest.TestCase):
    def test_returns_record_counts_key(self) -> None:
        result = build_child_summary()
        self.assertIn("record_counts", result)

    def test_record_counts_has_all_record_types(self) -> None:
        result = build_child_summary()
        for rt in RECORD_TYPES:
            self.assertIn(rt, result["record_counts"])

    def test_record_counts_has_all_count_keys(self) -> None:
        result = build_child_summary()
        for rt in RECORD_TYPES:
            for key in COUNT_KEYS:
                self.assertIn(key, result["record_counts"][rt])

    def test_no_error_category_by_default(self) -> None:
        result = build_child_summary()
        self.assertNotIn("error_category", result)

    def test_error_category_included_when_provided(self) -> None:
        result = build_child_summary(error_category="network_error")
        self.assertEqual(result["error_category"], "network_error")

    def test_counts_reflect_supplied_values(self) -> None:
        result = build_child_summary(
            cash_supported=5,
            cash_inserted=3,
            cash_duplicates=1,
            cash_skipped_other_account=1,
        )
        rc = result["record_counts"]
        self.assertEqual(rc["cash_flows"]["supported"], 5)
        self.assertEqual(rc["cash_flows"]["inserted"], 3)
        self.assertEqual(rc["cash_flows"]["duplicates"], 1)
        self.assertEqual(rc["cash_flows"]["skipped_other_account"], 1)

    def test_excludes_value_like_fields(self) -> None:
        # Verify no absolute financial value fields appear as keys in the summary.
        # NOTE: "nav" is permitted as a substring of the record type "daily_nav_snapshots";
        # what must be absent are standalone financial fields like amount, balance, price.
        result = build_child_summary()
        all_keys: set[str] = set()
        for key, val in result.items():
            all_keys.add(key)
            if isinstance(val, dict):
                for subkey, subval in val.items():
                    all_keys.add(subkey)
                    if isinstance(subval, dict):
                        all_keys.update(subval.keys())
        for forbidden in ("amount", "balance", "price"):
            self.assertNotIn(forbidden, all_keys)

    def test_returns_fresh_object_each_call(self) -> None:
        a = build_child_summary()
        b = build_child_summary()
        a["record_counts"]["cash_flows"]["supported"] = 42
        self.assertEqual(b["record_counts"]["cash_flows"]["supported"], 0)


class BuildParentSummaryTests(unittest.TestCase):
    def test_account_counts_total(self) -> None:
        result = build_parent_summary(
            child_statuses=["succeeded", "failed"],
            child_summaries=[empty_record_counts(), empty_record_counts()],
        )
        self.assertEqual(result["account_counts"]["total"], 2)

    def test_account_counts_succeeded(self) -> None:
        result = build_parent_summary(
            child_statuses=["succeeded", "succeeded", "failed"],
            child_summaries=[empty_record_counts(), empty_record_counts(), empty_record_counts()],
        )
        self.assertEqual(result["account_counts"]["succeeded"], 2)

    def test_account_counts_partially_succeeded(self) -> None:
        result = build_parent_summary(
            child_statuses=["partially_succeeded"],
            child_summaries=[empty_record_counts()],
        )
        self.assertEqual(result["account_counts"]["partially_succeeded"], 1)

    def test_account_counts_failed(self) -> None:
        result = build_parent_summary(
            child_statuses=["failed"],
            child_summaries=[empty_record_counts()],
        )
        self.assertEqual(result["account_counts"]["failed"], 1)

    def test_record_counts_aggregated_from_child_summaries(self) -> None:
        child_a = build_child_summary(cash_supported=3, cash_inserted=2)
        child_b = build_child_summary(cash_supported=5, cash_inserted=4)
        result = build_parent_summary(
            child_statuses=["succeeded", "succeeded"],
            child_summaries=[child_a, child_b],
        )
        self.assertEqual(result["record_counts"]["cash_flows"]["supported"], 8)
        self.assertEqual(result["record_counts"]["cash_flows"]["inserted"], 6)

    def test_nav_aggregation_through_build_parent_summary(self) -> None:
        child = build_child_summary(nav_supported=4)
        result = build_parent_summary(
            child_statuses=["succeeded"],
            child_summaries=[child],
        )
        self.assertEqual(result["record_counts"]["daily_nav_snapshots"]["supported"], 4)

    def test_accepts_raw_record_counts_dicts(self) -> None:
        rc = empty_record_counts()
        rc["daily_nav_snapshots"]["inserted"] = 7
        result = build_parent_summary(
            child_statuses=["succeeded"],
            child_summaries=[rc],
        )
        self.assertEqual(result["record_counts"]["daily_nav_snapshots"]["inserted"], 7)

    def test_empty_children(self) -> None:
        result = build_parent_summary(child_statuses=[], child_summaries=[])
        self.assertEqual(result["account_counts"]["total"], 0)
        self.assertEqual(result["record_counts"]["cash_flows"]["supported"], 0)

    def test_returns_fresh_object_each_call(self) -> None:
        a = build_parent_summary(child_statuses=[], child_summaries=[])
        b = build_parent_summary(child_statuses=[], child_summaries=[])
        a["record_counts"]["cash_flows"]["supported"] = 99
        self.assertEqual(b["record_counts"]["cash_flows"]["supported"], 0)


class SanitizeErrorMessageTests(unittest.TestCase):
    def test_none_returns_none(self) -> None:
        self.assertIsNone(sanitize_error_message(None))

    def test_plain_message_passes_through(self) -> None:
        result = sanitize_error_message("connection refused")
        self.assertEqual(result, "connection refused")

    def test_redacts_postgres_url(self) -> None:
        msg = "Error: postgresql://user:secret@host:5432/dbname failed"
        result = sanitize_error_message(msg)
        self.assertNotIn("secret", result)
        self.assertNotIn("postgresql://", result)
        self.assertIn("[redacted]", result)

    def test_redacts_postgres_url_variant(self) -> None:
        msg = "conn=postgres://admin:pass@localhost/mydb"
        result = sanitize_error_message(msg)
        self.assertNotIn("admin", result)
        self.assertNotIn("pass", result)
        self.assertIn("[redacted]", result)

    def test_redacts_token_assignment(self) -> None:
        msg = "token=abc123xyz789 was rejected"
        result = sanitize_error_message(msg)
        self.assertNotIn("abc123xyz789", result)
        self.assertIn("[redacted]", result)

    def test_redacts_password_assignment(self) -> None:
        msg = "password=hunter2 is wrong"
        result = sanitize_error_message(msg)
        self.assertNotIn("hunter2", result)
        self.assertIn("[redacted]", result)

    def test_redacts_secret_assignment(self) -> None:
        msg = "secret=mysecretvalue caused failure"
        result = sanitize_error_message(msg)
        self.assertNotIn("mysecretvalue", result)
        self.assertIn("[redacted]", result)

    def test_redacts_key_assignment(self) -> None:
        msg = "api_key=ABCDEFGH1234 expired"
        result = sanitize_error_message(msg)
        self.assertNotIn("ABCDEFGH1234", result)
        self.assertIn("[redacted]", result)

    def test_redacts_amount_assignment(self) -> None:
        msg = "amount=12345.67 exceeded limit"
        result = sanitize_error_message(msg)
        self.assertNotIn("12345.67", result)
        self.assertIn("[redacted]", result)

    def test_redacts_nav_assignment(self) -> None:
        msg = "nav=99999.00 was calculated"
        result = sanitize_error_message(msg)
        self.assertNotIn("99999.00", result)
        self.assertIn("[redacted]", result)

    def test_truncates_to_500_chars(self) -> None:
        long_msg = "x" * 1000
        result = sanitize_error_message(long_msg)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertLessEqual(len(result), 500)

    def test_short_message_not_truncated(self) -> None:
        msg = "short error"
        result = sanitize_error_message(msg)
        self.assertEqual(result, msg)


if __name__ == "__main__":
    unittest.main()
