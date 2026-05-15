-- Deploy superfolio:create_automation_layer to pg

BEGIN;

CREATE TABLE public.integration_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_key VARCHAR(100) NOT NULL,
    brokerage_id UUID NOT NULL REFERENCES public.brokerages(id),
    name VARCHAR(120) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT integration_connections_key_not_blank_check CHECK (btrim(integration_key) <> ''),
    CONSTRAINT integration_connections_name_not_blank_check CHECK (btrim(name) <> ''),
    CONSTRAINT integration_connections_unique_name UNIQUE (brokerage_id, integration_key, name)
);

CREATE TABLE public.integration_connection_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL REFERENCES public.integration_connections(id) ON DELETE CASCADE,
    credential_name VARCHAR(200) NOT NULL,
    ciphertext BYTEA NOT NULL,
    encryption_key_id VARCHAR(100) NOT NULL,
    encryption_version INTEGER NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    rotated_at TIMESTAMPTZ,
    CONSTRAINT integration_connection_credentials_name_not_blank_check CHECK (btrim(credential_name) <> ''),
    CONSTRAINT integration_connection_credentials_key_id_not_blank_check CHECK (btrim(encryption_key_id) <> ''),
    CONSTRAINT integration_connection_credentials_version_positive_check CHECK (encryption_version > 0)
);

CREATE UNIQUE INDEX integration_connection_credentials_active_unique
    ON public.integration_connection_credentials (connection_id, credential_name)
    WHERE is_active = true;

CREATE INDEX integration_connection_credentials_connection_id_idx
    ON public.integration_connection_credentials (connection_id);

CREATE TABLE public.integration_feeds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL REFERENCES public.integration_connections(id) ON DELETE CASCADE,
    feed_key VARCHAR(100) NOT NULL,
    display_name VARCHAR(120),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT integration_feeds_key_not_blank_check CHECK (btrim(feed_key) <> ''),
    CONSTRAINT integration_feeds_key_no_colon_check CHECK (position(':' in feed_key) = 0),
    CONSTRAINT integration_feeds_unique_key UNIQUE (connection_id, feed_key)
);

CREATE TABLE public.account_integration_assignments (
    account_id UUID PRIMARY KEY REFERENCES public.accounts(id) ON DELETE CASCADE,
    connection_id UUID NOT NULL REFERENCES public.integration_connections(id),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX account_integration_assignments_connection_id_idx
    ON public.account_integration_assignments (connection_id);

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
    connection_id UUID REFERENCES public.integration_connections(id),
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

CREATE INDEX automation_job_accounts_connection_id_idx
    ON public.automation_job_accounts (connection_id);

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

    IF p_brokerage_code IS NULL OR btrim(p_brokerage_code) = '' THEN
        RAISE EXCEPTION 'automation target resolution requires brokerage_code';
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
    IF p_brokerage_code IS NULL OR btrim(p_brokerage_code) = '' THEN
        RAISE EXCEPTION 'automation target resolution requires brokerage_code';
    END IF;

    IF p_account_external_ids IS NULL OR array_length(p_account_external_ids, 1) IS NULL THEN
        RAISE EXCEPTION 'target_type=accounts requires account_external_ids';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM unnest(p_account_external_ids) AS requested(account_external_id)
        WHERE btrim(requested.account_external_id) <> ''
    ) THEN
        RAISE EXCEPTION 'target_type=accounts requires at least one non-blank account_external_id';
    END IF;

    RETURN QUERY
    SELECT a.id, b.code::TEXT, a.external_id::TEXT, a.base_currency::TEXT, a.display_name::TEXT
    FROM public.accounts a
    JOIN public.brokerages b ON b.id = a.brokerage_id
    WHERE b.code = upper(btrim(p_brokerage_code))
      AND b.is_active = true
      AND a.is_active = true
      AND a.external_id IN (
          SELECT btrim(requested.account_external_id)
          FROM unnest(p_account_external_ids) AS requested(account_external_id)
          WHERE btrim(requested.account_external_id) <> ''
      )
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
    IF p_stale_before IS NULL THEN
        RAISE EXCEPTION 'p_stale_before must not be NULL';
    END IF;

    UPDATE public.automation_job_accounts
    SET status = 'failed',
        error_message = NULLIF(btrim(p_error_message), ''),
        completed_at = now()
    WHERE status IN ('pending', 'running')
      AND (
          started_at < p_stale_before
          OR automation_job_id IN (
              SELECT id
              FROM public.automation_jobs
              WHERE status = 'running'
                AND started_at < p_stale_before
          )
      );
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

