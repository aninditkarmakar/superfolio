from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
REVERT_SCHEMA = MIGRATIONS_DIR / "revert" / "create_mvp_schema.sql"
VERIFY_SCHEMA = MIGRATIONS_DIR / "verify" / "create_mvp_schema.sql"
PORTFOLIO_LAYER_DEPLOY = MIGRATIONS_DIR / "deploy" / "create_portfolio_layer.sql"

ACCOUNT_SCOPED_START_INGESTION_RUN_SIGNATURE = (
    "public.start_ingestion_run(TEXT, TEXT, TEXT, DATE, DATE, TEXT)"
)


class MigrationContractTests(unittest.TestCase):
    def test_revert_drops_current_and_legacy_start_ingestion_run_signatures(self) -> None:
        sql = REVERT_SCHEMA.read_text(encoding="utf-8")

        self.assertIn(
            f"DROP FUNCTION IF EXISTS {ACCOUNT_SCOPED_START_INGESTION_RUN_SIGNATURE};",
            sql,
        )

    def test_verify_rejects_extra_start_ingestion_run_overloads(self) -> None:
        sql = VERIFY_SCHEMA.read_text(encoding="utf-8")

        self.assertIn("p.proname = 'start_ingestion_run'", sql)
        self.assertIn("to_regprocedure", sql)
        self.assertIn(
            "'public.start_ingestion_run(text,text,text,date,date,text)'",
            sql,
        )

    def test_portfolio_layer_migration_files_exist(self) -> None:
        migration_name = "create_portfolio_layer.sql"

        self.assertTrue((MIGRATIONS_DIR / "deploy" / migration_name).exists())
        self.assertTrue((MIGRATIONS_DIR / "revert" / migration_name).exists())
        self.assertTrue((MIGRATIONS_DIR / "verify" / migration_name).exists())

    def test_portfolio_layer_migration_is_in_sqitch_plan(self) -> None:
        plan_text = (MIGRATIONS_DIR / "sqitch.plan").read_text()

        self.assertIn("create_portfolio_layer", plan_text)
        self.assertLess(
            plan_text.index("create_mvp_schema"),
            plan_text.index("create_portfolio_layer"),
        )

    def test_create_portfolio_uses_do_nothing_on_conflict(self) -> None:
        sql = PORTFOLIO_LAYER_DEPLOY.read_text(encoding="utf-8")

        self.assertIn("ON CONFLICT (name) DO NOTHING", sql)

    def test_create_portfolio_does_not_silently_update_reporting_currency(self) -> None:
        sql = PORTFOLIO_LAYER_DEPLOY.read_text(encoding="utf-8")

        self.assertNotIn("SET reporting_currency = EXCLUDED.reporting_currency", sql)

    def test_create_portfolio_raises_on_currency_mismatch(self) -> None:
        sql = PORTFOLIO_LAYER_DEPLOY.read_text(encoding="utf-8")

        self.assertIn("already exists with reporting_currency", sql)

    def test_attach_portfolio_account_rejects_currency_mismatch_before_insert(self) -> None:
        sql = PORTFOLIO_LAYER_DEPLOY.read_text(encoding="utf-8")

        self.assertIn("v_reporting_currency", sql)
        self.assertIn("v_account_base_currency", sql)
        self.assertIn("a.base_currency INTO v_account_id, v_account_base_currency", sql)
        self.assertIn("v_account_base_currency <> v_reporting_currency", sql)
        self.assertIn("base currency % does not match portfolio reporting currency %", sql)
        mismatch_pos = sql.index("v_account_base_currency <> v_reporting_currency")
        insert_pos = sql.index("INSERT INTO public.portfolio_accounts")
        self.assertLess(mismatch_pos, insert_pos)

    def test_bridge_overlap_rejects_exact_duplicate_window(self) -> None:
        sql = PORTFOLIO_LAYER_DEPLOY.read_text(encoding="utf-8")

        self.assertIn(
            "(departure_date = p_departure_date AND arrival_date = p_arrival_date)",
            sql,
        )

    def test_bridge_overlap_still_checks_open_interval_daterange(self) -> None:
        sql = PORTFOLIO_LAYER_DEPLOY.read_text(encoding="utf-8")

        self.assertIn("daterange(departure_date + 1, arrival_date, '[)')", sql)
        self.assertIn("daterange(p_departure_date + 1, p_arrival_date, '[)')", sql)

    def test_bridge_overlap_uses_case_guard_for_existing_bridge(self) -> None:
        sql = PORTFOLIO_LAYER_DEPLOY.read_text(encoding="utf-8")

        self.assertIn("CASE WHEN departure_date < arrival_date", sql)

    def test_bridge_overlap_uses_case_guard_for_new_bridge(self) -> None:
        sql = PORTFOLIO_LAYER_DEPLOY.read_text(encoding="utf-8")

        self.assertIn("CASE WHEN p_departure_date < p_arrival_date", sql)

    def test_bridge_overlap_uses_empty_daterange_for_same_day_bridges(self) -> None:
        sql = PORTFOLIO_LAYER_DEPLOY.read_text(encoding="utf-8")

        self.assertIn("'empty'::daterange", sql)

    def test_bridge_overlap_does_not_contain_unguarded_daterange_expression(self) -> None:
        sql = PORTFOLIO_LAYER_DEPLOY.read_text(encoding="utf-8")

        self.assertNotIn(
            "OR daterange(departure_date + 1, arrival_date, '[)') && daterange(p_departure_date + 1, p_arrival_date, '[)')",
            sql,
        )

    def test_create_portfolio_guards_missing_row_after_conflict(self) -> None:
        sql = PORTFOLIO_LAYER_DEPLOY.read_text(encoding="utf-8")

        self.assertIn("Portfolio % disappeared after conflict", sql)
        disappeared_pos = sql.index("Portfolio % disappeared after conflict")
        exists_pos = sql.index("already exists with reporting_currency")
        self.assertLess(disappeared_pos, exists_pos)

    def test_transfer_bridge_validates_blank_currency_before_comparison(self) -> None:
        sql = PORTFOLIO_LAYER_DEPLOY.read_text(encoding="utf-8")

        self.assertIn("p_currency IS NULL OR btrim(p_currency) = ''", sql)
        self.assertIn("Bridge currency must not be NULL or blank", sql)
        null_check_pos = sql.index("p_currency IS NULL OR btrim(p_currency) = ''")
        mismatch_pos = sql.index("upper(btrim(p_currency)) <> v_reporting_currency")
        self.assertLess(null_check_pos, mismatch_pos)


    def test_automation_layer_is_registered_after_portfolio_layer(self) -> None:
        plan = (MIGRATIONS_DIR / "sqitch.plan").read_text(encoding="utf-8")

        portfolio_pos = plan.index("create_portfolio_layer")
        automation_pos = plan.index("create_automation_layer")

        self.assertLess(portfolio_pos, automation_pos)

    def test_automation_layer_migration_files_exist(self) -> None:
        for path in (
            MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql",
            MIGRATIONS_DIR / "revert" / "create_automation_layer.sql",
            MIGRATIONS_DIR / "verify" / "create_automation_layer.sql",
        ):
            self.assertTrue(path.exists(), f"missing {path}")

    def test_automation_layer_defines_parent_and_child_tables(self) -> None:
        sql = (MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE public.automation_jobs", sql)
        self.assertIn("CREATE TABLE public.automation_job_accounts", sql)
        self.assertIn("summary JSONB", sql)
        self.assertIn("automation_jobs_target_type_check", sql)
        self.assertIn("automation_jobs_portfolio_target_check", sql)
        self.assertIn("automation_jobs_manual_dates_required_check", sql)
        self.assertIn("automation_job_accounts_unique_account", sql)

    def test_automation_layer_revert_drops_child_before_parent(self) -> None:
        sql = (MIGRATIONS_DIR / "revert" / "create_automation_layer.sql").read_text(encoding="utf-8")

        child_pos = sql.index("DROP TABLE IF EXISTS public.automation_job_accounts")
        parent_pos = sql.index("DROP TABLE IF EXISTS public.automation_jobs")

        self.assertLess(child_pos, parent_pos)

    def test_automation_layer_verify_constraint_check_raises_on_mismatch(self) -> None:
        sql = (MIGRATIONS_DIR / "verify" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("SELECT 1 / (count(*) = 4)::int", sql)

    def test_automation_layer_dates_are_nullable_with_manual_check(self) -> None:
        sql = (MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("requested_start_date DATE,", sql)
        self.assertIn("requested_end_date DATE,", sql)
        self.assertIn("automation_jobs_manual_dates_required_check", sql)
        self.assertNotIn("requested_start_date DATE NOT NULL", sql)
        self.assertNotIn("requested_end_date DATE NOT NULL", sql)

    def test_automation_layer_date_range_check_explicitly_allows_null_dates(self) -> None:
        sql = (MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("requested_start_date IS NULL", sql)
        self.assertIn("OR requested_end_date IS NULL", sql)
        self.assertIn("OR requested_start_date <= requested_end_date", sql)

    def test_automation_layer_defines_lifecycle_functions(self) -> None:
        sql = (MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql").read_text(encoding="utf-8")

        for name in (
            "public.create_automation_job",
            "public.finalize_automation_job",
            "public.add_automation_job_account",
            "public.mark_automation_job_account_running",
            "public.finalize_automation_job_account",
        ):
            self.assertIn(f"CREATE FUNCTION {name}", sql)

    def test_automation_layer_revert_drops_lifecycle_functions(self) -> None:
        sql = (MIGRATIONS_DIR / "revert" / "create_automation_layer.sql").read_text(encoding="utf-8")

        for name in (
            "public.finalize_automation_job_account",
            "public.mark_automation_job_account_running",
            "public.add_automation_job_account",
            "public.finalize_automation_job",
            "public.create_automation_job",
        ):
            self.assertIn(f"DROP FUNCTION IF EXISTS {name}", sql)

    def test_automation_layer_finalizers_reject_non_terminal_statuses(self) -> None:
        sql = (MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertEqual(
            2,
            sql.count("v_status NOT IN ('succeeded', 'partially_succeeded', 'failed')"),
        )
        self.assertIn("Invalid final automation job status", sql)
        self.assertIn("Invalid final automation job account status", sql)

    def test_automation_layer_verify_lifecycle_functions_uses_non_throwing_resolution(self) -> None:
        sql = (MIGRATIONS_DIR / "verify" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("to_regprocedure('public.create_automation_job", sql)
        self.assertNotIn("'public.create_automation_job(text,text,uuid,text,text,date,date)'::regprocedure", sql)

    def test_automation_layer_defines_target_and_cleanup_functions(self) -> None:
        sql = (MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE FUNCTION public.resolve_automation_portfolio_accounts", sql)
        self.assertIn("CREATE FUNCTION public.resolve_automation_account_targets", sql)
        self.assertIn("CREATE FUNCTION public.fail_stale_automation_runs", sql)
        self.assertIn("a.is_active = true", sql)
        self.assertIn("b.is_active = true", sql)
        self.assertIn("p.is_active = true", sql)

    def test_automation_layer_revert_drops_target_and_cleanup_functions(self) -> None:
        sql = (MIGRATIONS_DIR / "revert" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("DROP FUNCTION IF EXISTS public.fail_stale_automation_runs(TIMESTAMPTZ, TEXT)", sql)
        self.assertIn("DROP FUNCTION IF EXISTS public.resolve_automation_account_targets(TEXT, TEXT[])", sql)
        self.assertIn("DROP FUNCTION IF EXISTS public.resolve_automation_portfolio_accounts(TEXT, TEXT)", sql)

    def test_automation_layer_verify_target_and_cleanup_functions(self) -> None:
        sql = (MIGRATIONS_DIR / "verify" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("to_regprocedure('public.resolve_automation_portfolio_accounts(text,text)')", sql)
        self.assertIn("to_regprocedure('public.resolve_automation_account_targets(text,text[])')", sql)
        self.assertIn("to_regprocedure('public.fail_stale_automation_runs(timestamptz,text)')", sql)
        self.assertIn("SELECT 1 / (count(*) = 3)::int", sql)

    def test_automation_layer_target_resolution_requires_brokerage_code(self) -> None:
        sql = (MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertEqual(2, sql.count("p_brokerage_code IS NULL OR btrim(p_brokerage_code) = ''"))
        self.assertIn("automation target resolution requires brokerage_code", sql)

    def test_automation_layer_stale_cleanup_fails_pending_children_of_stale_parents(self) -> None:
        sql = (MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("status IN ('pending', 'running')", sql)
        self.assertIn("automation_job_id IN (", sql)
        self.assertIn("FROM public.automation_jobs", sql)
        self.assertIn("started_at < p_stale_before", sql)

    def test_automation_layer_account_target_resolution_trims_external_ids(self) -> None:
        sql = (MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("FROM unnest(p_account_external_ids) AS requested(account_external_id)", sql)
        self.assertIn("SELECT btrim(requested.account_external_id)", sql)
        self.assertIn("btrim(requested.account_external_id) <> ''", sql)

    def test_automation_layer_account_target_resolution_rejects_all_blank_external_ids(self) -> None:
        sql = (MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("IF NOT EXISTS (", sql)
        self.assertIn("target_type=accounts requires at least one non-blank account_external_id", sql)

    def test_automation_layer_stale_cleanup_requires_cutoff(self) -> None:
        sql = (MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("IF p_stale_before IS NULL THEN", sql)
        self.assertIn("p_stale_before must not be NULL", sql)

    # ------------------------------------------------------------------
    # Task 15: Overlap detection function
    # ------------------------------------------------------------------

    def test_automation_layer_deploy_defines_overlap_detection_function(self) -> None:
        sql = (MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE FUNCTION public.has_overlapping_automation_load", sql)
        self.assertIn("daterange", sql)

    def test_automation_layer_overlap_function_uses_correct_parameter_types(self) -> None:
        sql = (MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("p_integration_key TEXT", sql)
        self.assertIn("p_account_id UUID", sql)
        self.assertIn("p_requested_start_date DATE", sql)
        self.assertIn("p_requested_end_date DATE", sql)

    def test_automation_layer_overlap_function_returns_boolean(self) -> None:
        sql = (MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql").read_text(encoding="utf-8")

        func_start = sql.index("CREATE FUNCTION public.has_overlapping_automation_load")
        func_segment = sql[func_start:func_start + 500]
        self.assertIn("RETURNS BOOLEAN", func_segment)

    def test_automation_layer_revert_drops_overlap_function(self) -> None:
        sql = (MIGRATIONS_DIR / "revert" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn(
            "DROP FUNCTION IF EXISTS public.has_overlapping_automation_load(TEXT, UUID, DATE, DATE, UUID);",
            sql,
        )

    def test_automation_layer_revert_drops_overlap_function_before_tables(self) -> None:
        sql = (MIGRATIONS_DIR / "revert" / "create_automation_layer.sql").read_text(encoding="utf-8")

        drop_func_pos = sql.index("DROP FUNCTION IF EXISTS public.has_overlapping_automation_load")
        drop_table_pos = sql.index("DROP TABLE IF EXISTS public.automation_job_accounts")
        self.assertLess(drop_func_pos, drop_table_pos)

    def test_automation_layer_verify_checks_overlap_function(self) -> None:
        sql = (MIGRATIONS_DIR / "verify" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn(
            "to_regprocedure('public.has_overlapping_automation_load(text,uuid,date,date,uuid)')",
            sql,
        )

    def test_automation_layer_verify_overlap_function_uses_error_raising_style(self) -> None:
        """Verify must use 1/(count=N)::int pattern — not a silent no-op SELECT 1 WHERE."""
        sql = (MIGRATIONS_DIR / "verify" / "create_automation_layer.sql").read_text(encoding="utf-8")

        # Should not contain a bare "SELECT 1 WHERE ... IS NOT NULL" for the new function alone
        # (that would be a silent pass on missing function). Must use the raising integer-divide style.
        self.assertIn("1 /", sql)

    # ------------------------------------------------------------------
    # Issue 1 fix: exclude-self parameter added to has_overlapping_automation_load
    # ------------------------------------------------------------------

    def test_automation_layer_overlap_function_has_exclude_job_id_parameter(self) -> None:
        """Deploy SQL must declare p_exclude_automation_job_id UUID parameter."""
        sql = (MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("p_exclude_automation_job_id UUID", sql)

    def test_automation_layer_overlap_function_excludes_current_job(self) -> None:
        """Deploy SQL WHERE clause must exclude the current job row to prevent self-match."""
        sql = (MIGRATIONS_DIR / "deploy" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("j.id <> p_exclude_automation_job_id", sql)

    def test_automation_layer_revert_drops_overlap_function_with_five_params(self) -> None:
        """Revert must drop the updated 5-parameter signature (TEXT, UUID, DATE, DATE, UUID)."""
        sql = (MIGRATIONS_DIR / "revert" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn(
            "DROP FUNCTION IF EXISTS public.has_overlapping_automation_load(TEXT, UUID, DATE, DATE, UUID);",
            sql,
        )

    def test_automation_layer_verify_checks_overlap_function_with_five_param_signature(self) -> None:
        """Verify to_regprocedure must reference the 5-parameter signature."""
        sql = (MIGRATIONS_DIR / "verify" / "create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn(
            "to_regprocedure('public.has_overlapping_automation_load(text,uuid,date,date,uuid)')",
            sql,
        )


class AutomationConnectionMigrationTests(unittest.TestCase):
    def test_automation_layer_creates_connection_tables(self) -> None:
        text = Path("migrations/deploy/create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE public.integration_connections", text)
        self.assertIn("CREATE TABLE public.integration_connection_credentials", text)
        self.assertIn("CREATE TABLE public.integration_feeds", text)
        self.assertIn("CREATE TABLE public.account_integration_assignments", text)
        self.assertIn("connection_id UUID REFERENCES public.integration_connections(id)", text)

    def test_automation_layer_enforces_connection_uniqueness(self) -> None:
        text = Path("migrations/deploy/create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("integration_connections_unique_name", text)
        self.assertIn("integration_connection_credentials_active_unique", text)
        self.assertIn("integration_feeds_unique_key", text)

    def test_revert_drops_connection_tables(self) -> None:
        text = Path("migrations/revert/create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("DROP TABLE IF EXISTS public.account_integration_assignments", text)
        self.assertIn("DROP TABLE IF EXISTS public.integration_connection_credentials", text)
        self.assertIn("DROP TABLE IF EXISTS public.integration_feeds", text)
        self.assertIn("DROP TABLE IF EXISTS public.integration_connections", text)

    def test_revert_drops_automation_job_accounts_before_integration_connections(self) -> None:
        text = Path("migrations/revert/create_automation_layer.sql").read_text(encoding="utf-8")

        child_pos = text.index("DROP TABLE IF EXISTS public.automation_job_accounts")
        parent_pos = text.index("DROP TABLE IF EXISTS public.integration_connections")
        self.assertLess(child_pos, parent_pos)

    def test_deploy_creates_connection_id_index_on_assignments(self) -> None:
        text = Path("migrations/deploy/create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("account_integration_assignments_connection_id_idx", text)
        self.assertIn(
            "ON public.account_integration_assignments (connection_id)",
            text,
        )

    def test_deploy_creates_connection_id_index_on_job_accounts(self) -> None:
        text = Path("migrations/deploy/create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("automation_job_accounts_connection_id_idx", text)
        self.assertIn(
            "ON public.automation_job_accounts (connection_id)",
            text,
        )

    def test_deploy_creates_connection_id_index_on_credentials(self) -> None:
        text = Path("migrations/deploy/create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("integration_connection_credentials_connection_id_idx", text)
        self.assertIn(
            "ON public.integration_connection_credentials (connection_id)",
            text,
        )

    def test_verify_checks_connection_tables(self) -> None:
        text = Path("migrations/verify/create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("public.integration_connections", text)
        self.assertIn("public.integration_connection_credentials", text)
        self.assertIn("public.integration_feeds", text)
        self.assertIn("public.account_integration_assignments", text)


class IntegrationConnectionFunctionTests(unittest.TestCase):
    """Task 3: Tests for connection management PostgreSQL functions."""

    DEPLOY = Path("migrations/deploy/create_automation_layer.sql")
    REVERT = Path("migrations/revert/create_automation_layer.sql")
    VERIFY = Path("migrations/verify/create_automation_layer.sql")

    def test_deploy_defines_create_integration_connection(self) -> None:
        sql = self.DEPLOY.read_text(encoding="utf-8")

        self.assertIn("CREATE FUNCTION public.create_integration_connection", sql)
        self.assertIn("p_integration_key TEXT", sql)
        self.assertIn("p_brokerage_code TEXT", sql)
        self.assertIn("p_name TEXT", sql)
        self.assertIn("RETURNS UUID", sql)

    def test_deploy_create_connection_validates_blank_integration_key(self) -> None:
        sql = self.DEPLOY.read_text(encoding="utf-8")

        self.assertIn("integration_key must not be blank", sql)

    def test_deploy_create_connection_validates_blank_name(self) -> None:
        sql = self.DEPLOY.read_text(encoding="utf-8")

        self.assertIn("connection name must not be blank", sql)

    def test_deploy_create_connection_looks_up_active_brokerage(self) -> None:
        sql = self.DEPLOY.read_text(encoding="utf-8")

        self.assertIn("Active brokerage not found for code:", sql)
        self.assertIn("b.is_active = true", sql)

    def test_deploy_defines_set_integration_credential(self) -> None:
        sql = self.DEPLOY.read_text(encoding="utf-8")

        self.assertIn("CREATE FUNCTION public.set_integration_credential", sql)
        self.assertIn("p_connection_id UUID", sql)
        self.assertIn("p_credential_name TEXT", sql)
        self.assertIn("p_ciphertext BYTEA", sql)
        self.assertIn("p_encryption_key_id TEXT", sql)
        self.assertIn("p_encryption_version INTEGER", sql)
        self.assertIn("RETURNS UUID", sql)

    def test_deploy_set_credential_rotates_existing_active_credential(self) -> None:
        sql = self.DEPLOY.read_text(encoding="utf-8")

        self.assertIn("is_active = false", sql)
        self.assertIn("rotated_at = now()", sql)

    def test_deploy_defines_create_integration_feed(self) -> None:
        sql = self.DEPLOY.read_text(encoding="utf-8")

        self.assertIn("CREATE FUNCTION public.create_integration_feed", sql)
        self.assertIn("p_feed_key TEXT", sql)
        self.assertIn("p_display_name TEXT DEFAULT NULL", sql)
        self.assertIn("RETURNS UUID", sql)

    def test_deploy_create_feed_validates_blank_feed_key(self) -> None:
        sql = self.DEPLOY.read_text(encoding="utf-8")

        self.assertIn("feed_key must not be blank", sql)

    def test_deploy_defines_set_account_integration_assignment(self) -> None:
        sql = self.DEPLOY.read_text(encoding="utf-8")

        self.assertIn("CREATE FUNCTION public.set_account_integration_assignment", sql)
        self.assertIn("p_account_external_id TEXT", sql)
        self.assertIn("RETURNS UUID", sql)

    def test_deploy_assignment_validates_brokerage_match(self) -> None:
        sql = self.DEPLOY.read_text(encoding="utf-8")

        self.assertIn("Account brokerage does not match integration connection brokerage", sql)

    def test_deploy_assignment_upserts_on_conflict(self) -> None:
        sql = self.DEPLOY.read_text(encoding="utf-8")

        self.assertIn("ON CONFLICT (account_id) DO UPDATE", sql)

    def test_deploy_defines_validate_account_integration_assignments(self) -> None:
        sql = self.DEPLOY.read_text(encoding="utf-8")

        self.assertIn("CREATE FUNCTION public.validate_account_integration_assignments", sql)
        self.assertIn("p_target_type TEXT", sql)
        self.assertIn("p_portfolio_name TEXT", sql)
        self.assertIn("RETURNS TABLE (account_external_id TEXT)", sql)

    def test_deploy_defines_list_integration_connections(self) -> None:
        sql = self.DEPLOY.read_text(encoding="utf-8")

        self.assertIn("CREATE FUNCTION public.list_integration_connections()", sql)

    def test_deploy_defines_list_integration_feeds(self) -> None:
        sql = self.DEPLOY.read_text(encoding="utf-8")

        self.assertIn("CREATE FUNCTION public.list_integration_feeds(p_connection_id UUID)", sql)

    def test_revert_drops_create_integration_connection(self) -> None:
        sql = self.REVERT.read_text(encoding="utf-8")

        self.assertIn("DROP FUNCTION IF EXISTS public.create_integration_connection(TEXT, TEXT, TEXT);", sql)

    def test_revert_drops_set_integration_credential(self) -> None:
        sql = self.REVERT.read_text(encoding="utf-8")

        self.assertIn(
            "DROP FUNCTION IF EXISTS public.set_integration_credential(UUID, TEXT, BYTEA, TEXT, INTEGER);",
            sql,
        )

    def test_revert_drops_create_integration_feed(self) -> None:
        sql = self.REVERT.read_text(encoding="utf-8")

        self.assertIn("DROP FUNCTION IF EXISTS public.create_integration_feed(UUID, TEXT, TEXT);", sql)

    def test_revert_drops_set_account_integration_assignment(self) -> None:
        sql = self.REVERT.read_text(encoding="utf-8")

        self.assertIn(
            "DROP FUNCTION IF EXISTS public.set_account_integration_assignment(TEXT, TEXT, UUID);",
            sql,
        )

    def test_revert_drops_validate_account_integration_assignments(self) -> None:
        sql = self.REVERT.read_text(encoding="utf-8")

        self.assertIn(
            "DROP FUNCTION IF EXISTS public.validate_account_integration_assignments(TEXT, TEXT, TEXT, TEXT[]);",
            sql,
        )

    def test_revert_drops_list_integration_connections(self) -> None:
        sql = self.REVERT.read_text(encoding="utf-8")

        self.assertIn("DROP FUNCTION IF EXISTS public.list_integration_connections();", sql)

    def test_revert_drops_list_integration_feeds(self) -> None:
        sql = self.REVERT.read_text(encoding="utf-8")

        self.assertIn("DROP FUNCTION IF EXISTS public.list_integration_feeds(UUID);", sql)

    def test_revert_drops_connection_functions_before_tables(self) -> None:
        sql = self.REVERT.read_text(encoding="utf-8")

        func_pos = sql.index("DROP FUNCTION IF EXISTS public.create_integration_connection")
        table_pos = sql.index("DROP TABLE IF EXISTS public.integration_connections")
        self.assertLess(func_pos, table_pos)

    def test_verify_checks_connection_management_functions(self) -> None:
        sql = self.VERIFY.read_text(encoding="utf-8")

        self.assertIn("to_regprocedure('public.create_integration_connection(text,text,text)')", sql)
        self.assertIn("to_regprocedure('public.set_integration_credential(uuid,text,bytea,text,integer)')", sql)
        self.assertIn("to_regprocedure('public.create_integration_feed(uuid,text,text)')", sql)
        self.assertIn("to_regprocedure('public.set_account_integration_assignment(text,text,uuid)')", sql)
        self.assertIn(
            "to_regprocedure('public.validate_account_integration_assignments(text,text,text,text[])')",
            sql,
        )
        self.assertIn("to_regprocedure('public.list_integration_connections()')", sql)
        self.assertIn("to_regprocedure('public.list_integration_feeds(uuid)')", sql)

    def test_verify_uses_error_raising_count_style_for_connection_functions(self) -> None:
        sql = self.VERIFY.read_text(encoding="utf-8")

        self.assertIn("count(*) = 7", sql)


if __name__ == "__main__":
    unittest.main()
