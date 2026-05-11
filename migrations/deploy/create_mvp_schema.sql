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
        status IN ('pending', 'running', 'succeeded', 'failed')
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

COMMIT;
