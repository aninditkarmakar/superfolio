"""Adapter registry and broker-specific adapter implementations.

Adapters are narrow and broker-specific. They validate broker config,
fetch source payloads for one resolved account, and surface
broker-specific errors clearly. They do not decide target resolution,
mode behavior, or failure aggregation.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Protocol

from portfolio_engine.database import AutomationAccountTarget
from portfolio_engine.automation.ibkr_flex_client import IbkrFlexWebServiceClient
from portfolio_engine.automation.types import (
    AutomationRunRequest,
    BrokerAdapter,
    BrokerPayload,
    IntegrationConfig,
    IntegrationConnectionContext,
    IntegrationFeedContext,
)


class IbkrFlexClient(Protocol):
    def fetch_report(
        self,
        *,
        token: str,
        query_id: str,
        connection_id: str = "connection",
        feed_key: str = "feed",
    ) -> str: ...


class IbkrFlexWebServiceAdapter:
    """Adapter for the IBKR Flex Web Service data source."""

    def __init__(
        self,
        *,
        client: IbkrFlexClient | None = None,
        client_factory: Callable[..., IbkrFlexClient] = IbkrFlexWebServiceClient,
    ) -> None:
        self._client = client
        self._client_factory = client_factory

    def _client_for_request(self, request: AutomationRunRequest) -> IbkrFlexClient:
        if self._client is not None:
            return self._client
        debug_dir = Path(request.debug_raw_xml_dir) if request.debug_raw_xml_dir else None
        return self._client_factory(debug_raw_xml_dir=debug_dir)

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

    def preflight_connection(
        self,
        connection: IntegrationConnectionContext,
        feeds: tuple[IntegrationFeedContext, ...],
    ) -> None:
        """Validate connection credentials and each feed's secrets.

        Raises RuntimeError containing 'missing_connection_credential' if flex_token
        is absent from connection.credentials. Raises RuntimeError containing
        'missing_feed_secret' if query_id is absent from any feed's secrets.
        """
        if "flex_token" not in connection.credentials:
            raise RuntimeError("missing_connection_credential: flex_token")
        for feed in feeds:
            if "query_id" not in feed.secrets:
                raise RuntimeError(f"missing_feed_secret: {feed.feed_key}: query_id")

    def fetch_feed_payload(
        self,
        connection: IntegrationConnectionContext,
        feed: IntegrationFeedContext,
        request: AutomationRunRequest,
    ) -> BrokerPayload:
        """Fetch one Flex XML report for one connection feed."""
        token = connection.credentials["flex_token"].reveal()
        query_id = feed.secrets["query_id"].reveal()
        client = self._client_for_request(request)
        xml_text = client.fetch_report(
            token=token,
            query_id=query_id,
            connection_id=connection.connection_id,
            feed_key=feed.feed_key,
        )
        return BrokerPayload(
            xml_text=xml_text,
            source_name=f"ibkr_flex_ws:{connection.connection_id}:{feed.feed_key}",
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

