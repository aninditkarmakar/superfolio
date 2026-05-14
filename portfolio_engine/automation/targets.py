"""Target parsing and validation for automation trigger inputs."""
from __future__ import annotations

from portfolio_engine.automation.types import VALID_TARGET_TYPES


class AutomationValidationError(ValueError):
    """Raised when automation trigger inputs fail cross-field validation."""


def parse_account_external_ids(value: str | None) -> tuple[str, ...]:
    """Parse a comma-separated string of account external IDs.

    - None returns an empty tuple.
    - Tokens are stripped of whitespace; empty tokens are ignored.
    - Duplicate IDs are removed, preserving first-seen order.
    """
    if not value:
        return ()
    seen: dict[str, None] = {}
    for token in value.split(","):
        stripped = token.strip()
        if stripped:
            seen.setdefault(stripped, None)
    return tuple(seen)


def validate_target_inputs(
    *,
    target_type: str,
    portfolio_name: str | None,
    account_external_ids: tuple[str, ...],
) -> None:
    """Validate cross-field consistency of target inputs.

    Normalizes target_type by stripping whitespace and lowercasing.
    Treats blank portfolio_name as absent.
    Raises AutomationValidationError on any cross-field violation.
    """
    normalized = target_type.strip().lower()
    has_portfolio_name = bool(portfolio_name and portfolio_name.strip())
    has_account_ids = bool(account_external_ids)

    if normalized == "portfolio":
        if not has_portfolio_name and has_account_ids:
            raise AutomationValidationError(
                "target_type=portfolio requires portfolio_name and rejects account_external_ids"
            )
        if not has_portfolio_name:
            raise AutomationValidationError(
                "target_type=portfolio requires portfolio_name"
            )
        if has_account_ids:
            raise AutomationValidationError(
                "target_type=portfolio rejects account_external_ids"
            )
    elif normalized == "accounts":
        if not has_account_ids and has_portfolio_name:
            raise AutomationValidationError(
                "target_type=accounts requires account_external_ids and rejects portfolio_name"
            )
        if not has_account_ids:
            raise AutomationValidationError(
                "target_type=accounts requires account_external_ids"
            )
        if has_portfolio_name:
            raise AutomationValidationError(
                "target_type=accounts rejects portfolio_name"
            )
    else:
        valid_str = " or ".join(sorted(VALID_TARGET_TYPES, reverse=True))
        raise AutomationValidationError(f"target_type must be {valid_str}")
