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
        self.assertIn("SUPERFOLIO_CREDENTIAL_MASTER_KEY", msg)

    def test_preflight_does_not_include_database_url_in_missing(self):
        adapter = self._get_adapter()
        config = load_integration_config("ibkr_flex_ws")
        env = {"SUPERFOLIO_CREDENTIAL_MASTER_KEY": "masterkey"}
        with mock.patch.dict(os.environ, env, clear=True):
            # Should pass; DATABASE_URL absence is not a preflight concern
            adapter.preflight_validate_config(config)

    def test_preflight_passes_when_all_broker_vars_present(self):
        adapter = self._get_adapter()
        config = load_integration_config("ibkr_flex_ws")
        env = {
            "SUPERFOLIO_CREDENTIAL_MASTER_KEY": "masterkey",
            "DATABASE_URL": "postgresql://localhost/db",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            adapter.preflight_validate_config(config)

    def test_preflight_treats_blank_env_var_as_missing(self):
        adapter = self._get_adapter()
        config = load_integration_config("ibkr_flex_ws")
        env = {"SUPERFOLIO_CREDENTIAL_MASTER_KEY": "   "}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                adapter.preflight_validate_config(config)
        self.assertIn("SUPERFOLIO_CREDENTIAL_MASTER_KEY", str(ctx.exception))

    def test_preflight_treats_empty_string_as_missing(self):
        adapter = self._get_adapter()
        config = load_integration_config("ibkr_flex_ws")
        env = {"SUPERFOLIO_CREDENTIAL_MASTER_KEY": ""}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                adapter.preflight_validate_config(config)
        self.assertIn("SUPERFOLIO_CREDENTIAL_MASTER_KEY", str(ctx.exception))

    def test_preflight_missing_only_master_key_raises_not_database_url(self):
        adapter = self._get_adapter()
        config = load_integration_config("ibkr_flex_ws")
        env = {"DATABASE_URL": "postgresql://localhost/db"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                adapter.preflight_validate_config(config)
        self.assertIn("SUPERFOLIO_CREDENTIAL_MASTER_KEY", str(ctx.exception))
        self.assertNotIn("DATABASE_URL", str(ctx.exception))


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
        # Overlap detection (Task 15)
        self.overlapping_load: bool = False
        self.overlapping_account_ids: set[str] = set()
        self.overlapping_load_accounts: set[str] = set()
        self.overlap_check_calls: list = []
        # Portfolio id resolution (Issue 1 fix)
        self.portfolio_id_by_name: dict[str, str] = {}
        self.portfolio_id_lookup_calls: list[str] = []
        # Connection-aware target resolution (Task 10)
        self.connection_targets: list | None = None
        self.connection_resolve_calls: list = []
        # Connection credential and feed loading (Task 11)
        self.connection_credentials: dict[str, dict[str, bytes]] = {}
        self.connection_feeds: dict[str, list] = {}
        self.credential_calls: list[str] = []
        self.feed_calls: list[str] = []

    def fail_stale_automation_runs(self, *, stale_before, error_message) -> int:
        self._event_log.append("fail_stale")
        self.fail_stale_calls.append({"stale_before": stale_before, "error_message": error_message})
        return 0

    def get_portfolio_id_by_name(self, portfolio_name: str) -> str | None:
        """Return the portfolio UUID for the given active portfolio name, or None if not found."""
        self._event_log.append("lookup_portfolio")
        self.portfolio_id_lookup_calls.append(portfolio_name)
        return self.portfolio_id_by_name.get(portfolio_name)

    def create_automation_job(self, request) -> str:
        if self._raise_on_create is not None:
            raise self._raise_on_create
        # Enforce the DB check constraint: portfolio_id IS NOT NULL for portfolio target.
        if request.target_type == "portfolio" and request.portfolio_id is None:
            raise ValueError(
                "automation_jobs_portfolio_target_check: portfolio_id must not be NULL"
                " for target_type='portfolio'"
            )
        if request.target_type == "accounts" and request.portfolio_id is not None:
            raise ValueError(
                "automation_jobs_portfolio_target_check: portfolio_id must be NULL"
                " for target_type='accounts'"
            )
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

    def resolve_automation_targets_with_connections(
        self,
        *,
        target_type: str,
        portfolio_name: str | None,
        brokerage_code: str,
        account_external_ids: list,
    ):
        """Return connection-aware targets. Falls back to converting account_targets / portfolio_accounts
        (with a default non-null connection_id) when connection_targets has not been set explicitly."""
        from portfolio_engine.database import AutomationConnectionTarget
        self.connection_resolve_calls.append({
            "target_type": target_type,
            "portfolio_name": portfolio_name,
            "brokerage_code": brokerage_code,
            "account_external_ids": account_external_ids,
        })
        if self.connection_targets is not None:
            return list(self.connection_targets)
        # Backward-compat fallback: convert existing account_targets / portfolio_accounts
        source = self.portfolio_accounts if target_type == "portfolio" else self.account_targets
        return [
            AutomationConnectionTarget(
                account_id=t.account_id,
                brokerage_code=t.brokerage_code,
                account_external_id=t.account_external_id,
                base_currency=t.base_currency,
                display_name=t.display_name,
                connection_id="test-connection-id",
                connection_name="Test Connection",
            )
            for t in source
        ]

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

    def has_overlapping_automation_load(
        self,
        *,
        integration_key: str,
        account_id: str,
        requested_start_date,
        requested_end_date,
        exclude_automation_job_id: str,
    ) -> bool:
        self.overlap_check_calls.append({
            "integration_key": integration_key,
            "account_id": account_id,
            "requested_start_date": requested_start_date,
            "requested_end_date": requested_end_date,
            "exclude_automation_job_id": exclude_automation_job_id,
        })
        return self.overlapping_load or account_id in self.overlapping_account_ids or account_id in self.overlapping_load_accounts

    def list_active_connection_credentials(self, connection_id: str) -> dict[str, bytes]:
        self.credential_calls.append(connection_id)
        return dict(self.connection_credentials.get(connection_id, {}))

    def list_active_integration_feeds(self, connection_id: str) -> list:
        self.feed_calls.append(connection_id)
        return list(self.connection_feeds.get(connection_id, []))


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
        """Portfolio target calls resolve_automation_targets_with_connections and adds a child row."""
        request = self._make_portfolio_request()
        db = FakeAutomationDatabase()
        db.portfolio_id_by_name["MyPortfolio"] = "portfolio-uuid"
        db.portfolio_accounts = [self._make_account_target(account_id="port-acct-uuid")]

        self._run(request, db)

        self.assertEqual(len(db.connection_resolve_calls), 1)
        self.assertEqual(len(db.added_accounts), 1)
        _child_id, child_req = db.added_accounts[0]
        self.assertEqual(child_req.account_id, "port-acct-uuid")

    def test_portfolio_resolution_passes_portfolio_name_and_brokerage(self):
        """resolve_automation_targets_with_connections is called with portfolio_name and brokerage_code."""
        request = self._make_portfolio_request(portfolio_name="MyPortfolio")
        db = FakeAutomationDatabase()
        db.portfolio_id_by_name["MyPortfolio"] = "portfolio-uuid"
        db.portfolio_accounts = [self._make_account_target()]

        self._run(request, db)

        self.assertEqual(len(db.connection_resolve_calls), 1)
        call = db.connection_resolve_calls[0]
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

        self.assertEqual(len(db.connection_resolve_calls), 1)
        call = db.connection_resolve_calls[0]
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
        """RuntimeError from adapter.preflight_validate_config finalizes parent as failed.
        Children must also be finalized as failed (Issue 2 fix: no pending children remain)."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        class FailPreflight(FakeAdapter):
            def preflight_validate_config(self, config) -> None:
                raise RuntimeError("missing required environment variables: SUPERFOLIO_CREDENTIAL_MASTER_KEY")

        self._run(request, db, adapter=FailPreflight())

        self.assertEqual(len(db.finalized_jobs), 1)
        self.assertEqual(db.finalized_jobs[0].status, "failed")
        self.assertEqual(len(db.finalized_children), 1, "child must be finalized on preflight failure")
        self.assertEqual(db.finalized_children[0].status, "failed")
        self.assertIsNotNone(db.finalized_jobs[0].error_message)

    def test_preflight_failure_error_is_sanitized(self):
        """Error message from preflight RuntimeError must be sanitized (no raw secrets)."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        class FailPreflight(FakeAdapter):
            def preflight_validate_config(self, config) -> None:
                raise RuntimeError("missing required environment variables: SUPERFOLIO_CREDENTIAL_MASTER_KEY")

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


class AutomationLoadCleanupExceptionEdgeCaseTests(unittest.TestCase):
    """TDD tests for Task 13 final code-quality notes (Issue 1 & Issue 2).

    Issue 1: cleanup complete_ingestion_run(failed) raising must not replace the original
             bulk exception; original must propagate with cleanup context attached as a note.
    Issue 2: success-path complete_ingestion_run is inside the try block; if it raises,
             the except calls complete a second time (double-complete / misclassification).
             Fix: move success complete outside try; call complete exactly once on success path.
    """

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

    # --- Issue 1 orchestrator-level test ---

    def test_issue1_cleanup_failure_preserves_original_error_in_child(self):
        """Issue 1: when bulk_ingest raises and complete_ingestion_run(failed) also raises,
        the child must be finalized with the original bulk error, not the cleanup error."""
        request = self._make_request()
        db = FakeAutomationDatabase()
        db.account_targets = [self._make_account_target()]

        def raising_bulk(ingestion_run_id, records):
            raise RuntimeError("cash failed")

        def raising_complete_on_failed(*, ingestion_run_id, status, error_message):
            if status == "failed":
                raise RuntimeError("cleanup failed")

        db.bulk_ingest_cash_flows = raising_bulk  # type: ignore
        db.complete_ingestion_run = raising_complete_on_failed  # type: ignore

        result = self._run(request, db, adapter=self._make_cash_flow_adapter())

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(db.finalized_children), 1)
        child_fin = db.finalized_children[0]
        self.assertEqual(child_fin.status, "failed")
        # Original bulk error must appear in the child error message
        self.assertIn("cash failed", child_fin.error_message or "")
        # Cleanup error must NOT replace the original
        self.assertNotIn("cleanup failed", child_fin.error_message or "")

    # --- Issue 1 load_payload unit-level test ---

    def test_issue1_load_payload_reraises_original_with_cleanup_note(self):
        """Issue 1 (load_payload unit): when bulk raises and cleanup complete also raises,
        the original exception is re-raised with a note about the cleanup failure."""
        from portfolio_engine.automation.ingestion import load_payload

        db = FakeAutomationDatabase()

        def raising_bulk(ingestion_run_id, records):
            raise RuntimeError("cash failed")

        def raising_complete_on_failed(*, ingestion_run_id, status, error_message):
            if status == "failed":
                raise RuntimeError("cleanup failed")

        db.bulk_ingest_cash_flows = raising_bulk  # type: ignore
        db.complete_ingestion_run = raising_complete_on_failed  # type: ignore

        with self.assertRaises(RuntimeError) as ctx:
            load_payload(
                self._CASH_XML,
                database=db,
                brokerage_code="IBKR",
                account_external_id="U100",
                source_type="FLEX_WEB_SERVICE",
                source_name="test.xml",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )

        exc = ctx.exception
        # The original exception must propagate (not the cleanup one)
        self.assertIn("cash failed", str(exc))
        # Cleanup context must be attached as a note on the original exception
        notes = getattr(exc, "__notes__", None) or []
        self.assertTrue(
            any("cleanup failed" in note for note in notes),
            f"Expected cleanup context in __notes__ but got: {notes!r}",
        )

    # --- Issue 2 orchestrator-level tests ---

    def test_issue2_success_complete_raises_cleanup_also_raises_child_finalized_failed(self):
        """Issue 2: when success complete_ingestion_run raises and cleanup also raises,
        complete must be called exactly twice (success attempt + cleanup attempt),
        child finalized failed with the original success-completion error."""
        request = self._make_request()
        db = FakeAutomationDatabase()
        db.account_targets = [self._make_account_target()]

        complete_calls: list[str] = []

        def always_raising_complete(*, ingestion_run_id, status, error_message):
            complete_calls.append(status)
            raise RuntimeError("completion failed")

        db.complete_ingestion_run = always_raising_complete  # type: ignore

        # Default adapter returns empty XML — no bulk calls, success path hits complete
        result = self._run(request, db)

        # complete_ingestion_run must be called twice: once for success, once for cleanup
        self.assertEqual(len(complete_calls), 2,
                         f"Expected 2 complete calls (success + cleanup) but got: {complete_calls}")
        self.assertEqual(complete_calls[1], "failed",
                         "Second call must be the cleanup call with status='failed'")
        self.assertEqual(result.status, "failed")
        self.assertEqual(len(db.finalized_children), 1)
        child_fin = db.finalized_children[0]
        self.assertEqual(child_fin.status, "failed")
        self.assertIn("completion failed", child_fin.error_message or "")

    def test_issue2_success_complete_raises_cleanup_succeeds_child_finalized_failed(self):
        """Issue 2: when success complete_ingestion_run raises but cleanup completion succeeds,
        complete is called twice (success attempt + cleanup), child is finalized failed,
        and the DB records the cleanup completion."""
        request = self._make_request()
        db = FakeAutomationDatabase()
        db.account_targets = [self._make_account_target()]

        complete_calls: list[str] = []

        def raising_on_success_only(*, ingestion_run_id, status, error_message):
            complete_calls.append(status)
            if status != "failed":
                raise RuntimeError("success complete failed")
            # cleanup call succeeds: record it
            db.completed_ingestion_runs.append((ingestion_run_id, status, error_message))

        db.complete_ingestion_run = raising_on_success_only  # type: ignore

        result = self._run(request, db)

        self.assertEqual(len(complete_calls), 2,
                         f"Expected 2 complete calls but got: {complete_calls}")
        self.assertEqual(complete_calls[0], "succeeded")
        self.assertEqual(complete_calls[1], "failed")
        self.assertEqual(result.status, "failed")
        child_fin = db.finalized_children[0]
        self.assertEqual(child_fin.status, "failed")
        self.assertIn("success complete failed", child_fin.error_message or "")
        # Cleanup completion recorded in DB
        self.assertEqual(len(db.completed_ingestion_runs), 1)
        self.assertEqual(db.completed_ingestion_runs[0][1], "failed")

    # --- Issue 2 load_payload unit-level tests ---

    def test_issue2_load_payload_success_complete_raises_attempts_cleanup(self):
        """Issue 2 (load_payload unit): when success complete_ingestion_run raises,
        it attempts exactly one cleanup call with status='failed', then re-raises original."""
        from portfolio_engine.automation.ingestion import load_payload

        db = FakeAutomationDatabase()

        complete_calls: list[str] = []

        def always_raising_complete(*, ingestion_run_id, status, error_message):
            complete_calls.append(status)
            raise RuntimeError("completion failed")

        db.complete_ingestion_run = always_raising_complete  # type: ignore

        # Empty XML — no bulk calls; success-path complete raises
        with self.assertRaises(RuntimeError) as ctx:
            load_payload(
                "<FlexQueryResponse></FlexQueryResponse>",
                database=db,
                brokerage_code="IBKR",
                account_external_id="U100",
                source_type="FLEX_WEB_SERVICE",
                source_name="test.xml",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )

        self.assertIn("completion failed", str(ctx.exception))
        # Must be called twice: success attempt + exactly one cleanup attempt
        self.assertEqual(len(complete_calls), 2,
                         f"Expected 2 complete calls (success + cleanup) but got: {complete_calls}")
        self.assertEqual(complete_calls[1], "failed",
                         "Second call must be cleanup with status='failed'")

    def test_issue2_load_payload_success_complete_raises_cleanup_also_raises_has_note(self):
        """Issue 2 (load_payload unit): when success complete raises and cleanup also raises,
        original exception is re-raised with a note about the cleanup failure."""
        from portfolio_engine.automation.ingestion import load_payload

        db = FakeAutomationDatabase()

        def always_raising_complete(*, ingestion_run_id, status, error_message):
            raise RuntimeError("completion failed")

        db.complete_ingestion_run = always_raising_complete  # type: ignore

        with self.assertRaises(RuntimeError) as ctx:
            load_payload(
                "<FlexQueryResponse></FlexQueryResponse>",
                database=db,
                brokerage_code="IBKR",
                account_external_id="U100",
                source_type="FLEX_WEB_SERVICE",
                source_name="test.xml",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )

        exc = ctx.exception
        self.assertIn("completion failed", str(exc))
        notes = getattr(exc, "__notes__", None) or []
        self.assertTrue(
            any("completion failed" in note for note in notes),
            f"Expected cleanup context in __notes__ but got: {notes!r}",
        )

    def test_issue2_load_payload_success_complete_raises_cleanup_succeeds_reraises_original(self):
        """Issue 2 (load_payload unit): when success complete raises but cleanup succeeds,
        original exception is still re-raised."""
        from portfolio_engine.automation.ingestion import load_payload

        db = FakeAutomationDatabase()

        def raising_on_success_only(*, ingestion_run_id, status, error_message):
            if status != "failed":
                raise RuntimeError("success complete raised")
            db.completed_ingestion_runs.append((ingestion_run_id, status, error_message))

        db.complete_ingestion_run = raising_on_success_only  # type: ignore

        with self.assertRaises(RuntimeError) as ctx:
            load_payload(
                "<FlexQueryResponse></FlexQueryResponse>",
                database=db,
                brokerage_code="IBKR",
                account_external_id="U100",
                source_type="FLEX_WEB_SERVICE",
                source_name="test.xml",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )

        self.assertIn("success complete raised", str(ctx.exception))
        # Cleanup completion succeeded and was recorded
        self.assertEqual(len(db.completed_ingestion_runs), 1)
        self.assertEqual(db.completed_ingestion_runs[0][1], "failed")


# ---------------------------------------------------------------------------
# Task 14: Per-account error isolation and parent aggregation
# ---------------------------------------------------------------------------


class FailingOneAccountAdapter(FakeAdapter):
    """Adapter that fails for U200 with a message containing a secret token."""

    def fetch_payload(self, account, request, config):
        if account.account_external_id == "U200":
            raise RuntimeError("token=secret failed")
        return super().fetch_payload(account, request, config)


class AutomationOrchestratorAccountIsolationTests(unittest.TestCase):
    """Task 14: Per-account error isolation, parent aggregation, and sanitization."""

    def _run(self, request, db, adapter=None):
        from portfolio_engine.automation.orchestrator import run_automation
        if adapter is None:
            adapter = FakeAdapter()
        return run_automation(request, database=db, adapter=adapter)

    def _make_request(self, *, mode="dry-run", account_external_ids=("U100", "U200"), **kwargs):
        from portfolio_engine.automation.types import AutomationRunRequest
        defaults = dict(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode=mode,
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
            account_external_ids=account_external_ids,
        )
        defaults.update(kwargs)
        return AutomationRunRequest(**defaults)

    def _make_account_target(self, *, account_id, external_id):
        from portfolio_engine.database import AutomationAccountTarget
        return AutomationAccountTarget(
            account_id=account_id,
            brokerage_code="IBKR",
            account_external_id=external_id,
            base_currency="USD",
            display_name=f"Account {external_id}",
        )

    def _make_two_account_db(self):
        db = FakeAutomationDatabase()
        db.account_targets = [
            self._make_account_target(account_id="acct-u100", external_id="U100"),
            self._make_account_target(account_id="acct-u200", external_id="U200"),
        ]
        return db

    # ------------------------------------------------------------------
    # Minimum test from plan: FailingOneAccountAdapter with U100/U200 dry-run
    # ------------------------------------------------------------------

    def test_account_failure_does_not_stop_other_accounts(self):
        """U200 fetch fails; U100 succeeds. Both children finalized, parent partially_succeeded.
        The failed child error_message must not contain the raw secret value.
        """
        request = self._make_request()
        db = self._make_two_account_db()

        result = self._run(request, db, adapter=FailingOneAccountAdapter())

        # Parent must be partially_succeeded (mixed success/failure)
        self.assertEqual(result.status, "partially_succeeded")

        # Both children must be finalized
        self.assertEqual(len(db.finalized_children), 2)

        # Find the failed child (U200 maps to child-2)
        finalized_by_id = {f.automation_job_account_id: f for f in db.finalized_children}
        failed_child = finalized_by_id["child-2"]
        succeeded_child = finalized_by_id["child-1"]

        self.assertEqual(failed_child.status, "failed")
        self.assertEqual(succeeded_child.status, "succeeded")

        # Error message must not leak the secret
        self.assertIsNotNone(failed_child.error_message)
        self.assertNotIn("secret", failed_child.error_message or "")

    # ------------------------------------------------------------------
    # Successful account still contributes to summary
    # ------------------------------------------------------------------

    def test_account_failure_successful_account_contributes_to_parent_summary(self):
        """When U200 fails and U100 succeeds, parent account_counts reflect 1 succeeded, 1 failed."""
        request = self._make_request()
        db = self._make_two_account_db()

        result = self._run(request, db, adapter=FailingOneAccountAdapter())

        counts = result.summary["account_counts"]
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["succeeded"], 1)
        self.assertEqual(counts["failed"], 1)

    # ------------------------------------------------------------------
    # Failed child summary: stable zero record_counts shape and error_category
    # ------------------------------------------------------------------

    def test_failed_child_summary_has_zero_record_counts_and_error_category(self):
        """Failed child (U200) must have record_counts with zero values and error_category set."""
        request = self._make_request()
        db = self._make_two_account_db()

        self._run(request, db, adapter=FailingOneAccountAdapter())

        finalized_by_id = {f.automation_job_account_id: f for f in db.finalized_children}
        failed_child = finalized_by_id["child-2"]

        summary = failed_child.summary
        self.assertIsInstance(summary, dict)
        self.assertIn("record_counts", summary)
        self.assertIn("error_category", summary)

        # All record counts must be zero
        for _rt, counts in summary["record_counts"].items():
            for key, val in counts.items():
                self.assertEqual(val, 0, f"record_counts[{_rt}][{key}] must be 0 for failed child")

    # ------------------------------------------------------------------
    # All accounts failing → parent failed
    # ------------------------------------------------------------------

    def test_all_accounts_failing_yields_parent_failed(self):
        """When all accounts fail, parent status must be failed (not partially_succeeded)."""
        request = self._make_request(account_external_ids=("U200", "U300"))
        db = FakeAutomationDatabase()
        db.account_targets = [
            self._make_account_target(account_id="acct-u200", external_id="U200"),
            self._make_account_target(account_id="acct-u300", external_id="U300"),
        ]

        class AlwaysFailAdapter(FakeAdapter):
            def fetch_payload(self, account, request, config):
                raise RuntimeError("all accounts fail")

        result = self._run(request, db, adapter=AlwaysFailAdapter())

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(db.finalized_children), 2)
        for child_fin in db.finalized_children:
            self.assertEqual(child_fin.status, "failed")

    def test_all_accounts_failing_parent_account_counts(self):
        """All-fail: parent account_counts.failed == total and succeeded == 0."""
        request = self._make_request(account_external_ids=("U200", "U300"))
        db = FakeAutomationDatabase()
        db.account_targets = [
            self._make_account_target(account_id="acct-u200", external_id="U200"),
            self._make_account_target(account_id="acct-u300", external_id="U300"),
        ]

        class AlwaysFailAdapter(FakeAdapter):
            def fetch_payload(self, account, request, config):
                raise RuntimeError("all accounts fail")

        result = self._run(request, db, adapter=AlwaysFailAdapter())

        counts = result.summary["account_counts"]
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["failed"], 2)
        self.assertEqual(counts["succeeded"], 0)

    # ------------------------------------------------------------------
    # Load mode: one account-level load failure, one success → partially_succeeded
    # ------------------------------------------------------------------

    def test_load_mode_one_account_fetch_fails_one_succeeds_partially_succeeded(self):
        """Load mode: U200 fetch fails, U100 succeeds → parent partially_succeeded; both children finalized."""
        request = self._make_request(mode="load")
        db = self._make_two_account_db()

        result = self._run(request, db, adapter=FailingOneAccountAdapter())

        self.assertEqual(result.status, "partially_succeeded")
        self.assertEqual(len(db.finalized_children), 2)

        finalized_by_id = {f.automation_job_account_id: f for f in db.finalized_children}
        self.assertEqual(finalized_by_id["child-1"].status, "succeeded")
        self.assertEqual(finalized_by_id["child-2"].status, "failed")

    def test_load_mode_all_accounts_fail_parent_failed(self):
        """Load mode: all accounts fail → parent failed."""
        request = self._make_request(mode="load")
        db = self._make_two_account_db()

        class AlwaysFailAdapter(FakeAdapter):
            def fetch_payload(self, account, request, config):
                raise RuntimeError("load network timeout")

        result = self._run(request, db, adapter=AlwaysFailAdapter())

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(db.finalized_children), 2)

    # ------------------------------------------------------------------
    # Sanitization: various sensitive patterns in error messages
    # ------------------------------------------------------------------

    def test_sanitization_redacts_token_assignment_in_child_error(self):
        """token=<value> in fetch exception message is redacted in child error_message."""
        request = self._make_request(account_external_ids=("U200",))
        db = FakeAutomationDatabase()
        db.account_targets = [self._make_account_target(account_id="acct-u200", external_id="U200")]

        result = self._run(request, db, adapter=FailingOneAccountAdapter())

        child_fin = db.finalized_children[0]
        self.assertIsNotNone(child_fin.error_message)
        # The secret value must have been redacted.
        self.assertNotIn("secret", child_fin.error_message or "")

    def test_sanitization_redacts_password_in_child_error(self):
        """password=<value> in fetch exception message is redacted in child error_message."""
        request = self._make_request(account_external_ids=("U100",))
        db = FakeAutomationDatabase()
        db.account_targets = [self._make_account_target(account_id="acct-u100", external_id="U100")]

        class PasswordLeakAdapter(FakeAdapter):
            def fetch_payload(self, account, request, config):
                raise RuntimeError("authentication failed: password=hunter2")

        result = self._run(request, db, adapter=PasswordLeakAdapter())

        child_fin = db.finalized_children[0]
        self.assertIsNotNone(child_fin.error_message)
        self.assertNotIn("hunter2", child_fin.error_message or "")

    def test_sanitization_redacts_database_url_in_child_error(self):
        """postgresql:// connection strings in fetch exception are redacted in child error_message."""
        request = self._make_request(account_external_ids=("U100",))
        db = FakeAutomationDatabase()
        db.account_targets = [self._make_account_target(account_id="acct-u100", external_id="U100")]

        class DbUrlLeakAdapter(FakeAdapter):
            def fetch_payload(self, account, request, config):
                raise RuntimeError("connect failed: postgresql://user:pass@host:5432/db")

        result = self._run(request, db, adapter=DbUrlLeakAdapter())

        child_fin = db.finalized_children[0]
        self.assertIsNotNone(child_fin.error_message)
        self.assertNotIn("postgresql://", child_fin.error_message or "")
        self.assertNotIn("pass", child_fin.error_message or "")

    # ------------------------------------------------------------------
    # Precise contract: failed child error_category value
    # ------------------------------------------------------------------

    def test_failed_child_error_category_is_fetch_or_parse_error(self):
        """Failed child (U200) summary error_category must be 'fetch_or_parse_error' (not a generic value).
        This test would fail if the error_category key were missing or had a wrong value.
        """
        request = self._make_request()
        db = self._make_two_account_db()

        self._run(request, db, adapter=FailingOneAccountAdapter())

        finalized_by_id = {f.automation_job_account_id: f for f in db.finalized_children}
        failed_child = finalized_by_id["child-2"]
        self.assertEqual(failed_child.summary.get("error_category"), "fetch_or_parse_error")

    def test_succeeded_child_has_no_error_category(self):
        """Succeeded child (U100) summary must not have an error_category key."""
        request = self._make_request()
        db = self._make_two_account_db()

        self._run(request, db, adapter=FailingOneAccountAdapter())

        finalized_by_id = {f.automation_job_account_id: f for f in db.finalized_children}
        succeeded_child = finalized_by_id["child-1"]
        self.assertNotIn("error_category", succeeded_child.summary)


