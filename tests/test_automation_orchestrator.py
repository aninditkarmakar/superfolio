"""Tests for the automation adapter registry and IBKR adapter boundary."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from portfolio_engine.automation.config import load_integration_config
from portfolio_engine.automation.types import BrokerAdapter
from portfolio_engine.database import BulkIngestionSummary


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
        self.added_accounts: list = []
        self.portfolio_resolve_calls: list = []
        self.account_resolve_calls: list = []
        self.running_children: list[str] = []
        self.finalized_children: list = []
        self._event_log: list[str] = []
        self._raise_on_create = raise_on_create
        self._child_counter = 0
        # Ingestion tracking (Task 13)
        self.started_ingestion_runs: list = []
        self.completed_ingestion_runs: list = []
        self.cash_bulk_calls: list = []
        self.nav_bulk_calls: list = []

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
        self.portfolio_resolve_calls.append({"portfolio_name": portfolio_name, "brokerage_code": brokerage_code})
        return list(self.portfolio_accounts)

    def resolve_automation_account_targets(self, *, brokerage_code, account_external_ids):
        self.account_resolve_calls.append({"brokerage_code": brokerage_code, "account_external_ids": account_external_ids})
        return list(self.account_targets)

    def add_automation_job_account(self, request) -> str:
        self._child_counter += 1
        child_id = f"child-{self._child_counter}"
        self.added_accounts.append((child_id, request))
        return child_id

    def mark_automation_job_account_running(self, automation_job_account_id: str) -> str:
        self._event_log.append(f"mark_running:{automation_job_account_id}")
        self.running_children.append(automation_job_account_id)
        return automation_job_account_id

    def finalize_automation_job_account(self, request) -> str:
        self._event_log.append(f"finalize_child:{request.automation_job_account_id}")
        self.finalized_children.append(request)
        return request.automation_job_account_id

    def start_ingestion_run(self, request) -> str:
        self.started_ingestion_runs.append(request)
        return "ingestion-run-uuid"

    def complete_ingestion_run(self, *, ingestion_run_id: str, status: str, error_message: str | None) -> None:
        self.completed_ingestion_runs.append((ingestion_run_id, status, error_message))

    def bulk_ingest_cash_flows(self, ingestion_run_id: str, records: list) -> BulkIngestionSummary:
        self.cash_bulk_calls.append({"ingestion_run_id": ingestion_run_id, "records": records})
        return BulkIngestionSummary(
            inserted_count=0,
            duplicate_count=0,
            skipped_unknown_account_count=0,
            skipped_inactive_account_count=0,
            conflict_count=0,
            skipped_accounts=[],
            record_results=[],
        )

    def bulk_ingest_daily_nav_snapshots(self, ingestion_run_id: str, records: list) -> BulkIngestionSummary:
        self.nav_bulk_calls.append({"ingestion_run_id": ingestion_run_id, "records": records})
        return BulkIngestionSummary(
            inserted_count=0,
            duplicate_count=0,
            skipped_unknown_account_count=0,
            skipped_inactive_account_count=0,
            conflict_count=0,
            skipped_accounts=[],
            record_results=[],
        )


class FakeAdapter:
    """Minimal in-memory fake broker adapter for testing dry-run orchestration."""

    def preflight_validate_config(self, config) -> None:
        return None

    def fetch_payload(self, account, request, config):
        from portfolio_engine.automation.types import BrokerPayload
        return BrokerPayload(
            xml_text="<FlexQueryResponse></FlexQueryResponse>",
            source_name="fake.xml",
        )


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
        """A valid dry-run request (with resolved accounts) creates one parent job, adds child rows, returns its id."""
        from portfolio_engine.automation.orchestrator import run_automation
        from portfolio_engine.database import AutomationAccountTarget
        request = self._make_request(account_external_ids=("U100",))
        db = FakeAutomationDatabase()
        db.account_targets = [
            AutomationAccountTarget(
                account_id="account-uuid",
                brokerage_code="IBKR",
                account_external_id="U100",
                base_currency="USD",
                display_name="Main",
            )
        ]
        result = run_automation(request, database=db, adapter=FakeAdapter())

        self.assertEqual(result.automation_job_id, "job-uuid")
        self.assertEqual(len(db.created_jobs), 1)
        self.assertEqual(len(db.added_accounts), 1, "child row must be created for the resolved account")
        self.assertIsNone(result.error_message)

    def test_valid_request_finalizes_parent_job_as_succeeded(self):
        """Valid dry-run request (with resolved accounts) must finalize parent job as succeeded.

        After Task 12 the dry-run execution loop runs and parent is finalized based on child statuses.
        """
        from portfolio_engine.automation.orchestrator import run_automation
        from portfolio_engine.database import AutomationAccountTarget
        request = self._make_request(account_external_ids=("U100",))
        db = FakeAutomationDatabase()
        db.account_targets = [
            AutomationAccountTarget(
                account_id="account-uuid",
                brokerage_code="IBKR",
                account_external_id="U100",
                base_currency="USD",
                display_name="Main",
            )
        ]
        result = run_automation(request, database=db, adapter=FakeAdapter())

        self.assertEqual(len(db.finalized_jobs), 1, "parent job must be finalized")
        finalized = db.finalized_jobs[0]
        self.assertEqual(finalized.status, "succeeded")
        self.assertEqual(finalized.automation_job_id, "job-uuid")
        self.assertIsNone(finalized.error_message)
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


class AutomationOrchestratorTargetResolutionTests(unittest.TestCase):
    """Tests for Task 11: target resolution and child snapshot creation."""

    def _run(self, request, db):
        from portfolio_engine.automation.orchestrator import run_automation
        return run_automation(request, database=db)

    def _make_accounts_request(self, **kwargs):
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

    def _make_portfolio_request(self, **kwargs):
        from portfolio_engine.automation.types import AutomationRunRequest
        defaults = dict(
            target_type="portfolio",
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
            portfolio_name="MyPortfolio",
        )
        defaults.update(kwargs)
        return AutomationRunRequest(**defaults)

    def _make_account_target(self, *, account_id="account-uuid", external_id="U100"):
        from portfolio_engine.database import AutomationAccountTarget
        return AutomationAccountTarget(
            account_id=account_id,
            brokerage_code="IBKR",
            account_external_id=external_id,
            base_currency="USD",
            display_name="Main",
        )

    def test_account_target_resolution_creates_child_rows(self):
        """Accounts dry-run with U100 resolved → one child row with account_id 'account-uuid'."""
        request = self._make_accounts_request()
        db = FakeAutomationDatabase()
        db.account_targets = [self._make_account_target()]

        self._run(request, db)

        self.assertEqual(len(db.added_accounts), 1)
        _child_id, child_req = db.added_accounts[0]
        self.assertEqual(child_req.account_id, "account-uuid")

    def test_portfolio_target_resolution_creates_child_row(self):
        """Portfolio target calls resolve_automation_portfolio_accounts and adds a child row."""
        request = self._make_portfolio_request()
        db = FakeAutomationDatabase()
        db.portfolio_accounts = [self._make_account_target(account_id="port-acct-uuid")]

        self._run(request, db)

        self.assertEqual(len(db.portfolio_resolve_calls), 1)
        self.assertEqual(len(db.added_accounts), 1)
        _child_id, child_req = db.added_accounts[0]
        self.assertEqual(child_req.account_id, "port-acct-uuid")

    def test_portfolio_resolution_passes_portfolio_name_and_brokerage(self):
        """resolve_automation_portfolio_accounts is called with portfolio_name and brokerage_code."""
        request = self._make_portfolio_request(portfolio_name="MyPortfolio")
        db = FakeAutomationDatabase()
        db.portfolio_accounts = [self._make_account_target()]

        self._run(request, db)

        self.assertEqual(len(db.portfolio_resolve_calls), 1)
        call = db.portfolio_resolve_calls[0]
        self.assertEqual(call["portfolio_name"], "MyPortfolio")
        self.assertEqual(call["brokerage_code"], "IBKR")

    def test_empty_resolved_account_set_fails_preflight(self):
        """No resolved accounts → parent finalized as failed with 'empty resolved account set'."""
        request = self._make_accounts_request()
        db = FakeAutomationDatabase()
        # account_targets is empty by default

        result = self._run(request, db)

        self.assertEqual(result.status, "failed")
        self.assertIn("empty resolved account set", result.error_message or "")
        self.assertEqual(len(db.added_accounts), 0)

    def test_empty_resolved_set_finalizes_parent_as_failed(self):
        """Empty resolved set must finalize the parent job as failed (not leave it running)."""
        request = self._make_accounts_request()
        db = FakeAutomationDatabase()

        self._run(request, db)

        self.assertEqual(len(db.finalized_jobs), 1)
        self.assertEqual(db.finalized_jobs[0].status, "failed")

    def test_account_target_resolution_passes_external_ids_and_brokerage(self):
        """resolve_automation_account_targets is called with account_external_ids and brokerage_code."""
        request = self._make_accounts_request(account_external_ids=("U100", "U200"))
        db = FakeAutomationDatabase()
        db.account_targets = [
            self._make_account_target(account_id="acct-1", external_id="U100"),
            self._make_account_target(account_id="acct-2", external_id="U200"),
        ]

        self._run(request, db)

        self.assertEqual(len(db.account_resolve_calls), 1)
        call = db.account_resolve_calls[0]
        self.assertEqual(call["brokerage_code"], "IBKR")
        self.assertIn("U100", call["account_external_ids"])
        self.assertIn("U200", call["account_external_ids"])

    def test_child_row_add_includes_automation_job_id(self):
        """Each add_automation_job_account request must carry the parent job_id."""
        request = self._make_accounts_request()
        db = FakeAutomationDatabase()
        db.account_targets = [self._make_account_target()]

        self._run(request, db)

        self.assertEqual(len(db.added_accounts), 1)
        _child_id, child_req = db.added_accounts[0]
        self.assertEqual(child_req.automation_job_id, "job-uuid")

    def test_child_rows_exist_before_dry_run_execution(self):
        """After child rows are created, dry-run execution succeeds and child rows exist."""
        from portfolio_engine.automation.orchestrator import run_automation
        request = self._make_accounts_request()
        db = FakeAutomationDatabase()
        db.account_targets = [self._make_account_target()]

        result = run_automation(request, database=db, adapter=FakeAdapter())

        self.assertIsNone(result.error_message)
        self.assertEqual(len(db.added_accounts), 1, "child rows must exist")
        self.assertEqual(result.status, "succeeded")

    def test_multiple_resolved_accounts_each_get_child_row(self):
        """Each resolved account produces exactly one child row."""
        request = self._make_accounts_request(account_external_ids=("U100", "U200"))
        db = FakeAutomationDatabase()
        db.account_targets = [
            self._make_account_target(account_id="acct-1", external_id="U100"),
            self._make_account_target(account_id="acct-2", external_id="U200"),
        ]

        self._run(request, db)

        self.assertEqual(len(db.added_accounts), 2)
        child_account_ids = {req.account_id for _cid, req in db.added_accounts}
        self.assertIn("acct-1", child_account_ids)
        self.assertIn("acct-2", child_account_ids)

    def test_valid_target_resolution_preserves_child_ids(self):
        """Returned child IDs from add_automation_job_account must appear on result.automation_job_account_ids."""
        request = self._make_accounts_request(account_external_ids=("U100", "U200"))
        db = FakeAutomationDatabase()
        db.account_targets = [
            self._make_account_target(account_id="acct-1", external_id="U100"),
            self._make_account_target(account_id="acct-2", external_id="U200"),
        ]

        result = self._run(request, db)

        self.assertIsNotNone(result.automation_job_account_ids)
        self.assertIn("child-1", result.automation_job_account_ids)
        self.assertIn("child-2", result.automation_job_account_ids)

    def test_child_insert_error_finalizes_parent_as_failed_and_reraises(self):
        """If add_automation_job_account raises, parent is finalized as failed and exception re-raised."""
        request = self._make_accounts_request()
        db = FakeAutomationDatabase()
        db.account_targets = [self._make_account_target()]

        original_exc = RuntimeError("db child insert failed")

        with mock.patch.object(db, "add_automation_job_account", side_effect=original_exc):
            with self.assertRaises(RuntimeError) as ctx:
                self._run(request, db)
            self.assertIs(ctx.exception, original_exc)
        self.assertEqual(len(db.finalized_jobs), 1)
        self.assertEqual(db.finalized_jobs[0].status, "failed")


class AutomationOrchestratorDryRunTests(unittest.TestCase):
    """Tests for Task 12: per-account dry-run execution."""

    def _run(self, request, db, adapter=None):
        from portfolio_engine.automation.orchestrator import run_automation
        if adapter is None:
            adapter = FakeAdapter()
        return run_automation(request, database=db, adapter=adapter)

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

    def _make_account_target(self, *, account_id="account-uuid", external_id="U100"):
        from portfolio_engine.database import AutomationAccountTarget
        return AutomationAccountTarget(
            account_id=account_id,
            brokerage_code="IBKR",
            account_external_id=external_id,
            base_currency="USD",
            display_name="Main",
        )

    def _make_db_with_accounts(self, *accounts):
        db = FakeAutomationDatabase()
        db.account_targets = list(accounts)
        return db

    def test_dry_run_finalizes_child_without_ingestion_run(self):
        """Dry-run with one account: result.status succeeded, child final status succeeded, ingestion_run_id None."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        result = self._run(request, db)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(len(db.finalized_children), 1)
        child_fin = db.finalized_children[0]
        self.assertEqual(child_fin.status, "succeeded")
        self.assertIsNone(child_fin.ingestion_run_id)

    def test_dry_run_marks_child_running_before_finalize(self):
        """mark_automation_job_account_running must be called before finalize_automation_job_account."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        self._run(request, db)

        self.assertEqual(len(db.running_children), 1)
        self.assertEqual(db.running_children[0], "child-1")
        mark_idx = db._event_log.index("mark_running:child-1")
        finalize_idx = db._event_log.index("finalize_child:child-1")
        self.assertLess(mark_idx, finalize_idx)

    def test_dry_run_parent_status_succeeded_when_all_children_succeeded(self):
        """Parent final status is succeeded when all child accounts succeed."""
        request = self._make_request(account_external_ids=("U100", "U200"))
        db = self._make_db_with_accounts(
            self._make_account_target(account_id="acct-1", external_id="U100"),
            self._make_account_target(account_id="acct-2", external_id="U200"),
        )

        result = self._run(request, db)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(len(db.finalized_children), 2)
        for child_fin in db.finalized_children:
            self.assertEqual(child_fin.status, "succeeded")

    def test_dry_run_parent_summary_aggregates_child_summaries(self):
        """Parent summary must contain aggregated account_counts and record_counts."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        result = self._run(request, db)

        self.assertIn("account_counts", result.summary)
        self.assertIn("record_counts", result.summary)
        self.assertEqual(result.summary["account_counts"]["total"], 1)
        self.assertEqual(result.summary["account_counts"]["succeeded"], 1)

    def test_dry_run_parent_finalizes_with_succeeded_status(self):
        """Finalized parent job has status succeeded after all children succeed."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        self._run(request, db)

        self.assertEqual(len(db.finalized_jobs), 1)
        self.assertEqual(db.finalized_jobs[0].status, "succeeded")
        self.assertIsNone(db.finalized_jobs[0].error_message)

    def test_dry_run_child_finalize_has_no_ingestion_run(self):
        """Child finalization in dry-run must have ingestion_run_id=None (no DB writes)."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        self._run(request, db)

        self.assertEqual(len(db.finalized_children), 1)
        self.assertIsNone(db.finalized_children[0].ingestion_run_id)

    def test_preflight_is_called_before_account_loop(self):
        """adapter.preflight_validate_config must be called (before account execution)."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        preflight_calls = []

        class TrackingAdapter(FakeAdapter):
            def preflight_validate_config(self, config) -> None:
                preflight_calls.append(config)
                return None

        self._run(request, db, adapter=TrackingAdapter())

        self.assertEqual(len(preflight_calls), 1)

    def test_preflight_runtime_error_finalizes_parent_failed(self):
        """RuntimeError from adapter.preflight_validate_config finalizes parent as failed; no child finalization."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        class FailPreflight(FakeAdapter):
            def preflight_validate_config(self, config) -> None:
                raise RuntimeError("missing required environment variables: IBKR_FLEX_TOKEN")

        self._run(request, db, adapter=FailPreflight())

        self.assertEqual(len(db.finalized_jobs), 1)
        self.assertEqual(db.finalized_jobs[0].status, "failed")
        self.assertEqual(len(db.finalized_children), 0, "no child should be finalized on preflight failure")
        self.assertIsNotNone(db.finalized_jobs[0].error_message)

    def test_preflight_failure_error_is_sanitized(self):
        """Error message from preflight RuntimeError must be sanitized (no raw secrets)."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        class FailPreflight(FakeAdapter):
            def preflight_validate_config(self, config) -> None:
                raise RuntimeError("missing required environment variables: IBKR_FLEX_TOKEN")

        self._run(request, db, adapter=FailPreflight())

        error_msg = db.finalized_jobs[0].error_message
        self.assertIsNotNone(error_msg)
        self.assertNotIn("postgresql://", error_msg or "")

    def test_get_adapter_used_when_adapter_is_none(self):
        """When adapter=None, get_adapter is called with config.adapter_key."""
        from portfolio_engine.automation.orchestrator import run_automation
        from portfolio_engine.automation.types import AutomationRunRequest
        request = self._make_request()
        db = FakeAutomationDatabase()
        # No accounts → fails before preflight; just verifies get_adapter is invoked
        fake_adapter = FakeAdapter()
        with mock.patch(
            "portfolio_engine.automation.orchestrator.get_adapter",
            return_value=fake_adapter,
        ) as mock_get:
            run_automation(request, database=db)
        mock_get.assert_called_once()

    def test_dry_run_child_summary_has_record_counts(self):
        """Finalized child summary dict must contain record_counts key."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        self._run(request, db)

        self.assertEqual(len(db.finalized_children), 1)
        child_summary = db.finalized_children[0].summary
        self.assertIsNotNone(child_summary)
        self.assertIn("record_counts", child_summary)

    def test_dry_run_result_has_child_ids(self):
        """AutomationRunResult.automation_job_account_ids must include the child id."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        result = self._run(request, db)

        self.assertIn("child-1", result.automation_job_account_ids)

    # ------------------------------------------------------------------
    # Issue 1: per-account exception handling in dry-run loop
    # ------------------------------------------------------------------

    def test_fetch_payload_exception_finalizes_child_as_failed(self):
        """If fetch_payload raises, the child must be finalized as failed with ingestion_run_id=None."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        class ErrorFetchAdapter(FakeAdapter):
            def fetch_payload(self, account, request, config):
                raise RuntimeError("network unreachable")

        result = self._run(request, db, adapter=ErrorFetchAdapter())

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(db.finalized_children), 1, "child must be finalized even on fetch error")
        child_fin = db.finalized_children[0]
        self.assertEqual(child_fin.status, "failed")
        self.assertIsNone(child_fin.ingestion_run_id)

    def test_fetch_payload_exception_no_running_child_remains(self):
        """After fetch_payload raises, no child row should remain in an unfinalized running state."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        class ErrorFetchAdapter(FakeAdapter):
            def fetch_payload(self, account, request, config):
                raise RuntimeError("network unreachable")

        self._run(request, db, adapter=ErrorFetchAdapter())

        running_ids = set(db.running_children)
        finalized_ids = {f.automation_job_account_id for f in db.finalized_children}
        self.assertTrue(
            running_ids.issubset(finalized_ids),
            f"Running children {running_ids} not all finalized; finalized: {finalized_ids}",
        )

    def test_fetch_payload_exception_parent_finalized_failed(self):
        """If the only child fails via fetch_payload exception, parent must be finalized as failed."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        class ErrorFetchAdapter(FakeAdapter):
            def fetch_payload(self, account, request, config):
                raise RuntimeError("timeout")

        self._run(request, db, adapter=ErrorFetchAdapter())

        self.assertEqual(len(db.finalized_jobs), 1)
        self.assertEqual(db.finalized_jobs[0].status, "failed")

    def test_fetch_payload_exception_child_error_message_is_sanitized(self):
        """Child error_message when fetch_payload raises must be sanitized (no raw secrets)."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        class ErrorFetchAdapter(FakeAdapter):
            def fetch_payload(self, account, request, config):
                raise RuntimeError("token=supersecret postgresql://user:pass@host/db")

        self._run(request, db, adapter=ErrorFetchAdapter())

        child_fin = db.finalized_children[0]
        self.assertIsNotNone(child_fin.error_message)
        self.assertNotIn("supersecret", child_fin.error_message or "")
        self.assertNotIn("postgresql://", child_fin.error_message or "")

    def test_fetch_payload_exception_child_summary_has_record_counts(self):
        """Child summary on failure must still contain record_counts (privacy-safe empty shape)."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        class ErrorFetchAdapter(FakeAdapter):
            def fetch_payload(self, account, request, config):
                raise RuntimeError("timeout")

        self._run(request, db, adapter=ErrorFetchAdapter())

        child_fin = db.finalized_children[0]
        self.assertIsInstance(child_fin.summary, dict)
        self.assertIn("record_counts", child_fin.summary)

    def test_two_accounts_first_fetch_raises_second_succeeds_parent_partially_succeeded(self):
        """Two accounts: first fetch raises, second succeeds → parent status is partially_succeeded."""
        request = self._make_request(account_external_ids=("U100", "U200"))
        db = self._make_db_with_accounts(
            self._make_account_target(account_id="acct-1", external_id="U100"),
            self._make_account_target(account_id="acct-2", external_id="U200"),
        )

        call_count = [0]

        class FirstFailAdapter(FakeAdapter):
            def fetch_payload(self, account, req, config):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise RuntimeError("first account failed")
                return super().fetch_payload(account, req, config)

        result = self._run(request, db, adapter=FirstFailAdapter())

        self.assertEqual(result.status, "partially_succeeded")
        self.assertEqual(len(db.finalized_jobs), 1)
        self.assertEqual(db.finalized_jobs[0].status, "partially_succeeded")

    def test_two_accounts_first_fetch_raises_both_children_finalized(self):
        """Two accounts: first fetch raises, second succeeds → both children are finalized."""
        request = self._make_request(account_external_ids=("U100", "U200"))
        db = self._make_db_with_accounts(
            self._make_account_target(account_id="acct-1", external_id="U100"),
            self._make_account_target(account_id="acct-2", external_id="U200"),
        )

        call_count = [0]

        class FirstFailAdapter(FakeAdapter):
            def fetch_payload(self, account, req, config):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise RuntimeError("first account failed")
                return super().fetch_payload(account, req, config)

        self._run(request, db, adapter=FirstFailAdapter())

        self.assertEqual(len(db.finalized_children), 2, "both children must be finalized")
        statuses = {f.automation_job_account_id: f.status for f in db.finalized_children}
        self.assertEqual(statuses["child-1"], "failed")
        self.assertEqual(statuses["child-2"], "succeeded")

    def test_two_accounts_first_fetch_raises_second_still_executed(self):
        """Two accounts: first fetch raises → loop must continue and execute the second account."""
        request = self._make_request(account_external_ids=("U100", "U200"))
        db = self._make_db_with_accounts(
            self._make_account_target(account_id="acct-1", external_id="U100"),
            self._make_account_target(account_id="acct-2", external_id="U200"),
        )

        call_count = [0]

        class FirstFailAdapter(FakeAdapter):
            def fetch_payload(self, account, req, config):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise RuntimeError("first account failed")
                return super().fetch_payload(account, req, config)

        self._run(request, db, adapter=FirstFailAdapter())

        self.assertEqual(call_count[0], 2, "fetch_payload must be called for both accounts")


