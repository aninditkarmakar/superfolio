-- Verify superfolio:create_automation_layer on pg

SELECT id, trigger_type, target_type, portfolio_id, integration_key, mode, status,
       summary, requested_start_date, requested_end_date, error_message,
       started_at, completed_at, created_at
FROM public.automation_jobs
WHERE false;

SELECT id, automation_job_id, account_id, status, ingestion_run_id, summary,
       error_message, started_at, completed_at, created_at
FROM public.automation_job_accounts
WHERE false;

SELECT 1 / (count(*) = 4)::int
FROM pg_constraint
WHERE conname IN (
    'automation_jobs_target_type_check',
    'automation_jobs_portfolio_target_check',
    'automation_jobs_manual_dates_required_check',
    'automation_job_accounts_unique_account'
);

SELECT 1 / (count(*) = 5)::int
FROM (
    VALUES
        (to_regprocedure('public.create_automation_job(text,text,uuid,text,text,date,date)')),
        (to_regprocedure('public.finalize_automation_job(uuid,text,jsonb,text)')),
        (to_regprocedure('public.add_automation_job_account(uuid,uuid)')),
        (to_regprocedure('public.mark_automation_job_account_running(uuid)')),
        (to_regprocedure('public.finalize_automation_job_account(uuid,text,uuid,jsonb,text)'))
) AS functions(signature)
WHERE signature IS NOT NULL;

SELECT 1 / (count(*) = 3)::int
FROM (
    VALUES
        (to_regprocedure('public.resolve_automation_portfolio_accounts(text,text)')),
        (to_regprocedure('public.resolve_automation_account_targets(text,text[])')),
        (to_regprocedure('public.fail_stale_automation_runs(timestamptz,text)'))
) AS functions(signature)
WHERE signature IS NOT NULL;

SELECT 1 / (count(*) = 1)::int
FROM (
    VALUES
        (to_regprocedure('public.has_overlapping_automation_load(text,uuid,date,date,uuid)'))
) AS functions(signature)
WHERE signature IS NOT NULL;
