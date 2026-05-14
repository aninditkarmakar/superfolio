# Database Function Contracts

SuperFolio uses PostgreSQL functions as the database mutation boundary for account administration and ingestion. Application code should call these functions through `portfolio_engine.database.SuperFolioDatabase` instead of writing directly to normalized tables.

## Python adapter

`portfolio_engine.database.SuperFolioDatabase` wraps:

| Adapter method | PostgreSQL function |
| --- | --- |
| `register_account(...)` | `public.register_account(...)` |
| `start_ingestion_run(...)` | `public.start_ingestion_run(...)` |
| `complete_ingestion_run(...)` | `public.complete_ingestion_run(...)` |
| `bulk_ingest_cash_flows(...)` | `public.bulk_ingest_cash_flows(...)` |
| `bulk_ingest_daily_nav_snapshots(...)` | `public.bulk_ingest_daily_nav_snapshots(...)` |
| `create_portfolio(...)` | `public.create_portfolio(...)` |
| `attach_portfolio_account(...)` | `public.attach_portfolio_account(...)` |
| `create_portfolio_transfer_bridge(...)` | `public.create_portfolio_transfer_bridge(...)` |

Use `connect_database()` to create the adapter from `DATABASE_URL` or an explicit database URL.

## Account functions

| Function | Purpose |
| --- | --- |
| `register_account(...)` | Registers an account or returns the existing account id when brokerage, external id, account type, and base currency match. |
| `update_account_metadata(...)` | Updates display name and account type for an existing account. |
| `set_account_active(...)` | Activates or deactivates an account without deleting history. |

## Portfolio functions

| Function | Purpose |
| --- | --- |
| `create_portfolio(...)` | Creates or updates a named portfolio with a reporting currency. |
| `attach_portfolio_account(...)` | Attaches an existing registered brokerage account to a portfolio. |
| `create_portfolio_transfer_bridge(...)` | Adds an in-transit transfer bridge after validating portfolio membership, date order, currency, and overlapping bridge windows. |

## Ingestion run functions

| Function | Purpose |
| --- | --- |
| `start_ingestion_run(...)` | Creates a `running` ingestion run for an active brokerage account, source type, optional date range, and optional source filename. |
| `complete_ingestion_run(...)` | Finalizes a running ingestion run as `succeeded`, `partially_succeeded`, or `failed`. |

## Single-record ingestion functions

| Function | Purpose |
| --- | --- |
| `ingest_cash_flow(...)` | Resolves the account, inserts or reuses a source record, and inserts one normalized cash-flow row. |
| `ingest_daily_nav_snapshot(...)` | Resolves the account, checks source-record and account/date conflicts, and inserts one normalized daily NAV row. |

Record statuses:

| Status | Meaning |
| --- | --- |
| `inserted` | A new source record and normalized row were inserted. |
| `skipped_duplicate` | The source dedupe key already exists and the normalized row already exists. |
| `skipped_unknown_account` | The source account id is not registered for the brokerage. |
| `skipped_inactive_account` | The source account exists but is inactive. |
| `conflict_existing_snapshot` | A daily NAV row already exists for the account/date with a different source dedupe key. |

## Bulk ingestion functions

| Function | Purpose |
| --- | --- |
| `bulk_ingest_cash_flows(p_ingestion_run_id uuid, p_records jsonb)` | Processes an array of cash-flow payloads through `ingest_cash_flow(...)`. |
| `bulk_ingest_daily_nav_snapshots(p_ingestion_run_id uuid, p_records jsonb)` | Processes an array of daily NAV payloads through `ingest_daily_nav_snapshot(...)`. |

Bulk return fields:

| Field | Meaning |
| --- | --- |
| `inserted_count` | Records inserted as new normalized rows. |
| `duplicate_count` | Records skipped because the source dedupe key already exists. |
| `skipped_unknown_account_count` | Records skipped because account configuration is missing. |
| `skipped_inactive_account_count` | Records skipped because account configuration is inactive. |
| `conflict_count` | Records skipped because of canonical-data conflicts. |
| `skipped_accounts` | Distinct external account ids skipped for unknown or inactive account status. |
| `record_results` | Per-record result details for diagnostics. |

## Cash-flow bulk JSON shape

```json
[
  {
    "account_external_id": "U100",
    "external_record_id": "12345",
    "dedupe_key": "IBKR:U100:CASH_TRANSACTION:12345",
    "source_report_date": "2026-01-03",
    "source_currency": "USD",
    "raw_payload": {"accountId": "U100", "amount": "1000.00"},
    "flow_date": "2026-01-03",
    "cash_flow_type": "Deposits/Withdrawals",
    "currency": "USD",
    "amount": "1000.00",
    "amount_base": "1000.00",
    "fx_rate_to_base": "1.0",
    "description": "Synthetic deposit"
  }
]
```

## Daily NAV bulk JSON shape

```json
[
  {
    "account_external_id": "U100",
    "external_record_id": "NAV:U100:20260103",
    "dedupe_key": "IBKR:U100:DAILY_NAV:20260103",
    "source_report_date": "2026-01-03",
    "source_currency": "USD",
    "raw_payload": {"accountId": "U100", "total": "12345.67"},
    "snapshot_date": "2026-01-03",
    "base_currency": "USD",
    "nav_base": "12345.67"
  }
]
```

## Error handling

Malformed JSON, invalid casts, missing required function inputs, unknown ingestion runs, and source-record integrity mismatches raise errors. Unknown or inactive accounts are represented as skipped record statuses so one bulk call can report account-level misses without aborting all records.