class DeriveParentStatusTests(unittest.TestCase):
    """Direct unit tests for the _derive_parent_status helper."""

    def _derive(self, statuses):
        from portfolio_engine.automation.orchestrator import _derive_parent_status
        return _derive_parent_status(statuses)

    def test_empty_list_returns_failed(self):
        self.assertEqual(self._derive([]), "failed")

    def test_single_failed_returns_failed(self):
        self.assertEqual(self._derive(["failed"]), "failed")

    def test_all_failed_returns_failed(self):
        self.assertEqual(self._derive(["failed", "failed"]), "failed")

    def test_mixed_succeeded_and_failed_returns_partially_succeeded(self):
        self.assertEqual(self._derive(["succeeded", "failed"]), "partially_succeeded")

    def test_mixed_succeeded_and_partially_succeeded_returns_partially_succeeded(self):
        self.assertEqual(self._derive(["succeeded", "partially_succeeded"]), "partially_succeeded")

    def test_single_partially_succeeded_returns_partially_succeeded(self):
        self.assertEqual(self._derive(["partially_succeeded"]), "partially_succeeded")

    def test_single_succeeded_returns_succeeded(self):
        self.assertEqual(self._derive(["succeeded"]), "succeeded")

    def test_all_succeeded_returns_succeeded(self):
        self.assertEqual(self._derive(["succeeded", "succeeded"]), "succeeded")


