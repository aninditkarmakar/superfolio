from __future__ import annotations

from pathlib import Path

from portfolio_engine.automation.types import IntegrationConfig


CONFIG_PATH = Path(__file__).with_name("integrations.yaml")


def load_integration_config(integration_key: str, path: Path = CONFIG_PATH) -> IntegrationConfig:
    key = integration_key.strip().lower()
    data = _load_simple_yaml(path)
    integrations = data.get("integrations", {})
    raw = integrations.get(key)
    if raw is None:
        raise ValueError(f"unknown integration: {integration_key}")

    return IntegrationConfig(
        integration_key=key,
        brokerage_code=str(raw["brokerage_code"]),
        source_type=str(raw["source_type"]),
        adapter_key=str(raw["adapter_key"]),
        supported_modes=tuple(str(mode) for mode in raw["supported_modes"]),
        required_env_keys=tuple(str(name) for name in raw["required_env_keys"]),
        stale_running_timeout_minutes=int(raw["stale_running_timeout_minutes"]),
    )


def _load_simple_yaml(path: Path) -> dict[str, object]:
    try:
        import yaml
    except ImportError as error:
        raise RuntimeError("PyYAML is required to read automation integration config") from error

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"invalid integration config file: {path}")
    return loaded
