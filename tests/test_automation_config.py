from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from portfolio_engine.automation.config import load_integration_config


class AutomationConfigTests(unittest.TestCase):
    def test_load_ibkr_flex_ws_config(self) -> None:
        config = load_integration_config("ibkr_flex_ws")

        self.assertEqual(config.integration_key, "ibkr_flex_ws")
        self.assertEqual(config.brokerage_code, "IBKR")
        self.assertEqual(config.source_type, "FLEX_WEB_SERVICE")
        self.assertIn("dry-run", config.supported_modes)
        self.assertIn("load", config.supported_modes)
        self.assertGreater(config.stale_running_timeout_minutes, 0)

    def test_unknown_integration_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown integration"):
            load_integration_config("missing")

    def test_integration_key_is_normalized(self) -> None:
        config = load_integration_config("  IBKR_FLEX_WS  ")
        self.assertEqual(config.integration_key, "ibkr_flex_ws")

    def test_supported_modes_is_tuple(self) -> None:
        config = load_integration_config("ibkr_flex_ws")
        self.assertIsInstance(config.supported_modes, tuple)

    def test_required_env_keys_is_tuple(self) -> None:
        config = load_integration_config("ibkr_flex_ws")
        self.assertIsInstance(config.required_env_keys, tuple)
        self.assertIn("DATABASE_URL", config.required_env_keys)

    def test_missing_required_field_fails_with_context(self) -> None:
        path = self._write_config(
            """
integrations:
  test:
    brokerage_code: IBKR
    source_type: FLEX_WEB_SERVICE
    adapter_key: ibkr_flex_ws
    supported_modes:
      - dry-run
    stale_running_timeout_minutes: 120
"""
        )

        with self.assertRaisesRegex(ValueError, "integration 'test' missing required field: required_env_keys"):
            load_integration_config("test", path=path)

    def test_null_list_field_fails_with_context(self) -> None:
        path = self._write_config(
            """
integrations:
  test:
    brokerage_code: IBKR
    source_type: FLEX_WEB_SERVICE
    adapter_key: ibkr_flex_ws
    supported_modes:
    required_env_keys:
      - DATABASE_URL
    stale_running_timeout_minutes: 120
"""
        )

        with self.assertRaisesRegex(ValueError, "integration 'test' field supported_modes must be a list"):
            load_integration_config("test", path=path)

    def test_invalid_supported_mode_fails(self) -> None:
        path = self._write_config(
            """
integrations:
  test:
    brokerage_code: IBKR
    source_type: FLEX_WEB_SERVICE
    adapter_key: ibkr_flex_ws
    supported_modes:
      - dry-run
      - bogus
    required_env_keys:
      - DATABASE_URL
    stale_running_timeout_minutes: 120
"""
        )

        with self.assertRaisesRegex(ValueError, "integration 'test' has unsupported modes: bogus"):
            load_integration_config("test", path=path)

    def test_null_scalar_field_fails_with_context(self) -> None:
        path = self._write_config(
            """
integrations:
  test:
    brokerage_code:
    source_type: FLEX_WEB_SERVICE
    adapter_key: ibkr_flex_ws
    supported_modes:
      - dry-run
    required_env_keys:
      - DATABASE_URL
    stale_running_timeout_minutes: 120
"""
        )

        with self.assertRaisesRegex(ValueError, "integration 'test' field brokerage_code must not be null"):
            load_integration_config("test", path=path)

    def test_null_timeout_field_fails_with_context(self) -> None:
        path = self._write_config(
            """
integrations:
  test:
    brokerage_code: IBKR
    source_type: FLEX_WEB_SERVICE
    adapter_key: ibkr_flex_ws
    supported_modes:
      - dry-run
    required_env_keys:
      - DATABASE_URL
    stale_running_timeout_minutes:
"""
        )

        with self.assertRaisesRegex(
            ValueError, "integration 'test' field stale_running_timeout_minutes must not be null"
        ):
            load_integration_config("test", path=path)

    def test_null_integrations_block_fails_with_context(self) -> None:
        path = self._write_config(
            """
integrations:
"""
        )

        with self.assertRaisesRegex(ValueError, "integration config field integrations must be a mapping"):
            load_integration_config("test", path=path)

    def test_non_integer_timeout_fails_with_context(self) -> None:
        path = self._write_config(
            """
integrations:
  test:
    brokerage_code: IBKR
    source_type: FLEX_WEB_SERVICE
    adapter_key: ibkr_flex_ws
    supported_modes:
      - dry-run
    required_env_keys:
      - DATABASE_URL
    stale_running_timeout_minutes: soon
"""
        )

        with self.assertRaisesRegex(
            ValueError, "integration 'test' field stale_running_timeout_minutes must be an integer"
        ):
            load_integration_config("test", path=path)

    def test_boolean_timeout_fails_with_context(self) -> None:
        path = self._write_config(
            """
integrations:
  test:
    brokerage_code: IBKR
    source_type: FLEX_WEB_SERVICE
    adapter_key: ibkr_flex_ws
    supported_modes:
      - dry-run
    required_env_keys:
      - DATABASE_URL
    stale_running_timeout_minutes: true
"""
        )

        with self.assertRaisesRegex(
            ValueError, "integration 'test' field stale_running_timeout_minutes must be an integer"
        ):
            load_integration_config("test", path=path)

    def test_float_timeout_fails_with_context(self) -> None:
        path = self._write_config(
            """
integrations:
  test:
    brokerage_code: IBKR
    source_type: FLEX_WEB_SERVICE
    adapter_key: ibkr_flex_ws
    supported_modes:
      - dry-run
    required_env_keys:
      - DATABASE_URL
    stale_running_timeout_minutes: 0.5
"""
        )

        with self.assertRaisesRegex(
            ValueError, "integration 'test' field stale_running_timeout_minutes must be an integer"
        ):
            load_integration_config("test", path=path)

    def test_null_list_item_fails_with_context(self) -> None:
        path = self._write_config(
            """
integrations:
  test:
    brokerage_code: IBKR
    source_type: FLEX_WEB_SERVICE
    adapter_key: ibkr_flex_ws
    supported_modes:
      - dry-run
    required_env_keys:
      - DATABASE_URL
      -
    stale_running_timeout_minutes: 120
"""
        )

        with self.assertRaisesRegex(ValueError, "integration 'test' field required_env_keys contains a null item"):
            load_integration_config("test", path=path)

    def test_ibkr_config_no_longer_requires_per_login_secrets(self) -> None:
        config = load_integration_config("ibkr_flex_ws")

        self.assertIn("SUPERFOLIO_CREDENTIAL_MASTER_KEY", config.required_env_keys)
        self.assertNotIn("IBKR_FLEX_TOKEN", config.required_env_keys)
        self.assertNotIn("IBKR_FLEX_QUERY_ID", config.required_env_keys)

    def _write_config(self, contents: str) -> Path:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "integrations.yaml"
        path.write_text(contents, encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