class AutomationOrchestratorLoadTests(unittest.TestCase):
    """Tests for Task 13: per-account load execution."""

    def _run(self, request, db, adapter=None):
        from portfolio_engine.automation.orchestrator import run_automation
        if adapter is None:
            adapter = FakeAdapter()
        return run_automation(request, database=db, adapter=adapter)

    def _make_request(self, **kwargs):
        from portfolio_engine.automation.types import AutomationRunRequest
        defaults = dict(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode="load",
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
            account_external_ids=("U100",),
        )
        defaults.update(kwargs)
        return AutomationRunRequest(**defaults)

    def _make_account_target(self, *, account_id="account-uuid", external_id="U100"):
        from portfolio_engine.database import AutomationAccountTarget
        return AutomationAccountTarget(
            account_id=account_id,
            brokerage_code="IBKR",
            account_external_id=external_id,
            base_currency="USD",
            display_name="Main",
        )

    def _make_db_with_accounts(self, *accounts):
        db = FakeAutomationDatabase()
        db.account_targets = list(accounts)
        return db

    def test_load_finalizes_child_with_ingestion_run(self):
        """Load mode: result.status succeeded, child ingestion_run_id is set, ingestion run completed succeeded."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        result = self._run(request, db)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(len(db.finalized_children), 1)
        child_fin = db.finalized_children[0]
        self.assertEqual(child_fin.status, "succeeded")
        self.assertIsNotNone(child_fin.ingestion_run_id)
        self.assertEqual(child_fin.ingestion_run_id, "ingestion-run-uuid")
        self.assertEqual(len(db.completed_ingestion_runs), 1)
        self.assertEqual(db.completed_ingestion_runs[0][1], "succeeded")

    def test_load_starts_ingestion_run_with_correct_fields(self):
        """load_payload starts an ingestion run with correct brokerage_code, account_external_id, source_type, dates."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target(external_id="U100"))

        self._run(request, db)

        self.assertEqual(len(db.started_ingestion_runs), 1)
        started = db.started_ingestion_runs[0]
        self.assertEqual(started.brokerage_code, "IBKR")
        self.assertEqual(started.account_external_id, "U100")
        self.assertEqual(started.source_type, "FLEX_WEB_SERVICE")
        self.assertEqual(started.requested_start_date, date(2024, 1, 1))
        self.assertEqual(started.requested_end_date, date(2024, 1, 31))

    def test_load_starts_ingestion_run_with_source_name(self):
        """load_payload passes source_name from BrokerPayload to start_ingestion_run."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        class NamedPayloadAdapter(FakeAdapter):
            def fetch_payload(self, account, req, config):
                from portfolio_engine.automation.types import BrokerPayload
                return BrokerPayload(
                    xml_text="<FlexQueryResponse></FlexQueryResponse>",
                    source_name="report-2024.xml",
                )

        self._run(request, db, adapter=NamedPayloadAdapter())

        started = db.started_ingestion_runs[0]
        self.assertEqual(started.source_filename, "report-2024.xml")

    def test_load_no_records_makes_no_bulk_calls(self):
        """When XML has no supported records, no bulk ingest calls are made; ingestion run completed succeeded."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        result = self._run(request, db)

        self.assertEqual(len(db.cash_bulk_calls), 0)
        self.assertEqual(len(db.nav_bulk_calls), 0)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(db.completed_ingestion_runs[0][1], "succeeded")

    def test_load_child_summary_has_record_counts(self):
        """Finalized child summary must have record_counts key."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        self._run(request, db)

        child_fin = db.finalized_children[0]
        self.assertIsNotNone(child_fin.summary)
        self.assertIn("record_counts", child_fin.summary)

    def test_load_parent_finalizes_succeeded(self):
        """Load mode with one succeeding account: parent finalized as succeeded."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        self._run(request, db)

        self.assertEqual(len(db.finalized_jobs), 1)
        self.assertEqual(db.finalized_jobs[0].status, "succeeded")
        self.assertIsNone(db.finalized_jobs[0].error_message)

    def test_load_ingestion_run_id_not_none(self):
        """Load mode child finalization must have ingestion_run_id set (not None)."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        self._run(request, db)

        self.assertIsNotNone(db.finalized_children[0].ingestion_run_id)

    def test_load_dry_run_does_not_create_ingestion_run(self):
        """dry-run mode must not create any ingestion runs."""
        from portfolio_engine.automation.types import AutomationRunRequest
        request = AutomationRunRequest(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
            account_external_ids=("U100",),
        )
        db = self._make_db_with_accounts(self._make_account_target())

        self._run(request, db)

        self.assertEqual(len(db.started_ingestion_runs), 0)
        self.assertEqual(len(db.completed_ingestion_runs), 0)

    def test_load_fetch_exception_finalizes_child_failed(self):
        """Load mode: fetch_payload exception finalizes child as failed, no ingestion run started."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        class ErrorAdapter(FakeAdapter):
            def fetch_payload(self, account, req, config):
                raise RuntimeError("network error")

        result = self._run(request, db, adapter=ErrorAdapter())

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(db.finalized_children), 1)
        self.assertEqual(db.finalized_children[0].status, "failed")
        self.assertIsNone(db.finalized_children[0].ingestion_run_id)
        self.assertEqual(len(db.started_ingestion_runs), 0)

    def test_load_two_accounts_first_fails_second_succeeds_partial(self):
        """Load mode: first account fetch fails, second succeeds → partially_succeeded parent."""
        request = self._make_request(account_external_ids=("U100", "U200"))
        db = self._make_db_with_accounts(
            self._make_account_target(account_id="acct-1", external_id="U100"),
            self._make_account_target(account_id="acct-2", external_id="U200"),
        )

        call_count = [0]

        class FirstFailAdapter(FakeAdapter):
            def fetch_payload(self, account, req, config):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise RuntimeError("first account failed")
                return super().fetch_payload(account, req, config)

        result = self._run(request, db, adapter=FirstFailAdapter())

        self.assertEqual(result.status, "partially_succeeded")
        self.assertEqual(len(db.finalized_children), 2)

    def test_load_marks_child_running_before_finalize(self):
        """mark_automation_job_account_running must be called before finalize in load mode."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        self._run(request, db)

        self.assertEqual(len(db.running_children), 1)
        mark_idx = db._event_log.index("mark_running:child-1")
        finalize_idx = db._event_log.index("finalize_child:child-1")
        self.assertLess(mark_idx, finalize_idx)

    def test_load_child_ids_preserved_in_result(self):
        """AutomationRunResult.automation_job_account_ids includes child id in load mode."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        result = self._run(request, db)

        self.assertIn("child-1", result.automation_job_account_ids)


