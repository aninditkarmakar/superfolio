-- Verify superfolio:create_mvp_schema on pg

BEGIN;

SELECT 1 / count(*)
FROM pg_extension
WHERE extname = 'pgcrypto';

SELECT 1 / (count(*) = 6)::int
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
      'brokerages',
      'accounts',
      'ingestion_runs',
      'source_records',
      'cash_flows',
      'daily_nav_snapshots'
  );

SELECT 1 / (count(*) = 7)::int
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'brokerages'
  AND column_name IN (
      'id',
      'code',
      'name',
      'import_format',
      'is_active',
      'created_at',
      'updated_at'
  );

SELECT 1 / (count(*) = 9)::int
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'accounts'
  AND column_name IN (
      'id',
      'brokerage_id',
      'external_id',
      'display_name',
      'account_type',
      'base_currency',
      'is_active',
      'created_at',
      'updated_at'
  );

SELECT 1 / (count(*) = 12)::int
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'ingestion_runs'
  AND column_name IN (
      'id',
      'brokerage_id',
      'account_id',
      'source_type',
      'status',
      'requested_start_date',
      'requested_end_date',
      'source_filename',
      'error_message',
      'started_at',
      'completed_at',
      'created_at'
  );

SELECT 1 / count(*)
FROM pg_constraint c
JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'public'
  AND t.relname = 'ingestion_runs'
  AND c.conname = 'ingestion_runs_status_check'
  AND pg_get_constraintdef(c.oid) LIKE '%partially_succeeded%';

SELECT 1 / (count(*) = 11)::int
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'source_records'
  AND column_name IN (
      'id',
      'ingestion_run_id',
      'brokerage_id',
      'account_id',
      'record_type',
      'external_record_id',
      'dedupe_key',
      'source_report_date',
      'source_currency',
      'raw_payload',
      'first_seen_at'
  );

SELECT 1 / (count(*) = 10)::int
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'cash_flows'
  AND column_name IN (
      'id',
      'account_id',
      'source_record_id',
      'flow_date',
      'cash_flow_type',
      'currency',
      'amount',
      'amount_base',
      'fx_rate_to_base',
      'description'
  );

SELECT 1 / (count(*) = 6)::int
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'daily_nav_snapshots'
  AND column_name IN (
      'id',
      'account_id',
      'source_record_id',
      'snapshot_date',
      'base_currency',
      'nav_base'
  );

SELECT 1 / (count(*) = 16)::int
FROM information_schema.table_constraints
WHERE table_schema = 'public'
  AND constraint_name IN (
      'brokerages_code_key',
      'brokerages_code_not_blank_check',
      'brokerages_name_not_blank_check',
      'brokerages_import_format_not_blank_check',
      'accounts_brokerage_external_id_key',
      'accounts_external_id_not_blank_check',
      'accounts_account_type_not_blank_check',
      'accounts_base_currency_uppercase_check',
      'ingestion_runs_source_type_check',
      'ingestion_runs_status_check',
      'ingestion_runs_requested_date_range_check',
      'ingestion_runs_completed_after_started_check',
      'source_records_brokerage_dedupe_key',
      'source_records_record_type_check',
      'source_records_dedupe_key_not_blank_check',
      'source_records_source_currency_uppercase_check'
  );

SELECT 1 / (count(*) = 7)::int
FROM information_schema.table_constraints
WHERE table_schema = 'public'
  AND constraint_name IN (
      'cash_flows_source_record_id_key',
      'cash_flows_cash_flow_type_not_blank_check',
      'cash_flows_currency_uppercase_check',
      'cash_flows_fx_rate_to_base_positive_check',
      'daily_nav_snapshots_account_snapshot_date_key',
      'daily_nav_snapshots_source_record_id_key',
      'daily_nav_snapshots_base_currency_uppercase_check'
  );

SELECT 1 / count(*)
FROM public.brokerages
WHERE code = 'IBKR'
  AND name = 'Interactive Brokers'
  AND import_format = 'IBKR_FLEX_XML'
  AND is_active = true;

SELECT 1 / (count(*) = 9)::int
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.proname IN (
      'register_account',
      'update_account_metadata',
      'set_account_active',
      'start_ingestion_run',
      'complete_ingestion_run',
      'ingest_cash_flow',
      'ingest_daily_nav_snapshot',
      'bulk_ingest_cash_flows',
      'bulk_ingest_daily_nav_snapshots'
  );

SELECT 1 / (
    count(*) = 1
    AND to_regprocedure('public.start_ingestion_run(text,text,text,date,date,text)') IS NOT NULL
)::int
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.proname = 'start_ingestion_run';

