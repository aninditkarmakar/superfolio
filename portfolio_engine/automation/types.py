from __future__ import annotations

import types as _types
from dataclasses import dataclass
from datetime import date
from typing import Mapping, Protocol

from portfolio_engine.database import AutomationAccountTarget
from portfolio_engine.automation.credentials import SecretValue


VALID_TARGET_TYPES = frozenset({"portfolio", "accounts"})
VALID_MODES = frozenset({"dry-run", "load"})
VALID_STATUSES = frozenset({"pending", "running", "succeeded", "partially_succeeded", "failed"})


@dataclass(frozen=True)
class IntegrationConfig:
    integration_key: str
    brokerage_code: str
    source_type: str
    adapter_key: str
    supported_modes: tuple[str, ...]
    required_env_keys: tuple[str, ...]
    stale_running_timeout_minutes: int


@dataclass(frozen=True)
class AutomationRunRequest:
    target_type: str
    integration_key: str
    mode: str
    requested_start_date: date
    requested_end_date: date
    portfolio_name: str | None = None
    account_external_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class BrokerPayload:
    xml_text: str
    source_name: str | None = None


@dataclass(frozen=True)
class IntegrationConnectionContext:
    connection_id: str
    integration_key: str
    brokerage_code: str
    name: str
    credentials: Mapping[str, SecretValue]

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "credentials", _types.MappingProxyType(dict(self.credentials))
        )


@dataclass(frozen=True)
class IntegrationFeedContext:
    feed_id: str
    feed_key: str
    display_name: str | None
    secrets: Mapping[str, SecretValue]

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "secrets", _types.MappingProxyType(dict(self.secrets))
        )


class BrokerAdapter(Protocol):
    def preflight_validate_config(self, config: IntegrationConfig) -> None: ...
    def fetch_payload(
        self,
        account: AutomationAccountTarget,
        request: AutomationRunRequest,
        config: IntegrationConfig,
    ) -> BrokerPayload: ...
    def preflight_connection(
        self,
        connection: IntegrationConnectionContext,
        feeds: tuple[IntegrationFeedContext, ...],
    ) -> None:
        """Validate decrypted connection and feed credential shape before fetch."""

    def fetch_feed_payload(
        self,
        connection: IntegrationConnectionContext,
        feed: IntegrationFeedContext,
        request: AutomationRunRequest,
    ) -> BrokerPayload: ...


@dataclass(frozen=True)
class AccountRunResult:
    status: str
    ingestion_run_id: str | None
    summary: dict[str, object]
    error_message: str | None = None
