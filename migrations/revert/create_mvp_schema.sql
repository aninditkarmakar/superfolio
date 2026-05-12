-- Revert superfolio:create_mvp_schema from pg

BEGIN;

DROP FUNCTION IF EXISTS public.bulk_ingest_daily_nav_snapshots(UUID, JSONB);
DROP FUNCTION IF EXISTS public.bulk_ingest_cash_flows(UUID, JSONB);
DROP FUNCTION IF EXISTS public.ingest_daily_nav_snapshot(UUID, TEXT, TEXT, TEXT, DATE, TEXT, JSONB, DATE, TEXT, NUMERIC);
DROP FUNCTION IF EXISTS public.ingest_cash_flow(UUID, TEXT, TEXT, TEXT, DATE, TEXT, JSONB, DATE, TEXT, TEXT, NUMERIC, NUMERIC, NUMERIC, TEXT);
DROP FUNCTION IF EXISTS public._insert_source_record(UUID, UUID, UUID, TEXT, TEXT, TEXT, DATE, TEXT, JSONB);
DROP FUNCTION IF EXISTS public._resolve_ingestion_account(UUID, TEXT);
DROP FUNCTION IF EXISTS public.complete_ingestion_run(UUID, TEXT, TEXT);
DROP FUNCTION IF EXISTS public.start_ingestion_run(TEXT, TEXT, TEXT, DATE, DATE, TEXT);
DROP FUNCTION IF EXISTS public.set_account_active(UUID, BOOLEAN);
DROP FUNCTION IF EXISTS public.update_account_metadata(UUID, TEXT, TEXT);
DROP FUNCTION IF EXISTS public.register_account(TEXT, TEXT, TEXT, TEXT, TEXT);

DROP TABLE IF EXISTS public.daily_nav_snapshots;
DROP TABLE IF EXISTS public.cash_flows;
DROP TABLE IF EXISTS public.source_records;
DROP TABLE IF EXISTS public.ingestion_runs;
DROP TABLE IF EXISTS public.accounts;
DROP TABLE IF EXISTS public.brokerages;

COMMIT;
