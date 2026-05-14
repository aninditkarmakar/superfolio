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