# ---------------------------------------------------------------------------
# Task 15: Overlap detection and load blocking
# ---------------------------------------------------------------------------


class AutomationOrchestratorOverlapTests(unittest.TestCase):
    """Task 15: Overlapping load detection, blocking, and isolation."""

    def _run(self, request, db, adapter=None):
        from portfolio_engine.automation.orchestrator import run_automation
        if adapter is None:
            adapter = FakeAdapter()
        return run_automation(request, database=db, adapter=adapter)

    def _make_load_request(self, **kwargs):
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

    def _make_dry_run_request(self, **kwargs):
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

    def test_overlapping_load_marks_child_failed(self):
        """Load request with overlapping_load=True: result.status failed, child finalized failed."""
        request = self._make_load_request()
        db = self._make_db_with_accounts(self._make_account_target())
        db.overlapping_load = True

        result = self._run(request, db)

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(db.finalized_children), 1)
        self.assertEqual(db.finalized_children[0].status, "failed")

    def test_overlapping_load_error_message_contains_category(self):
        """Overlap failure error_message on child must contain 'overlapping_load_job'."""
        request = self._make_load_request()
        db = self._make_db_with_accounts(self._make_account_target())
        db.overlapping_load = True

        self._run(request, db)

        child_fin = db.finalized_children[0]
        self.assertIsNotNone(child_fin.error_message)
        self.assertIn("overlapping_load_job", child_fin.error_message)

    def test_overlapping_load_does_not_call_fetch_payload(self):
        """When overlap is detected, fetch_payload must not be called for that account."""
        request = self._make_load_request()
        db = self._make_db_with_accounts(self._make_account_target())
        db.overlapping_load = True

        fetch_calls = []

        class TrackingAdapter(FakeAdapter):
            def fetch_payload(self, account, req, config):
                fetch_calls.append(account)
                return super().fetch_payload(account, req, config)

        self._run(request, db, adapter=TrackingAdapter())

        self.assertEqual(len(fetch_calls), 0, "fetch_payload must not be called when overlap is detected")

    def test_dry_run_does_not_call_has_overlapping_automation_load(self):
        """Dry-run mode must never call has_overlapping_automation_load."""
        request = self._make_dry_run_request()
        db = self._make_db_with_accounts(self._make_account_target())

        self._run(request, db)

        self.assertEqual(len(db.overlap_check_calls), 0, "dry-run must not check for overlap")

    def test_load_calls_overlap_check_with_resolved_account_id(self):
        """Overlap check must receive the resolved account_id (UUID), not the external id."""
        request = self._make_load_request()
        db = self._make_db_with_accounts(
            self._make_account_target(account_id="resolved-uuid", external_id="U100")
        )

        self._run(request, db)

        self.assertEqual(len(db.overlap_check_calls), 1)
        self.assertEqual(db.overlap_check_calls[0]["account_id"], "resolved-uuid")

    def test_load_calls_overlap_check_before_fetch_payload_when_no_overlap(self):
        """When overlap=False, overlap check runs before fetch; fetch is called exactly once."""
        request = self._make_load_request()
        db = self._make_db_with_accounts(self._make_account_target())

        event_log = []

        class TrackingAdapter(FakeAdapter):
            def fetch_payload(self, account, req, config):
                event_log.append("fetch")
                return super().fetch_payload(account, req, config)

        original_overlap = db.has_overlapping_automation_load

        def tracking_overlap(**kwargs):
            event_log.append("overlap_check")
            return original_overlap(**kwargs)

        db.has_overlapping_automation_load = tracking_overlap

        self._run(request, db, adapter=TrackingAdapter())

        self.assertIn("overlap_check", event_log)
        self.assertIn("fetch", event_log)
        self.assertLess(event_log.index("overlap_check"), event_log.index("fetch"))

    def test_mixed_overlap_one_blocked_one_succeeds_partially_succeeded(self):
        """Two accounts: first overlaps (blocked), second succeeds → partially_succeeded."""
        request = self._make_load_request(account_external_ids=("U100", "U200"))
        db = self._make_db_with_accounts(
            self._make_account_target(account_id="acct-1", external_id="U100"),
            self._make_account_target(account_id="acct-2", external_id="U200"),
        )

        call_count = [0]
        original_overlap = db.has_overlapping_automation_load

        def first_overlaps(**kwargs):
            call_count[0] += 1
            return call_count[0] == 1

        db.has_overlapping_automation_load = first_overlaps

        result = self._run(request, db)

        self.assertEqual(result.status, "partially_succeeded")
        self.assertEqual(len(db.finalized_children), 2)
        finalized_by_id = {f.automation_job_account_id: f for f in db.finalized_children}
        self.assertEqual(finalized_by_id["child-1"].status, "failed")
        self.assertEqual(finalized_by_id["child-2"].status, "succeeded")

    def test_overlapping_load_parent_finalized_failed_when_only_account(self):
        """Single account with overlap → parent finalized as failed."""
        request = self._make_load_request()
        db = self._make_db_with_accounts(self._make_account_target())
        db.overlapping_load = True

        self._run(request, db)

        self.assertEqual(len(db.finalized_jobs), 1)
        self.assertEqual(db.finalized_jobs[0].status, "failed")

    def test_overlapping_load_child_summary_is_privacy_safe(self):
        """Overlap failure child summary must have record_counts (privacy-safe shape)."""
        request = self._make_load_request()
        db = self._make_db_with_accounts(self._make_account_target())
        db.overlapping_load = True

        self._run(request, db)

        child_fin = db.finalized_children[0]
        self.assertIsNotNone(child_fin.summary)
        self.assertIn("record_counts", child_fin.summary)

    # ------------------------------------------------------------------
    # Issue 1 fix: orchestrator must pass exclude_automation_job_id=job_id
    # ------------------------------------------------------------------

    def test_load_passes_job_id_as_exclude_automation_job_id_to_overlap_check(self):
        """Orchestrator must pass exclude_automation_job_id matching the current job_id."""
        request = self._make_load_request()
        db = self._make_db_with_accounts(self._make_account_target())

        self._run(request, db)

        self.assertEqual(len(db.overlap_check_calls), 1)
        call = db.overlap_check_calls[0]
        self.assertIn("exclude_automation_job_id", call)
        self.assertEqual(call["exclude_automation_job_id"], "job-uuid")

    # ------------------------------------------------------------------
    # Issue 2 fix: overlapping load child must have error_category=overlapping_load_job
    # ------------------------------------------------------------------

    def test_overlapping_load_child_summary_has_overlapping_load_job_error_category(self):
        """Overlap failure child summary error_category must be 'overlapping_load_job', not 'fetch_or_parse_error'."""
        request = self._make_load_request()
        db = self._make_db_with_accounts(self._make_account_target())
        db.overlapping_load = True

        self._run(request, db)

        child_fin = db.finalized_children[0]
        self.assertIsNotNone(child_fin.summary)
        summary = child_fin.summary
        self.assertIn("error_category", summary)
        self.assertEqual(summary["error_category"], "overlapping_load_job")
        self.assertNotEqual(summary.get("error_category"), "fetch_or_parse_error")


