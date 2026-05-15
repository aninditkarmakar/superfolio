from __future__ import annotations


ALLOWED_BROKER_FETCH_CATEGORIES = frozenset(
    {
        "ibkr_auth_failed",
        "ibkr_invalid_query",
        "ibkr_pacing_limit",
        "ibkr_report_not_ready",
        "ibkr_fetch_failed",
    }
)


class BrokerFetchError(RuntimeError):
    """Broker fetch failure with a privacy-safe category for automation summaries."""

    def __init__(self, category: str, message: str | None = None) -> None:
        self.category = category
        super().__init__(message or category)


def safe_fetch_error_category(exc: BaseException) -> str:
    """Return an allowlisted broker fetch category or the generic feed failure category."""
    if isinstance(exc, BrokerFetchError) and exc.category in ALLOWED_BROKER_FETCH_CATEGORIES:
        return exc.category
    return "feed_fetch_failed"
