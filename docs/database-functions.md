# Database Function Contracts

SuperFolio uses PostgreSQL functions as the database mutation boundary for ingestion and account administration. Application and ingestion clients should call these functions instead of writing directly to normalized ingestion tables.

## Account functions

| Function | Purpose |
| --- | --- |
| `register_account(...)` | Explicitly registers an account before ingestion. It returns the existing account id only when the existing account has the same account type and base currency. It raises on unknown brokerage or conflicting account metadata. |
| `update_account_metadata(...)` | Updates user/admin-controlled account label and account type. It does not change broker identity or base currency. |
| `set_account_active(...)` | Activates or deactivates an account. Ingestion skips inactive accounts. |

## Ingestion run functions

| Function | Purpose |
| --- | --- |
| `start_ingestion_run(...)` | Creates a `running` ingestion run for a brokerage, source type, optional date range, and optional source filename. |
| `complete_ingestion_run(...)` | Finalizes a run as `succeeded`, `partially_succeeded`, or `failed`. It clears `error_message` for success and allows an optional message for partial or failed runs. |

## Single-record ingestion functions

| Function | Purpose |
| --- | --- |
| `ingest_cash_flow(...)` | Resolves an existing active account, inserts a source record idempotently, then inserts one normalized cash-flow row. |
| `ingest_daily_nav_snapshot(...)` | Resolves an existing active account, checks source-record and account/date conflicts, inserts a source record idempotently, then inserts one normalized daily NAV row. |

Single-record functions return a `record_status`:

| Status | Meaning |
| --- | --- |
| `inserted` | A new source record and normalized row were inserted. |
| `skipped_duplicate` | The source dedupe key already exists. No new normalized row was inserted. |
| `skipped_unknown_account` | The source account id was not registered for the brokerage. |
| `skipped_inactive_account` | The source account exists but is inactive. |
| `conflict_existing_snapshot` | A daily NAV row already exists for the account/date with a different source dedupe key. |

## Bulk ingestion functions

| Function | Purpose |
| --- | --- |
| `bulk_ingest_cash_flows(p_ingestion_run_id uuid, p_records jsonb)` | Processes a JSONB array of cash-flow records using `ingest_cash_flow(...)`. |
| `bulk_ingest_daily_nav_snapshots(p_ingestion_run_id uuid, p_records jsonb)` | Processes a JSONB array of NAV records using `ingest_daily_nav_snapshot(...)`. |

Bulk functions return summary counts:

| Field | Meaning |
| --- | --- |
| `inserted_count` | Records inserted as new normalized rows. |
| `duplicate_count` | Records skipped because the source dedupe key already exists. |
| `skipped_unknown_account_count` | Records skipped because account configuration is missing. |
| `skipped_inactive_account_count` | Records skipped because account configuration is inactive. |
| `conflict_count` | Records skipped because of a canonical-data conflict. |
| `skipped_accounts` | Distinct external account ids skipped for unknown or inactive account status. Returns an empty array when no accounts were skipped. |
| `record_results` | Per-record result details for diagnostics. |

## Cash-flow bulk JSON shape

```json
[
  {
    "account_external_id": "U100",
    "external_record_id": "CF-1",
    "dedupe_key": "IBKR:U100:CASH:2026-02-03:CF-1",
    "source_report_date": "2026-02-03",
    "source_currency": "USD",
    "raw_payload": {"accountId": "U100", "amount": "1000.00"},
    "flow_date": "2026-02-03",
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
    "account_external_id": "U200",
    "external_record_id": "NAV-1",
    "dedupe_key": "IBKR:U200:NAV:2026-03-03:NAV-1",
    "source_report_date": "2026-03-03",
    "source_currency": "USD",
    "raw_payload": {"accountId": "U200", "nav": "12345.67"},
    "snapshot_date": "2026-03-03",
    "base_currency": "USD",
    "nav_base": "12345.67"
  }
]
```

## MVP limits

- The bulk functions process records in a PL/pgSQL loop to keep one canonical behavior path. This avoids app-side per-record network calls while keeping the implementation simple.
- Unexpected malformed JSON or type-cast errors abort the bulk function. Account-level misses are handled as skipped records.
- Skipped-account summaries live in the function return value and can be copied by callers into `ingestion_runs.error_message` when completing a run as `partially_succeeded`.
