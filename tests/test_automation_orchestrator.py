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


# ---------------------------------------------------------------------------
# Orchestrator tests
# ---------------------------------------------------------------------------

from datetime import date  # noqa: E402 — after stdlib imports for clarity


class FakeAutomationDatabase:
    """In-memory fake implementing the database interface required by run_automation."""

    def __init__(self, *, raise_on_create: Exception | None = None):
        self.created_jobs: list = []
        self.finalized_jobs: list = []
        self.fail_stale_calls: list = []
        self.portfolio_accounts: list = []
        self.account_targets: list = []
        self._event_log: list[str] = []
        self._raise_on_create = raise_on_create

    def fail_stale_automation_runs(self, *, stale_before, error_message) -> int:
        self._event_log.append("fail_stale")
        self.fail_stale_calls.append({"stale_before": stale_before, "error_message": error_message})
        return 0

    def create_automation_job(self, request) -> str:
        if self._raise_on_create is not None:
            raise self._raise_on_create
        self._event_log.append("create_job")
        self.created_jobs.append(request)
        return "job-uuid"

    def finalize_automation_job(self, request) -> str:
        self._event_log.append("finalize_job")
        self.finalized_jobs.append(request)
        return request.automation_job_id

    def resolve_automation_portfolio_accounts(self, *, portfolio_name, brokerage_code):
        return list(self.portfolio_accounts)

    def resolve_automation_account_targets(self, *, brokerage_code, account_external_ids):
        return list(self.account_targets)


