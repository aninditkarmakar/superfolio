-- Deploy superfolio:create_automation_layer to pg

BEGIN;

CREATE TABLE public.automation_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_type VARCHAR(30) NOT NULL,
    target_type VARCHAR(30) NOT NULL,
    portfolio_id UUID REFERENCES public.portfolios(id),
    integration_key VARCHAR(100) NOT NULL,
    mode VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL,
    summary JSONB,
    requested_start_date DATE,
    requested_end_date DATE,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT automation_jobs_trigger_type_check CHECK (
        trigger_type IN ('manual', 'scheduled')
    ),
    CONSTRAINT automation_jobs_target_type_check CHECK (
        target_type IN ('portfolio', 'accounts')
    ),
    CONSTRAINT automation_jobs_portfolio_target_check CHECK (
        (target_type = 'portfolio' AND portfolio_id IS NOT NULL)
        OR (target_type = 'accounts' AND portfolio_id IS NULL)
    ),
    CONSTRAINT automation_jobs_integration_key_not_blank_check CHECK (btrim(integration_key) <> ''),
    CONSTRAINT automation_jobs_mode_check CHECK (mode IN ('dry-run', 'load')),
    CONSTRAINT automation_jobs_status_check CHECK (
        status IN ('pending', 'running', 'succeeded', 'partially_succeeded', 'failed')
    ),
    CONSTRAINT automation_jobs_manual_dates_required_check CHECK (
        trigger_type <> 'manual'
        OR (requested_start_date IS NOT NULL AND requested_end_date IS NOT NULL)
    ),
    CONSTRAINT automation_jobs_requested_date_range_check CHECK (
        requested_start_date IS NULL
        OR requested_end_date IS NULL
        OR requested_start_date <= requested_end_date
    ),
    CONSTRAINT automation_jobs_completed_after_started_check CHECK (
        completed_at IS NULL OR completed_at >= started_at
    )
);

CREATE TABLE public.automation_job_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    automation_job_id UUID NOT NULL REFERENCES public.automation_jobs(id) ON DELETE CASCADE,
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    status VARCHAR(30) NOT NULL,
    ingestion_run_id UUID REFERENCES public.ingestion_runs(id),
    summary JSONB,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT automation_job_accounts_unique_account UNIQUE (automation_job_id, account_id),
    CONSTRAINT automation_job_accounts_status_check CHECK (
        status IN ('pending', 'running', 'succeeded', 'partially_succeeded', 'failed')
    ),
    CONSTRAINT automation_job_accounts_completed_after_started_check CHECK (
        completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at
    )
);

CREATE INDEX automation_jobs_status_started_at_idx
    ON public.automation_jobs (status, started_at);

CREATE INDEX automation_jobs_integration_mode_dates_idx
    ON public.automation_jobs (integration_key, mode, requested_start_date, requested_end_date);

CREATE INDEX automation_job_accounts_account_status_idx
    ON public.automation_job_accounts (account_id, status);

CREATE INDEX automation_job_accounts_ingestion_run_id_idx
    ON public.automation_job_accounts (ingestion_run_id);

COMMIT;
