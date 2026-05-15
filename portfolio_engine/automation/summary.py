from __future__ import annotations

from typing import Any

from portfolio_engine.automation.sanitization import sanitize_error_message

RECORD_TYPES = ("cash_flows", "daily_nav_snapshots")
COUNT_KEYS = (
    "supported",
    "inserted",
    "duplicates",
    "skipped_unknown_account",
    "skipped_inactive_account",
    "skipped_other_account",
    "conflicts",
)


def empty_record_counts() -> dict[str, dict[str, int]]:
    """Return a fresh nested dict of zero counts for all record types and count keys."""
    return {rt: {key: 0 for key in COUNT_KEYS} for rt in RECORD_TYPES}


_FEED_RESULT_ALLOWED_FIELDS = frozenset(
    {"feed_key", "display_name", "status", "error_category", "record_counts", "message"}
)


def _sanitize_feed_result(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of entry with only allowed non-secret fields, sanitizing message."""
    result: dict[str, Any] = {}
    for field in _FEED_RESULT_ALLOWED_FIELDS:
        if field not in entry:
            continue
        if field == "message":
            result[field] = sanitize_error_message(entry[field])
        else:
            result[field] = entry[field]
    return result


def build_child_summary(
    *,
    cash_supported: int = 0,
    cash_inserted: int = 0,
    cash_duplicates: int = 0,
    cash_skipped_unknown_account: int = 0,
    cash_skipped_inactive_account: int = 0,
    cash_skipped_other_account: int = 0,
    cash_conflicts: int = 0,
    nav_supported: int = 0,
    nav_inserted: int = 0,
    nav_duplicates: int = 0,
    nav_skipped_unknown_account: int = 0,
    nav_skipped_inactive_account: int = 0,
    nav_skipped_other_account: int = 0,
    nav_conflicts: int = 0,
    error_category: str | None = None,
    feed_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a sanitized child (account-level) summary dict with record_counts only."""
    counts: dict[str, dict[str, int]] = {
        "cash_flows": {
            "supported": cash_supported,
            "inserted": cash_inserted,
            "duplicates": cash_duplicates,
            "skipped_unknown_account": cash_skipped_unknown_account,
            "skipped_inactive_account": cash_skipped_inactive_account,
            "skipped_other_account": cash_skipped_other_account,
            "conflicts": cash_conflicts,
        },
        "daily_nav_snapshots": {
            "supported": nav_supported,
            "inserted": nav_inserted,
            "duplicates": nav_duplicates,
            "skipped_unknown_account": nav_skipped_unknown_account,
            "skipped_inactive_account": nav_skipped_inactive_account,
            "skipped_other_account": nav_skipped_other_account,
            "conflicts": nav_conflicts,
        },
    }
    result: dict[str, Any] = {"record_counts": counts}
    if error_category is not None:
        result["error_category"] = error_category
    if feed_results is not None:
        result["feed_results"] = [_sanitize_feed_result(entry) for entry in feed_results]
    return result


def build_parent_summary(
    child_statuses: list[str],
    child_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate child (account-level) results into a parent (job-level) summary.

    Tolerates child_summaries that are full child summaries ({"record_counts": ...})
    or raw record_counts dicts (the result of empty_record_counts()).
    """
    account_counts = {
        "total": len(child_statuses),
        "succeeded": child_statuses.count("succeeded"),
        "partially_succeeded": child_statuses.count("partially_succeeded"),
        "failed": child_statuses.count("failed"),
    }

    if len(child_statuses) != len(child_summaries):
        raise ValueError(
            "child_statuses and child_summaries must have the same length"
            f" (got {len(child_statuses)} and {len(child_summaries)})"
        )

    aggregate = empty_record_counts()
    for child in child_summaries:
        # Accept either {"record_counts": {...}} or raw record_counts dict
        if "record_counts" in child:
            rc: dict[str, dict[str, int]] = child["record_counts"]
        else:
            rc = child  # type: ignore[assignment]
        for rt in RECORD_TYPES:
            if rt not in rc:
                continue
            record_type_counts = rc[rt]
            if not isinstance(record_type_counts, dict):
                continue
            for key in COUNT_KEYS:
                aggregate[rt][key] += record_type_counts.get(key, 0)

    return {
        "account_counts": account_counts,
        "record_counts": aggregate,
    }