SELECT 1 / (count(*) = 2)::int
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.proname IN (
      '_resolve_ingestion_account',
      '_insert_source_record'
  );

DO $$
DECLARE
    v_ingestion_run_id UUID;
    v_completed_run_id UUID;
    v_status TEXT;
    v_error_message TEXT;
    v_completed_at TIMESTAMPTZ;
BEGIN
    PERFORM public.register_account(
        'IBKR',
        'U100',
        'INDIVIDUAL',
        'USD',
        'Synthetic Account'
    );

    v_ingestion_run_id := public.start_ingestion_run(
        'IBKR',
        'U100',
        'MANUAL_FILE',
        DATE '2026-01-01',
        DATE '2026-01-31',
        'synthetic-flex.xml'
    );

    v_completed_run_id := public.complete_ingestion_run(
        v_ingestion_run_id,
        'partially_succeeded',
        'Skipped unknown accounts: U404'
    );

    SELECT status, error_message, completed_at
      INTO v_status, v_error_message, v_completed_at
    FROM public.ingestion_runs
    WHERE id = v_completed_run_id;

    IF v_status IS DISTINCT FROM 'partially_succeeded'
       OR v_error_message IS DISTINCT FROM 'Skipped unknown accounts: U404'
       OR v_completed_at IS NULL THEN
        RAISE EXCEPTION 'Ingestion run completion verification failed for %', v_ingestion_run_id;
    END IF;
END;
$$;

DO $$
DECLARE
    v_account_id UUID;
    v_ingestion_run_id UUID;
    v_run_account_id UUID;
BEGIN
    SELECT public.register_account(
        'IBKR',
        'UVERIFY',
        'INDIVIDUAL',
        'USD',
        'Verify Account'
    ) INTO v_account_id;

    v_ingestion_run_id := public.start_ingestion_run(
        'IBKR',
        'UVERIFY',
        'MANUAL_FILE',
        DATE '2026-03-01',
        DATE '2026-03-31',
        'account-scoped.xml'
    );

    SELECT account_id INTO v_run_account_id
    FROM public.ingestion_runs
    WHERE id = v_ingestion_run_id;

    IF v_run_account_id IS DISTINCT FROM v_account_id THEN
        RAISE EXCEPTION 'Ingestion run account_id verification failed for %', v_ingestion_run_id;
    END IF;
END;
$$;

DO $$
BEGIN
    PERFORM public.start_ingestion_run(
        'IBKR',
        'UDOESNOTEXIST',
        'MANUAL_FILE',
        NULL,
        NULL,
        'unknown-account.xml'
    );
    RAISE EXCEPTION 'Expected start_ingestion_run to reject an unknown account';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLERRM = 'Expected start_ingestion_run to reject an unknown account' THEN
            RAISE;
        END IF;
END;
$$;

DO $$
BEGIN
    PERFORM public.start_ingestion_run(
        'IBKR',
        '',
        'MANUAL_FILE',
        NULL,
        NULL,
        'blank-account.xml'
    );
    RAISE EXCEPTION 'Expected start_ingestion_run to reject a blank account_external_id';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLERRM = 'Expected start_ingestion_run to reject a blank account_external_id' THEN
            RAISE;
        END IF;
END;
$$;

