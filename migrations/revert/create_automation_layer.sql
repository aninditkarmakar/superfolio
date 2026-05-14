-- Revert superfolio:create_automation_layer from pg

BEGIN;

DROP TABLE IF EXISTS public.automation_job_accounts;
DROP TABLE IF EXISTS public.automation_jobs;

COMMIT;