class DeriveIngestionStatusTests(unittest.TestCase):
    """Direct unit tests for _derive_ingestion_status helper in ingestion.py."""

    def _derive(self, cash_summary: BulkIngestionSummary, nav_summary: BulkIngestionSummary):
        from portfolio_engine.automation.ingestion import _derive_ingestion_status
        return _derive_ingestion_status(cash_summary, nav_summary)

    def _empty(self) -> BulkIngestionSummary:
        return BulkIngestionSummary(
            inserted_count=0,
            duplicate_count=0,
            skipped_unknown_account_count=0,
            skipped_inactive_account_count=0,
            conflict_count=0,
            skipped_accounts=[],
            record_results=[],
        )

    def test_both_empty_returns_succeeded(self):
        self.assertEqual(self._derive(self._empty(), self._empty()), "succeeded")

    def test_duplicates_only_returns_succeeded(self):
        cash = BulkIngestionSummary(
            inserted_count=0,
            duplicate_count=5,
            skipped_unknown_account_count=0,
            skipped_inactive_account_count=0,
            conflict_count=0,
            skipped_accounts=[],
            record_results=[],
        )
        self.assertEqual(self._derive(cash, self._empty()), "succeeded")

    def test_skipped_unknown_account_returns_partially_succeeded(self):
        cash = BulkIngestionSummary(
            inserted_count=0,
            duplicate_count=0,
            skipped_unknown_account_count=1,
            skipped_inactive_account_count=0,
            conflict_count=0,
            skipped_accounts=[],
            record_results=[],
        )
        self.assertEqual(self._derive(cash, self._empty()), "partially_succeeded")

    def test_skipped_inactive_account_returns_partially_succeeded(self):
        nav = BulkIngestionSummary(
            inserted_count=0,
            duplicate_count=0,
            skipped_unknown_account_count=0,
            skipped_inactive_account_count=1,
            conflict_count=0,
            skipped_accounts=[],
            record_results=[],
        )
        self.assertEqual(self._derive(self._empty(), nav), "partially_succeeded")

    def test_conflict_returns_partially_succeeded(self):
        nav = BulkIngestionSummary(
            inserted_count=0,
            duplicate_count=0,
            skipped_unknown_account_count=0,
            skipped_inactive_account_count=0,
            conflict_count=2,
            skipped_accounts=[],
            record_results=[],
        )
        self.assertEqual(self._derive(self._empty(), nav), "partially_succeeded")

    def test_inserted_only_returns_succeeded(self):
        cash = BulkIngestionSummary(
            inserted_count=3,
            duplicate_count=0,
            skipped_unknown_account_count=0,
            skipped_inactive_account_count=0,
            conflict_count=0,
            skipped_accounts=[],
            record_results=[],
        )
        self.assertEqual(self._derive(cash, self._empty()), "succeeded")