WITH account_created AS (
    SELECT public.register_account(
        'IBKR',
        'U100',
        'INDIVIDUAL',
        'USD',
        'Synthetic Account'
    ) AS account_id
),
run_started AS (
    SELECT public.start_ingestion_run(
        'IBKR',
        'U100',
        'MANUAL_FILE',
        DATE '2026-02-01',
        DATE '2026-02-28',
        'cash-flow-synthetic.xml'
    ) AS ingestion_run_id
    FROM account_created
),
first_insert AS (
    SELECT result.record_status, result.cash_flow_id
    FROM run_started r,
         public.ingest_cash_flow(
             r.ingestion_run_id,
             'U100',
             'CF-1',
             'IBKR:U100:CASH:2026-02-03:CF-1',
             DATE '2026-02-03',
             'USD',
             '{"accountId":"U100","amount":"1000.00"}'::jsonb,
             DATE '2026-02-03',
             'Deposits/Withdrawals',
             'USD',
             1000.00,
             1000.00,
             1.0,
             'Synthetic deposit'
         ) AS result
),
duplicate_insert AS (
    SELECT result.record_status
    FROM run_started r,
         first_insert fi,
         public.ingest_cash_flow(
             r.ingestion_run_id,
             'U100',
             'CF-1',
             'IBKR:U100:CASH:2026-02-03:CF-1',
             DATE '2026-02-03',
             'USD',
             '{"accountId":"U100","amount":"1000.00"}'::jsonb,
             DATE '2026-02-03',
             'Deposits/Withdrawals',
             'USD',
             1000.00,
             1000.00,
             1.0,
             'Synthetic deposit'
         ) AS result
),
unknown_insert AS (
    SELECT result.record_status
    FROM run_started r,
         duplicate_insert di,
         public.ingest_cash_flow(
             r.ingestion_run_id,
             'U404',
             'CF-404',
             'IBKR:U404:CASH:2026-02-04:CF-404',
             DATE '2026-02-04',
             'USD',
             '{"accountId":"U404","amount":"500.00"}'::jsonb,
             DATE '2026-02-04',
             'Deposits/Withdrawals',
             'USD',
             500.00,
             500.00,
             1.0,
             'Synthetic skipped deposit'
         ) AS result
)
SELECT 1 / count(*)
FROM first_insert fi
CROSS JOIN duplicate_insert di
CROSS JOIN unknown_insert ui
WHERE fi.record_status = 'inserted'
  AND fi.cash_flow_id IS NOT NULL
  AND di.record_status = 'skipped_duplicate'
  AND ui.record_status = 'skipped_unknown_account';

WITH account_created AS (
    SELECT public.register_account(
        'IBKR',
        'U200',
        'INDIVIDUAL',
        'USD',
        'Synthetic NAV Account'
    ) AS account_id
),
run_started AS (
    SELECT public.start_ingestion_run(
        'IBKR',
        'U200',
        'MANUAL_FILE',
        DATE '2026-03-01',
        DATE '2026-03-31',
        'daily-nav-synthetic.xml'
    ) AS ingestion_run_id
    FROM account_created
),
first_insert AS (
    SELECT result.record_status, result.daily_nav_snapshot_id
    FROM run_started r,
         public.ingest_daily_nav_snapshot(
             r.ingestion_run_id,
             'U200',
             'NAV-1',
             'IBKR:U200:NAV:2026-03-03:NAV-1',
             DATE '2026-03-03',
             'USD',
             '{"accountId":"U200","nav":"12345.67"}'::jsonb,
             DATE '2026-03-03',
             'USD',
             12345.67
         ) AS result
),
duplicate_insert AS (
    SELECT result.record_status
    FROM run_started r,
         first_insert fi,
         public.ingest_daily_nav_snapshot(
             r.ingestion_run_id,
             'U200',
             'NAV-1',
             'IBKR:U200:NAV:2026-03-03:NAV-1',
             DATE '2026-03-03',
             'USD',
             '{"accountId":"U200","nav":"12345.67"}'::jsonb,
             DATE '2026-03-03',
             'USD',
             12345.67
         ) AS result
),
unknown_insert AS (
    SELECT result.record_status
    FROM run_started r,
         duplicate_insert di,
         public.ingest_daily_nav_snapshot(
             r.ingestion_run_id,
             'U404',
             'NAV-404',
             'IBKR:U404:NAV:2026-03-04:NAV-404',
             DATE '2026-03-04',
             'USD',
             '{"accountId":"U404","nav":"999.99"}'::jsonb,
             DATE '2026-03-04',
             'USD',
             999.99
         ) AS result
),
conflict_insert AS (
    SELECT result.record_status
    FROM run_started r,
         unknown_insert ui,
         public.ingest_daily_nav_snapshot(
             r.ingestion_run_id,
             'U200',
             'NAV-2',
             'IBKR:U200:NAV:2026-03-03:NAV-2',
             DATE '2026-03-03',
             'USD',
             '{"accountId":"U200","nav":"12345.67","revision":"second-source"}'::jsonb,
             DATE '2026-03-03',
             'USD',
             12345.67
         ) AS result
)
SELECT 1 / count(*)
FROM first_insert fi
CROSS JOIN duplicate_insert di
CROSS JOIN unknown_insert ui
CROSS JOIN conflict_insert ci
WHERE fi.record_status = 'inserted'
  AND fi.daily_nav_snapshot_id IS NOT NULL
  AND di.record_status = 'skipped_duplicate'
  AND ui.record_status = 'skipped_unknown_account'
  AND ci.record_status = 'conflict_existing_snapshot';

SELECT 1 / (count(*) = 0)::int
FROM public.source_records sr
WHERE sr.dedupe_key = 'IBKR:U200:NAV:2026-03-03:NAV-2';

