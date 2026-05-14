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


if __name__ == "__main__":
    unittest.main()
