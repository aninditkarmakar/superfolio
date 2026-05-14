from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
