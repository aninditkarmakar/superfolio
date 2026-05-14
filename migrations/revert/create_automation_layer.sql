-- Revert superfolio:create_automation_layer from pg

BEGIN;

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

COMMIT;
