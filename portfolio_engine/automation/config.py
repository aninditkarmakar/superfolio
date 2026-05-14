from __future__ import annotations

from pathlib import Path

from portfolio_engine.automation.types import IntegrationConfig, VALID_MODES


CONFIG_PATH = Path(__file__).with_name("integrations.yaml")


def load_integration_config(integration_key: str, path: Path = CONFIG_PATH) -> IntegrationConfig:
    key = integration_key.strip().lower()
    data = _load_simple_yaml(path)
    integrations = data.get("integrations", {})
    if not isinstance(integrations, dict):
        raise ValueError("integration config field integrations must be a mapping")
    raw = integrations.get(key)
    if raw is None:
        raise ValueError(f"unknown integration: {integration_key}")
    if not isinstance(raw, dict):
        raise ValueError(f"integration '{key}' must be a mapping")

    _require_fields(
        key,
        raw,
        (
            "brokerage_code",
            "source_type",
            "adapter_key",
            "supported_modes",
            "required_env_keys",
            "stale_running_timeout_minutes",
        ),
    )
    supported_modes = _string_tuple_field(key, raw, "supported_modes")
    invalid_modes = sorted(set(supported_modes) - VALID_MODES)
    if invalid_modes:
        raise ValueError(f"integration '{key}' has unsupported modes: {', '.join(invalid_modes)}")
    required_env_keys = _string_tuple_field(key, raw, "required_env_keys")
    stale_running_timeout_minutes = _int_field(key, raw, "stale_running_timeout_minutes")

    return IntegrationConfig(
        integration_key=key,
        brokerage_code=_string_field(key, raw, "brokerage_code"),
        source_type=_string_field(key, raw, "source_type"),
        adapter_key=_string_field(key, raw, "adapter_key"),
        supported_modes=supported_modes,
        required_env_keys=required_env_keys,
        stale_running_timeout_minutes=stale_running_timeout_minutes,
    )


def _require_fields(key: str, raw: dict[object, object], required_fields: tuple[str, ...]) -> None:
    for field in required_fields:
        if field not in raw:
            raise ValueError(f"integration '{key}' missing required field: {field}")


def _string_tuple_field(key: str, raw: dict[object, object], field: str) -> tuple[str, ...]:
    value = raw[field]
    if not isinstance(value, list):
        raise ValueError(f"integration '{key}' field {field} must be a list")
    if any(item is None for item in value):
        raise ValueError(f"integration '{key}' field {field} contains a null item")
    return tuple(str(item) for item in value)


def _string_field(key: str, raw: dict[object, object], field: str) -> str:
    value = raw[field]
    if value is None:
        raise ValueError(f"integration '{key}' field {field} must not be null")
    return str(value)


def _int_field(key: str, raw: dict[object, object], field: str) -> int:
    value = raw[field]
    if value is None:
        raise ValueError(f"integration '{key}' field {field} must not be null")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"integration '{key}' field {field} must be an integer") from error


def _load_simple_yaml(path: Path) -> dict[str, object]:
    try:
        import yaml
    except ImportError as error:
        raise RuntimeError("PyYAML is required to read automation integration config") from error

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"invalid integration config file: {path}")
    return loaded
