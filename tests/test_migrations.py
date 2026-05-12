from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCHEMA = REPO_ROOT / "migrations" / "deploy" / "create_mvp_schema.sql"
REVERT_SCHEMA = REPO_ROOT / "migrations" / "revert" / "create_mvp_schema.sql"
VERIFY_SCHEMA = REPO_ROOT / "migrations" / "verify" / "create_mvp_schema.sql"

LEGACY_START_INGESTION_RUN_SIGNATURE = (
    "public.start_ingestion_run(TEXT, TEXT, DATE, DATE, TEXT)"
)
ACCOUNT_SCOPED_START_INGESTION_RUN_SIGNATURE = (
    "public.start_ingestion_run(TEXT, TEXT, TEXT, DATE, DATE, TEXT)"
)


class MigrationContractTests(unittest.TestCase):
    def test_deploy_removes_legacy_start_ingestion_run_overload_before_create(self) -> None:
        sql = DEPLOY_SCHEMA.read_text(encoding="utf-8")
        legacy_drop = f"DROP FUNCTION IF EXISTS {LEGACY_START_INGESTION_RUN_SIGNATURE};"
        create = "CREATE FUNCTION public.start_ingestion_run("

        self.assertIn(legacy_drop, sql)
        self.assertLess(sql.index(legacy_drop), sql.index(create))

    def test_revert_drops_current_and_legacy_start_ingestion_run_signatures(self) -> None:
        sql = REVERT_SCHEMA.read_text(encoding="utf-8")

        self.assertIn(
            f"DROP FUNCTION IF EXISTS {ACCOUNT_SCOPED_START_INGESTION_RUN_SIGNATURE};",
            sql,
        )
        self.assertIn(
            f"DROP FUNCTION IF EXISTS {LEGACY_START_INGESTION_RUN_SIGNATURE};",
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


if __name__ == "__main__":
    unittest.main()
