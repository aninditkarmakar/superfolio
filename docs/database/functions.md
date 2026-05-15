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
| `create_automation_job(...)` | `public.create_automation_job(...)` |
| `finalize_automation_job(...)` | `public.finalize_automation_job(...)` |
| `add_automation_job_account(...)` | `public.add_automation_job_account(...)` |
| `mark_automation_job_account_running(...)` | `public.mark_automation_job_account_running(...)` |
| `finalize_automation_job_account(...)` | `public.finalize_automation_job_account(...)` |
| `resolve_automation_portfolio_accounts(...)` | `public.resolve_automation_portfolio_accounts(...)` |
| `resolve_automation_account_targets(...)` | `public.resolve_automation_account_targets(...)` |
| `resolve_automation_targets_with_connections(...)` | `public.resolve_automation_targets_with_connections(...)` |
| `fail_stale_automation_runs(...)` | `public.fail_stale_automation_runs(...)` |
| `has_overlapping_automation_load(...)` | `public.has_overlapping_automation_load(...)` |
| `create_integration_connection(...)` | `public.create_integration_connection(...)` |
| `set_integration_credential(...)` | `public.set_integration_credential(...)` |
| `create_integration_feed(...)` | `public.create_integration_feed(...)` |
| `set_account_integration_assignment(...)` | `public.set_account_integration_assignment(...)` |
| `validate_account_integration_assignments(...)` | `public.validate_account_integration_assignments(...)` |
| `list_integration_connections()` | `public.list_integration_connections()` |
| `list_integration_feeds(...)` | `public.list_integration_feeds(...)` |
| `list_active_connection_credentials(...)` | `public.list_active_connection_credentials(...)` |
| `list_active_integration_feeds(...)` | `public.list_active_integration_feeds(...)` |

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
| `create_portfolio(...)` | Inserts a named portfolio with a reporting currency and returns the new id; returns the existing id if name and currency already match; raises an error if the name exists with a different reporting currency. |
| `attach_portfolio_account(...)` | Attaches an existing registered brokerage account to a portfolio after validating that the account base currency matches the portfolio reporting currency. |
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

## Automation functions

Automation functions manage the full lifecycle of a parent automation job and its per-account child outcomes.

**Lifecycle:**

| Function | Purpose |
| --- | --- |
| `create_automation_job(...)` | Creates a new `pending` automation job row with target type, integration, mode, and requested date range. Returns the new job id. |
| `finalize_automation_job(...)` | Transitions the parent job to `succeeded`, `partially_succeeded`, or `failed` and records a sanitized summary and optional error message. |
| `add_automation_job_account(...)` | Appends a `pending` per-account child row to an automation job. |
| `mark_automation_job_account_running(...)` | Transitions a child account row to `running`. |
| `finalize_automation_job_account(...)` | Finalizes a child account row with a terminal status, optional `ingestion_run_id` (load mode only), sanitized summary counts, and optional error message. |

`add_automation_job_account` accepts an optional `connection_id` parameter that snapshots which integration connection was assigned to the account at the time the job was created.

**Target resolution:**

| Function | Purpose |
| --- | --- |
| `resolve_automation_portfolio_accounts(...)` | Returns the set of active accounts belonging to a named portfolio for use as automation targets. |
| `resolve_automation_account_targets(...)` | Resolves a list of external account ids to their registered account rows for use as automation targets. |

**Stale cleanup and overlap detection:**

| Function | Purpose |
| --- | --- |
| `fail_stale_automation_runs(...)` | Marks pending or running automation jobs and their child account rows as `failed` when they have been stuck beyond a configurable staleness threshold. Called at the start of each workflow run. |
| `has_overlapping_automation_load(...)` | Returns true when an active pending or running load job for the same integration and account has a requested date range that overlaps (inclusive on both ends) the proposed range, excluding the current automation job id. Used to block duplicate load attempts. |

## Connection management functions

These functions create and query integration connections, which represent distinct broker logins.

| Function | Purpose |
| --- | --- |
| `create_integration_connection(p_integration_key, p_brokerage_code, p_name)` | Creates a new named integration connection for the given brokerage and integration key. Returns the new connection UUID. Raises an error if the brokerage code is not found or is inactive. |
| `list_integration_connections()` | Returns all integration connections with their integration key, brokerage code, display name, and active status. Ordered by name. |

## Credential storage and listing functions

Credential material is encrypted in the application layer before being passed to the database. The database stores ciphertext only.

| Function | Purpose |
| --- | --- |
| `set_integration_credential(p_connection_id, p_credential_name, p_ciphertext, p_encryption_key_id, p_encryption_version)` | Rotates the named credential for a connection: deactivates the existing active row (recording `rotated_at`) and inserts a new active row. Returns the new credential UUID. |
| `list_active_connection_credentials(p_connection_id)` | Returns `(credential_name, ciphertext)` pairs for all active credentials belonging to the connection. Used by the orchestrator at runtime to load credentials for decryption. |

## Feed functions

Feeds represent distinct Flex query configurations within a connection.

| Function | Purpose |
| --- | --- |
| `create_integration_feed(p_connection_id, p_feed_key, p_display_name)` | Creates a new feed for the connection. `feed_key` must be non-blank and contain no colons. Returns the new feed UUID. |
| `list_integration_feeds(p_connection_id)` | Returns all feeds (active and inactive) for the connection, ordered by `feed_key`. |
| `list_active_integration_feeds(p_connection_id)` | Returns only active feeds for the connection. Used by the orchestrator at runtime to determine which Flex queries to execute. |

## Assignment functions

Assignments bind registered accounts to the integration connection responsible for fetching their data.

| Function | Purpose |
| --- | --- |
| `set_account_integration_assignment(p_brokerage_code, p_account_external_id, p_connection_id)` | Upserts an integration assignment for the account. If an assignment already exists it is updated to point at the new connection. Validates that the account and connection belong to the same brokerage. Returns the account UUID. |
| `validate_account_integration_assignments(p_target_type, p_portfolio_name, p_brokerage_code, p_account_external_ids)` | Returns the external ids of active accounts in the target that have no active integration assignment. An empty result set means all accounts are assigned. `target_type` must be `portfolio` or `account_list`. |

## Connection-aware target resolution

| Function | Purpose |
| --- | --- |
| `resolve_automation_targets_with_connections(p_target_type, p_portfolio_name, p_brokerage_code, p_account_external_ids)` | Resolves automation targets and left-joins each account's active integration connection. Returns rows with `account_id`, `brokerage_code`, `account_external_id`, `base_currency`, `display_name`, `connection_id`, and `connection_name`. Accounts without an active assignment return `NULL` for `connection_id` and `connection_name`. |

This function is the primary target resolution path used by the orchestrator. The legacy functions `resolve_automation_portfolio_accounts` and `resolve_automation_account_targets` remain available for single-connection use cases where connection information is not needed.
