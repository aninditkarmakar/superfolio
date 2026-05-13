# TWR Calculation Workflow

SuperFolio supports two TWR calculation workflows:
- `scripts/calculate_twr.py` calculates daily linked TWR from local IBKR Flex XML reports and does not query PostgreSQL.
- `scripts/calculate_twr_from_db.py` calculates daily linked TWR from normalized PostgreSQL facts for one selected brokerage account.

## Inputs

| Flex element | Used for |
| --- | --- |
| `CashTransaction` | External cash-flow amounts in base currency. |
| `EquitySummaryByReportDateInBase` | Daily ending NAV snapshots in base currency. |

By default, cash flows are filtered to `CashTransaction` records whose `type` is `Deposits/Withdrawals`.

## Command

```bash
python scripts/calculate_twr.py \
  --cash-flows scratch/Cash_Flows.xml \
  --daily-nav scratch/Daily_NAV.xml \
  --start-date 2026-01-01 \
  --end-date 2026-01-31 \
  --daily-output output/twr.csv
```

## Options

| Flag | Default | Purpose |
| --- | --- | --- |
| `--cash-flows` | `scratch/Cash_Flows.xml` | Flex XML file containing `CashTransaction` records. |
| `--daily-nav` | `scratch/Daily_NAV.xml` | Flex XML file containing `EquitySummaryByReportDateInBase` records. |
| `--flow-date-field` | `reportDate` | Cash transaction date attribute used for alignment. |
| `--flow-timing` | `start` | Return convention: `start` treats flows as beginning-of-period; `end` treats flows as end-of-period. |
| `--cash-flow-type` | `Deposits/Withdrawals` | Cash transaction type filter; pass an empty string to include all types. |
| `--start-date` | none | Inclusive date filter in `YYYY-MM-DD` format. |
| `--end-date` | none | Inclusive date filter in `YYYY-MM-DD` format. |
| `--daily-output` | none | Optional CSV path for daily rows. |

## Database-backed command

```bash
python scripts/calculate_twr_from_db.py \
  --brokerage-code IBKR \
  --account-external-id U100 \
  --start-date 2026-01-01 \
  --end-date 2026-01-31 \
  --daily-output output/twr.csv
```

The database-backed command uses `DATABASE_URL` by default and accepts `--database-url` for a one-run override. It reads `daily_nav_snapshots` and only `cash_flows` rows whose `cash_flow_type` is `Deposits/Withdrawals`. It does not accept a cash-flow type option.

## Cash-flow alignment

The engine aligns each cash flow to the first NAV date on or after the flow effective date. Cash flows after the final NAV date are dropped and reported as a warning.

## Return math

For each NAV snapshot after the first one, the engine calculates a period return and links it into cumulative TWR.

With `--flow-timing start`:

```text
period_return = ending_nav / (previous_nav + net_flow) - 1
```

With `--flow-timing end`:

```text
period_return = (ending_nav - net_flow) / previous_nav - 1
```

The first row has no period return because there is no previous NAV.

## CSV output

When `--daily-output` is provided, the CSV contains one row per NAV snapshot with report date, ending NAV base value, net cash flow base value, period return, and cumulative TWR.

## Current limits

- The XML TWR CLI reads local XML files and does not query the database; use `calculate_twr_from_db.py` after records have been loaded into PostgreSQL.
- The parser uses base-currency values from Flex XML and does not fetch external FX rates.
- Holdings, attribution, and benchmark comparison are not implemented in this workflow.
