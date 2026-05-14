from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from portfolio_engine.database import AutomationAccountTarget


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


class BrokerAdapter(Protocol):
    def preflight_validate_config(self, config: IntegrationConfig) -> None: ...
    def fetch_payload(
        self,
        account: AutomationAccountTarget,
        request: AutomationRunRequest,
        config: IntegrationConfig,
    ) -> BrokerPayload: ...


@dataclass(frozen=True)
class AccountRunResult:
    status: str
    ingestion_run_id: str | None
    summary: dict[str, object]
    error_message: str | None = None