class AutomationOrchestratorValidationTests(unittest.TestCase):
    """Tests for request validation and preflight failure persistence."""

    def _run(self, request, db=None):
        from portfolio_engine.automation.orchestrator import run_automation
        if db is None:
            db = FakeAutomationDatabase()
        return run_automation(request, database=db)

    def _make_request(self, **kwargs):
        from portfolio_engine.automation.types import AutomationRunRequest
        defaults = dict(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
            account_external_ids=("U100",),
        )
        defaults.update(kwargs)
        return AutomationRunRequest(**defaults)

    def test_import_run_automation(self):
        from portfolio_engine.automation.orchestrator import run_automation  # noqa: F401
        self.assertTrue(callable(run_automation))

    def test_preflight_failure_persists_failed_parent_job(self):
        """Empty account_external_ids for target_type=accounts must fail validation,
        create one parent job, and finalize it as failed."""
        request = self._make_request(account_external_ids=())
        db = FakeAutomationDatabase()
        result = self._run(request, db)

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(db.created_jobs), 1)
        self.assertEqual(len(db.finalized_jobs), 1)
        self.assertEqual(db.finalized_jobs[0].status, "failed")
        self.assertEqual(db.finalized_jobs[0].automation_job_id, "job-uuid")

    def test_preflight_failure_result_has_job_id(self):
        request = self._make_request(account_external_ids=())
        db = FakeAutomationDatabase()
        result = self._run(request, db)

        self.assertEqual(result.automation_job_id, "job-uuid")

    def test_stale_cleanup_runs_before_job_creation(self):
        """fail_stale_automation_runs must be called once before create_automation_job."""
        request = self._make_request(account_external_ids=("U100",))
        db = FakeAutomationDatabase()
        self._run(request, db)

        self.assertEqual(len(db.fail_stale_calls), 1)
        self.assertEqual(len(db.created_jobs), 1)
        # Verify ordering via event log
        fail_idx = db._event_log.index("fail_stale")
        create_idx = db._event_log.index("create_job")
        self.assertLess(fail_idx, create_idx)

    def test_invalid_mode_persists_failed_parent(self):
        request = self._make_request(mode="invalid-mode")
        db = FakeAutomationDatabase()
        result = self._run(request, db)

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(db.created_jobs), 1)
        self.assertEqual(len(db.finalized_jobs), 1)
        self.assertEqual(db.finalized_jobs[0].status, "failed")

    def test_invalid_date_range_persists_failed_parent(self):
        request = self._make_request(
            requested_start_date=date(2024, 2, 1),
            requested_end_date=date(2024, 1, 1),
        )
        db = FakeAutomationDatabase()
        result = self._run(request, db)

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(db.created_jobs), 1)
        self.assertEqual(len(db.finalized_jobs), 1)
        self.assertEqual(db.finalized_jobs[0].status, "failed")

    def test_invalid_target_type_persists_failed_parent(self):
        request = self._make_request(target_type="invalid-type")
        db = FakeAutomationDatabase()
        result = self._run(request, db)

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(db.created_jobs), 1)
        self.assertEqual(len(db.finalized_jobs), 1)

    def test_preflight_error_message_is_sanitized(self):
        """Error messages on finalized jobs must be sanitized (no raw secrets)."""
        request = self._make_request(account_external_ids=())
        db = FakeAutomationDatabase()
        result = self._run(request, db)

        error_msg = db.finalized_jobs[0].error_message
        # Should be a string (not None) but must not contain raw connection strings
        self.assertIsNotNone(error_msg)
        self.assertNotIn("postgresql://", error_msg or "")

    def test_db_create_exception_propagates_no_finalize(self):
        """If create_automation_job raises, the exception propagates and finalize is not called."""
        from portfolio_engine.automation.orchestrator import run_automation
        from portfolio_engine.automation.types import AutomationRunRequest
        request = AutomationRunRequest(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
            account_external_ids=("U100",),
        )
        db = FakeAutomationDatabase(raise_on_create=RuntimeError("db unavailable"))
        with self.assertRaises(RuntimeError):
            run_automation(request, database=db)
        self.assertEqual(len(db.finalized_jobs), 0)

    def test_stale_cleanup_uses_config_timeout(self):
        """stale_before must be based on the integration config stale_running_timeout_minutes."""
        from datetime import timezone, timedelta
        request = self._make_request(account_external_ids=("U100",))
        db = FakeAutomationDatabase()
        config = load_integration_config("ibkr_flex_ws")

        before_call = __import__("datetime").datetime.now(timezone.utc)
        self._run(request, db)
        after_call = __import__("datetime").datetime.now(timezone.utc)

        stale_before = db.fail_stale_calls[0]["stale_before"]
        expected_delta = timedelta(minutes=config.stale_running_timeout_minutes)
        self.assertGreaterEqual(stale_before, before_call - expected_delta - timedelta(seconds=5))
        self.assertLessEqual(stale_before, after_call - expected_delta + timedelta(seconds=5))

    def test_valid_request_creates_and_returns_job_id(self):
        """A valid request (with accounts) must create one parent job and return its id."""
        request = self._make_request(account_external_ids=("U100",))
        db = FakeAutomationDatabase()
        result = self._run(request, db)

        self.assertEqual(result.automation_job_id, "job-uuid")
        self.assertEqual(len(db.created_jobs), 1)

    def test_valid_request_finalizes_parent_job_as_failed_placeholder(self):
        """Valid request (no validation error) must finalize parent job as failed (placeholder path).

        The placeholder path must persist the job so no running-only state remains in the DB.
        """
        request = self._make_request(account_external_ids=("U100",))
        db = FakeAutomationDatabase()
        result = self._run(request, db)

        self.assertEqual(len(db.finalized_jobs), 1, "placeholder path must finalize the parent job")
        finalized = db.finalized_jobs[0]
        self.assertEqual(finalized.status, "failed")
        self.assertEqual(finalized.automation_job_id, "job-uuid")
        self.assertEqual(finalized.error_message, "target execution not implemented yet")
        self.assertIsInstance(finalized.summary, dict)

    def test_validation_runtime_error_propagates(self):
        """RuntimeError raised inside _validate_request must propagate, not be swallowed."""
        from portfolio_engine.automation import orchestrator
        request = self._make_request(account_external_ids=("U100",))
        db = FakeAutomationDatabase()

        with mock.patch.object(orchestrator, "_validate_request", side_effect=RuntimeError("internal")):
            with self.assertRaises(RuntimeError):
                self._run(request, db)

    def test_finalized_job_has_sanitized_summary(self):
        """Finalized failed jobs must include a privacy-safe summary dict."""
        request = self._make_request(account_external_ids=())
        db = FakeAutomationDatabase()
        self._run(request, db)

        summary = db.finalized_jobs[0].summary
        self.assertIsInstance(summary, dict)
        self.assertIn("account_counts", summary)


if __name__ == "__main__":
    unittest.main()
