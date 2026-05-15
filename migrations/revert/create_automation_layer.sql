-- Revert superfolio:create_automation_layer from pg

BEGIN;

DROP FUNCTION IF EXISTS public.list_integration_feeds(UUID);
DROP FUNCTION IF EXISTS public.list_integration_connections();
DROP FUNCTION IF EXISTS public.validate_account_integration_assignments(TEXT, TEXT, TEXT, TEXT[]);
DROP FUNCTION IF EXISTS public.set_account_integration_assignment(TEXT, TEXT, UUID);
DROP FUNCTION IF EXISTS public.create_integration_feed(UUID, TEXT, TEXT);
DROP FUNCTION IF EXISTS public.set_integration_credential(UUID, TEXT, BYTEA, TEXT, INTEGER);
DROP FUNCTION IF EXISTS public.create_integration_connection(TEXT, TEXT, TEXT);

DROP FUNCTION IF EXISTS public.has_overlapping_automation_load(TEXT, UUID, DATE, DATE, UUID);
DROP FUNCTION IF EXISTS public.fail_stale_automation_runs(TIMESTAMPTZ, TEXT);
DROP FUNCTION IF EXISTS public.resolve_automation_account_targets(TEXT, TEXT[]);
DROP FUNCTION IF EXISTS public.resolve_automation_portfolio_accounts(TEXT, TEXT);

DROP FUNCTION IF EXISTS public.finalize_automation_job_account(UUID, TEXT, UUID, JSONB, TEXT);
DROP FUNCTION IF EXISTS public.mark_automation_job_account_running(UUID);
DROP FUNCTION IF EXISTS public.add_automation_job_account(UUID, UUID);
DROP FUNCTION IF EXISTS public.finalize_automation_job(UUID, TEXT, JSONB, TEXT);
DROP FUNCTION IF EXISTS public.create_automation_job(TEXT, TEXT, UUID, TEXT, TEXT, DATE, DATE);

DROP TABLE IF EXISTS public.automation_job_accounts;
DROP TABLE IF EXISTS public.automation_jobs;

DROP TABLE IF EXISTS public.account_integration_assignments;
DROP TABLE IF EXISTS public.integration_connection_credentials;
DROP TABLE IF EXISTS public.integration_feeds;
DROP TABLE IF EXISTS public.integration_connections;

COMMIT;
