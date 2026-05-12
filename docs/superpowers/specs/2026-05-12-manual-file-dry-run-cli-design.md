# Manual Flex File Dry-Run CLI Design

## Problem

Before loading IBKR Flex XML into the database, the user needs a safe way to inspect what a manual file contains and what records the ingestion mappers would produce. The dry run should work without a database connection and without requiring the user to know whether a Flex file contains cash-flow records, daily NAV records, or both.

## Proposed approach

Add a local dry-run command for one Flex XML file at a time. The command scans the file for supported Flex record types, maps supported records into the same bulk-ready dictionaries that load mode will later send to the database adapter, and prints a privacy-safe summary.

The dry run is intentionally database-free. It validates parsing and mapper output, not account readiness or database conflicts.

## Scope

In scope:

- A Python CLI entry point for dry-running one Flex XML file.
- File-kind agnostic processing: a single input file may contain `CashTransaction` records, `EquitySummaryByReportDateInBase` records, or both.
- Support for `CashTransaction` records whose `type` is `Deposits/Withdrawals`.
- Support for `EquitySummaryByReportDateInBase` daily NAV records.
- Optional date filtering using `reportDate`.
- Privacy-safe summary output:
  - mapped cash-flow count
  - mapped daily NAV count
  - unsupported cash transaction count
  - accounts seen
  - source currencies seen
  - cash-flow and NAV date ranges
  - duplicate dedupe keys within the file
- Clear non-zero failures for malformed XML or missing required attributes in supported records.
- Unit tests using synthetic XML fixtures only.

Out of scope:

- Database reads or writes.
- Account-readiness checks.
- Database duplicate/conflict checks.
- Starting or completing ingestion runs.
- Loading records into PostgreSQL.
- TWR calculation.
- Support for non-`Deposits/Withdrawals` `CashTransaction` types such as dividends, fees, interest, transfers, or internal movements.

## Command interface

The command should be shaped as a subcommand so load mode can be added later without changing the top-level script:

```bash
python scripts/ingest_flex_file.py dry-run path/to/flex.xml \
  --start-date 2025-01-01 \
  --end-date 2025-04-30
```

Options:

```text
dry-run FILE
--start-date YYYY-MM-DD
--end-date YYYY-MM-DD
```

`--start-date` and `--end-date` are optional inclusive filters applied to each supported record's `reportDate`.

## Record handling

The command should parse the XML with `xml.etree.ElementTree`, not string matching.

For each `CashTransaction` element:

- If `type == "Deposits/Withdrawals"`, map it through the existing cash-transaction mapper.
- If `type` is any other value, count it as unsupported and do not map it.
- Apply date filtering using the canonical cash-flow date, `reportDate`.

For each `EquitySummaryByReportDateInBase` element:

- Map it through the existing daily NAV mapper.
- Apply date filtering using `reportDate`.

The mapper output should remain compatible with the existing database bulk JSON shape. The dry run may summarize fields from those dictionaries, but it should not print raw Flex XML payloads or absolute account values beyond counts and identifiers that are necessary for local operator verification.

## Output

The default output should be human-readable text. It should include enough detail to decide whether the file is ready for load mode without exposing full raw broker records.

Recommended format:

```text
Dry run: scratch/Flex.xml
Cash-flow records mapped: 4
Daily NAV snapshots mapped: 83
Unsupported CashTransaction records skipped: 2
Accounts seen: U100, U200
Currencies seen: CAD, USD
Cash-flow date range: 2025-01-02 to 2025-04-25
Daily NAV date range: 2025-01-01 to 2025-04-25
Duplicate dedupe keys: 0
No database writes performed.
```

If no records of a supported type are found, print `0` for that count and omit the corresponding date range or print `(none)`.

If duplicate dedupe keys are found within the file, print their count and a small sample of dedupe keys so the operator can diagnose repeated records before load mode exists. Dedupe keys are allowed in dry-run output because they are synthetic identifiers produced by the mapper, not raw account balances or transaction values.

## Error handling

The command should exit non-zero and print `Error: <message>` for:

- file not found
- malformed XML
- invalid `--start-date` or `--end-date`
- `--start-date` after `--end-date`
- missing required attributes in supported records
- invalid decimal/date values in supported records

Unsupported cash transaction types are not errors. They are counted and skipped because support for them is intentionally future scope.

## Testing

Tests should cover:

- A mixed XML file containing both supported record types.
- A file with only cash transactions.
- A file with only daily NAV snapshots.
- Unsupported cash transaction types are counted and skipped.
- Date filtering applies to both record types.
- Duplicate dedupe keys within one file are detected.
- Malformed XML exits non-zero with a clear error.
- Missing required attributes in supported records exit non-zero.
- CLI output includes the no-write guarantee.

All tests should use small synthetic XML strings/files. They must not read from `scratch/` or print raw sample data.

## Implementation notes

The existing `portfolio_engine.ingestion.flex_mappers` module already contains mapping logic for cash transactions and daily NAV snapshots. The dry-run block should reuse that mapping behavior instead of duplicating field conversion rules.

If the existing mapper functions only map one record type at a time, add a thin dry-run coordinator that scans the XML once and dispatches each supported element to the existing attribute-level mapping functions. This keeps the dry-run file-kind agnostic while preserving the mapper boundary.

## Future extensions

Later blocks can build on this command by adding:

- load mode using `SuperFolioDatabase.start_ingestion_run(...)`, bulk ingestion methods, and `complete_ingestion_run(...)`
- account-readiness checks
- additional `CashTransaction` type support
- optional machine-readable JSON dry-run output