# ---------------------------------------------------------------------------
# Final review Issue 1: Portfolio target must resolve portfolio_id before job creation
# ---------------------------------------------------------------------------


class PortfolioJobPortfolioIdResolutionTests(unittest.TestCase):
    """Tests for Issue 1: portfolio jobs must have portfolio_id resolved before parent job creation."""

    def _run(self, request, db, adapter=None):
        from portfolio_engine.automation.orchestrator import run_automation
        if adapter is None:
            adapter = FakeAdapter()
        return run_automation(request, database=db, adapter=adapter)

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

    def _make_account_target(self, *, account_id="account-uuid", external_id="U100"):
        from portfolio_engine.database import AutomationAccountTarget
        return AutomationAccountTarget(
            account_id=account_id,
            brokerage_code="IBKR",
            account_external_id=external_id,
            base_currency="USD",
            display_name="Main",
        )

    def test_portfolio_job_creates_parent_with_non_null_portfolio_id(self):
        """Portfolio target job must have portfolio_id set on the created parent row."""
        request = self._make_portfolio_request()
        db = FakeAutomationDatabase()
        db.portfolio_id_by_name["MyPortfolio"] = "resolved-portfolio-uuid"
        db.portfolio_accounts = [self._make_account_target(account_id="port-acct")]

        self._run(request, db)

        self.assertEqual(len(db.created_jobs), 1)
        job = db.created_jobs[0]
        self.assertIsNotNone(job.portfolio_id, "portfolio_id must not be None for portfolio target job")

    def test_portfolio_job_portfolio_id_matches_resolved_id(self):
        """portfolio_id on the created parent job must match the id returned by get_portfolio_id_by_name."""
        request = self._make_portfolio_request()
        db = FakeAutomationDatabase()
        db.portfolio_id_by_name["MyPortfolio"] = "resolved-portfolio-uuid"
        db.portfolio_accounts = [self._make_account_target()]

        self._run(request, db)

        self.assertEqual(len(db.created_jobs), 1)
        self.assertEqual(db.created_jobs[0].portfolio_id, "resolved-portfolio-uuid")

    def test_portfolio_id_looked_up_before_job_creation(self):
        """get_portfolio_id_by_name must be called before create_automation_job."""
        request = self._make_portfolio_request()
        db = FakeAutomationDatabase()
        db.portfolio_id_by_name["MyPortfolio"] = "resolved-portfolio-uuid"
        db.portfolio_accounts = [self._make_account_target()]

        self._run(request, db)

        self.assertEqual(len(db.portfolio_id_lookup_calls), 1)
        self.assertEqual(db.portfolio_id_lookup_calls[0], "MyPortfolio")
        # Verify ordering: lookup_portfolio must appear before create_job in the event log
        lookup_idx = db._event_log.index("lookup_portfolio")
        create_idx = db._event_log.index("create_job")
        self.assertLess(lookup_idx, create_idx, "portfolio lookup must occur before job creation")

    def test_portfolio_unknown_portfolio_raises_before_job_creation(self):
        """When portfolio is not found by name, the error must occur before any parent job is created."""
        request = self._make_portfolio_request()
        db = FakeAutomationDatabase()
        # portfolio_id_by_name is empty — portfolio "MyPortfolio" not found

        with self.assertRaises(Exception):
            self._run(request, db)

        self.assertEqual(len(db.created_jobs), 0, "no job must be created when portfolio not found")

    def test_portfolio_unknown_portfolio_raises_validation_error(self):
        """Unknown portfolio name raises AutomationValidationError or ValueError before job creation."""
        from portfolio_engine.automation.targets import AutomationValidationError
        request = self._make_portfolio_request(portfolio_name="NonExistentPortfolio")
        db = FakeAutomationDatabase()
        # portfolio_id_by_name is empty — portfolio not found

        with self.assertRaises((AutomationValidationError, ValueError)) as ctx:
            self._run(request, db)

        self.assertIn("NonExistentPortfolio", str(ctx.exception))

    def test_accounts_job_has_null_portfolio_id(self):
        """Accounts target job must still have portfolio_id=None (existing behavior preserved)."""
        from portfolio_engine.database import AutomationAccountTarget
        request = self._make_accounts_request()
        db = FakeAutomationDatabase()
        db.account_targets = [
            AutomationAccountTarget(
                account_id="acct-uuid",
                brokerage_code="IBKR",
                account_external_id="U100",
                base_currency="USD",
                display_name="Main",
            )
        ]

        self._run(request, db)

        self.assertEqual(len(db.created_jobs), 1)
        self.assertIsNone(db.created_jobs[0].portfolio_id)

    def test_fake_db_enforces_portfolio_id_non_null_for_portfolio_jobs(self):
        """FakeAutomationDatabase constraint: portfolio job with portfolio_id=None raises ValueError."""
        from portfolio_engine.database import AutomationJobStart
        db = FakeAutomationDatabase()
        bad_request = AutomationJobStart(
            trigger_type="manual",
            target_type="portfolio",
            portfolio_id=None,
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
        )
        with self.assertRaises(ValueError):
            db.create_automation_job(bad_request)

    def test_fake_db_enforces_portfolio_id_null_for_accounts_jobs(self):
        """FakeAutomationDatabase constraint: accounts job with portfolio_id set raises ValueError."""
        from portfolio_engine.database import AutomationJobStart
        db = FakeAutomationDatabase()
        bad_request = AutomationJobStart(
            trigger_type="manual",
            target_type="accounts",
            portfolio_id="some-uuid",
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
        )
        with self.assertRaises(ValueError):
            db.create_automation_job(bad_request)

    def test_portfolio_job_get_portfolio_id_called_with_correct_name(self):
        """get_portfolio_id_by_name must be called with the portfolio_name from the request."""
        request = self._make_portfolio_request(portfolio_name="SpecificPortfolio")
        db = FakeAutomationDatabase()
        db.portfolio_id_by_name["SpecificPortfolio"] = "specific-portfolio-uuid"
        db.portfolio_accounts = [self._make_account_target()]

        self._run(request, db)

        self.assertEqual(len(db.portfolio_id_lookup_calls), 1)
        self.assertEqual(db.portfolio_id_lookup_calls[0], "SpecificPortfolio")

    def test_portfolio_job_resolves_accounts_after_portfolio_id_lookup(self):
        """Portfolio account resolution must still happen after portfolio_id is resolved."""
        request = self._make_portfolio_request()
        db = FakeAutomationDatabase()
        db.portfolio_id_by_name["MyPortfolio"] = "portfolio-uuid"
        db.portfolio_accounts = [self._make_account_target(account_id="port-acct")]

        self._run(request, db)

        self.assertEqual(len(db.connection_resolve_calls), 1)
        self.assertEqual(len(db.added_accounts), 1)


