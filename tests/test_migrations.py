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


if __name__ == "__main__":
    unittest.main()
