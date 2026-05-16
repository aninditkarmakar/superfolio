# Load a Flex XML File

Use `load` after reviewing a dry-run summary. The command creates an ingestion run and writes supported account-scoped records into PostgreSQL.

## Prerequisites

- Python dependencies are installed.
- Sqitch migrations are deployed.
- `DATABASE_URL` is set, or you pass `--database-url`.
- The target account is registered with `scripts/register_account.py`.
- You have reviewed `dry-run` output for the same file and account.

## Command

```bash
python scripts/ingest_flex_file.py load scratch/Flex.xml \
  --brokerage-code IBKR \
  --account-external-id U100 \
  --start-date 2026-01-01 \
  --end-date 2026-01-31
```

## Options

| Argument | Required | Description |
| --- | --- | --- |
| `file` | Yes | Path to the local Flex XML file. |
| `--brokerage-code` | Yes | Brokerage code, for example `IBKR`. |
| `--account-external-id` | Yes | Account ID to load. Records for other accounts are counted but not written. |
| `--database-url` | No | One-run database URL override. Defaults to `DATABASE_URL`. |
| `--start-date` | No | Inclusive `reportDate` filter in `YYYY-MM-DD` format. |
| `--end-date` | No | Inclusive `reportDate` filter in `YYYY-MM-DD` format. |

## Supported records

| Flex XML tag | Supported condition |
| --- | --- |
| `CashTransaction` | `type="Deposits/Withdrawals"` only. |
| `EquitySummaryByReportDateInBase` | Daily NAV snapshots. |

Required cash-transaction attributes are `accountId`, `reportDate`, `currency`, `amount`, and `type`. If `transactionID` is missing, `dateTime` is also required for fallback deduplication. Daily NAV records require `accountId`, `reportDate`, `currency`, and `total`.

## Load sequence

1. Analyze the whole XML file.
2. Filter supported records to `--account-external-id`.
3. Start one `manual_file` ingestion run.
4. Bulk ingest supported cash flows, if any.
5. Bulk ingest supported daily NAV snapshots, if any.
6. Mark the ingestion run `succeeded`, `partially_succeeded`, or `failed`.

## Output

```text
Load: scratch/Flex.xml
Ingestion run: <run-uuid>
Target account: U100
Cash-flow records mapped: 1
Daily NAV snapshots mapped: 1
Unsupported CashTransaction records skipped: 1
Cash-flow results: inserted=1 duplicate=0 skipped_unknown=0 skipped_inactive=0 conflicts=0
Daily NAV results: inserted=1 duplicate=0 skipped_unknown=0 skipped_inactive=0 conflicts=0
Cash-flow records skipped for other accounts: 0
Daily NAV snapshots skipped for other accounts: 0
Currencies seen: USD
Final status: succeeded
```

`Skipped accounts:` and `Message:` lines are printed only when relevant.

## Idempotency and statuses

Source records are deduplicated by brokerage and dedupe key. Re-loading the same file is safe: duplicate records are counted as duplicates and do not make the run partial.

| Final status | Meaning |
| --- | --- |
| `succeeded` | All mapped records were inserted or recognized as duplicates. |
| `partially_succeeded` | At least one record hit an unknown account, inactive account, or daily NAV conflict. The command still exits `0`. |
| `failed` | An exception occurred after the run started; the command attempts to mark the run failed and exits `1`. |

## Privacy behavior

Load output prints counts, statuses, currencies, and IDs. It does not print raw amounts, NAV values, FX rates, descriptions, raw XML payloads, or dedupe keys.

## Common gotchas

- If the target account does not appear in the file, the load can complete with zero mapped records.
- Unknown accounts are reported through skipped counts rather than as hard failures during bulk ingestion.
- A different daily NAV source record for an already-loaded account/date is a conflict and makes the run `partially_succeeded`.
- Files are read as UTF-8.