# ---------------------------------------------------------------------------
# Final review Issue 2: Preflight failure must finalize children before parent
# ---------------------------------------------------------------------------


class PreflightFailureChildFinalizationTests(unittest.TestCase):
    """Tests for Issue 2: children must be finalized as failed when preflight validation fails."""

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

    class _FailPreflight(FakeAdapter):
        def preflight_validate_config(self, config) -> None:
            raise RuntimeError("missing required environment variables: SUPERFOLIO_CREDENTIAL_MASTER_KEY")

    def test_preflight_failure_finalizes_single_child_as_failed(self):
        """Preflight failure with one child: child must be finalized as failed (not left pending)."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        self._run(request, db, adapter=self._FailPreflight())

        self.assertEqual(len(db.finalized_children), 1)
        self.assertEqual(db.finalized_children[0].status, "failed")

    def test_preflight_failure_finalizes_all_children_when_multiple(self):
        """Preflight failure with two children: both must be finalized as failed."""
        request = self._make_request(account_external_ids=("U100", "U200"))
        db = self._make_db_with_accounts(
            self._make_account_target(account_id="acct-1", external_id="U100"),
            self._make_account_target(account_id="acct-2", external_id="U200"),
        )

        self._run(request, db, adapter=self._FailPreflight())

        self.assertEqual(len(db.finalized_children), 2)
        for child in db.finalized_children:
            self.assertEqual(child.status, "failed")

    def test_preflight_failure_no_pending_child_remains(self):
        """After preflight failure, no child added via add_automation_job_account remains unfinalized."""
        request = self._make_request(account_external_ids=("U100", "U200"))
        db = self._make_db_with_accounts(
            self._make_account_target(account_id="acct-1", external_id="U100"),
            self._make_account_target(account_id="acct-2", external_id="U200"),
        )

        self._run(request, db, adapter=self._FailPreflight())

        added_child_ids = {cid for cid, _ in db.added_accounts}
        finalized_child_ids = {f.automation_job_account_id for f in db.finalized_children}
        self.assertEqual(added_child_ids, finalized_child_ids,
                         "Every added child must be finalized after preflight failure")

    def test_preflight_failure_child_error_category_is_preflight_failed(self):
        """Child summary error_category on preflight failure must be 'preflight_failed'."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        self._run(request, db, adapter=self._FailPreflight())

        child_fin = db.finalized_children[0]
        self.assertIsNotNone(child_fin.summary)
        self.assertIn("error_category", child_fin.summary)
        self.assertEqual(child_fin.summary["error_category"], "preflight_failed")

    def test_preflight_failure_child_summary_has_record_counts(self):
        """Child summary on preflight failure must have record_counts (privacy-safe shape)."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        self._run(request, db, adapter=self._FailPreflight())

        child_fin = db.finalized_children[0]
        self.assertIsNotNone(child_fin.summary)
        self.assertIn("record_counts", child_fin.summary)

    def test_preflight_failure_child_has_sanitized_error_message(self):
        """Child error_message on preflight failure must be sanitized (no raw secrets)."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        class FailPreflightWithSecret(FakeAdapter):
            def preflight_validate_config(self, config) -> None:
                raise RuntimeError("token=supersecret postgresql://user:pass@host/db")

        self._run(request, db, adapter=FailPreflightWithSecret())

        child_fin = db.finalized_children[0]
        self.assertIsNotNone(child_fin.error_message)
        self.assertNotIn("supersecret", child_fin.error_message or "")
        self.assertNotIn("postgresql://", child_fin.error_message or "")

    def test_preflight_failure_parent_summary_reflects_all_children_failed(self):
        """Parent summary account_counts must reflect all children failed when preflight fails."""
        request = self._make_request(account_external_ids=("U100", "U200"))
        db = self._make_db_with_accounts(
            self._make_account_target(account_id="acct-1", external_id="U100"),
            self._make_account_target(account_id="acct-2", external_id="U200"),
        )

        self._run(request, db, adapter=self._FailPreflight())

        self.assertEqual(len(db.finalized_jobs), 1)
        parent = db.finalized_jobs[0]
        self.assertIsNotNone(parent.summary)
        counts = parent.summary["account_counts"]
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["failed"], 2)
        self.assertEqual(counts["succeeded"], 0)

    def test_preflight_failure_parent_status_is_failed(self):
        """Parent status must be 'failed' when preflight fails."""
        request = self._make_request(account_external_ids=("U100", "U200"))
        db = self._make_db_with_accounts(
            self._make_account_target(account_id="acct-1", external_id="U100"),
            self._make_account_target(account_id="acct-2", external_id="U200"),
        )

        self._run(request, db, adapter=self._FailPreflight())

        self.assertEqual(db.finalized_jobs[0].status, "failed")

    def test_preflight_failure_children_finalized_before_parent(self):
        """All child finalizations must occur before the parent finalization in event log."""
        request = self._make_request(account_external_ids=("U100", "U200"))
        db = self._make_db_with_accounts(
            self._make_account_target(account_id="acct-1", external_id="U100"),
            self._make_account_target(account_id="acct-2", external_id="U200"),
        )

        self._run(request, db, adapter=self._FailPreflight())

        log = db._event_log
        parent_finalize_idx = [i for i, e in enumerate(log) if e == "finalize_job"]
        child_finalize_indices = [i for i, e in enumerate(log) if e.startswith("finalize_child:")]

        self.assertEqual(len(parent_finalize_idx), 1)
        self.assertEqual(len(child_finalize_indices), 2)
        parent_idx = parent_finalize_idx[0]
        for child_idx in child_finalize_indices:
            self.assertLess(child_idx, parent_idx,
                            "child finalization must occur before parent finalization")

    def test_preflight_failure_result_has_child_ids(self):
        """AutomationRunResult.automation_job_account_ids must include child ids even on preflight failure."""
        request = self._make_request()
        db = self._make_db_with_accounts(self._make_account_target())

        result = self._run(request, db, adapter=self._FailPreflight())

        self.assertIn("child-1", result.automation_job_account_ids)

class AdapterContextTests(unittest.TestCase):
    def test_secret_value_is_redacted_in_adapter_context(self) -> None:
        from portfolio_engine.automation.types import IntegrationConnectionContext
        from portfolio_engine.automation.credentials import SecretValue

        secret = SecretValue("plain")
        context = IntegrationConnectionContext(
            connection_id="connection-uuid",
            integration_key="ibkr_flex_ws",
            brokerage_code="IBKR",
            name="IBKR Personal",
            credentials={"flex_token": secret},
        )

        self.assertEqual(str(context.credentials["flex_token"]), "<redacted>")
        self.assertEqual(context.credentials["flex_token"].reveal(), "plain")

    def test_ibkr_adapter_preflight_requires_token_and_feed_query_ids(self) -> None:
        from portfolio_engine.automation.adapters import IbkrFlexWebServiceAdapter
        from portfolio_engine.automation.types import IntegrationConnectionContext, IntegrationFeedContext

        adapter = IbkrFlexWebServiceAdapter()
        connection = IntegrationConnectionContext(
            connection_id="connection-uuid",
            integration_key="ibkr_flex_ws",
            brokerage_code="IBKR",
            name="IBKR Personal",
            credentials={},
        )
        feed = IntegrationFeedContext(
            feed_id="feed-uuid",
            feed_key="daily",
            display_name="Daily",
            secrets={},
        )

        with self.assertRaisesRegex(RuntimeError, "missing_connection_credential"):
            adapter.preflight_connection(connection, (feed,))

    def test_ibkr_adapter_preflight_passes_when_token_and_query_id_present(self) -> None:
        from portfolio_engine.automation.adapters import IbkrFlexWebServiceAdapter
        from portfolio_engine.automation.types import IntegrationConnectionContext, IntegrationFeedContext
        from portfolio_engine.automation.credentials import SecretValue

        adapter = IbkrFlexWebServiceAdapter()
        connection = IntegrationConnectionContext(
            connection_id="connection-uuid",
            integration_key="ibkr_flex_ws",
            brokerage_code="IBKR",
            name="IBKR Personal",
            credentials={"flex_token": SecretValue("tok123")},
        )
        feed = IntegrationFeedContext(
            feed_id="feed-uuid",
            feed_key="daily",
            display_name="Daily",
            secrets={"query_id": SecretValue("987654")},
        )

        # Should not raise
        adapter.preflight_connection(connection, (feed,))

    def test_ibkr_adapter_preflight_missing_feed_query_id_raises_missing_feed_secret(self) -> None:
        from portfolio_engine.automation.adapters import IbkrFlexWebServiceAdapter
        from portfolio_engine.automation.types import IntegrationConnectionContext, IntegrationFeedContext
        from portfolio_engine.automation.credentials import SecretValue

        adapter = IbkrFlexWebServiceAdapter()
        connection = IntegrationConnectionContext(
            connection_id="connection-uuid",
            integration_key="ibkr_flex_ws",
            brokerage_code="IBKR",
            name="IBKR Personal",
            credentials={"flex_token": SecretValue("tok123")},
        )
        feed = IntegrationFeedContext(
            feed_id="feed-uuid",
            feed_key="daily",
            display_name="Daily",
            secrets={},
        )

        with self.assertRaisesRegex(RuntimeError, "missing_feed_secret"):
            adapter.preflight_connection(connection, (feed,))

    def test_ibkr_adapter_fetch_feed_payload_error_does_not_leak_secrets(self) -> None:
        from portfolio_engine.automation.adapters import IbkrFlexWebServiceAdapter
        from portfolio_engine.automation.fetch_errors import BrokerFetchError
        from portfolio_engine.automation.types import AutomationRunRequest, IntegrationConnectionContext, IntegrationFeedContext
        from portfolio_engine.automation.credentials import SecretValue
        from datetime import date

        class FailingClient:
            def fetch_report(self, *, token, query_id, connection_id="connection", feed_key="feed"):
                raise BrokerFetchError("ibkr_auth_failed", "ibkr_auth_failed")

        adapter = IbkrFlexWebServiceAdapter(client=FailingClient())
        connection = IntegrationConnectionContext(
            connection_id="connection-uuid",
            integration_key="ibkr_flex_ws",
            brokerage_code="IBKR",
            name="IBKR Personal",
            credentials={"flex_token": SecretValue("supersecrettoken")},
        )
        feed = IntegrationFeedContext(
            feed_id="feed-uuid",
            feed_key="daily",
            display_name="Daily",
            secrets={"query_id": SecretValue("myprivatequery")},
        )
        request = AutomationRunRequest(
            target_type="portfolio",
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
        )

        with self.assertRaises(BrokerFetchError) as ctx:
            adapter.fetch_feed_payload(connection, feed, request)

        error_msg = str(ctx.exception)
        self.assertNotIn("supersecrettoken", error_msg)
        self.assertNotIn("myprivatequery", error_msg)

    def test_connection_context_credentials_are_immutable(self) -> None:
        from portfolio_engine.automation.types import IntegrationConnectionContext
        from portfolio_engine.automation.credentials import SecretValue

        context = IntegrationConnectionContext(
            connection_id="c1",
            integration_key="ibkr_flex_ws",
            brokerage_code="IBKR",
            name="Test",
            credentials={"flex_token": SecretValue("tok")},
        )

        with self.assertRaises(TypeError):
            context.credentials["flex_token"] = SecretValue("newvalue")  # type: ignore[index]

    def test_feed_context_secrets_are_immutable(self) -> None:
        from portfolio_engine.automation.types import IntegrationFeedContext
        from portfolio_engine.automation.credentials import SecretValue

        feed = IntegrationFeedContext(
            feed_id="f1",
            feed_key="daily",
            display_name="Daily",
            secrets={"query_id": SecretValue("qid")},
        )

        with self.assertRaises(TypeError):
            feed.secrets["query_id"] = SecretValue("newvalue")  # type: ignore[index]

    def test_connection_context_is_not_hashable(self) -> None:
        from portfolio_engine.automation.types import IntegrationConnectionContext

        context = IntegrationConnectionContext(
            connection_id="c1",
            integration_key="ibkr_flex_ws",
            brokerage_code="IBKR",
            name="Test",
            credentials={},
        )

        with self.assertRaises(TypeError):
            hash(context)

    def test_feed_context_is_not_hashable(self) -> None:
        from portfolio_engine.automation.types import IntegrationFeedContext

        feed = IntegrationFeedContext(
            feed_id="f1",
            feed_key="daily",
            display_name="Daily",
            secrets={},
        )

        with self.assertRaises(TypeError):
            hash(feed)

    def test_broker_adapter_protocol_fetch_feed_payload_body_is_ellipsis(self) -> None:
        """Protocol method body must be ... (not a docstring-only stub that returns None)."""
        import inspect
        from portfolio_engine.automation.types import BrokerAdapter

        src = inspect.getsource(BrokerAdapter.fetch_feed_payload)
        self.assertIn("...", src, "fetch_feed_payload protocol body must use ellipsis")

    def test_broker_adapter_protocol_preflight_connection_body_is_ellipsis(self) -> None:
        """Protocol method body must be ... (not a docstring-only stub that returns None)."""
        import inspect
        from portfolio_engine.automation.types import BrokerAdapter

        src = inspect.getsource(BrokerAdapter.preflight_connection)
        self.assertIn("...", src, "preflight_connection protocol body must use ellipsis")


