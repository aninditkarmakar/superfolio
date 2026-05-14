from __future__ import annotations

from typing import Any

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
            for key in COUNT_KEYS:
                aggregate[rt][key] += rc[rt].get(key, 0)

    return {
        "account_counts": account_counts,
        "record_counts": aggregate,
    }
