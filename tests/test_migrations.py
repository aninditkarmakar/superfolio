from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
REVERT_SCHEMA = MIGRATIONS_DIR / "revert" / "create_mvp_schema.sql"
VERIFY_SCHEMA = MIGRATIONS_DIR / "verify" / "create_mvp_schema.sql"

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


if __name__ == "__main__":
    unittest.main()
