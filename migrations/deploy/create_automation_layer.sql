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

CREATE FUNCTION public.create_automation_job(
    p_trigger_type TEXT,
    p_target_type TEXT,
    p_portfolio_id UUID,
    p_integration_key TEXT,
    p_mode TEXT,
    p_requested_start_date DATE,
    p_requested_end_date DATE
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_id UUID;
    v_trigger_type TEXT;
    v_target_type TEXT;
    v_integration_key TEXT;
    v_mode TEXT;
BEGIN
    v_trigger_type := lower(btrim(p_trigger_type));
    v_target_type := lower(btrim(p_target_type));
    v_integration_key := lower(btrim(p_integration_key));
    v_mode := lower(btrim(p_mode));

    IF v_trigger_type = '' OR v_target_type = '' OR v_integration_key = '' OR v_mode = '' THEN
        RAISE EXCEPTION 'automation job trigger_type, target_type, integration_key, and mode must not be blank';
    END IF;

    INSERT INTO public.automation_jobs (
        trigger_type,
        target_type,
        portfolio_id,
        integration_key,
        mode,
        status,
        requested_start_date,
        requested_end_date
    )
    VALUES (
        v_trigger_type,
        v_target_type,
        p_portfolio_id,
        v_integration_key,
        v_mode,
        'running',
        p_requested_start_date,
        p_requested_end_date
    )
    RETURNING id INTO v_job_id;

    RETURN v_job_id;
END;
$$;

CREATE FUNCTION public.finalize_automation_job(
    p_automation_job_id UUID,
    p_status TEXT,
    p_summary JSONB DEFAULT NULL,
    p_error_message TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_id UUID;
    v_status TEXT;
BEGIN
    v_status := lower(btrim(p_status));

    IF v_status NOT IN ('succeeded', 'partially_succeeded', 'failed') THEN
        RAISE EXCEPTION 'Invalid final automation job status: %', p_status;
    END IF;

    UPDATE public.automation_jobs
    SET status = v_status,
        summary = p_summary,
        error_message = NULLIF(btrim(p_error_message), ''),
        completed_at = now()
    WHERE id = p_automation_job_id
      AND status IN ('pending', 'running')
    RETURNING id INTO v_job_id;

    IF v_job_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or already completed automation job id: %', p_automation_job_id;
    END IF;

    RETURN v_job_id;
END;
$$;

CREATE FUNCTION public.add_automation_job_account(
    p_automation_job_id UUID,
    p_account_id UUID
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_account_id UUID;
BEGIN
    INSERT INTO public.automation_job_accounts (
        automation_job_id,
        account_id,
        status
    )
    VALUES (
        p_automation_job_id,
        p_account_id,
        'pending'
    )
    RETURNING id INTO v_job_account_id;

    RETURN v_job_account_id;
END;
$$;

CREATE FUNCTION public.mark_automation_job_account_running(
    p_automation_job_account_id UUID
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_account_id UUID;
BEGIN
    UPDATE public.automation_job_accounts
    SET status = 'running',
        started_at = now()
    WHERE id = p_automation_job_account_id
      AND status = 'pending'
    RETURNING id INTO v_job_account_id;

    IF v_job_account_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or non-pending automation job account id: %', p_automation_job_account_id;
    END IF;

    RETURN v_job_account_id;
END;
$$;

CREATE FUNCTION public.finalize_automation_job_account(
    p_automation_job_account_id UUID,
    p_status TEXT,
    p_ingestion_run_id UUID DEFAULT NULL,
    p_summary JSONB DEFAULT NULL,
    p_error_message TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_account_id UUID;
    v_status TEXT;
BEGIN
    v_status := lower(btrim(p_status));

    IF v_status NOT IN ('succeeded', 'partially_succeeded', 'failed') THEN
        RAISE EXCEPTION 'Invalid final automation job account status: %', p_status;
    END IF;

    UPDATE public.automation_job_accounts
    SET status = v_status,
        ingestion_run_id = p_ingestion_run_id,
        summary = p_summary,
        error_message = NULLIF(btrim(p_error_message), ''),
        completed_at = now()
    WHERE id = p_automation_job_account_id
      AND status IN ('pending', 'running')
    RETURNING id INTO v_job_account_id;

    IF v_job_account_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or already completed automation job account id: %', p_automation_job_account_id;
    END IF;

    RETURN v_job_account_id;
END;
$$;

CREATE FUNCTION public.resolve_automation_portfolio_accounts(
    p_portfolio_name TEXT,
    p_brokerage_code TEXT
)
RETURNS TABLE (
    account_id UUID,
    brokerage_code TEXT,
    account_external_id TEXT,
    base_currency TEXT,
    display_name TEXT
)
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_portfolio_name IS NULL OR btrim(p_portfolio_name) = '' THEN
        RAISE EXCEPTION 'target_type=portfolio requires portfolio_name';
    END IF;

    RETURN QUERY
    SELECT a.id, b.code::TEXT, a.external_id::TEXT, a.base_currency::TEXT, a.display_name::TEXT
    FROM public.portfolio_accounts pa
    JOIN public.portfolios p ON p.id = pa.portfolio_id
    JOIN public.accounts a ON a.id = pa.account_id
    JOIN public.brokerages b ON b.id = a.brokerage_id
    WHERE p.name = btrim(p_portfolio_name)
      AND p.is_active = true
      AND a.is_active = true
      AND b.is_active = true
      AND b.code = upper(btrim(p_brokerage_code))
    ORDER BY b.code, a.external_id;
END;
$$;

CREATE FUNCTION public.resolve_automation_account_targets(
    p_brokerage_code TEXT,
    p_account_external_ids TEXT[]
)
RETURNS TABLE (
    account_id UUID,
    brokerage_code TEXT,
    account_external_id TEXT,
    base_currency TEXT,
    display_name TEXT
)
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_account_external_ids IS NULL OR array_length(p_account_external_ids, 1) IS NULL THEN
        RAISE EXCEPTION 'target_type=accounts requires account_external_ids';
    END IF;

    RETURN QUERY
    SELECT a.id, b.code::TEXT, a.external_id::TEXT, a.base_currency::TEXT, a.display_name::TEXT
    FROM public.accounts a
    JOIN public.brokerages b ON b.id = a.brokerage_id
    WHERE b.code = upper(btrim(p_brokerage_code))
      AND b.is_active = true
      AND a.is_active = true
      AND a.external_id = ANY(p_account_external_ids)
    ORDER BY b.code, a.external_id;
END;
$$;

CREATE FUNCTION public.fail_stale_automation_runs(
    p_stale_before TIMESTAMPTZ,
    p_error_message TEXT
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_child_count INTEGER;
    v_parent_count INTEGER;
BEGIN
    UPDATE public.automation_job_accounts
    SET status = 'failed',
        error_message = NULLIF(btrim(p_error_message), ''),
        completed_at = now()
    WHERE status = 'running'
      AND started_at < p_stale_before;
    GET DIAGNOSTICS v_child_count = ROW_COUNT;

    UPDATE public.automation_jobs
    SET status = 'failed',
        error_message = NULLIF(btrim(p_error_message), ''),
        completed_at = now()
    WHERE status = 'running'
      AND started_at < p_stale_before;
    GET DIAGNOSTICS v_parent_count = ROW_COUNT;

    RETURN v_child_count + v_parent_count;
END;
$$;

COMMIT;