# ---------------------------------------------------------------------------
# Task 10: Connection-aware target resolution and child snapshotting
# ---------------------------------------------------------------------------

SAMPLE_XML = "<FlexQueryResponse></FlexQueryResponse>"


def _make_connection_target(
    account_id: str,
    account_external_id: str,
    *,
    connection_id: str | None,
    brokerage_code: str = "IBKR",
    base_currency: str = "USD",
    display_name: str | None = None,
    connection_name: str | None = None,
):
    from portfolio_engine.database import AutomationConnectionTarget
    return AutomationConnectionTarget(
        account_id=account_id,
        brokerage_code=brokerage_code,
        account_external_id=account_external_id,
        base_currency=base_currency,
        display_name=display_name or account_external_id,
        connection_id=connection_id,
        connection_name=connection_name,
    )


def _make_portfolio_run_request(**kwargs):
    from portfolio_engine.automation.types import AutomationRunRequest
    defaults = dict(
        target_type="portfolio",
        integration_key="ibkr_flex_ws",
        mode="dry-run",
        requested_start_date=date(2024, 1, 1),
        requested_end_date=date(2024, 1, 31),
        portfolio_name="All Accounts",
    )
    defaults.update(kwargs)
    return AutomationRunRequest(**defaults)


def _make_accounts_run_request(**kwargs):
    from portfolio_engine.automation.types import AutomationRunRequest
    defaults = dict(
        target_type="accounts",
        integration_key="ibkr_flex_ws",
        mode="dry-run",
        requested_start_date=date(2024, 1, 1),
        requested_end_date=date(2024, 1, 31),
        account_external_ids=("U100", "U200"),
    )
    defaults.update(kwargs)
    return AutomationRunRequest(**defaults)


class FakeConnectionAdapter:
    """Adapter that tracks which account IDs were fetched and returns canned XML."""

    def __init__(self, *, payload_by_feed=None, preflight_connection_error=None):
        self.payload_by_feed = payload_by_feed or {}
        self.fetched_account_ids: list[str] = []
        self.preflight_connection_calls: list = []
        self._preflight_connection_error = preflight_connection_error

    def preflight_validate_config(self, config) -> None:
        return None

    def preflight_connection(self, connection, feeds) -> None:
        self.preflight_connection_calls.append((connection, feeds))
        if self._preflight_connection_error is not None:
            raise self._preflight_connection_error

    def fetch_payload(self, account, request, config):
        from portfolio_engine.automation.types import BrokerPayload
        self.fetched_account_ids.append(account.account_id)
        xml = self.payload_by_feed.get("daily", SAMPLE_XML)
        return BrokerPayload(xml_text=xml, source_name="fake-connection.xml")


class ConnectionAssignmentOrchestratorTests(unittest.TestCase):
    """Tests for Task 10: connection-aware target resolution and missing-assignment handling."""

    def _run(self, request, db, adapter=None):
        from portfolio_engine.automation.orchestrator import run_automation
        if adapter is None:
            adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})
        # Populate default credentials for all connection IDs in connection_targets
        # so credential loading does not interfere with Task 10 connection-assignment tests.
        if db.connection_targets:
            connection_ids = {
                t.connection_id
                for t in db.connection_targets
                if t.connection_id is not None
            }
            for cid in connection_ids:
                if cid not in db.connection_credentials:
                    from cryptography.fernet import Fernet
                    f = Fernet(_TEST_MASTER_KEY.encode())
                    db.connection_credentials[cid] = {
                        "flex_token": f.encrypt(b"test-token"),
                    }
                if cid not in db.connection_feeds:
                    db.connection_feeds[cid] = []
        with mock.patch.dict(os.environ, {"SUPERFOLIO_CREDENTIAL_MASTER_KEY": _TEST_MASTER_KEY}):
            return run_automation(request, database=db, adapter=adapter)

    def _find_child(self, db, child_id: str):
        """Return the finalized child row matching the given child_id."""
        for f in db.finalized_children:
            if f.automation_job_account_id == child_id:
                return f
        return None

    def test_missing_connection_assignment_fails_child_and_continues(self) -> None:
        """Account with connection_id=None is finalized as failed; account with connection
        is still executed and fetched."""
        db = FakeAutomationDatabase()
        db.portfolio_id_by_name["All Accounts"] = "portfolio-uuid"
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id="connection-1"),
            _make_connection_target("account-2", "U200", connection_id=None),
        ]
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        result = self._run(_make_portfolio_run_request(), db=db, adapter=adapter)

        self.assertEqual(result.status, "partially_succeeded")
        # Child-2 (account-2) must be finalized with missing_integration_connection
        child_2 = self._find_child(db, "child-2")
        self.assertIsNotNone(child_2)
        self.assertEqual(child_2.summary["error_category"], "missing_integration_connection")
        self.assertEqual(child_2.status, "failed")
        # Account-1 must still have been fetched
        self.assertIn("account-1", adapter.fetched_account_ids)

    def test_missing_connection_child_is_not_fetched(self) -> None:
        """Account with connection_id=None must never be passed to adapter.fetch_payload."""
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id="connection-1"),
            _make_connection_target("account-2", "U200", connection_id=None),
        ]
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        self._run(_make_accounts_run_request(account_external_ids=("U100", "U200")), db=db, adapter=adapter)

        self.assertNotIn("account-2", adapter.fetched_account_ids)

    def test_child_row_snapshots_connection_id(self) -> None:
        """add_automation_job_account must be called with connection_id from the resolved target."""
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id="connection-abc"),
        ]
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        self._run(_make_accounts_run_request(account_external_ids=("U100",)), db=db, adapter=adapter)

        self.assertEqual(len(db.added_accounts), 1)
        _child_id, child_req = db.added_accounts[0]
        self.assertEqual(child_req.connection_id, "connection-abc")

    def test_null_connection_child_row_snapshots_none(self) -> None:
        """add_automation_job_account for a missing-connection account must pass connection_id=None."""
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id=None),
        ]

        self._run(_make_accounts_run_request(account_external_ids=("U100",)), db=db)

        self.assertEqual(len(db.added_accounts), 1)
        _child_id, child_req = db.added_accounts[0]
        self.assertIsNone(child_req.connection_id)

    def test_all_missing_connections_fails_parent(self) -> None:
        """When every resolved target has connection_id=None, parent must be finalized as failed."""
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id=None),
            _make_connection_target("account-2", "U200", connection_id=None),
        ]
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        result = self._run(
            _make_accounts_run_request(account_external_ids=("U100", "U200")),
            db=db, adapter=adapter,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(db.finalized_jobs), 1)
        self.assertEqual(db.finalized_jobs[0].status, "failed")

    def test_all_missing_connections_no_fetch_attempted(self) -> None:
        """When all targets lack connection_id, adapter.fetch_payload must never be called."""
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id=None),
        ]
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        self._run(_make_accounts_run_request(account_external_ids=("U100",)), db=db, adapter=adapter)

        self.assertEqual(len(adapter.fetched_account_ids), 0)

    def test_missing_connection_child_error_category_in_summary(self) -> None:
        """Finalized missing-connection child summary must have error_category='missing_integration_connection'."""
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id=None),
        ]

        self._run(_make_accounts_run_request(account_external_ids=("U100",)), db=db)

        child_1 = self._find_child(db, "child-1")
        self.assertIsNotNone(child_1)
        self.assertIn("error_category", child_1.summary)
        self.assertEqual(child_1.summary["error_category"], "missing_integration_connection")

    def test_assigned_and_missing_accounts_both_get_child_rows(self) -> None:
        """Both assigned and missing-connection targets must have child rows inserted."""
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id="connection-1"),
            _make_connection_target("account-2", "U200", connection_id=None),
        ]

        self._run(_make_accounts_run_request(account_external_ids=("U100", "U200")), db=db)

        self.assertEqual(len(db.added_accounts), 2)
        added_account_ids = {req.account_id for _, req in db.added_accounts}
        self.assertIn("account-1", added_account_ids)
        self.assertIn("account-2", added_account_ids)

    def test_resolve_automation_targets_with_connections_called_for_accounts(self) -> None:
        """Orchestrator must call resolve_automation_targets_with_connections for accounts target."""
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id="connection-1"),
        ]

        self._run(_make_accounts_run_request(account_external_ids=("U100",)), db=db)

        self.assertEqual(len(db.connection_resolve_calls), 1)
        call = db.connection_resolve_calls[0]
        self.assertEqual(call["brokerage_code"], "IBKR")
        self.assertIn("U100", call["account_external_ids"])

    def test_resolve_automation_targets_with_connections_called_for_portfolio(self) -> None:
        """Orchestrator must call resolve_automation_targets_with_connections for portfolio target."""
        db = FakeAutomationDatabase()
        db.portfolio_id_by_name["All Accounts"] = "portfolio-uuid"
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id="connection-1"),
        ]

        self._run(_make_portfolio_run_request(), db=db)

        self.assertEqual(len(db.connection_resolve_calls), 1)
        call = db.connection_resolve_calls[0]
        self.assertEqual(call["target_type"], "portfolio")
        self.assertEqual(call["portfolio_name"], "All Accounts")

    def test_partially_succeeded_with_mixed_connections(self) -> None:
        """One assigned (succeeds) + one missing → parent partially_succeeded, both children finalized."""
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id="connection-1"),
            _make_connection_target("account-2", "U200", connection_id=None),
        ]
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        result = self._run(
            _make_accounts_run_request(account_external_ids=("U100", "U200")),
            db=db, adapter=adapter,
        )

        self.assertEqual(result.status, "partially_succeeded")
        self.assertEqual(len(db.finalized_children), 2)
        child_statuses = {f.automation_job_account_id: f.status for f in db.finalized_children}
        self.assertEqual(child_statuses["child-1"], "succeeded")
        self.assertEqual(child_statuses["child-2"], "failed")


# ---------------------------------------------------------------------------
# Task 11: Credential loading, decryption, and per-connection error isolation
# ---------------------------------------------------------------------------

_TEST_MASTER_KEY = "NdCDktJuoy2s0j5XScl4bvkXDcXMrUvpMzixhCY0_uc="


def _encrypt_value(plaintext: str) -> bytes:
    """Encrypt a plaintext string with the test master key."""
    from cryptography.fernet import Fernet
    return Fernet(_TEST_MASTER_KEY.encode()).encrypt(plaintext.encode())


