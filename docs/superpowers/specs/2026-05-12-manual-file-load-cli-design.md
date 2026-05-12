# Manual Flex File Load CLI Design

## Problem

The manual Flex XML workflow can now inspect files safely with `dry-run`, but it cannot yet persist supported records into PostgreSQL. The next block should make manual file handling account-scoped: the operator chooses the target brokerage account, both `dry-run` and `load` preview only records for that account, and `load` persists matching supported records into PostgreSQL under an ingestion run tied to that target account.

## Proposed approach

Make both `dry-run` and `load` require the target brokerage account external ID:

```bash
python scripts/ingest_flex_file.py dry-run scratch/Flex.xml \
  --account-external-id U17072019 \
  --start-date 2025-01-01 \
  --end-date 2025-04-30

python scripts/ingest_flex_file.py load scratch/Flex.xml \
  --brokerage-code IBKR \
  --account-external-id U17072019 \
  --start-date 2025-01-01 \
  --end-date 2025-04-30
```

The `dry-run` command should stay database-free and use `--account-external-id` only to filter and summarize the XML. The `load` command should require both `--brokerage-code` and `--account-external-id`. It should use `DATABASE_URL` by default and support `--database-url` as a one-run override, matching the account registration CLI.

The analyzer should become the shared parsing and mapping boundary for both `dry-run` and `load`. It should scan the XML once, produce full database bulk records for internal load mode, and support target-account filtering while preserving privacy-safe output behavior. The CLI must never print raw record dictionaries, raw Flex payloads, amounts, NAV values, or full dedupe key values.

## Scope

In scope:

- Add a `load FILE` subcommand to the existing manual Flex ingestion CLI.
- Require `--account-external-id` for both `dry-run` and `load`.
- Require `--brokerage-code` for load mode.
- Support optional `--database-url`, `--start-date`, and `--end-date`.
- Reuse existing Flex mapper logic for supported records.
- Reuse `SuperFolioDatabase` and `connect_database()` for all database writes.
- Add account scoping to `ingestion_runs` and `start_ingestion_run(...)` so each manual load run records the user-selected target account.
- Start one ingestion run for the whole file and target account, not one run per record type.
- Bulk-load matching supported `CashTransaction type="Deposits/Withdrawals"` records.
- Bulk-load matching supported `EquitySummaryByReportDateInBase` records.
- Skip supported records whose XML `accountId` does not match `--account-external-id`, and report skip counts as warnings.
- Complete the ingestion run as `succeeded`, `partially_succeeded`, or `failed`.
- Print privacy-safe dry-run and load summaries with counts, statuses, target account ID, currencies, skipped non-target counts, and DB skipped account IDs.
- Unit-test with synthetic XML and fake database adapters only.

Out of scope:

- Registering accounts automatically.
- Support for cash transaction types other than `Deposits/Withdrawals`.
- JSON output.
- Direct SQL outside `SuperFolioDatabase`.
- Real database integration tests.
- TWR calculation after load.

## Command interface

```text
dry-run FILE
--account-external-id ACCOUNT_EXTERNAL_ID
--start-date YYYY-MM-DD
--end-date YYYY-MM-DD

load FILE
--brokerage-code BROKERAGE_CODE
--account-external-id ACCOUNT_EXTERNAL_ID
--database-url DATABASE_URL
--start-date YYYY-MM-DD
--end-date YYYY-MM-DD
```

`--account-external-id` is required for both commands. `--brokerage-code` is required for `load` because database account resolution is scoped by brokerage. `--database-url`, `--start-date`, and `--end-date` are optional. Date filters are inclusive and apply to each supported record's `reportDate`.

`source_type` for the ingestion run should be `manual_file`. `source_filename` should be the input file's basename. Requested start and end dates should be copied from the CLI filters when supplied. The ingestion run should store the resolved account for `--account-external-id`.

## Data flow

1. Parse CLI arguments.
2. Validate the date range.
3. Analyze the XML file with the shared Flex analyzer.
4. Partition supported records by `account_external_id == args.account_external_id`.
5. For `dry-run`, print a privacy-safe account-scoped summary and return `0`; no database connection is opened.
6. For `load`, open the database connection with `connect_database(args.database_url)`.
7. Start one ingestion run:
   - `brokerage_code=args.brokerage_code`
   - `account_external_id=args.account_external_id`
   - `source_type="manual_file"`
   - `requested_start_date=args.start_date`
   - `requested_end_date=args.end_date`
   - `source_filename=args.file.name`
8. If matching mapped cash-flow records exist, call `bulk_ingest_cash_flows(...)`.
9. If matching mapped daily NAV records exist, call `bulk_ingest_daily_nav_snapshots(...)`.
10. Derive final status from bulk summaries.
11. Complete the ingestion run.
12. Print a privacy-safe summary and return `0`.

Empty record categories should not call their corresponding bulk function with an empty list.

If `load` cannot resolve an active target account for `(brokerage_code, account_external_id)`, `start_ingestion_run(...)` should raise before creating an ingestion run. The CLI should print `Error: <message>` and return `1`.

## Database changes

`ingestion_runs` should gain an `account_id` foreign key referencing `accounts(id)`. The `start_ingestion_run(...)` database function should accept `p_account_external_id TEXT`, resolve it within the supplied brokerage, require the account to be active, and store the resolved `account_id` on the run.

The Python `IngestionRunStart` dataclass and `SuperFolioDatabase.start_ingestion_run(...)` adapter should add `account_external_id`. Existing bulk ingestion functions can keep resolving each record by `account_external_id`; the CLI must only pass records matching the run's target account.

