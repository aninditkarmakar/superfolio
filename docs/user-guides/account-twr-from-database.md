# Calculate Account TWR from the Database

Use `scripts/calculate_twr_from_db.py` to calculate daily linked TWR for one registered account from normalized PostgreSQL facts.

## Prerequisites

- The database schema is deployed.
- The account is registered.
- Flex records have been loaded into `cash_flows` and `daily_nav_snapshots`.
- `DATABASE_URL` is set, or you pass `--database-url`.

## Command

```bash
python scripts/calculate_twr_from_db.py \
  --brokerage-code IBKR \
  --account-external-id U100 \
  --start-date 2026-01-01 \
  --end-date 2026-01-31 \
  --daily-output output/account-twr.csv
```

## Options

| Flag | Required | Default | Description |
| --- | --- | --- | --- |
| `--brokerage-code` | Yes | none | Brokerage code, for example `IBKR`. |
| `--account-external-id` | Yes | none | Broker account ID. |
| `--database-url` | No | `DATABASE_URL` | One-run database URL override. |
| `--flow-timing` | No | `start` | Return convention: `start` or `end`. |
| `--start-date` | No | none | Inclusive date filter in `YYYY-MM-DD` format. |
| `--end-date` | No | none | Inclusive date filter in `YYYY-MM-DD` format. |
| `--daily-output` | No | none | Optional CSV path. |

The database workflow always uses cash flows whose `cash_flow_type` is `Deposits/Withdrawals`. There is no database CLI flag to include other cash-flow types.

## Output

```text
Brokerage: IBKR
Account: U100
NAV snapshots: 22
Cash-flow records: 2
Return periods: 21
Date range: 2026-01-01 to 2026-01-31
Cash-flow type: Deposits/Withdrawals
Cash-flow timing: start
TWR: 1.234567%
Daily output written to output/account-twr.csv
```

Cash-flow records outside the NAV date range are dropped and reported:

```text
Warning: 1 cash-flow record(s) fell outside the NAV date range and were dropped.
```

## CSV output

When `--daily-output` is supplied, the CSV columns are:

| Column | Description |
| --- | --- |
| `date` | NAV snapshot date. |
| `ending_nav_base` | Ending NAV in account base currency. |
| `net_cash_flow_base` | Net aligned external cash flow in account base currency. |
| `period_return` | Empty on the first row. |
| `cumulative_twr` | Linked cumulative TWR. |

CSV files include absolute NAV and cash-flow values. Keep them private.

## Failure behavior

| Condition | Behavior |
| --- | --- |
| Missing required flags | Argparse exits non-zero. |
| No NAV snapshots | Exits `1` with `No NAV snapshots found for the selected account and date range.` |
| `--start-date` after `--end-date` | Exits `1`. |
| Missing `DATABASE_URL` and no override | Exits `1`. |
| Database query error | Exits `1` and prints `Error: <message>` to stderr. |

## Limitations

- Single account only. Use the portfolio guide for consolidated reporting.
- Cash flows are fixed to `Deposits/Withdrawals`.
- Values must already be normalized in the account's base currency.
- No holdings, attribution, or benchmark comparison.