def _make_feed_record(feed_key: str, *, feed_id: str | None = None, display_name: str | None = None):
    """Create a fake IntegrationFeedRecord for tests."""
    from portfolio_engine.database import IntegrationFeedRecord
    from datetime import timezone
    from datetime import datetime
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return IntegrationFeedRecord(
        id=feed_id or f"feed-{feed_key}",
        connection_id="connection-x",
        feed_key=feed_key,
        display_name=display_name,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


class CredentialLoadingOrchestratorTests(unittest.TestCase):
    """Tests for Task 11: per-connection credential loading and decryption."""

    def _run(self, request, db, adapter=None, master_key=_TEST_MASTER_KEY):
        from portfolio_engine.automation.orchestrator import run_automation
        if adapter is None:
            adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})
        with mock.patch.dict(os.environ, {"SUPERFOLIO_CREDENTIAL_MASTER_KEY": master_key}):
            return run_automation(request, database=db, adapter=adapter)

    def _find_child(self, db, child_id: str):
        for f in db.finalized_children:
            if f.automation_job_account_id == child_id:
                return f
        return None

    def _make_db_with_two_connections(self):
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id="connection-1"),
            _make_connection_target("account-2", "U200", connection_id="connection-2"),
        ]
        # Both connections with valid credentials and feeds
        db.connection_credentials["connection-1"] = {
            "flex_token": _encrypt_value("token1"),
            "feed:daily:query_id": _encrypt_value("query1"),
        }
        db.connection_feeds["connection-1"] = [_make_feed_record("daily")]
        db.connection_credentials["connection-2"] = {
            "flex_token": _encrypt_value("token2"),
            "feed:daily:query_id": _encrypt_value("query2"),
        }
        db.connection_feeds["connection-2"] = [_make_feed_record("daily")]
        return db

    def test_credentials_loaded_and_decrypted_for_connection(self) -> None:
        """When valid credentials exist, orchestrator decrypts them and calls preflight_connection."""
        db = self._make_db_with_two_connections()
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        result = self._run(
            _make_accounts_run_request(account_external_ids=("U100", "U200")),
            db=db, adapter=adapter,
        )

        self.assertEqual(result.status, "succeeded")
        # preflight_connection must have been called once per connection
        self.assertEqual(len(adapter.preflight_connection_calls), 2)

    def test_missing_flex_token_fails_only_that_connection(self) -> None:
        """Missing flex_token credential fails only children in that connection group."""
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id="connection-1"),
            _make_connection_target("account-2", "U200", connection_id="connection-2"),
        ]
        # connection-1 has no flex_token
        db.connection_credentials["connection-1"] = {}
        db.connection_feeds["connection-1"] = [_make_feed_record("daily")]
        # connection-2 has valid credentials
        db.connection_credentials["connection-2"] = {
            "flex_token": _encrypt_value("token2"),
            "feed:daily:query_id": _encrypt_value("query2"),
        }
        db.connection_feeds["connection-2"] = [_make_feed_record("daily")]
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        result = self._run(
            _make_accounts_run_request(account_external_ids=("U100", "U200")),
            db=db, adapter=adapter,
        )

        self.assertEqual(result.status, "partially_succeeded")
        child_1 = self._find_child(db, "child-1")
        self.assertIsNotNone(child_1)
        self.assertEqual(child_1.status, "failed")
        self.assertEqual(child_1.summary["error_category"], "missing_connection_credential")
        child_2 = self._find_child(db, "child-2")
        self.assertIsNotNone(child_2)
        self.assertEqual(child_2.status, "succeeded")

    def test_missing_feed_query_id_fails_only_that_connection(self) -> None:
        """Missing feed query_id credential fails only children of that connection."""
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id="connection-1"),
            _make_connection_target("account-2", "U200", connection_id="connection-2"),
        ]
        # connection-1 has token but no feed query_id
        db.connection_credentials["connection-1"] = {
            "flex_token": _encrypt_value("token1"),
        }
        db.connection_feeds["connection-1"] = [_make_feed_record("daily")]
        # connection-2 has everything valid
        db.connection_credentials["connection-2"] = {
            "flex_token": _encrypt_value("token2"),
            "feed:daily:query_id": _encrypt_value("query2"),
        }
        db.connection_feeds["connection-2"] = [_make_feed_record("daily")]
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        result = self._run(
            _make_accounts_run_request(account_external_ids=("U100", "U200")),
            db=db, adapter=adapter,
        )

        self.assertEqual(result.status, "partially_succeeded")
        child_1 = self._find_child(db, "child-1")
        self.assertEqual(child_1.status, "failed")
        self.assertEqual(child_1.summary["error_category"], "missing_feed_secret")
        child_2 = self._find_child(db, "child-2")
        self.assertEqual(child_2.status, "succeeded")

    def test_tampered_ciphertext_fails_only_that_connection(self) -> None:
        """Bad ciphertext for a connection credential fails only that connection's children."""
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id="connection-1"),
            _make_connection_target("account-2", "U200", connection_id="connection-2"),
        ]
        # connection-1 has tampered (invalid) ciphertext
        db.connection_credentials["connection-1"] = {
            "flex_token": b"tampered-garbage-bytes",
        }
        db.connection_feeds["connection-1"] = [_make_feed_record("daily")]
        # connection-2 is fine
        db.connection_credentials["connection-2"] = {
            "flex_token": _encrypt_value("token2"),
            "feed:daily:query_id": _encrypt_value("query2"),
        }
        db.connection_feeds["connection-2"] = [_make_feed_record("daily")]
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        result = self._run(
            _make_accounts_run_request(account_external_ids=("U100", "U200")),
            db=db, adapter=adapter,
        )

        self.assertEqual(result.status, "partially_succeeded")
        child_1 = self._find_child(db, "child-1")
        self.assertEqual(child_1.status, "failed")
        self.assertEqual(child_1.summary["error_category"], "credential_decryption_failed")
        child_2 = self._find_child(db, "child-2")
        self.assertEqual(child_2.status, "succeeded")

    def test_adapter_preflight_connection_called_with_connection_context(self) -> None:
        """Orchestrator passes IntegrationConnectionContext with decrypted credentials."""
        from portfolio_engine.automation.types import IntegrationConnectionContext
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target(
                "account-1", "U100", connection_id="connection-1",
                connection_name="My IBKR Login",
            ),
        ]
        db.connection_credentials["connection-1"] = {
            "flex_token": _encrypt_value("mytoken"),
            "feed:daily:query_id": _encrypt_value("myquery"),
        }
        db.connection_feeds["connection-1"] = [_make_feed_record("daily")]
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        self._run(
            _make_accounts_run_request(account_external_ids=("U100",)),
            db=db, adapter=adapter,
        )

        self.assertEqual(len(adapter.preflight_connection_calls), 1)
        connection_ctx, feeds = adapter.preflight_connection_calls[0]
        self.assertIsInstance(connection_ctx, IntegrationConnectionContext)
        self.assertEqual(connection_ctx.connection_id, "connection-1")
        self.assertIn("flex_token", connection_ctx.credentials)
        self.assertEqual(connection_ctx.credentials["flex_token"].reveal(), "mytoken")

    def test_adapter_preflight_connection_called_with_feed_contexts(self) -> None:
        """Orchestrator passes IntegrationFeedContext with decrypted query_id secret."""
        from portfolio_engine.automation.types import IntegrationFeedContext
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id="connection-1"),
        ]
        db.connection_credentials["connection-1"] = {
            "flex_token": _encrypt_value("mytoken"),
            "feed:daily:query_id": _encrypt_value("myquery"),
        }
        db.connection_feeds["connection-1"] = [_make_feed_record("daily", feed_id="feed-uuid-1")]
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        self._run(
            _make_accounts_run_request(account_external_ids=("U100",)),
            db=db, adapter=adapter,
        )

        _, feeds = adapter.preflight_connection_calls[0]
        self.assertEqual(len(feeds), 1)
        self.assertIsInstance(feeds[0], IntegrationFeedContext)
        self.assertEqual(feeds[0].feed_key, "daily")
        self.assertEqual(feeds[0].secrets["query_id"].reveal(), "myquery")

    def test_preflight_connection_error_fails_only_that_connection(self) -> None:
        """RuntimeError from preflight_connection fails only that connection group."""
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id="connection-1"),
            _make_connection_target("account-2", "U200", connection_id="connection-2"),
        ]
        # Both valid credentials
        for cid in ("connection-1", "connection-2"):
            db.connection_credentials[cid] = {
                "flex_token": _encrypt_value("token"),
                "feed:daily:query_id": _encrypt_value("query"),
            }
            db.connection_feeds[cid] = [_make_feed_record("daily")]

        call_count = {"n": 0}

        class SelectiveFailAdapter(FakeConnectionAdapter):
            def preflight_connection(self, connection, feeds):
                call_count["n"] += 1
                if connection.connection_id == "connection-1":
                    raise RuntimeError("connection_preflight_failed: bad config")

        adapter = SelectiveFailAdapter(payload_by_feed={"daily": SAMPLE_XML})

        result = self._run(
            _make_accounts_run_request(account_external_ids=("U100", "U200")),
            db=db, adapter=adapter,
        )

        self.assertEqual(result.status, "partially_succeeded")
        child_1 = self._find_child(db, "child-1")
        self.assertEqual(child_1.status, "failed")
        child_2 = self._find_child(db, "child-2")
        self.assertEqual(child_2.status, "succeeded")

    def test_credentials_loaded_per_connection_not_globally(self) -> None:
        """DB credential loading is called once per unique connection_id."""
        db = self._make_db_with_two_connections()
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        self._run(
            _make_accounts_run_request(account_external_ids=("U100", "U200")),
            db=db, adapter=adapter,
        )

        self.assertIn("connection-1", db.credential_calls)
        self.assertIn("connection-2", db.credential_calls)

    def test_all_connections_fail_results_in_parent_failed(self) -> None:
        """If every connection group fails with missing_connection_credential, parent is failed."""
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id="connection-1"),
        ]
        # No credentials at all
        db.connection_credentials["connection-1"] = {}
        db.connection_feeds["connection-1"] = [_make_feed_record("daily")]

        result = self._run(
            _make_accounts_run_request(account_external_ids=("U100",)),
            db=db,
        )

        self.assertEqual(result.status, "failed")

    def _run_without_master_key(self, request, db, adapter=None):
        """Run automation with the master key env var absent."""
        from portfolio_engine.automation.orchestrator import run_automation
        if adapter is None:
            adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})
        env = {k: v for k, v in os.environ.items() if k != "SUPERFOLIO_CREDENTIAL_MASTER_KEY"}
        with mock.patch.dict(os.environ, env, clear=True):
            return run_automation(request, database=db, adapter=adapter)

    def test_missing_master_key_fails_all_connections_with_distinct_category(self) -> None:
        """Missing SUPERFOLIO_CREDENTIAL_MASTER_KEY fails all connections as credential_master_key_error."""
        db = self._make_db_with_two_connections()
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        result = self._run_without_master_key(
            _make_accounts_run_request(account_external_ids=("U100", "U200")),
            db=db, adapter=adapter,
        )

        self.assertEqual(result.status, "failed")
        child_1 = self._find_child(db, "child-1")
        self.assertIsNotNone(child_1)
        self.assertEqual(child_1.status, "failed")
        self.assertEqual(child_1.summary["error_category"], "credential_master_key_error")
        # Must not be misreported as per-connection ciphertext corruption
        self.assertNotEqual(child_1.summary["error_category"], "credential_decryption_failed")
        child_2 = self._find_child(db, "child-2")
        self.assertIsNotNone(child_2)
        self.assertEqual(child_2.status, "failed")
        self.assertEqual(child_2.summary["error_category"], "credential_master_key_error")
        # Error messages must not contain any key material
        for finalized in db.finalized_children:
            self.assertNotIn("SUPERFOLIO", finalized.error_message or "")

    def test_malformed_master_key_fails_all_connections_with_distinct_category(self) -> None:
        """Malformed (non-Fernet) master key fails all connections as credential_master_key_error."""
        db = self._make_db_with_two_connections()
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        result = self._run(
            _make_accounts_run_request(account_external_ids=("U100", "U200")),
            db=db, adapter=adapter,
            master_key="this-is-not-a-valid-fernet-key",
        )

        self.assertEqual(result.status, "failed")
        child_1 = self._find_child(db, "child-1")
        self.assertIsNotNone(child_1)
        self.assertEqual(child_1.status, "failed")
        self.assertEqual(child_1.summary["error_category"], "credential_master_key_error")
        self.assertNotEqual(child_1.summary["error_category"], "credential_decryption_failed")
        child_2 = self._find_child(db, "child-2")
        self.assertIsNotNone(child_2)
        self.assertEqual(child_2.status, "failed")
        self.assertEqual(child_2.summary["error_category"], "credential_master_key_error")
        # Error messages must not leak the malformed key value
        for finalized in db.finalized_children:
            self.assertNotIn("this-is-not-a-valid-fernet-key", finalized.error_message or "")

    def test_master_key_error_does_not_mask_tampered_ciphertext_category(self) -> None:
        """Tampered ciphertext with a valid key still yields credential_decryption_failed."""
        db = FakeAutomationDatabase()
        db.connection_targets = [
            _make_connection_target("account-1", "U100", connection_id="connection-1"),
        ]
        db.connection_credentials["connection-1"] = {
            "flex_token": b"tampered-garbage-bytes",
        }
        db.connection_feeds["connection-1"] = [_make_feed_record("daily")]
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        result = self._run(
            _make_accounts_run_request(account_external_ids=("U100",)),
            db=db, adapter=adapter,
        )

        child_1 = self._find_child(db, "child-1")
        self.assertIsNotNone(child_1)
        self.assertEqual(child_1.status, "failed")
        self.assertEqual(child_1.summary["error_category"], "credential_decryption_failed")
        # Tampered ciphertext must NOT be reported as a master key config failure
        self.assertNotEqual(child_1.summary["error_category"], "credential_master_key_error")


