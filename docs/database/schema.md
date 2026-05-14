# Database Schema

This document describes the PostgreSQL schema deployed across three migrations: `migrations/deploy/create_mvp_schema.sql` (account registration, ingestion runs, source records, cash flows, and daily NAV snapshots), `migrations/deploy/create_portfolio_layer.sql` (portfolios, portfolio accounts, and transfer bridges), and `migrations/deploy/create_automation_layer.sql` (automation jobs and per-account job outcomes). The schema stores account-scoped IBKR Flex ingestion data, deduplicates broker-origin records, keeps raw source records separate from normalized portfolio facts, supports logical portfolio groupings across multiple accounts, and tracks parent automation job lifecycle and per-account outcomes for manual and future scheduled ingestion runs.

## Relationship overview

```mermaid
erDiagram
    BROKERAGES ||--o{ ACCOUNTS : has
    BROKERAGES ||--o{ INGESTION_RUNS : receives
    ACCOUNTS ||--o{ INGESTION_RUNS : scopes
    ACCOUNTS ||--o{ SOURCE_RECORDS : owns
    INGESTION_RUNS ||--o{ SOURCE_RECORDS : produced
    SOURCE_RECORDS ||--o| CASH_FLOWS : normalizes
    SOURCE_RECORDS ||--o| DAILY_NAV_SNAPSHOTS : normalizes
    PORTFOLIOS ||--o{ PORTFOLIO_ACCOUNTS : contains
    ACCOUNTS ||--o{ PORTFOLIO_ACCOUNTS : member_of
    PORTFOLIOS ||--o{ PORTFOLIO_TRANSFER_BRIDGES : defines
    AUTOMATION_JOBS ||--o{ AUTOMATION_JOB_ACCOUNTS : contains
    INGESTION_RUNS ||--o| AUTOMATION_JOB_ACCOUNTS : linked_by
```

## Tables

### `brokerages`

Stores supported brokerage integrations. The seed data inserts `IBKR` with import format `IBKR_FLEX_XML`.

Key constraints:

- `code` is unique and non-blank.
- `name` and `import_format` are non-blank.
- `is_active` allows an integration to be disabled without deleting history.

### `accounts`

Stores registered brokerage accounts. Every ingestion run is scoped to one active account.

Key constraints:

- `UNIQUE (brokerage_id, external_id)`.
- `external_id` and `account_type` are non-blank.
- `base_currency` must be an uppercase three-letter currency code.

### `ingestion_runs`

Tracks each ingestion attempt for one brokerage account.

Key constraints:

- `account_id` is a required foreign key to `accounts(id)`.
- `source_type` must be `FLEX_WEB_SERVICE` or `MANUAL_FILE`.
- `status` must be `pending`, `running`, `succeeded`, `partially_succeeded`, or `failed`.
- Date ranges must be ordered when both ends are present.
- Completed runs must have `completed_at >= started_at`.

### `source_records`

Stores unique broker-origin records and acts as the deduplication layer.

Key constraints:

- `UNIQUE (brokerage_id, dedupe_key)`.
- `record_type` must be `CASH_TRANSACTION` or `DAILY_NAV`.
- `dedupe_key` is non-blank.
- `source_currency` must be uppercase when present.

### `cash_flows`

Stores normalized external cash movements from supported `CashTransaction` records.

Key constraints:

- `source_record_id` is unique, preserving a one-to-one source-to-normalized relationship.
- `cash_flow_type` is non-blank.
- `currency` must be uppercase.
- `fx_rate_to_base` must be positive when present.

### `daily_nav_snapshots`

Stores one canonical daily NAV value per account/date.

Key constraints:

- `source_record_id` is unique.
- `UNIQUE (account_id, snapshot_date)` prevents conflicting canonical NAV rows.
- `base_currency` must be uppercase.

### `portfolios`

Stores saved portfolio calculation/view definitions. A portfolio has a unique name used as its lookup key, a reporting currency, an active flag, and references brokerage accounts through `portfolio_accounts`.

### `portfolio_accounts`

Stores many-to-many membership between portfolios and brokerage accounts. An account can belong to multiple portfolios when its base currency matches the portfolio reporting currency. Inactive accounts still contribute historical data when they are members.

### `automation_jobs`

Stores one user-triggered or future scheduled automation operation. Manual jobs require a requested start and end date, record the target type (`portfolio` or `accounts`), selected integration, mode (`dry-run` or `load`), status, sanitized parent summary, and sanitized error message.

### `automation_job_accounts`

Stores the resolved account snapshot for one automation job. Each row tracks account-level status, optional linked `ingestion_runs.id` for load mode, sanitized child summary counts, and sanitized error message. Dry-run rows leave `ingestion_run_id` null.

For load mode, active pending or running load jobs for the same integration and account whose requested date range overlaps the new job's range block new load attempts. The parent `automation_jobs` row and all child `automation_job_accounts` rows are created first; overlap is then evaluated per-account during execution by `has_overlapping_automation_load`, which excludes the current job id from the check. Accounts found to overlap are set to `failed` with `error_category="overlapping_load_job"` in the child summary JSON.

### `portfolio_transfer_bridges`

Stores explicit in-transit transfer adjustments for a portfolio. Source and destination accounts must both be portfolio members, bridge currency must match the portfolio reporting currency, and overlapping bridge windows for the same source/destination account pair are rejected.

## Deduplication model

`ingestion_runs` records the ingestion attempt. `source_records` records unique broker-origin rows. This separation lets scheduled pulls, manual backfills, and overlapping Flex files safely contain the same broker records.

Cash-flow dedupe keys prefer IBKR `transactionID` when present. Daily NAV dedupe keys use brokerage, account, record type, and report date.

## Supporting indexes

- `source_records_account_id_idx`
- `source_records_ingestion_run_id_idx`
- `cash_flows_account_flow_date_idx`
- `ingestion_runs_brokerage_started_at_idx`