class AutomationLoadPartialTests(unittest.TestCase):
    """Tests for load mode partial_succeeded scenarios via FakeAutomationDatabase overrides."""

    def _run(self, request, db, adapter=None):
        from portfolio_engine.automation.orchestrator import run_automation
        if adapter is None:
            adapter = FakeAdapter()
        return run_automation(request, database=db, adapter=adapter)

    def _make_request(self, **kwargs):
        from portfolio_engine.automation.types import AutomationRunRequest
        defaults = dict(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode="load",
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
            account_external_ids=("U100",),
        )
        defaults.update(kwargs)
        return AutomationRunRequest(**defaults)

    def _make_account_target(self, *, account_id="account-uuid", external_id="U100"):
        from portfolio_engine.database import AutomationAccountTarget
        return AutomationAccountTarget(
            account_id=account_id,
            brokerage_code="IBKR",
            account_external_id=external_id,
            base_currency="USD",
            display_name="Main",
        )

    def test_partial_bulk_summary_produces_partially_succeeded_child(self):
        """When bulk_ingest_cash_flows returns skipped_unknown_account, child and parent are partially_succeeded."""
        request = self._make_request()
        db = FakeAutomationDatabase()
        db.account_targets = [self._make_account_target()]

        # Override bulk_ingest_cash_flows to return a partial summary
        partial_summary = BulkIngestionSummary(
            inserted_count=0,
            duplicate_count=0,
            skipped_unknown_account_count=1,
            skipped_inactive_account_count=0,
            conflict_count=0,
            skipped_accounts=["U999"],
            record_results=[],
        )

        def partial_bulk(ingestion_run_id, records):
            db.cash_bulk_calls.append({"ingestion_run_id": ingestion_run_id, "records": records})
            return partial_summary

        db.bulk_ingest_cash_flows = partial_bulk  # type: ignore

        # Use an adapter that returns XML with one CashTransaction for U100
        # within the requested date range so bulk_ingest_cash_flows is called.
        _CASH_XML = (
            '<FlexQueryResponse>'
            '<CashTransaction accountId="U100" reportDate="20240115"'
            ' dateTime="20240115;120000" currency="USD" amount="100.00"'
            ' fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" />'
            '</FlexQueryResponse>'
        )

        class CashFlowAdapter(FakeAdapter):
            def fetch_payload(self, account, req, config):
                from portfolio_engine.automation.types import BrokerPayload
                return BrokerPayload(xml_text=_CASH_XML, source_name="synthetic.xml")

        result = self._run(request, db, adapter=CashFlowAdapter())

        self.assertEqual(result.status, "partially_succeeded")
        self.assertEqual(len(db.finalized_children), 1)
        child_fin = db.finalized_children[0]
        self.assertEqual(child_fin.status, "partially_succeeded")
        self.assertEqual(child_fin.error_message, "skipped accounts or conflicts require review")
        self.assertEqual(len(db.finalized_jobs), 1)
        self.assertEqual(db.finalized_jobs[0].status, "partially_succeeded")
        self.assertEqual(len(db.completed_ingestion_runs), 1)
        self.assertEqual(db.completed_ingestion_runs[0][1], "partially_succeeded")