## Analyzer shape

The current dry-run analyzer stores sanitized record dictionaries so that output cannot accidentally leak values. Load mode needs the full bulk payloads, including amounts, NAV values, FX rates, and raw payloads, but those must remain internal.

The analyzer should therefore expose both:

- full mapped records for database calls
- derived privacy-safe summary fields for output
- account-scoped filtered records for the target account
- skipped non-target counts split by record category

One acceptable shape is to introduce or extend a result dataclass such as `FlexAnalysisResult` with full record tuples and a method that returns an account-scoped result for `account_external_id`. The existing `FlexDryRunSummary` API should remain available for the dry-run CLI and tests, but it should represent the selected account's matching records plus skipped non-target counts. Exact naming can be chosen during implementation, but the boundary must make it hard for CLI formatting code to print sensitive fields by accident.

## Output

Success output should be human-readable and privacy-safe:

```text
Dry run: scratch/Flex.xml
Target account: U17072019
Cash-flow records mapped: 4
Daily NAV snapshots mapped: 83
Unsupported CashTransaction records skipped: 2
Cash-flow records skipped for other accounts: 1
Daily NAV snapshots skipped for other accounts: 10
Currencies seen: CAD, USD
Cash-flow date range: 2025-01-01 to 2025-04-30
Daily NAV date range: 2025-01-01 to 2025-04-30
Duplicate dedupe keys: 0
No database writes performed.
```

Load success output should be human-readable and privacy-safe:

```text
Load: scratch/Flex.xml
Ingestion run: 00000000-0000-0000-0000-000000000000
Target account: U17072019
Cash-flow records mapped: 4
Daily NAV snapshots mapped: 83
Unsupported CashTransaction records skipped: 2
Cash-flow records skipped for other accounts: 1
Daily NAV snapshots skipped for other accounts: 10
Cash-flow results: inserted=4 duplicate=0 skipped_unknown=0 skipped_inactive=0 conflicts=0
Daily NAV results: inserted=83 duplicate=0 skipped_unknown=0 skipped_inactive=0 conflicts=0
Currencies seen: CAD, USD
Final status: succeeded
```

Partial output should include skipped account IDs when present:

```text
Skipped accounts: U999
Final status: partially_succeeded
Message: skipped accounts or conflicts require review
```

Output must not include:

- cash-flow amounts
- NAV values
- raw payload dictionaries
- full record dictionaries
- dedupe key values, because fallback cash-flow dedupe keys can contain amounts

## Status rules

| Condition | Final status |
| --- | --- |
| Only inserted and/or duplicate records | `succeeded` |
| Non-target XML records skipped before bulk load | `succeeded` |
| Unknown account skips | `partially_succeeded` |
| Inactive account skips | `partially_succeeded` |
| NAV or cash-flow conflicts | `partially_succeeded` |
| Parser, mapper, connection, or bulk DB exception | `failed` |

Duplicate records alone are not a partial failure because they represent idempotent re-ingestion. Non-target records are not a partial failure because the operator intentionally scoped the run to one account. Unsupported cash transaction types are not a partial failure in this block; they are counted and skipped because broader cash transaction support is out of scope.

When final status is `partially_succeeded`, `complete_ingestion_run(...)` should receive an error message such as `skipped accounts or conflicts require review`. When final status is `succeeded`, the error message should be `None`.

## Failure handling

If an error occurs before `start_ingestion_run(...)` returns an id, including an unknown or inactive target account, the CLI should print `Error: <message>` to stderr and return `1`.

If an error occurs after the ingestion run has started, load mode should attempt to complete that run as `failed` with the original error message, then print `Error: <message>` and return `1`.

If the attempt to mark the run failed also raises, the CLI should print the original error and include that finalization failed. It should not silently swallow either error.

Database connections should be closed by using the existing `SuperFolioDatabase` context manager.

## Testing

Tests should use small synthetic XML files and fake database adapters. They must not read `scratch/`, print private sample data, or require a real PostgreSQL connection.

Required tests:

- `load` requires `--brokerage-code`.
- `dry-run` requires `--account-external-id`.
- `load` requires `--account-external-id`.
- `dry-run` filters supported records to the target account and reports non-target skipped counts without opening a database connection.
- `load` passes `--database-url` to the connector when provided.
- A mixed file starts exactly one ingestion run with `source_type="manual_file"`, `source_filename` from the input file, and the selected target account.
- Cash-flow and daily NAV records for the target account are both bulk-loaded when present.
- Supported records for other accounts are skipped before bulk calls.
- Non-target record skips are printed as counts and do not change final status from `succeeded`.
- Unknown or inactive target account failures occur before DB writes and before an ingestion run id is returned.
- Empty categories skip their bulk calls.
- Duplicate-only summaries complete as `succeeded`.
- Unknown account, inactive account, and conflict summaries complete as `partially_succeeded`.
- Skipped account IDs are printed without amounts or raw payloads.
- Exceptions after run start complete the run as `failed`.
- If failed-run finalization also fails, both failures are surfaced.
- Output privacy tests cover cash-flow amounts, NAV totals, raw payload content, and fallback dedupe-key amounts.
- Migration deploy/revert/verify coverage confirms `ingestion_runs.account_id` and the updated `start_ingestion_run(...)` signature.
- Existing dry-run behavior and tests continue to pass.

## Future extensions

Later blocks can add account-readiness preflight, richer cash transaction type support, JSON output, real database smoke tests, and a DB-to-TWR adapter that reads normalized rows into the existing TWR dataclasses.
