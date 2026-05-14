"""Tests for the automation adapter registry and IBKR adapter boundary."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from portfolio_engine.automation.config import load_integration_config
from portfolio_engine.automation.types import BrokerAdapter


class TestGetAdapter(unittest.TestCase):
    def _get_adapter(self, key: str):
        from portfolio_engine.automation.adapters import get_adapter
        return get_adapter(key)

    def test_get_adapter_ibkr_flex_ws_returns_correct_class(self):
        adapter = self._get_adapter("ibkr_flex_ws")
        self.assertEqual(type(adapter).__name__, "IbkrFlexWebServiceAdapter")

    def test_get_adapter_implements_broker_adapter_protocol(self):
        adapter = self._get_adapter("ibkr_flex_ws")
        self.assertTrue(hasattr(adapter, "preflight_validate_config"))
        self.assertTrue(hasattr(adapter, "fetch_payload"))

    def test_get_adapter_normalizes_whitespace(self):
        adapter = self._get_adapter("  ibkr_flex_ws  ")
        self.assertEqual(type(adapter).__name__, "IbkrFlexWebServiceAdapter")

    def test_get_adapter_normalizes_case(self):
        adapter = self._get_adapter("IBKR_FLEX_WS")
        self.assertEqual(type(adapter).__name__, "IbkrFlexWebServiceAdapter")

    def test_get_adapter_normalizes_mixed_case_and_whitespace(self):
        adapter = self._get_adapter("  Ibkr_Flex_Ws  ")
        self.assertEqual(type(adapter).__name__, "IbkrFlexWebServiceAdapter")

    def test_get_adapter_unknown_key_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            self._get_adapter("unknown_broker")
        self.assertIn("unknown_broker", str(ctx.exception))

    def test_get_adapter_empty_key_raises_value_error(self):
        with self.assertRaises(ValueError):
            self._get_adapter("")

    def test_get_adapter_another_unknown_key_contextual_message(self):
        with self.assertRaises(ValueError) as ctx:
            self._get_adapter("some_future_broker")
        self.assertIn("some_future_broker", str(ctx.exception))


class TestIbkrFlexWebServiceAdapterPreflightValidation(unittest.TestCase):
    def _get_adapter(self):
        from portfolio_engine.automation.adapters import IbkrFlexWebServiceAdapter
        return IbkrFlexWebServiceAdapter()

    def test_preflight_raises_when_broker_env_vars_absent(self):
        adapter = self._get_adapter()
        config = load_integration_config("ibkr_flex_ws")
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                adapter.preflight_validate_config(config)
        self.assertIn("missing required environment variables", str(ctx.exception))

    def test_preflight_raises_listing_missing_broker_vars(self):
        adapter = self._get_adapter()
        config = load_integration_config("ibkr_flex_ws")
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                adapter.preflight_validate_config(config)
        msg = str(ctx.exception)
        self.assertIn("IBKR_FLEX_TOKEN", msg)
        self.assertIn("IBKR_FLEX_QUERY_ID", msg)

    def test_preflight_does_not_include_database_url_in_missing(self):
        adapter = self._get_adapter()
        config = load_integration_config("ibkr_flex_ws")
        env = {"IBKR_FLEX_TOKEN": "tok", "IBKR_FLEX_QUERY_ID": "qid"}
        with mock.patch.dict(os.environ, env, clear=True):
            # Should pass; DATABASE_URL absence is not a preflight concern
            adapter.preflight_validate_config(config)

    def test_preflight_passes_when_all_broker_vars_present(self):
        adapter = self._get_adapter()
        config = load_integration_config("ibkr_flex_ws")
        env = {
            "IBKR_FLEX_TOKEN": "sometoken",
            "IBKR_FLEX_QUERY_ID": "12345",
            "DATABASE_URL": "postgresql://localhost/db",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            adapter.preflight_validate_config(config)

    def test_preflight_treats_blank_env_var_as_missing(self):
        adapter = self._get_adapter()
        config = load_integration_config("ibkr_flex_ws")
        env = {"IBKR_FLEX_TOKEN": "   ", "IBKR_FLEX_QUERY_ID": "qid"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                adapter.preflight_validate_config(config)
        self.assertIn("IBKR_FLEX_TOKEN", str(ctx.exception))

    def test_preflight_treats_empty_string_as_missing(self):
        adapter = self._get_adapter()
        config = load_integration_config("ibkr_flex_ws")
        env = {"IBKR_FLEX_TOKEN": "", "IBKR_FLEX_QUERY_ID": "qid"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                adapter.preflight_validate_config(config)
        self.assertIn("IBKR_FLEX_TOKEN", str(ctx.exception))

    def test_preflight_missing_only_one_var_raises(self):
        adapter = self._get_adapter()
        config = load_integration_config("ibkr_flex_ws")
        env = {"IBKR_FLEX_TOKEN": "tok"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                adapter.preflight_validate_config(config)
        self.assertIn("IBKR_FLEX_QUERY_ID", str(ctx.exception))
        self.assertNotIn("IBKR_FLEX_TOKEN", str(ctx.exception))


class TestIbkrFlexWebServiceAdapterFetchPayload(unittest.TestCase):
    def _get_adapter(self):
        from portfolio_engine.automation.adapters import IbkrFlexWebServiceAdapter
        return IbkrFlexWebServiceAdapter()

    def test_fetch_payload_raises_not_implemented_error(self):
        from portfolio_engine.automation.types import AutomationRunRequest, IntegrationConfig
        from portfolio_engine.database import AutomationAccountTarget
        from datetime import date

        adapter = self._get_adapter()
        account = AutomationAccountTarget(
            account_id="1",
            account_external_id="U1234567",
            brokerage_code="IBKR",
            base_currency="USD",
            display_name="Test Account",
        )
        request = AutomationRunRequest(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
        )
        config = load_integration_config("ibkr_flex_ws")
        with self.assertRaises(NotImplementedError) as ctx:
            adapter.fetch_payload(account, request, config)
        self.assertIn("follow-up", str(ctx.exception))


class AutomationAdapterTests(unittest.TestCase):
    """Named class required by the spec verification command."""

    def test_get_ibkr_adapter(self):
        from portfolio_engine.automation.adapters import get_adapter
        adapter = get_adapter("ibkr_flex_ws")
        self.assertEqual(type(adapter).__name__, "IbkrFlexWebServiceAdapter")

    def test_ibkr_adapter_preflight_requires_env_keys(self):
        from portfolio_engine.automation.adapters import get_adapter
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                get_adapter("ibkr_flex_ws").preflight_validate_config(
                    load_integration_config("ibkr_flex_ws")
                )
        self.assertIn("missing required environment variables", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