class AutomationLoadIngestionRunCleanupTests(unittest.TestCase):
    """Tests for Task 13 fix: complete ingestion run as failed on bulk ingest exception."""

    _CASH_XML = (
        '<FlexQueryResponse>'
        '<CashTransaction accountId="U100" reportDate="20240115"'
        ' dateTime="20240115;120000" currency="USD" amount="100.00"'
        ' fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" />'
        '</FlexQueryResponse>'
    )

    def _run(self, request, db, adapter=None):
        from portfolio_engine.automation.orchestrator import run_automation
        if adapter is None:
            adapter = FakeAdapter()
        return run_automation(request, database=db, adapter=adapter)

    def _make_request(self, **kwargs):
        from portfolio_engine.automation.types import AutomationRunRequest
        defaults = dict(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode="load",
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
            account_external_ids=("U100",),
        )
        defaults.update(kwargs)
        return AutomationRunRequest(**defaults)

    def _make_account_target(self, *, account_id="account-uuid", external_id="U100"):
        from portfolio_engine.database import AutomationAccountTarget
        return AutomationAccountTarget(
            account_id=account_id,
            brokerage_code="IBKR",
            account_external_id=external_id,
            base_currency="USD",
            display_name="Main",
        )

    def _make_cash_flow_adapter(self):
        xml = self._CASH_XML

        class CashFlowAdapter(FakeAdapter):
            def fetch_payload(self, account, req, config):
                from portfolio_engine.automation.types import BrokerPayload
                return BrokerPayload(xml_text=xml, source_name="synthetic.xml")

        return CashFlowAdapter()

    def test_bulk_ingest_exception_completes_ingestion_run_as_failed(self):
        """When bulk_ingest_cash_flows raises after start_ingestion_run, ingestion run must be completed as failed."""
        request = self._make_request()
        db = FakeAutomationDatabase()
        db.account_targets = [self._make_account_target()]

        def raising_bulk(ingestion_run_id, records):
            raise RuntimeError("bulk insert failed")

        db.bulk_ingest_cash_flows = raising_bulk  # type: ignore

        result = self._run(request, db, adapter=self._make_cash_flow_adapter())

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(db.completed_ingestion_runs), 1)
        run_id, status, _msg = db.completed_ingestion_runs[0]
        self.assertEqual(run_id, "ingestion-run-uuid")
        self.assertEqual(status, "failed")

    def test_bulk_ingest_exception_no_uncompleted_ingestion_run(self):
        """After bulk_ingest_cash_flows raises, no ingestion run must be left open (started but not completed)."""
        request = self._make_request()
        db = FakeAutomationDatabase()
        db.account_targets = [self._make_account_target()]

        def raising_bulk(ingestion_run_id, records):
            raise RuntimeError("bulk insert failed")

        db.bulk_ingest_cash_flows = raising_bulk  # type: ignore

        self._run(request, db, adapter=self._make_cash_flow_adapter())

        started_ids = {r.account_external_id for r in db.started_ingestion_runs}
        self.assertEqual(len(db.started_ingestion_runs), len(db.completed_ingestion_runs),
                         "every started ingestion run must be completed")
        self.assertGreater(len(db.completed_ingestion_runs), 0)

    def test_bulk_ingest_exception_child_finalized_as_failed(self):
        """When bulk_ingest raises, the orchestrator child must be finalized as failed."""
        request = self._make_request()
        db = FakeAutomationDatabase()
        db.account_targets = [self._make_account_target()]

        def raising_bulk(ingestion_run_id, records):
            raise RuntimeError("bulk insert failed")

        db.bulk_ingest_cash_flows = raising_bulk  # type: ignore

        result = self._run(request, db, adapter=self._make_cash_flow_adapter())

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(db.finalized_children), 1)
        self.assertEqual(db.finalized_children[0].status, "failed")

    def test_bulk_ingest_exception_error_message_is_sanitized(self):
        """Error message stored on failed ingestion run must not contain raw secrets."""
        request = self._make_request()
        db = FakeAutomationDatabase()
        db.account_targets = [self._make_account_target()]

        def raising_bulk(ingestion_run_id, records):
            raise RuntimeError("token=supersecret postgresql://user:pass@host/db")

        db.bulk_ingest_cash_flows = raising_bulk  # type: ignore

        self._run(request, db, adapter=self._make_cash_flow_adapter())

        self.assertEqual(len(db.completed_ingestion_runs), 1)
        _run_id, _status, msg = db.completed_ingestion_runs[0]
        self.assertIsNotNone(msg)
        self.assertNotIn("supersecret", msg or "")
        self.assertNotIn("postgresql://", msg or "")

    def test_nav_bulk_ingest_exception_completes_ingestion_run_as_failed(self):
        """When bulk_ingest_daily_nav_snapshots raises, ingestion run must be completed as failed."""
        nav_xml = (
            '<FlexQueryResponse>'
            '<EquitySummaryByReportDateInBase accountId="U100" reportDate="20240115"'
            ' currency="USD" total="10000.00" cash="0.00" stock="10000.00" />'
            '</FlexQueryResponse>'
        )
        request = self._make_request()
        db = FakeAutomationDatabase()
        db.account_targets = [self._make_account_target()]

        def raising_nav_bulk(ingestion_run_id, records):
            raise RuntimeError("nav bulk insert failed")

        db.bulk_ingest_daily_nav_snapshots = raising_nav_bulk  # type: ignore

        class NavAdapter(FakeAdapter):
            def fetch_payload(self, account, req, config):
                from portfolio_engine.automation.types import BrokerPayload
                return BrokerPayload(xml_text=nav_xml, source_name="nav.xml")

        result = self._run(request, db, adapter=NavAdapter())

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(db.completed_ingestion_runs), 1)
        _run_id, status, _msg = db.completed_ingestion_runs[0]
        self.assertEqual(status, "failed")

    def test_bulk_exception_does_not_affect_second_account(self):
        """When first account's bulk raises, second account is still processed successfully."""
        request = self._make_request(account_external_ids=("U100", "U200"))
        db = FakeAutomationDatabase()
        db.account_targets = [
            self._make_account_target(account_id="acct-1", external_id="U100"),
            self._make_account_target(account_id="acct-2", external_id="U200"),
        ]

        call_count = [0]

        def sometimes_raising_bulk(ingestion_run_id, records):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("first bulk failed")
            return BulkIngestionSummary(
                inserted_count=1,
                duplicate_count=0,
                skipped_unknown_account_count=0,
                skipped_inactive_account_count=0,
                conflict_count=0,
                skipped_accounts=[],
                record_results=[],
            )

        db.bulk_ingest_cash_flows = sometimes_raising_bulk  # type: ignore

        result = self._run(request, db, adapter=self._make_cash_flow_adapter())

        self.assertEqual(result.status, "partially_succeeded")
        self.assertEqual(len(db.finalized_children), 2)
        statuses = {f.automation_job_account_id: f.status for f in db.finalized_children}
        self.assertEqual(statuses["child-1"], "failed")
        self.assertEqual(statuses["child-2"], "succeeded")
        self.assertEqual(len(db.completed_ingestion_runs), 2,
                         "both ingestion runs must be completed (one failed, one succeeded)")


if __name__ == "__main__":
    unittest.main()