# ---------------------------------------------------------------------------
# Task 12: Multi-feed dry-run execution
# ---------------------------------------------------------------------------

_MULTI_FEED_CASH_XML = "<FlexQueryResponse></FlexQueryResponse>"
_MULTI_FEED_NAV_XML = "<FlexQueryResponse></FlexQueryResponse>"

# Synthetic XML with real supported records for aggregation tests.
_MULTI_FEED_CASH_XML_WITH_RECORDS = (
    '<FlexQueryResponse>'
    '<CashTransaction accountId="U100" reportDate="20240115"'
    ' dateTime="20240115;120000" currency="USD" amount="500.00"'
    ' fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF-A1" />'
    '</FlexQueryResponse>'
)
_MULTI_FEED_NAV_XML_WITH_RECORDS = (
    '<FlexQueryResponse>'
    '<EquitySummaryByReportDateInBase accountId="U100" reportDate="20240115"'
    ' currency="USD" total="10000.00" />'
    '</FlexQueryResponse>'
)


class FakeMultiFeedAdapter:
    """Connection-aware adapter with fetch_feed_payload support for Task 12 tests."""

    def __init__(self, *, payload_by_feed=None, failing_feed_keys=None):
        self.payload_by_feed = payload_by_feed or {}
        self.failing_feed_keys: set[str] = set(failing_feed_keys or set())
        self.fetched_feed_keys: list[str] = []
        self.preflight_connection_calls: list = []

    def preflight_validate_config(self, config) -> None:
        return None

    def preflight_connection(self, connection, feeds) -> None:
        self.preflight_connection_calls.append((connection, feeds))

    def fetch_feed_payload(self, connection_context, feed_context, request):
        from portfolio_engine.automation.types import BrokerPayload
        self.fetched_feed_keys.append(feed_context.feed_key)
        if feed_context.feed_key in self.failing_feed_keys:
            raise RuntimeError(f"feed_fetch_failed: {feed_context.feed_key}")
        xml = self.payload_by_feed.get(feed_context.feed_key, SAMPLE_XML)
        return BrokerPayload(xml_text=xml, source_name=f"{feed_context.feed_key}.xml")


class StructuredFetchCategoryAdapter(FakeMultiFeedAdapter):
    def fetch_feed_payload(self, connection_context, feed_context, request):
        from portfolio_engine.automation.fetch_errors import BrokerFetchError
        if feed_context.feed_key == "cash":
            raise BrokerFetchError("ibkr_auth_failed", "ibkr_auth_failed")
        if feed_context.feed_key == "nav":
            raise BrokerFetchError("untrusted_category", "untrusted_category")
        return super().fetch_feed_payload(connection_context, feed_context, request)


def _configured_db_with_connection_feeds(feed_keys: list[str]) -> FakeAutomationDatabase:
    """Create a FakeAutomationDatabase with one account and the specified feeds."""
    db = FakeAutomationDatabase()
    db.connection_targets = [
        _make_connection_target("account-uuid", "U100", connection_id="test-connection-id"),
    ]
    creds: dict[str, bytes] = {"flex_token": _encrypt_value("test-token")}
    feeds = []
    for fk in feed_keys:
        creds[f"feed:{fk}:query_id"] = _encrypt_value(f"query-{fk}")
        feeds.append(_make_feed_record(fk))
    db.connection_credentials["test-connection-id"] = creds
    db.connection_feeds["test-connection-id"] = feeds
    return db


def _make_accounts_dry_run_request(external_id: str):
    """Create a dry-run AutomationRunRequest for a single account external ID."""
    from portfolio_engine.automation.types import AutomationRunRequest
    return AutomationRunRequest(
        target_type="accounts",
        integration_key="ibkr_flex_ws",
        mode="dry-run",
        requested_start_date=date(2024, 1, 1),
        requested_end_date=date(2024, 1, 31),
        account_external_ids=(external_id,),
    )


