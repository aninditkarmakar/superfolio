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
    cash_flows_supported: int = 0,
    cash_flows_inserted: int = 0,
    cash_flows_duplicates: int = 0,
    cash_flows_skipped_unknown_account: int = 0,
    cash_flows_skipped_inactive_account: int = 0,
    cash_flows_skipped_other_account: int = 0,
    cash_flows_conflicts: int = 0,
    daily_nav_snapshots_supported: int = 0,
    daily_nav_snapshots_inserted: int = 0,
    daily_nav_snapshots_duplicates: int = 0,
    daily_nav_snapshots_skipped_unknown_account: int = 0,
    daily_nav_snapshots_skipped_inactive_account: int = 0,
    daily_nav_snapshots_skipped_other_account: int = 0,
    daily_nav_snapshots_conflicts: int = 0,
    error_category: str | None = None,
) -> dict[str, Any]:
    """Build a sanitized child (account-level) summary dict with record_counts only."""
    counts: dict[str, dict[str, int]] = {
        "cash_flows": {
            "supported": cash_flows_supported,
            "inserted": cash_flows_inserted,
            "duplicates": cash_flows_duplicates,
            "skipped_unknown_account": cash_flows_skipped_unknown_account,
            "skipped_inactive_account": cash_flows_skipped_inactive_account,
            "skipped_other_account": cash_flows_skipped_other_account,
            "conflicts": cash_flows_conflicts,
        },
        "daily_nav_snapshots": {
            "supported": daily_nav_snapshots_supported,
            "inserted": daily_nav_snapshots_inserted,
            "duplicates": daily_nav_snapshots_duplicates,
            "skipped_unknown_account": daily_nav_snapshots_skipped_unknown_account,
            "skipped_inactive_account": daily_nav_snapshots_skipped_inactive_account,
            "skipped_other_account": daily_nav_snapshots_skipped_other_account,
            "conflicts": daily_nav_snapshots_conflicts,
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
