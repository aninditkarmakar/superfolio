# Manual Flex File Load CLI Design

## Problem

The manual Flex XML workflow can now inspect files safely with `dry-run`, but it cannot yet persist supported records into PostgreSQL. The next block should add a `load` mode that reuses the existing Flex mappers and database adapter, starts one ingestion run for the file, bulk-loads supported cash-flow and daily NAV records, completes the run with the right status, and prints a privacy-safe operator summary.

## Proposed approach

Add a `load` subcommand to `scripts/ingest_flex_file.py` alongside the existing `dry-run` subcommand:

```bash
python scripts/ingest_flex_file.py load scratch/Flex.xml \
  --brokerage-code IBKR \
  --start-date 2025-01-01 \
  --end-date 2025-04-30
```

The `load` command should require `--brokerage-code`. It should use `DATABASE_URL` by default and support `--database-url` as a one-run override, matching the account registration CLI.

The analyzer should become the shared parsing and mapping boundary for both `dry-run` and `load`. It should scan the XML once and produce full database bulk records for internal load mode, while preserving the current privacy-safe dry-run output behavior. The CLI must never print raw record dictionaries, raw Flex payloads, amounts, NAV values, or full dedupe key values.

## Scope

In scope:

- Add a `load FILE` subcommand to the existing manual Flex ingestion CLI.
- Require `--brokerage-code` for load mode.
- Support optional `--database-url`, `--start-date`, and `--end-date`.
- Reuse existing Flex mapper logic for supported records.
- Reuse `SuperFolioDatabase` and `connect_database()` for all database writes.
- Start one ingestion run for the whole file, not one run per record type.
- Bulk-load supported `CashTransaction type="Deposits/Withdrawals"` records.
- Bulk-load supported `EquitySummaryByReportDateInBase` records.
- Complete the ingestion run as `succeeded`, `partially_succeeded`, or `failed`.
- Print a privacy-safe load summary with counts, statuses, account IDs, currencies, and skipped account IDs.
- Unit-test with synthetic XML and fake database adapters only.

Out of scope:

- Account readiness preflight before load.
- Registering accounts automatically.
- Support for cash transaction types other than `Deposits/Withdrawals`.
- JSON output.
- Direct SQL outside `SuperFolioDatabase`.
- Real database integration tests.
- TWR calculation after load.

## Command interface

```text
load FILE
--brokerage-code BROKERAGE_CODE
--database-url DATABASE_URL
--start-date YYYY-MM-DD
--end-date YYYY-MM-DD
```

`--brokerage-code` is required. `--database-url`, `--start-date`, and `--end-date` are optional. Date filters are inclusive and apply to each supported record's `reportDate`, matching dry-run behavior.

`source_type` for the ingestion run should be `manual_file`. `source_filename` should be the input file's basename. Requested start and end dates should be copied from the CLI filters when supplied.

## Data flow

1. Parse CLI arguments.
2. Validate the date range.
3. Analyze the XML file with the shared Flex analyzer.
4. Open the database connection with `connect_database(args.database_url)`.
5. Start one ingestion run:
   - `brokerage_code=args.brokerage_code`
   - `source_type="manual_file"`
   - `requested_start_date=args.start_date`
   - `requested_end_date=args.end_date`
   - `source_filename=args.file.name`
6. If mapped cash-flow records exist, call `bulk_ingest_cash_flows(...)`.
7. If mapped daily NAV records exist, call `bulk_ingest_daily_nav_snapshots(...)`.
8. Derive final status from bulk summaries.
9. Complete the ingestion run.
10. Print a privacy-safe summary and return `0`.

Empty record categories should not call their corresponding bulk function with an empty list.

## Analyzer shape

The current dry-run analyzer stores sanitized record dictionaries so that output cannot accidentally leak values. Load mode needs the full bulk payloads, including amounts, NAV values, FX rates, and raw payloads, but those must remain internal.

The analyzer should therefore expose both:

- full mapped records for database calls
- derived privacy-safe summary fields for output

One acceptable shape is to introduce a new internal result dataclass such as `FlexAnalysisResult` with full record tuples and a `to_dry_run_summary()` or `safe_summary` method. The existing `FlexDryRunSummary` API should remain available for the current dry-run CLI and tests. Exact naming can be chosen during implementation, but the boundary must make it hard for CLI formatting code to print sensitive fields by accident.

## Output

Success output should be human-readable and privacy-safe:

```text
Load: scratch/Flex.xml
Ingestion run: 00000000-0000-0000-0000-000000000000
Cash-flow records mapped: 4
Daily NAV snapshots mapped: 83
Unsupported CashTransaction records skipped: 2
Cash-flow results: inserted=4 duplicate=0 skipped_unknown=0 skipped_inactive=0 conflicts=0
Daily NAV results: inserted=83 duplicate=0 skipped_unknown=0 skipped_inactive=0 conflicts=0
Accounts seen: U100, U200
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
| Unknown account skips | `partially_succeeded` |
| Inactive account skips | `partially_succeeded` |
| NAV or cash-flow conflicts | `partially_succeeded` |
| Parser, mapper, connection, or bulk DB exception | `failed` |

Duplicate records alone are not a partial failure because they represent idempotent re-ingestion. Unsupported cash transaction types are not a partial failure in this block; they are counted and skipped because broader cash transaction support is out of scope.

When final status is `partially_succeeded`, `complete_ingestion_run(...)` should receive an error message such as `skipped accounts or conflicts require review`. When final status is `succeeded`, the error message should be `None`.

## Failure handling

If an error occurs before `start_ingestion_run(...)` returns an id, the CLI should print `Error: <message>` to stderr and return `1`.

If an error occurs after the ingestion run has started, load mode should attempt to complete that run as `failed` with the original error message, then print `Error: <message>` and return `1`.

If the attempt to mark the run failed also raises, the CLI should print the original error and include that finalization failed. It should not silently swallow either error.

Database connections should be closed by using the existing `SuperFolioDatabase` context manager.

## Testing

Tests should use small synthetic XML files and fake database adapters. They must not read `scratch/`, print private sample data, or require a real PostgreSQL connection.

Required tests:

- `load` requires `--brokerage-code`.
- `load` passes `--database-url` to the connector when provided.
- A mixed file starts exactly one ingestion run with `source_type="manual_file"` and `source_filename` from the input file.
- Cash-flow and daily NAV records are both bulk-loaded when present.
- Empty categories skip their bulk calls.
- Duplicate-only summaries complete as `succeeded`.
- Unknown account, inactive account, and conflict summaries complete as `partially_succeeded`.
- Skipped account IDs are printed without amounts or raw payloads.
- Exceptions after run start complete the run as `failed`.
- If failed-run finalization also fails, both failures are surfaced.
- Output privacy tests cover cash-flow amounts, NAV totals, raw payload content, and fallback dedupe-key amounts.
- Existing dry-run behavior and tests continue to pass.

## Future extensions

Later blocks can add account-readiness preflight, richer cash transaction type support, JSON output, real database smoke tests, and a DB-to-TWR adapter that reads normalized rows into the existing TWR dataclasses.

