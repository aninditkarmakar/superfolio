-- Deploy superfolio:create_mvp_schema to pg

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE public.brokerages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(20) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    import_format VARCHAR(50) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT brokerages_code_not_blank_check CHECK (btrim(code) <> ''),
    CONSTRAINT brokerages_name_not_blank_check CHECK (btrim(name) <> ''),
    CONSTRAINT brokerages_import_format_not_blank_check CHECK (btrim(import_format) <> '')
);

CREATE TABLE public.accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brokerage_id UUID NOT NULL REFERENCES public.brokerages(id),
    external_id VARCHAR(50) NOT NULL,
    display_name VARCHAR(100),
    account_type VARCHAR(50) NOT NULL,
    base_currency CHAR(3) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT accounts_brokerage_external_id_key UNIQUE (brokerage_id, external_id),
    CONSTRAINT accounts_external_id_not_blank_check CHECK (btrim(external_id) <> ''),
    CONSTRAINT accounts_account_type_not_blank_check CHECK (btrim(account_type) <> ''),
    CONSTRAINT accounts_base_currency_uppercase_check CHECK (base_currency ~ '^[A-Z]{3}$')
);

CREATE TABLE public.ingestion_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brokerage_id UUID NOT NULL REFERENCES public.brokerages(id),
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    source_type VARCHAR(30) NOT NULL,
    status VARCHAR(30) NOT NULL,
    requested_start_date DATE,
    requested_end_date DATE,
    source_filename TEXT,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ingestion_runs_source_type_check CHECK (
        source_type IN ('FLEX_WEB_SERVICE', 'MANUAL_FILE')
    ),
    CONSTRAINT ingestion_runs_status_check CHECK (
        status IN ('pending', 'running', 'succeeded', 'partially_succeeded', 'failed')
    ),
    CONSTRAINT ingestion_runs_requested_date_range_check CHECK (
        requested_start_date IS NULL
        OR requested_end_date IS NULL
        OR requested_start_date <= requested_end_date
    ),
    CONSTRAINT ingestion_runs_completed_after_started_check CHECK (
        completed_at IS NULL OR completed_at >= started_at
    )
);

CREATE TABLE public.source_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingestion_run_id UUID NOT NULL REFERENCES public.ingestion_runs(id),
    brokerage_id UUID NOT NULL REFERENCES public.brokerages(id),
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    record_type VARCHAR(50) NOT NULL,
    external_record_id TEXT,
    dedupe_key TEXT NOT NULL,
    source_report_date DATE,
    source_currency CHAR(3),
    raw_payload JSONB,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT source_records_brokerage_dedupe_key UNIQUE (brokerage_id, dedupe_key),
    CONSTRAINT source_records_record_type_check CHECK (
        record_type IN ('CASH_TRANSACTION', 'DAILY_NAV')
    ),
    CONSTRAINT source_records_dedupe_key_not_blank_check CHECK (btrim(dedupe_key) <> ''),
    CONSTRAINT source_records_source_currency_uppercase_check CHECK (
        source_currency IS NULL OR source_currency ~ '^[A-Z]{3}$'
    )
);

CREATE TABLE public.cash_flows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    source_record_id UUID NOT NULL UNIQUE REFERENCES public.source_records(id),
    flow_date DATE NOT NULL,
    cash_flow_type VARCHAR(50) NOT NULL,
    currency CHAR(3) NOT NULL,
    amount NUMERIC(20, 8) NOT NULL,
    amount_base NUMERIC(20, 8) NOT NULL,
    fx_rate_to_base NUMERIC(20, 10),
    description TEXT,
    CONSTRAINT cash_flows_cash_flow_type_not_blank_check CHECK (btrim(cash_flow_type) <> ''),
    CONSTRAINT cash_flows_currency_uppercase_check CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT cash_flows_fx_rate_to_base_positive_check CHECK (
        fx_rate_to_base IS NULL OR fx_rate_to_base > 0
    )
);

