"""Adapter registry and broker-specific adapter implementations.

Adapters are narrow and broker-specific. They validate broker config,
fetch source payloads for one resolved account, and surface
broker-specific errors clearly. They do not decide target resolution,
mode behavior, or failure aggregation.
"""
from __future__ import annotations

import os

from portfolio_engine.database import AutomationAccountTarget
from portfolio_engine.automation.types import AutomationRunRequest, BrokerAdapter, BrokerPayload, IntegrationConfig


class IbkrFlexWebServiceAdapter:
    """Adapter for the IBKR Flex Web Service data source."""

    def preflight_validate_config(self, config: IntegrationConfig) -> None:
        """Raise RuntimeError if any required broker-specific env vars are absent or blank.

        DATABASE_URL is intentionally excluded because database availability
        is validated elsewhere in the orchestration pipeline.
        """
        missing = [
            key for key in config.required_env_keys
            if key != "DATABASE_URL" and not os.environ.get(key, "").strip()
        ]
        if missing:
            raise RuntimeError(
                "missing required environment variables: " + ", ".join(sorted(missing))
            )

    def fetch_payload(
        self,
        account: AutomationAccountTarget,
        request: AutomationRunRequest,
        config: IntegrationConfig,
    ) -> BrokerPayload:
        """Fetch raw Flex XML payload for the given account.

        Full IBKR Flex Web Service fetch internals are out of scope for this
        phase and require a follow-up design.
        """
        raise NotImplementedError(
            "IBKR Flex Web Service fetch internals require the follow-up IBKR fetch design"
        )


def get_adapter(adapter_key: str) -> BrokerAdapter:
    """Return the adapter instance for the given adapter key.

    Normalizes whitespace and case before lookup. Raises ValueError for
    unknown adapter keys.
    """
    normalized = adapter_key.strip().lower()
    if normalized == "ibkr_flex_ws":
        return IbkrFlexWebServiceAdapter()
    raise ValueError(f"unknown adapter: {adapter_key!r}")
