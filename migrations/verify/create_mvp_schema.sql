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

SELECT 1 / (count(*) = 11)::int
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'ingestion_runs'
  AND column_name IN (
      'id',
      'brokerage_id',
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

ROLLBACK;