CREATE FUNCTION public.has_overlapping_automation_load(
    p_integration_key TEXT,
    p_account_id UUID,
    p_requested_start_date DATE,
    p_requested_end_date DATE,
    p_exclude_automation_job_id UUID
)
RETURNS BOOLEAN
LANGUAGE sql
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.automation_jobs j
        JOIN public.automation_job_accounts ja ON ja.automation_job_id = j.id
        WHERE j.integration_key = lower(btrim(p_integration_key))
          AND j.mode = 'load'
          AND j.status IN ('pending', 'running')
          AND ja.account_id = p_account_id
          AND ja.status IN ('pending', 'running')
          AND j.id <> p_exclude_automation_job_id
          AND daterange(j.requested_start_date, j.requested_end_date, '[]')
              && daterange(p_requested_start_date, p_requested_end_date, '[]')
    );
$$;

CREATE FUNCTION public.create_integration_connection(
    p_integration_key TEXT,
    p_brokerage_code TEXT,
    p_name TEXT
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_connection_id UUID;
    v_brokerage_id  UUID;
    v_integration_key TEXT;
    v_name TEXT;
BEGIN
    v_integration_key := lower(btrim(p_integration_key));
    v_name := btrim(p_name);

    IF v_integration_key = '' THEN
        RAISE EXCEPTION 'integration_key must not be blank';
    END IF;
    IF v_name = '' THEN
        RAISE EXCEPTION 'connection name must not be blank';
    END IF;

    SELECT id INTO v_brokerage_id
    FROM public.brokerages
    WHERE code = upper(btrim(p_brokerage_code))
      AND is_active = true;

    IF v_brokerage_id IS NULL THEN
        RAISE EXCEPTION 'Active brokerage not found for code: %', p_brokerage_code;
    END IF;

    INSERT INTO public.integration_connections (integration_key, brokerage_id, name)
    VALUES (v_integration_key, v_brokerage_id, v_name)
    RETURNING id INTO v_connection_id;

    RETURN v_connection_id;
END;
$$;

CREATE FUNCTION public.set_integration_credential(
    p_connection_id UUID,
    p_credential_name TEXT,
    p_ciphertext BYTEA,
    p_encryption_key_id TEXT,
    p_encryption_version INTEGER
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_credential_id UUID;
BEGIN
    UPDATE public.integration_connection_credentials
    SET is_active = false,
        rotated_at = now()
    WHERE connection_id = p_connection_id
      AND credential_name = btrim(p_credential_name)
      AND is_active = true;

    INSERT INTO public.integration_connection_credentials (
        connection_id,
        credential_name,
        ciphertext,
        encryption_key_id,
        encryption_version,
        is_active
    )
    VALUES (
        p_connection_id,
        btrim(p_credential_name),
        p_ciphertext,
        btrim(p_encryption_key_id),
        p_encryption_version,
        true
    )
    RETURNING id INTO v_credential_id;

    RETURN v_credential_id;
END;
$$;

CREATE FUNCTION public.create_integration_feed(
    p_connection_id UUID,
    p_feed_key TEXT,
    p_display_name TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_feed_id UUID;
    v_feed_key TEXT;
    v_display_name TEXT;
BEGIN
    v_feed_key := btrim(p_feed_key);
    v_display_name := CASE WHEN p_display_name IS NULL THEN NULL ELSE NULLIF(btrim(p_display_name), '') END;

    IF v_feed_key = '' THEN
        RAISE EXCEPTION 'feed_key must not be blank';
    END IF;

    INSERT INTO public.integration_feeds (connection_id, feed_key, display_name)
    VALUES (p_connection_id, v_feed_key, v_display_name)
    RETURNING id INTO v_feed_id;

    RETURN v_feed_id;
END;
$$;

CREATE FUNCTION public.set_account_integration_assignment(
    p_brokerage_code TEXT,
    p_account_external_id TEXT,
    p_connection_id UUID
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_account_id           UUID;
    v_account_brokerage_id UUID;
    v_connection_brokerage_id UUID;
BEGIN
    SELECT a.id, a.brokerage_id
    INTO v_account_id, v_account_brokerage_id
    FROM public.accounts a
    JOIN public.brokerages b ON b.id = a.brokerage_id
    WHERE b.code = upper(btrim(p_brokerage_code))
      AND b.is_active = true
      AND a.external_id = btrim(p_account_external_id)
      AND a.is_active = true;

    IF v_account_id IS NULL THEN
        RAISE EXCEPTION 'Active account % not found for brokerage %',
            p_account_external_id, p_brokerage_code;
    END IF;

    SELECT brokerage_id INTO v_connection_brokerage_id
    FROM public.integration_connections
    WHERE id = p_connection_id;

    IF v_connection_brokerage_id IS NULL THEN
        RAISE EXCEPTION 'Integration connection % not found', p_connection_id;
    END IF;

    IF v_account_brokerage_id <> v_connection_brokerage_id THEN
        RAISE EXCEPTION 'Account brokerage does not match integration connection brokerage';
    END IF;

    INSERT INTO public.account_integration_assignments (account_id, connection_id, is_active)
    VALUES (v_account_id, p_connection_id, true)
    ON CONFLICT (account_id) DO UPDATE
        SET connection_id = EXCLUDED.connection_id,
            is_active     = true,
            updated_at    = now();

    RETURN v_account_id;
END;
$$;

CREATE FUNCTION public.validate_account_integration_assignments(
    p_target_type TEXT,
    p_portfolio_name TEXT,
    p_brokerage_code TEXT,
    p_account_external_ids TEXT[]
)
RETURNS TABLE (account_external_id TEXT)
LANGUAGE plpgsql
AS $$
BEGIN
    IF btrim(coalesce(p_brokerage_code, '')) = '' THEN
        RAISE EXCEPTION 'validate_account_integration_assignments requires brokerage_code';
    END IF;

    IF lower(btrim(p_target_type)) = 'portfolio' THEN
        IF btrim(coalesce(p_portfolio_name, '')) = '' THEN
            RAISE EXCEPTION 'validate_account_integration_assignments requires portfolio_name when target_type is portfolio';
        END IF;
        RETURN QUERY
        SELECT a.external_id::TEXT
        FROM public.portfolio_accounts pa
        JOIN public.portfolios p ON p.id = pa.portfolio_id
        JOIN public.accounts a ON a.id = pa.account_id
        JOIN public.brokerages b ON b.id = a.brokerage_id
        WHERE p.name = btrim(p_portfolio_name)
          AND p.is_active = true
          AND b.code = upper(btrim(p_brokerage_code))
          AND b.is_active = true
          AND a.is_active = true
          AND NOT EXISTS (
              SELECT 1
              FROM public.account_integration_assignments aia
              WHERE aia.account_id = a.id
                AND aia.is_active = true
          )
        ORDER BY a.external_id;
    ELSE
        RETURN QUERY
        SELECT a.external_id::TEXT
        FROM public.accounts a
        JOIN public.brokerages b ON b.id = a.brokerage_id
        WHERE b.code = upper(btrim(p_brokerage_code))
          AND b.is_active = true
          AND a.is_active = true
          AND a.external_id IN (
              SELECT btrim(requested.ext_id)
              FROM unnest(p_account_external_ids) AS requested(ext_id)
              WHERE btrim(requested.ext_id) <> ''
          )
          AND NOT EXISTS (
              SELECT 1
              FROM public.account_integration_assignments aia
              WHERE aia.account_id = a.id
                AND aia.is_active = true
          )
        ORDER BY a.external_id;
    END IF;
END;
$$;

CREATE FUNCTION public.list_integration_connections()
RETURNS TABLE (
    id UUID,
    integration_key TEXT,
    brokerage_code TEXT,
    name TEXT,
    is_active BOOLEAN,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
)
LANGUAGE sql
AS $$
    SELECT c.id, c.integration_key::TEXT, b.code::TEXT, c.name::TEXT,
           c.is_active, c.created_at, c.updated_at
    FROM public.integration_connections c
    JOIN public.brokerages b ON b.id = c.brokerage_id
    ORDER BY c.name;
$$;

CREATE FUNCTION public.list_integration_feeds(p_connection_id UUID)
RETURNS TABLE (
    id UUID,
    connection_id UUID,
    feed_key TEXT,
    display_name TEXT,
    is_active BOOLEAN,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
)
LANGUAGE sql
AS $$
    SELECT id, connection_id, feed_key::TEXT, display_name::TEXT,
           is_active, created_at, updated_at
    FROM public.integration_feeds
    WHERE connection_id = p_connection_id
    ORDER BY feed_key;
$$;

COMMIT;
