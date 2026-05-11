-- Revert superfolio:create_mvp_schema from pg

BEGIN;

DELETE FROM public.brokerages
WHERE code = 'IBKR'
  AND name = 'Interactive Brokers'
  AND import_format = 'IBKR_FLEX_XML';

DROP TABLE IF EXISTS public.daily_nav_snapshots;
DROP TABLE IF EXISTS public.cash_flows;
DROP TABLE IF EXISTS public.source_records;
DROP TABLE IF EXISTS public.ingestion_runs;
DROP TABLE IF EXISTS public.accounts;
DROP TABLE IF EXISTS public.brokerages;

COMMIT;