WITH account_created AS (
    SELECT public.register_account(
        'IBKR',
        'U300',
        'INDIVIDUAL',
        'USD',
        'Bulk Cash Account'
    ) AS account_id
),
run_started AS (
    SELECT public.start_ingestion_run(
        'IBKR',
        'U300',
        'MANUAL_FILE',
        DATE '2026-04-01',
        DATE '2026-04-30',
        'bulk-cash-synthetic.xml'
    ) AS ingestion_run_id
    FROM account_created
),
bulk_result AS (
    SELECT result.*
    FROM run_started r,
         public.bulk_ingest_cash_flows(
             r.ingestion_run_id,
             jsonb_build_array(
                 jsonb_build_object(
                     'account_external_id', 'U300',
                     'external_record_id', 'BCF-1',
                     'dedupe_key', 'IBKR:U300:CASH:2026-04-03:BCF-1',
                     'source_report_date', '2026-04-03',
                     'source_currency', 'USD',
                     'raw_payload', jsonb_build_object('accountId', 'U300', 'amount', '100.00'),
                     'flow_date', '2026-04-03',
                     'cash_flow_type', 'Deposits/Withdrawals',
                     'currency', 'USD',
                     'amount', '100.00',
                     'amount_base', '100.00',
                     'fx_rate_to_base', '1.0',
                     'description', 'Bulk synthetic deposit'
                 ),
                 jsonb_build_object(
                     'account_external_id', 'U404',
                     'external_record_id', 'BCF-404',
                     'dedupe_key', 'IBKR:U404:CASH:2026-04-03:BCF-404',
                     'source_report_date', '2026-04-03',
                     'source_currency', 'USD',
                     'raw_payload', jsonb_build_object('accountId', 'U404', 'amount', '25.00'),
                     'flow_date', '2026-04-03',
                     'cash_flow_type', 'Deposits/Withdrawals',
                     'currency', 'USD',
                     'amount', '25.00',
                     'amount_base', '25.00',
                     'fx_rate_to_base', '1.0',
                     'description', 'Bulk skipped deposit'
                 )
             )
         ) AS result
)
SELECT 1 / count(*)
FROM bulk_result
WHERE inserted_count = 1
  AND duplicate_count = 0
  AND skipped_unknown_account_count = 1
  AND skipped_inactive_account_count = 0
  AND conflict_count = 0
  AND skipped_accounts = ARRAY['U404']::TEXT[];

WITH account_created AS (
    SELECT public.register_account(
        'IBKR',
        'U400',
        'INDIVIDUAL',
        'USD',
        'Bulk NAV Account'
    ) AS account_id
),
run_started AS (
    SELECT public.start_ingestion_run(
        'IBKR',
        'U400',
        'MANUAL_FILE',
        DATE '2026-05-01',
        DATE '2026-05-31',
        'bulk-nav-synthetic.xml'
    ) AS ingestion_run_id
    FROM account_created
),
bulk_result AS (
    SELECT result.*
    FROM run_started r,
         public.bulk_ingest_daily_nav_snapshots(
             r.ingestion_run_id,
             jsonb_build_array(
                 jsonb_build_object(
                     'account_external_id', 'U400',
                     'external_record_id', 'BNAV-1',
                     'dedupe_key', 'IBKR:U400:NAV:2026-05-03:BNAV-1',
                     'source_report_date', '2026-05-03',
                     'source_currency', 'USD',
                     'raw_payload', jsonb_build_object('accountId', 'U400', 'nav', '10000.00'),
                     'snapshot_date', '2026-05-03',
                     'base_currency', 'USD',
                     'nav_base', '10000.00'
                 ),
                 jsonb_build_object(
                     'account_external_id', 'U404',
                     'external_record_id', 'BNAV-404',
                     'dedupe_key', 'IBKR:U404:NAV:2026-05-03:BNAV-404',
                     'source_report_date', '2026-05-03',
                     'source_currency', 'USD',
                     'raw_payload', jsonb_build_object('accountId', 'U404', 'nav', '500.00'),
                     'snapshot_date', '2026-05-03',
                     'base_currency', 'USD',
                     'nav_base', '500.00'
                 )
             )
         ) AS result
)
SELECT 1 / count(*)
FROM bulk_result
WHERE inserted_count = 1
  AND duplicate_count = 0
  AND skipped_unknown_account_count = 1
  AND skipped_inactive_account_count = 0
  AND conflict_count = 0
  AND skipped_accounts = ARRAY['U404']::TEXT[];

ROLLBACK;
