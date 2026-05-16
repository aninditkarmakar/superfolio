# Dry-Run a Flex XML File

Use `dry-run` to inspect a local IBKR Flex XML file before loading it into PostgreSQL. Dry-run mode performs no database writes and does not require a database connection.

## Supported records

| Flex XML tag | Supported condition | Maps to |
| --- | --- | --- |
| `CashTransaction` | `type="Deposits/Withdrawals"` | Cash-flow facts. |
| `EquitySummaryByReportDateInBase` | Always supported | Daily NAV snapshot facts. |

Other `CashTransaction` types are counted as unsupported and skipped.

## Command

```bash
python scripts/ingest_flex_file.py dry-run scratch/Flex.xml \
  --account-external-id U100 \
  --start-date 2026-01-01 \
  --end-date 2026-01-31
```

## Options

| Argument | Required | Description |
| --- | --- | --- |
| `file` | Yes | Path to the local Flex XML file. |
| `--account-external-id` | Yes | Account ID to preview. Records for other accounts are counted but not included. |
| `--start-date` | No | Inclusive `reportDate` filter in `YYYY-MM-DD` format. |
| `--end-date` | No | Inclusive `reportDate` filter in `YYYY-MM-DD` format. |

`--start-date` must be on or before `--end-date`.

## Output

```text
Dry run: scratch/Flex.xml
Target account: U100
Cash-flow records mapped: 1
Daily NAV snapshots mapped: 1
Unsupported CashTransaction records skipped: 1
Currencies seen: USD
Cash-flow date range: 2026-01-02 to 2026-01-02
Daily NAV date range: 2026-01-02 to 2026-01-02
Duplicate dedupe keys: 0
Cash-flow records skipped for other accounts: 1
Daily NAV snapshots skipped for other accounts: 1
No database writes performed.
```

## What the summary means

| Field | Meaning |
| --- | --- |
| `Cash-flow records mapped` | Supported cash-flow records for the target account and date range. |
| `Daily NAV snapshots mapped` | Supported daily NAV records for the target account and date range. |
| `Unsupported CashTransaction records skipped` | Cash transactions with unsupported `type` values. |
| `Currencies seen` | Currencies observed in mapped records. |
| `Duplicate dedupe keys` | Number of distinct repeated dedupe keys in the file. |
| `records skipped for other accounts` | Supported records present in the file but excluded by `--account-external-id`. |

## Privacy behavior

Dry-run output is designed to be privacy-safe. It does not print raw amounts, NAV values, FX rates, descriptions, raw XML payloads, or dedupe keys. It prints only counts, dates, currencies, and target-account metadata.

## Failure behavior

- Malformed XML exits `1`.
- Invalid date flags exit `1`.
- Supported records with missing required attributes fail the command.
- Unsupported cash transaction records are skipped before required-attribute validation.
- Missing files exit `1`.