class DryRunMultiFeedTests(unittest.TestCase):
    """Task 12: Dry-run fetches all enabled feeds per connection and aggregates results."""

    def _run(self, request, db, adapter):
        from portfolio_engine.automation.orchestrator import run_automation
        with mock.patch.dict(os.environ, {"SUPERFOLIO_CREDENTIAL_MASTER_KEY": _TEST_MASTER_KEY}):
            return run_automation(request, database=db, adapter=adapter)

    def _find_child(self, db, child_id: str):
        for f in db.finalized_children:
            if f.automation_job_account_id == child_id:
                return f
        return None

    def test_dry_run_fetches_all_enabled_feeds_for_connection(self) -> None:
        """Dry-run with two feeds: adapter.fetch_feed_payload called for both in feed_key order."""
        db = _configured_db_with_connection_feeds(["cash", "nav"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={"cash": _MULTI_FEED_CASH_XML, "nav": _MULTI_FEED_NAV_XML}
        )

        result = self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(adapter.fetched_feed_keys, ["cash", "nav"])
        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertIn("feed_results", child.summary)
        self.assertEqual(child.summary["feed_results"][0]["feed_key"], "cash")

    def test_dry_run_partial_when_one_feed_fails(self) -> None:
        """Dry-run with cash succeeds and nav fails: child and parent are partially_succeeded."""
        db = _configured_db_with_connection_feeds(["cash", "nav"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={"cash": _MULTI_FEED_CASH_XML},
            failing_feed_keys={"nav"},
        )

        result = self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        self.assertEqual(result.status, "partially_succeeded")
        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertEqual(child.status, "partially_succeeded")

    def test_dry_run_child_failed_when_all_feeds_fail(self) -> None:
        """Dry-run with all feeds failing: child status failed, parent status failed."""
        db = _configured_db_with_connection_feeds(["cash", "nav"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={},
            failing_feed_keys={"cash", "nav"},
        )

        result = self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        self.assertEqual(result.status, "failed")
        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertEqual(child.status, "failed")

    def test_dry_run_feed_results_present_in_child_summary(self) -> None:
        """Dry-run with one feed: child summary contains feed_results with one entry."""
        db = _configured_db_with_connection_feeds(["cash"])
        adapter = FakeMultiFeedAdapter(payload_by_feed={"cash": _MULTI_FEED_CASH_XML})

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertIn("feed_results", child.summary)
        self.assertEqual(len(child.summary["feed_results"]), 1)
        self.assertEqual(child.summary["feed_results"][0]["feed_key"], "cash")

    def test_dry_run_failed_feed_has_error_category_in_results(self) -> None:
        """A failed feed entry in feed_results must have status=failed and error_category set."""
        db = _configured_db_with_connection_feeds(["cash"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={},
            failing_feed_keys={"cash"},
        )

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertIn("feed_results", child.summary)
        feed_result = child.summary["feed_results"][0]
        self.assertEqual(feed_result["status"], "failed")
        self.assertIn("error_category", feed_result)

    def test_dry_run_feed_results_no_secrets(self) -> None:
        """feed_results in child summary must not contain query_id or credential values."""
        db = _configured_db_with_connection_feeds(["cash"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={},
            failing_feed_keys={"cash"},
        )

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        summary_str = str(child.summary)
        self.assertNotIn("query_id", summary_str)
        self.assertNotIn("query-cash", summary_str)

    def test_dry_run_feed_keys_fetched_in_stable_order(self) -> None:
        """Feeds must be fetched in stable (alphabetical) feed_key order."""
        db = _configured_db_with_connection_feeds(["nav", "cash"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={"cash": _MULTI_FEED_CASH_XML, "nav": _MULTI_FEED_NAV_XML}
        )

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        self.assertEqual(adapter.fetched_feed_keys, ["cash", "nav"])

    def test_dry_run_succeeded_feed_has_status_succeeded_in_results(self) -> None:
        """A succeeded feed entry in feed_results must have status=succeeded."""
        db = _configured_db_with_connection_feeds(["cash"])
        adapter = FakeMultiFeedAdapter(payload_by_feed={"cash": _MULTI_FEED_CASH_XML})

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        feed_result = child.summary["feed_results"][0]
        self.assertEqual(feed_result["status"], "succeeded")

    def test_dry_run_mixed_feed_results_both_entries_present(self) -> None:
        """With one success and one failure, feed_results has two entries."""
        db = _configured_db_with_connection_feeds(["cash", "nav"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={"cash": _MULTI_FEED_CASH_XML},
            failing_feed_keys={"nav"},
        )

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertEqual(len(child.summary["feed_results"]), 2)
        feed_keys = [fr["feed_key"] for fr in child.summary["feed_results"]]
        self.assertIn("cash", feed_keys)
        self.assertIn("nav", feed_keys)

    def test_dry_run_child_summary_has_record_counts(self) -> None:
        """Child summary for multi-feed dry-run must contain record_counts."""
        db = _configured_db_with_connection_feeds(["cash"])
        adapter = FakeMultiFeedAdapter(payload_by_feed={"cash": _MULTI_FEED_CASH_XML})

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertIn("record_counts", child.summary)

    def test_dry_run_marks_child_running_before_finalize(self) -> None:
        """mark_automation_job_account_running must be called before finalize in multi-feed mode."""
        db = _configured_db_with_connection_feeds(["cash"])
        adapter = FakeMultiFeedAdapter(payload_by_feed={"cash": _MULTI_FEED_CASH_XML})

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        self.assertGreaterEqual(len(db.running_children), 1)
        mark_idx = db._event_log.index("mark_running:child-1")
        finalize_idx = db._event_log.index("finalize_child:child-1")
        self.assertLess(mark_idx, finalize_idx)

    def test_dry_run_no_ingestion_run_created(self) -> None:
        """Multi-feed dry-run must not create any ingestion runs."""
        db = _configured_db_with_connection_feeds(["cash"])
        adapter = FakeMultiFeedAdapter(payload_by_feed={"cash": _MULTI_FEED_CASH_XML})

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        self.assertEqual(len(db.started_ingestion_runs), 0)

    def test_dry_run_no_active_feeds_fails_child_and_parent(self) -> None:
        """A connection group with zero active feeds must fail, not silently succeed."""
        db = _configured_db_with_connection_feeds([])  # no feeds configured
        adapter = FakeMultiFeedAdapter(payload_by_feed={})

        result = self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        self.assertEqual(result.status, "failed")
        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertEqual(child.status, "failed")
        self.assertEqual(child.summary.get("error_category"), "no_active_feeds")

    def test_dry_run_no_active_feeds_error_category_no_secrets(self) -> None:
        """no_active_feeds error category must not expose secrets in summary or error message."""
        db = _configured_db_with_connection_feeds([])
        adapter = FakeMultiFeedAdapter(payload_by_feed={})

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        summary_str = str(child.summary)
        self.assertNotIn("query_id", summary_str)
        self.assertNotIn("flex_token", summary_str)
        self.assertNotIn("test-token", summary_str)

    def test_dry_run_no_active_feeds_does_not_call_fetch(self) -> None:
        """When there are no active feeds, fetch_feed_payload must not be called."""
        db = _configured_db_with_connection_feeds([])
        adapter = FakeMultiFeedAdapter(payload_by_feed={})

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        self.assertEqual(adapter.fetched_feed_keys, [])

    def test_dry_run_no_active_feeds_marks_child_running_before_finalize(self) -> None:
        """no_active_feeds path must call mark_automation_job_account_running before finalize."""
        db = _configured_db_with_connection_feeds([])
        adapter = FakeMultiFeedAdapter(payload_by_feed={})

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        # Child must have been marked running.
        self.assertIn("child-1", db.running_children)
        # mark_running must precede finalize in the event log.
        mark_idx = db._event_log.index("mark_running:child-1")
        finalize_idx = db._event_log.index("finalize_child:child-1")
        self.assertLess(mark_idx, finalize_idx)

    def test_dry_run_two_feeds_record_counts_aggregated(self) -> None:
        """Successful cash+nav feeds: child record_counts sums non-zero counts across both feeds."""
        db = _configured_db_with_connection_feeds(["cash", "nav"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={
                "cash": _MULTI_FEED_CASH_XML_WITH_RECORDS,
                "nav": _MULTI_FEED_NAV_XML_WITH_RECORDS,
            }
        )

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        rc = child.summary["record_counts"]
        # Each feed contributed at least one supported record.
        self.assertGreater(rc["cash_flows"]["supported"], 0)
        self.assertGreater(rc["daily_nav_snapshots"]["supported"], 0)

    def test_dry_run_failed_feed_contributes_zero_counts(self) -> None:
        """A failed feed must not contribute counts; only the succeeded feed adds to aggregate."""
        db = _configured_db_with_connection_feeds(["cash", "nav"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={"cash": _MULTI_FEED_CASH_XML_WITH_RECORDS},
            failing_feed_keys={"nav"},
        )

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        rc = child.summary["record_counts"]
        # Cash feed succeeded; its counts must be positive.
        self.assertGreater(rc["cash_flows"]["supported"], 0)
        # Nav feed failed; nav counts must remain zero.
        self.assertEqual(rc["daily_nav_snapshots"]["supported"], 0)

    def test_dry_run_feed_result_preserves_allowed_broker_fetch_category(self) -> None:
        db = _configured_db_with_connection_feeds(["cash"])
        adapter = StructuredFetchCategoryAdapter()

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertEqual(child.summary["feed_results"][0]["error_category"], "ibkr_auth_failed")

    def test_dry_run_unknown_broker_fetch_category_falls_back(self) -> None:
        db = _configured_db_with_connection_feeds(["nav"])
        adapter = StructuredFetchCategoryAdapter()

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertEqual(child.summary["feed_results"][0]["error_category"], "feed_fetch_failed")


# ---------------------------------------------------------------------------
# Task 13: Multi-feed load execution for connection-aware adapters
# ---------------------------------------------------------------------------


def _make_accounts_load_request(*external_ids: str):
    """Create a load-mode AutomationRunRequest for one or more account external IDs."""
    from portfolio_engine.automation.types import AutomationRunRequest
    return AutomationRunRequest(
        target_type="accounts",
        integration_key="ibkr_flex_ws",
        mode="load",
        requested_start_date=date(2024, 1, 1),
        requested_end_date=date(2024, 1, 31),
        account_external_ids=tuple(external_ids),
    )


class LoadMultiFeedTests(unittest.TestCase):
    """Task 13: Load mode fetches all enabled feeds per connection and aggregates results."""

    # Reuse synthetic XML fixtures from Task 12
    CASH_XML = _MULTI_FEED_CASH_XML_WITH_RECORDS
    NAV_XML = _MULTI_FEED_NAV_XML_WITH_RECORDS

    def _run(self, request, db, adapter):
        from portfolio_engine.automation.orchestrator import run_automation
        with mock.patch.dict(os.environ, {"SUPERFOLIO_CREDENTIAL_MASTER_KEY": _TEST_MASTER_KEY}):
            return run_automation(request, database=db, adapter=adapter)

    def _find_child(self, db, child_id: str):
        for f in db.finalized_children:
            if f.automation_job_account_id == child_id:
                return f
        return None

    def test_load_fetches_all_feeds_and_sums_record_counts(self) -> None:
        """Load with two feeds (cash, nav): both succeed, record counts summed across feeds."""
        db = _configured_db_with_connection_feeds(["cash", "nav"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={"cash": self.CASH_XML, "nav": self.NAV_XML}
        )

        result = self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        self.assertEqual(result.status, "succeeded")
        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        rc = child.summary["record_counts"]
        self.assertGreaterEqual(rc["cash_flows"]["supported"], 1)
        self.assertGreaterEqual(rc["daily_nav_snapshots"]["supported"], 1)

    def test_load_partial_when_one_feed_fails_after_another_succeeds(self) -> None:
        """Load with cash succeeding and nav failing: parent and child partially_succeeded."""
        db = _configured_db_with_connection_feeds(["cash", "nav"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={"cash": self.CASH_XML},
            failing_feed_keys={"nav"},
        )

        result = self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        self.assertEqual(result.status, "partially_succeeded")
        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertEqual(child.status, "partially_succeeded")

    def test_load_all_feeds_fail_yields_failed(self) -> None:
        """Load with all feeds failing: child and parent are failed."""
        db = _configured_db_with_connection_feeds(["cash", "nav"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={},
            failing_feed_keys={"cash", "nav"},
        )

        result = self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        self.assertEqual(result.status, "failed")
        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertEqual(child.status, "failed")

    def test_load_overlap_check_runs_once_per_account_before_any_feed(self) -> None:
        """Overlap check is called exactly once per account before any feed is loaded."""
        db = _configured_db_with_connection_feeds(["cash", "nav"])
        db.overlapping_load = False
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={"cash": self.CASH_XML, "nav": self.NAV_XML}
        )

        self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        # Exactly one overlap check per account, not one per feed
        self.assertEqual(len(db.overlap_check_calls), 1)

    def test_load_overlap_fails_child_and_skips_all_feeds(self) -> None:
        """When overlap detected, child is failed and no feeds are fetched."""
        db = _configured_db_with_connection_feeds(["cash", "nav"])
        db.overlapping_load = True
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={"cash": self.CASH_XML, "nav": self.NAV_XML}
        )

        result = self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        self.assertEqual(result.status, "failed")
        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertEqual(child.status, "failed")
        self.assertEqual(child.summary.get("error_category"), "overlapping_load_job")
        # No feeds must have been fetched
        self.assertEqual(adapter.fetched_feed_keys, [])

    def test_load_feed_results_included_in_child_summary(self) -> None:
        """Load multi-feed: child summary includes feed_results with one entry per feed."""
        db = _configured_db_with_connection_feeds(["cash", "nav"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={"cash": self.CASH_XML, "nav": self.NAV_XML}
        )

        self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertIn("feed_results", child.summary)
        self.assertEqual(len(child.summary["feed_results"]), 2)
        feed_keys = [fr["feed_key"] for fr in child.summary["feed_results"]]
        self.assertIn("cash", feed_keys)
        self.assertIn("nav", feed_keys)

    def test_load_feed_results_no_secrets(self) -> None:
        """feed_results in child summary must not contain credential values."""
        db = _configured_db_with_connection_feeds(["cash"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={},
            failing_feed_keys={"cash"},
        )

        self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        summary_str = str(child.summary)
        self.assertNotIn("query_id", summary_str)
        self.assertNotIn("query-cash", summary_str)

    def test_load_ingestion_runs_created_per_feed(self) -> None:
        """Load multi-feed: one ingestion run is started per successful feed per account."""
        db = _configured_db_with_connection_feeds(["cash", "nav"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={"cash": self.CASH_XML, "nav": self.NAV_XML}
        )

        self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        # Two feeds succeed → two ingestion runs started and completed
        self.assertEqual(len(db.started_ingestion_runs), 2)
        self.assertEqual(len(db.completed_ingestion_runs), 2)

    def test_load_mixed_feed_results_statuses_per_feed(self) -> None:
        """Load with cash success and nav failure: feed_results reflect per-feed statuses."""
        db = _configured_db_with_connection_feeds(["cash", "nav"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={"cash": self.CASH_XML},
            failing_feed_keys={"nav"},
        )

        self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        feed_results_by_key = {fr["feed_key"]: fr for fr in child.summary["feed_results"]}
        self.assertEqual(feed_results_by_key["cash"]["status"], "succeeded")
        self.assertEqual(feed_results_by_key["nav"]["status"], "failed")

    def test_load_marks_child_running_before_finalize(self) -> None:
        """mark_automation_job_account_running called before finalize in load multi-feed mode."""
        db = _configured_db_with_connection_feeds(["cash"])
        adapter = FakeMultiFeedAdapter(payload_by_feed={"cash": self.CASH_XML})

        self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        self.assertIn("child-1", db.running_children)
        mark_idx = db._event_log.index("mark_running:child-1")
        finalize_idx = db._event_log.index("finalize_child:child-1")
        self.assertLess(mark_idx, finalize_idx)

    def test_load_feeds_fetched_in_stable_order(self) -> None:
        """Feeds are fetched in stable alphabetical feed_key order in load mode."""
        db = _configured_db_with_connection_feeds(["nav", "cash"])
        adapter = FakeMultiFeedAdapter(
            payload_by_feed={"cash": self.CASH_XML, "nav": self.NAV_XML}
        )

        self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        self.assertEqual(adapter.fetched_feed_keys, ["cash", "nav"])

    def test_load_no_active_feeds_fails_child(self) -> None:
        """Load with no active feeds: child and parent are failed."""
        db = _configured_db_with_connection_feeds([])
        adapter = FakeMultiFeedAdapter(payload_by_feed={})

        result = self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        self.assertEqual(result.status, "failed")
        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertEqual(child.status, "failed")
        self.assertEqual(child.summary.get("error_category"), "no_active_feeds")

    def test_load_child_summary_has_record_counts(self) -> None:
        """Load multi-feed child summary must contain record_counts."""
        db = _configured_db_with_connection_feeds(["cash"])
        adapter = FakeMultiFeedAdapter(payload_by_feed={"cash": self.CASH_XML})

        self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertIn("record_counts", child.summary)

    def test_load_feed_result_preserves_allowed_broker_fetch_category(self) -> None:
        """Load feed result must preserve allowed BrokerFetchError category (ibkr_auth_failed)."""
        db = _configured_db_with_connection_feeds(["cash"])
        adapter = StructuredFetchCategoryAdapter()

        self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertEqual(child.summary["feed_results"][0]["error_category"], "ibkr_auth_failed")

    def test_load_unknown_broker_fetch_category_falls_back(self) -> None:
        """Load feed result must fall back to 'feed_fetch_failed' for unknown broker fetch category."""
        db = _configured_db_with_connection_feeds(["nav"])
        adapter = StructuredFetchCategoryAdapter()

        self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertEqual(child.summary["feed_results"][0]["error_category"], "feed_fetch_failed")


# ---------------------------------------------------------------------------
# Task 7: Load mode fetch-once refactor — one fetch per feed per connection run
# ---------------------------------------------------------------------------


class LoadMultiFeedFetchOnceTests(unittest.TestCase):
    """Task 7: Load mode fetches each feed once and reuses XML for all eligible accounts."""

    def _run(self, request, db, adapter):
        from portfolio_engine.automation.orchestrator import run_automation
        with mock.patch.dict(os.environ, {"SUPERFOLIO_CREDENTIAL_MASTER_KEY": _TEST_MASTER_KEY}):
            return run_automation(request, database=db, adapter=adapter)

    def test_load_fetches_each_feed_once_for_multiple_accounts(self) -> None:
        """Two accounts on same connection with one feed: adapter.fetch_feed_payload called once."""
        db = _configured_db_with_connection_feeds(["cash"])
        db.connection_targets = [
            _make_connection_target("account-uuid-1", "U100", connection_id="test-connection-id"),
            _make_connection_target("account-uuid-2", "U200", connection_id="test-connection-id"),
        ]
        adapter = FakeMultiFeedAdapter(payload_by_feed={"cash": _MULTI_FEED_CASH_XML})

        self._run(_make_accounts_load_request("U100", "U200"), db=db, adapter=adapter)

        self.assertEqual(adapter.fetched_feed_keys, ["cash"])

    def test_load_does_not_fetch_when_all_accounts_overlap(self) -> None:
        """When all accounts in a connection group are overlapped, no feed is fetched."""
        db = _configured_db_with_connection_feeds(["cash"])
        db.overlapping_load_accounts = {"account-uuid"}
        adapter = FakeMultiFeedAdapter(payload_by_feed={"cash": _MULTI_FEED_CASH_XML})

        self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        self.assertEqual(adapter.fetched_feed_keys, [])


# ---------------------------------------------------------------------------
# Task 14: Overlap blocking is account/date scoped, not connection-scoped
# ---------------------------------------------------------------------------


class AutomationOverlapConnectionScopingTests(unittest.TestCase):
    """Task 14: Reassigning an account to a different connection must not bypass overlap blocking.

    The overlap check uses account_id and date range as the scope; connection_id
    is not a match condition. These tests confirm that behaviour.
    """

    def _run(self, request, db, adapter):
        from portfolio_engine.automation.orchestrator import run_automation
        with mock.patch.dict(os.environ, {"SUPERFOLIO_CREDENTIAL_MASTER_KEY": _TEST_MASTER_KEY}):
            return run_automation(request, database=db, adapter=adapter)

    def _find_child(self, db, child_id: str):
        for f in db.finalized_children:
            if f.automation_job_account_id == child_id:
                return f
        return None

    def test_reassigned_connection_does_not_bypass_overlap(self) -> None:
        """Overlap blocking must fire for an account even when the account's connection_id
        has been reassigned. The check is account-scoped: connection_id is irrelevant."""
        # _configured_db_with_connection_feeds uses account_id="account-uuid" /
        # external_id="U100" assigned to connection_id="test-connection-id".
        db = _configured_db_with_connection_feeds(["daily"])
        # Mark account-uuid as having an overlapping load (by account ID, not connection ID).
        db.overlapping_account_ids.add("account-uuid")

        result = self._run(
            _make_accounts_load_request("U100"),
            db=db,
            adapter=FakeConnectionAdapter(),
        )

        self.assertEqual(result.status, "failed")
        child = self._find_child(db, "child-1")
        self.assertIsNotNone(child)
        self.assertEqual(child.summary["error_category"], "overlapping_load_job")

    def test_overlap_check_call_does_not_include_connection_id(self) -> None:
        """The overlap check call recorded in the fake DB must not carry a connection_id key."""
        db = _configured_db_with_connection_feeds(["daily"])
        # No overlap — we just want to inspect the call arguments.
        db.overlapping_load = False

        self._run(
            _make_accounts_load_request("U100"),
            db=db,
            adapter=FakeConnectionAdapter(),
        )

        self.assertGreaterEqual(len(db.overlap_check_calls), 1)
        for call in db.overlap_check_calls:
            self.assertNotIn("connection_id", call,
                             "overlap check must not receive connection_id as a parameter")


if __name__ == "__main__":
    unittest.main()