CREATE TABLE public.daily_nav_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    source_record_id UUID NOT NULL UNIQUE REFERENCES public.source_records(id),
    snapshot_date DATE NOT NULL,
    base_currency CHAR(3) NOT NULL,
    nav_base NUMERIC(20, 8) NOT NULL,
    CONSTRAINT daily_nav_snapshots_account_snapshot_date_key UNIQUE (account_id, snapshot_date),
    CONSTRAINT daily_nav_snapshots_base_currency_uppercase_check CHECK (base_currency ~ '^[A-Z]{3}$')
);

CREATE INDEX source_records_account_id_idx ON public.source_records (account_id);
CREATE INDEX source_records_ingestion_run_id_idx ON public.source_records (ingestion_run_id);
CREATE INDEX cash_flows_account_flow_date_idx ON public.cash_flows (account_id, flow_date);
CREATE INDEX ingestion_runs_brokerage_started_at_idx
    ON public.ingestion_runs (brokerage_id, started_at);

INSERT INTO public.brokerages (code, name, import_format)
VALUES ('IBKR', 'Interactive Brokers', 'IBKR_FLEX_XML')
ON CONFLICT (code) DO NOTHING;

CREATE FUNCTION public.register_account(
    p_brokerage_code TEXT,
    p_external_id TEXT,
    p_account_type TEXT,
    p_base_currency TEXT,
    p_display_name TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_brokerage_id UUID;
    v_account_id UUID;
    v_normalized_brokerage_code TEXT;
    v_normalized_external_id TEXT;
    v_normalized_account_type TEXT;
    v_normalized_base_currency TEXT;
    v_existing_account_type TEXT;
    v_existing_base_currency TEXT;
BEGIN
    -- Validate required inputs: must not be NULL or blank
    IF p_brokerage_code IS NULL OR btrim(p_brokerage_code) = '' THEN
        RAISE EXCEPTION 'brokerage_code must not be NULL or blank';
    END IF;
    IF p_external_id IS NULL OR btrim(p_external_id) = '' THEN
        RAISE EXCEPTION 'external_id must not be NULL or blank';
    END IF;
    IF p_account_type IS NULL OR btrim(p_account_type) = '' THEN
        RAISE EXCEPTION 'account_type must not be NULL or blank';
    END IF;
    IF p_base_currency IS NULL OR btrim(p_base_currency) = '' THEN
        RAISE EXCEPTION 'base_currency must not be NULL or blank';
    END IF;

    -- Normalize inputs into local variables to avoid repeated operations and NULL ambiguity
    v_normalized_brokerage_code := upper(btrim(p_brokerage_code));
    v_normalized_external_id := btrim(p_external_id);
    v_normalized_account_type := btrim(p_account_type);
    v_normalized_base_currency := upper(btrim(p_base_currency));

    -- Resolve brokerage
    SELECT id INTO v_brokerage_id
    FROM public.brokerages
    WHERE code = v_normalized_brokerage_code
      AND is_active = true;

    IF v_brokerage_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or inactive brokerage code: %', p_brokerage_code;
    END IF;

    -- Atomically try to insert with conflict handling
    -- ON CONFLICT DO NOTHING ensures concurrent callers don't get duplicate-key errors
    INSERT INTO public.accounts (
        brokerage_id,
        external_id,
        display_name,
        account_type,
        base_currency
    )
    VALUES (
        v_brokerage_id,
        v_normalized_external_id,
        NULLIF(btrim(p_display_name), ''),
        v_normalized_account_type,
        v_normalized_base_currency
    )
    ON CONFLICT (brokerage_id, external_id) DO NOTHING
    RETURNING id INTO v_account_id;

    -- If INSERT returned an id, a new account was created
    IF v_account_id IS NOT NULL THEN
        RETURN v_account_id;
    END IF;

    -- INSERT returned no rows; account already exists. Fetch it and verify metadata.
    SELECT id, account_type, base_currency
      INTO v_account_id, v_existing_account_type, v_existing_base_currency
    FROM public.accounts
    WHERE brokerage_id = v_brokerage_id
      AND external_id = v_normalized_external_id;

    IF v_account_id IS NULL THEN
        RAISE EXCEPTION 'Unable to resolve account for brokerage %, external_id %',
            v_brokerage_id,
            v_normalized_external_id;
    END IF;

    -- Use IS DISTINCT FROM to handle NULL values correctly in metadata comparison
    IF v_existing_account_type IS DISTINCT FROM v_normalized_account_type
       OR v_existing_base_currency IS DISTINCT FROM v_normalized_base_currency THEN
        RAISE EXCEPTION
            'Account % already exists with account_type %, base_currency %',
            p_external_id,
            v_existing_account_type,
            v_existing_base_currency;
    END IF;

    RETURN v_account_id;
END;
$$;

CREATE FUNCTION public.update_account_metadata(
    p_account_id UUID,
    p_display_name TEXT,
    p_account_type TEXT
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_account_id UUID;
BEGIN
    IF p_account_type IS NULL OR btrim(p_account_type) = '' THEN
        RAISE EXCEPTION 'account_type must not be NULL or blank';
    END IF;

    UPDATE public.accounts
    SET display_name = NULLIF(btrim(p_display_name), ''),
        account_type = btrim(p_account_type),
        updated_at = now()
    WHERE id = p_account_id
    RETURNING id INTO v_account_id;

    IF v_account_id IS NULL THEN
        RAISE EXCEPTION 'Unknown account id: %', p_account_id;
    END IF;

    RETURN v_account_id;
END;
$$;

CREATE FUNCTION public.set_account_active(
    p_account_id UUID,
    p_is_active BOOLEAN
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_account_id UUID;
BEGIN
    IF p_is_active IS NULL THEN
        RAISE EXCEPTION 'is_active must not be NULL';
    END IF;

    UPDATE public.accounts
    SET is_active = p_is_active,
        updated_at = now()
    WHERE id = p_account_id
    RETURNING id INTO v_account_id;

    IF v_account_id IS NULL THEN
        RAISE EXCEPTION 'Unknown account id: %', p_account_id;
    END IF;

    RETURN v_account_id;
END;
$$;

CREATE FUNCTION public.start_ingestion_run(
    p_brokerage_code TEXT,
    p_account_external_id TEXT,
    p_source_type TEXT,
    p_requested_start_date DATE DEFAULT NULL,
    p_requested_end_date DATE DEFAULT NULL,
    p_source_filename TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_brokerage_id UUID;
    v_account_id UUID;
    v_ingestion_run_id UUID;
BEGIN
    IF p_source_type IS NULL OR btrim(p_source_type) = '' THEN
        RAISE EXCEPTION 'source_type must not be NULL or blank';
    END IF;

    IF p_account_external_id IS NULL OR btrim(p_account_external_id) = '' THEN
        RAISE EXCEPTION 'account_external_id must not be NULL or blank';
    END IF;

    SELECT id INTO v_brokerage_id
    FROM public.brokerages
    WHERE code = upper(btrim(p_brokerage_code))
      AND is_active = true;

    IF v_brokerage_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or inactive brokerage code: %', p_brokerage_code;
    END IF;

    SELECT id INTO v_account_id
    FROM public.accounts
    WHERE brokerage_id = v_brokerage_id
      AND external_id = btrim(p_account_external_id)
      AND is_active = true;

    IF v_account_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or inactive account external_id % for brokerage %',
            p_account_external_id,
            p_brokerage_code;
    END IF;

    INSERT INTO public.ingestion_runs (
        brokerage_id,
        account_id,
        source_type,
        status,
        requested_start_date,
        requested_end_date,
        source_filename
    )
    VALUES (
        v_brokerage_id,
        v_account_id,
        upper(btrim(p_source_type)),
        'running',
        p_requested_start_date,
        p_requested_end_date,
        NULLIF(btrim(p_source_filename), '')
    )
    RETURNING id INTO v_ingestion_run_id;

    RETURN v_ingestion_run_id;
END;
$$;

CREATE FUNCTION public.complete_ingestion_run(
    p_ingestion_run_id UUID,
    p_status TEXT,
    p_error_message TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_status TEXT;
    v_ingestion_run_id UUID;
BEGIN
    IF p_status IS NULL OR btrim(p_status) = '' THEN
        RAISE EXCEPTION 'status must not be NULL or blank';
    END IF;

    v_status := lower(btrim(p_status));

    IF v_status NOT IN ('succeeded', 'partially_succeeded', 'failed') THEN
        RAISE EXCEPTION 'Invalid final ingestion status: %', p_status;
    END IF;

    UPDATE public.ingestion_runs
    SET status = v_status,
        completed_at = now(),
        error_message = CASE
            WHEN v_status = 'succeeded' THEN NULL
            ELSE NULLIF(btrim(p_error_message), '')
        END
    WHERE id = p_ingestion_run_id
      AND status = 'running'
    RETURNING id INTO v_ingestion_run_id;

    IF v_ingestion_run_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or non-running ingestion run id: %', p_ingestion_run_id;
    END IF;

    RETURN v_ingestion_run_id;
END;
$$;

CREATE FUNCTION public._resolve_ingestion_account(
    p_brokerage_id UUID,
    p_account_external_id TEXT
)
RETURNS TABLE (
    account_id UUID,
    account_status TEXT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT a.id,
           CASE WHEN a.is_active THEN 'active' ELSE 'inactive' END
    FROM public.accounts a
    WHERE a.brokerage_id = p_brokerage_id
      AND a.external_id = btrim(p_account_external_id);

    IF NOT FOUND THEN
        RETURN QUERY SELECT NULL::UUID, 'unknown'::TEXT;
    END IF;
END;
$$;

CREATE FUNCTION public._insert_source_record(
    p_ingestion_run_id UUID,
    p_brokerage_id UUID,
    p_account_id UUID,
    p_record_type TEXT,
    p_external_record_id TEXT,
    p_dedupe_key TEXT,
    p_source_report_date DATE,
    p_source_currency TEXT,
    p_raw_payload JSONB
)
RETURNS TABLE (
    source_record_id UUID,
    was_inserted BOOLEAN
)
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO public.source_records (
        ingestion_run_id,
        brokerage_id,
        account_id,
        record_type,
        external_record_id,
        dedupe_key,
        source_report_date,
        source_currency,
        raw_payload
    )
    VALUES (
        p_ingestion_run_id,
        p_brokerage_id,
        p_account_id,
        upper(btrim(p_record_type)),
        NULLIF(btrim(p_external_record_id), ''),
        btrim(p_dedupe_key),
        p_source_report_date,
        NULLIF(upper(btrim(p_source_currency)), ''),
        p_raw_payload
    )
    ON CONFLICT (brokerage_id, dedupe_key) DO NOTHING
    RETURNING id, true
    INTO source_record_id, was_inserted;

    IF source_record_id IS NOT NULL THEN
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT sr.id, false
      INTO source_record_id, was_inserted
    FROM public.source_records sr
    WHERE sr.brokerage_id = p_brokerage_id
      AND sr.dedupe_key = btrim(p_dedupe_key);

    IF source_record_id IS NULL THEN
        RAISE EXCEPTION 'Unable to resolve source record for brokerage %, dedupe key %',
            p_brokerage_id,
            p_dedupe_key;
    END IF;

    RETURN NEXT;
END;
$$;

CREATE FUNCTION public.ingest_cash_flow(
    p_ingestion_run_id UUID,
    p_account_external_id TEXT,
    p_external_record_id TEXT,
    p_dedupe_key TEXT,
    p_source_report_date DATE,
    p_source_currency TEXT,
    p_raw_payload JSONB,
    p_flow_date DATE,
    p_cash_flow_type TEXT,
    p_currency TEXT,
    p_amount NUMERIC,
    p_amount_base NUMERIC,
    p_fx_rate_to_base NUMERIC DEFAULT NULL,
    p_description TEXT DEFAULT NULL
)
RETURNS TABLE (
    cash_flow_id UUID,
    source_record_id UUID,
    account_id UUID,
    record_status TEXT
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_brokerage_id UUID;
    v_account_status TEXT;
    v_was_inserted BOOLEAN;
BEGIN
    IF p_account_external_id IS NULL OR btrim(p_account_external_id) = '' THEN
        RAISE EXCEPTION 'account_external_id must not be NULL or blank';
    END IF;

    IF p_dedupe_key IS NULL OR btrim(p_dedupe_key) = '' THEN
        RAISE EXCEPTION 'dedupe_key must not be NULL or blank';
    END IF;

    IF p_cash_flow_type IS NULL OR btrim(p_cash_flow_type) = '' THEN
        RAISE EXCEPTION 'cash_flow_type must not be NULL or blank';
    END IF;

    IF p_currency IS NULL OR btrim(p_currency) = '' THEN
        RAISE EXCEPTION 'currency must not be NULL or blank';
    END IF;

    SELECT ir.brokerage_id INTO v_brokerage_id
    FROM public.ingestion_runs ir
    WHERE ir.id = p_ingestion_run_id
      AND ir.status = 'running';

    IF v_brokerage_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or non-running ingestion run id: %', p_ingestion_run_id;
    END IF;

    SELECT resolved.account_id, resolved.account_status
      INTO account_id, v_account_status
    FROM public._resolve_ingestion_account(v_brokerage_id, p_account_external_id) AS resolved;

    IF v_account_status = 'unknown' THEN
        cash_flow_id := NULL;
        source_record_id := NULL;
        record_status := 'skipped_unknown_account';
        RETURN NEXT;
        RETURN;
    END IF;

    IF v_account_status = 'inactive' THEN
        cash_flow_id := NULL;
        source_record_id := NULL;
        record_status := 'skipped_inactive_account';
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT inserted.source_record_id, inserted.was_inserted
      INTO source_record_id, v_was_inserted
    FROM public._insert_source_record(
        p_ingestion_run_id,
        v_brokerage_id,
        account_id,
        'CASH_TRANSACTION',
        p_external_record_id,
        p_dedupe_key,
        p_source_report_date,
        p_source_currency,
        p_raw_payload
    ) AS inserted;

    IF NOT v_was_inserted THEN
        SELECT cf.id INTO cash_flow_id
        FROM public.cash_flows cf
        WHERE cf.source_record_id = ingest_cash_flow.source_record_id;

        IF cash_flow_id IS NULL THEN
            RAISE EXCEPTION 'Source record % exists but no cash flow found', source_record_id;
        END IF;

        record_status := 'skipped_duplicate';
        RETURN NEXT;
        RETURN;
    END IF;

    INSERT INTO public.cash_flows (
        account_id,
        source_record_id,
        flow_date,
        cash_flow_type,
        currency,
        amount,
        amount_base,
        fx_rate_to_base,
        description
    )
    VALUES (
        account_id,
        source_record_id,
        p_flow_date,
        btrim(p_cash_flow_type),
        upper(btrim(p_currency)),
        p_amount,
        p_amount_base,
        p_fx_rate_to_base,
        NULLIF(btrim(p_description), '')
    )
    RETURNING id INTO cash_flow_id;

    record_status := 'inserted';
    RETURN NEXT;
END;
$$;

CREATE FUNCTION public.ingest_daily_nav_snapshot(
    p_ingestion_run_id UUID,
    p_account_external_id TEXT,
    p_external_record_id TEXT,
    p_dedupe_key TEXT,
    p_source_report_date DATE,
    p_source_currency TEXT,
    p_raw_payload JSONB,
    p_snapshot_date DATE,
    p_base_currency TEXT,
    p_nav_base NUMERIC
)
RETURNS TABLE (
    daily_nav_snapshot_id UUID,
    source_record_id UUID,
    account_id UUID,
    record_status TEXT
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_brokerage_id UUID;
    v_account_status TEXT;
    v_was_inserted BOOLEAN;
BEGIN
    IF p_account_external_id IS NULL OR btrim(p_account_external_id) = '' THEN
        RAISE EXCEPTION 'account_external_id must not be NULL or blank';
    END IF;

    IF p_dedupe_key IS NULL OR btrim(p_dedupe_key) = '' THEN
        RAISE EXCEPTION 'dedupe_key must not be NULL or blank';
    END IF;

    IF p_base_currency IS NULL OR btrim(p_base_currency) = '' THEN
        RAISE EXCEPTION 'base_currency must not be NULL or blank';
    END IF;

    IF p_snapshot_date IS NULL THEN
        RAISE EXCEPTION 'snapshot_date must not be NULL';
    END IF;

    IF p_nav_base IS NULL THEN
        RAISE EXCEPTION 'nav_base must not be NULL';
    END IF;

    SELECT ir.brokerage_id INTO v_brokerage_id
    FROM public.ingestion_runs ir
    WHERE ir.id = p_ingestion_run_id
      AND ir.status = 'running';

    IF v_brokerage_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or non-running ingestion run id: %', p_ingestion_run_id;
    END IF;

    SELECT resolved.account_id, resolved.account_status
      INTO account_id, v_account_status
    FROM public._resolve_ingestion_account(v_brokerage_id, p_account_external_id) AS resolved;

    IF v_account_status = 'unknown' THEN
        daily_nav_snapshot_id := NULL;
        source_record_id := NULL;
        record_status := 'skipped_unknown_account';
        RETURN NEXT;
        RETURN;
    END IF;

    IF v_account_status = 'inactive' THEN
        daily_nav_snapshot_id := NULL;
        source_record_id := NULL;
        record_status := 'skipped_inactive_account';
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT sr.id INTO source_record_id
    FROM public.source_records sr
    WHERE sr.brokerage_id = v_brokerage_id
      AND sr.dedupe_key = btrim(p_dedupe_key);

    IF source_record_id IS NOT NULL THEN
        SELECT dns.id INTO daily_nav_snapshot_id
        FROM public.daily_nav_snapshots dns
        WHERE dns.source_record_id = ingest_daily_nav_snapshot.source_record_id;

        IF daily_nav_snapshot_id IS NULL THEN
            RAISE EXCEPTION 'Source record % exists but no daily NAV snapshot found', source_record_id;
        END IF;

        record_status := 'skipped_duplicate';
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT dns.id INTO daily_nav_snapshot_id
    FROM public.daily_nav_snapshots dns
    WHERE dns.account_id = ingest_daily_nav_snapshot.account_id
      AND dns.snapshot_date = p_snapshot_date;

    IF daily_nav_snapshot_id IS NOT NULL THEN
        source_record_id := NULL;
        record_status := 'conflict_existing_snapshot';
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT inserted.source_record_id, inserted.was_inserted
      INTO source_record_id, v_was_inserted
    FROM public._insert_source_record(
        p_ingestion_run_id,
        v_brokerage_id,
        account_id,
        'DAILY_NAV',
        p_external_record_id,
        p_dedupe_key,
        p_source_report_date,
        p_source_currency,
        p_raw_payload
    ) AS inserted;

    IF NOT v_was_inserted THEN
        SELECT dns.id INTO daily_nav_snapshot_id
        FROM public.daily_nav_snapshots dns
        WHERE dns.source_record_id = ingest_daily_nav_snapshot.source_record_id;

        IF daily_nav_snapshot_id IS NULL THEN
            RAISE EXCEPTION 'Source record % exists but no daily NAV snapshot found', source_record_id;
        END IF;

        record_status := 'skipped_duplicate';
        RETURN NEXT;
        RETURN;
    END IF;

    INSERT INTO public.daily_nav_snapshots (
        account_id,
        source_record_id,
        snapshot_date,
        base_currency,
        nav_base
    )
    VALUES (
        account_id,
        source_record_id,
        p_snapshot_date,
        upper(btrim(p_base_currency)),
        p_nav_base
    )
    ON CONFLICT ON CONSTRAINT daily_nav_snapshots_account_snapshot_date_key DO NOTHING
    RETURNING id INTO daily_nav_snapshot_id;

    IF daily_nav_snapshot_id IS NULL THEN
        SELECT dns.id INTO daily_nav_snapshot_id
        FROM public.daily_nav_snapshots dns
        WHERE dns.account_id = ingest_daily_nav_snapshot.account_id
          AND dns.snapshot_date = p_snapshot_date;

        IF daily_nav_snapshot_id IS NULL THEN
            RAISE EXCEPTION 'Unable to resolve daily NAV snapshot for account %, snapshot date %',
                account_id,
                p_snapshot_date;
        END IF;

        IF v_was_inserted AND source_record_id IS NOT NULL THEN
            DELETE FROM public.source_records sr
            WHERE sr.id = ingest_daily_nav_snapshot.source_record_id;
        END IF;

        source_record_id := NULL;
        record_status := 'conflict_existing_snapshot';
        RETURN NEXT;
        RETURN;
    END IF;

    record_status := 'inserted';
    RETURN NEXT;
END;
$$;

CREATE FUNCTION public.bulk_ingest_cash_flows(
    p_ingestion_run_id UUID,
    p_records JSONB
)
RETURNS TABLE (
    inserted_count INTEGER,
    duplicate_count INTEGER,
    skipped_unknown_account_count INTEGER,
    skipped_inactive_account_count INTEGER,
    conflict_count INTEGER,
    skipped_accounts TEXT[],
    record_results JSONB
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_record JSONB;
    v_inserted_count INTEGER := 0;
    v_duplicate_count INTEGER := 0;
    v_skipped_unknown_account_count INTEGER := 0;
    v_skipped_inactive_account_count INTEGER := 0;
    v_conflict_count INTEGER := 0;
    v_skipped_accounts TEXT[] := ARRAY[]::TEXT[];
    v_record_results JSONB := '[]'::JSONB;
    v_result RECORD;
    v_account_external_id TEXT;
    v_dedupe_key TEXT;
BEGIN
    IF p_records IS NULL THEN
        RAISE EXCEPTION 'bulk_ingest_cash_flows expects a JSONB array';
    END IF;

    IF jsonb_typeof(p_records) <> 'array' THEN
        RAISE EXCEPTION 'bulk_ingest_cash_flows expects a JSONB array';
    END IF;

    FOR v_record IN SELECT jsonb_array_elements(p_records)
    LOOP
        v_account_external_id := v_record->>'account_external_id';
        v_dedupe_key := v_record->>'dedupe_key';

        SELECT result.cash_flow_id, result.source_record_id, result.account_id, result.record_status
        INTO v_result
        FROM public.ingest_cash_flow(
            p_ingestion_run_id,
            v_account_external_id,
            v_record->>'external_record_id',
            v_dedupe_key,
            (v_record->>'source_report_date')::DATE,
            v_record->>'source_currency',
            v_record->'raw_payload',
            (v_record->>'flow_date')::DATE,
            v_record->>'cash_flow_type',
            v_record->>'currency',
            (v_record->>'amount')::NUMERIC,
            (v_record->>'amount_base')::NUMERIC,
            (v_record->>'fx_rate_to_base')::NUMERIC,
            v_record->>'description'
        ) AS result;

        IF v_result.record_status = 'inserted' THEN
            v_inserted_count := v_inserted_count + 1;
        ELSIF v_result.record_status = 'skipped_duplicate' THEN
            v_duplicate_count := v_duplicate_count + 1;
        ELSIF v_result.record_status = 'skipped_unknown_account' THEN
            v_skipped_unknown_account_count := v_skipped_unknown_account_count + 1;
            v_skipped_accounts := array_append(v_skipped_accounts, v_account_external_id);
        ELSIF v_result.record_status = 'skipped_inactive_account' THEN
            v_skipped_inactive_account_count := v_skipped_inactive_account_count + 1;
            v_skipped_accounts := array_append(v_skipped_accounts, v_account_external_id);
        ELSIF v_result.record_status = 'conflict_existing_snapshot' THEN
            v_conflict_count := v_conflict_count + 1;
        END IF;

        v_record_results := v_record_results || jsonb_build_array(
            jsonb_build_object(
                'account_external_id', v_account_external_id,
                'dedupe_key', v_dedupe_key,
                'record_status', v_result.record_status,
                'cash_flow_id', v_result.cash_flow_id,
                'source_record_id', v_result.source_record_id,
                'account_id', v_result.account_id
            )
        );
    END LOOP;

    inserted_count := v_inserted_count;
    duplicate_count := v_duplicate_count;
    skipped_unknown_account_count := v_skipped_unknown_account_count;
    skipped_inactive_account_count := v_skipped_inactive_account_count;
    conflict_count := v_conflict_count;
    skipped_accounts := COALESCE(
        (SELECT ARRAY_AGG(DISTINCT x ORDER BY x) FROM UNNEST(v_skipped_accounts) AS t(x)),
        ARRAY[]::TEXT[]
    );
    record_results := v_record_results;
    RETURN NEXT;
END;
$$;

CREATE FUNCTION public.bulk_ingest_daily_nav_snapshots(
    p_ingestion_run_id UUID,
    p_records JSONB
)
RETURNS TABLE (
    inserted_count INTEGER,
    duplicate_count INTEGER,
    skipped_unknown_account_count INTEGER,
    skipped_inactive_account_count INTEGER,
    conflict_count INTEGER,
    skipped_accounts TEXT[],
    record_results JSONB
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_record JSONB;
    v_inserted_count INTEGER := 0;
    v_duplicate_count INTEGER := 0;
    v_skipped_unknown_account_count INTEGER := 0;
    v_skipped_inactive_account_count INTEGER := 0;
    v_conflict_count INTEGER := 0;
    v_skipped_accounts TEXT[] := ARRAY[]::TEXT[];
    v_record_results JSONB := '[]'::JSONB;
    v_result RECORD;
    v_account_external_id TEXT;
    v_dedupe_key TEXT;
BEGIN
    IF p_records IS NULL THEN
        RAISE EXCEPTION 'bulk_ingest_daily_nav_snapshots expects a JSONB array';
    END IF;

    IF jsonb_typeof(p_records) <> 'array' THEN
        RAISE EXCEPTION 'bulk_ingest_daily_nav_snapshots expects a JSONB array';
    END IF;

    FOR v_record IN SELECT jsonb_array_elements(p_records)
    LOOP
        v_account_external_id := v_record->>'account_external_id';
        v_dedupe_key := v_record->>'dedupe_key';

        SELECT result.daily_nav_snapshot_id, result.source_record_id, result.account_id, result.record_status
        INTO v_result
        FROM public.ingest_daily_nav_snapshot(
            p_ingestion_run_id,
            v_account_external_id,
            v_record->>'external_record_id',
            v_dedupe_key,
            (v_record->>'source_report_date')::DATE,
            v_record->>'source_currency',
            v_record->'raw_payload',
            (v_record->>'snapshot_date')::DATE,
            v_record->>'base_currency',
            (v_record->>'nav_base')::NUMERIC
        ) AS result;

        IF v_result.record_status = 'inserted' THEN
            v_inserted_count := v_inserted_count + 1;
        ELSIF v_result.record_status = 'skipped_duplicate' THEN
            v_duplicate_count := v_duplicate_count + 1;
        ELSIF v_result.record_status = 'skipped_unknown_account' THEN
            v_skipped_unknown_account_count := v_skipped_unknown_account_count + 1;
            v_skipped_accounts := array_append(v_skipped_accounts, v_account_external_id);
        ELSIF v_result.record_status = 'skipped_inactive_account' THEN
            v_skipped_inactive_account_count := v_skipped_inactive_account_count + 1;
            v_skipped_accounts := array_append(v_skipped_accounts, v_account_external_id);
        ELSIF v_result.record_status = 'conflict_existing_snapshot' THEN
            v_conflict_count := v_conflict_count + 1;
        END IF;

        v_record_results := v_record_results || jsonb_build_array(
            jsonb_build_object(
                'account_external_id', v_account_external_id,
                'dedupe_key', v_dedupe_key,
                'record_status', v_result.record_status,
                'daily_nav_snapshot_id', v_result.daily_nav_snapshot_id,
                'source_record_id', v_result.source_record_id,
                'account_id', v_result.account_id
            )
        );
    END LOOP;

    inserted_count := v_inserted_count;
    duplicate_count := v_duplicate_count;
    skipped_unknown_account_count := v_skipped_unknown_account_count;
    skipped_inactive_account_count := v_skipped_inactive_account_count;
    conflict_count := v_conflict_count;
    skipped_accounts := COALESCE(
        (SELECT ARRAY_AGG(DISTINCT x ORDER BY x) FROM UNNEST(v_skipped_accounts) AS t(x)),
        ARRAY[]::TEXT[]
    );
    record_results := v_record_results;
    RETURN NEXT;
END;
$$;

COMMIT;
