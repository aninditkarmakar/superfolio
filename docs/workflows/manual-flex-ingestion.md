# Manual Flex XML Ingestion

Use this workflow to inspect a local IBKR Flex XML file and load supported records into PostgreSQL. The current importer supports account-scoped manual files containing `CashTransaction` records of type `Deposits/Withdrawals` and `EquitySummaryByReportDateInBase` daily NAV records.

## Prerequisites

- Python dependencies from `requirements.txt` installed.
- PostgreSQL schema deployed with Sqitch.
- `DATABASE_URL` set in the environment or passed with `--database-url`.
- Flex XML stored locally, preferably under ignored `scratch/`.

## 1. Register the account

Register each brokerage account before loading records:

```bash
python scripts/register_account.py \
  --brokerage-code IBKR \
  --external-id U100 \
  --account-type Individual \
  --base-currency USD \
  --display-name "Main account"
```

The command returns the account id and normalized account details. Existing accounts are accepted only when account type and base currency match.

## 2. Dry-run the file

Preview supported records without database writes:

```bash
python scripts/ingest_flex_file.py dry-run scratch/Flex.xml \
  --account-external-id U100 \
  --start-date 2026-01-01 \
  --end-date 2026-01-31
```

Dry-run output is privacy-safe: it reports counts, accounts, currencies, date ranges, duplicate dedupe keys, and records skipped for other accounts. It does not print raw amounts, NAV values, or raw payloads.

## 3. Load supported records

After reviewing the dry run, load the account-scoped records:

```bash
python scripts/ingest_flex_file.py load scratch/Flex.xml \
  --brokerage-code IBKR \
  --account-external-id U100 \
  --start-date 2026-01-01 \
  --end-date 2026-01-31
```

Load mode creates one `ingestion_runs` row, bulk-loads supported cash-flow and daily NAV records, completes the run, and prints inserted, duplicate, skipped-account, and conflict counts.

## Account scoping

Both dry-run and load are scoped by `--account-external-id`. Supported records for other accounts are counted as skipped for other accounts and are not written by the load command.

## Final statuses

| Status | Meaning |
| --- | --- |
| `succeeded` | All mapped records were inserted or treated as idempotent duplicates. |
| `partially_succeeded` | One or more records were skipped because of unknown accounts, inactive accounts, or daily NAV conflicts. |
| `failed` | The load command encountered an exception and attempted to mark the ingestion run failed. |

## Current limits

- Only manual local files are implemented; Flex Web Service automation is planned.
- Only `Deposits/Withdrawals` cash transactions are supported by the ingestion workflow.
- Malformed XML or invalid required attributes fail the command rather than being silently skipped.
