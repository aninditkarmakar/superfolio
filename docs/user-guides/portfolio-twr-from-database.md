# Calculate Portfolio TWR from the Database

Use `scripts/calculate_portfolio_twr_from_db.py` to calculate consolidated daily linked TWR for a logical portfolio across its member accounts.

## Prerequisites

- The database schema is deployed through the portfolio layer.
- `DATABASE_URL` is set, or you pass `--database-url`.
- The portfolio exists.
- Member accounts are attached to the portfolio.
- Daily NAV snapshots and supported cash-flow records have been loaded.
- Transfer bridges have been created when needed for in-transit internal transfers.

## Command

```bash
python scripts/calculate_portfolio_twr_from_db.py \
  --portfolio-name "All Accounts" \
  --reporting-currency USD \
  --start-date 2026-01-01 \
  --end-date 2026-01-31 \
  --daily-output output/portfolio-twr.csv
```

## Options

| Flag | Required | Default | Description |
| --- | --- | --- | --- |
| `--portfolio-name` | Yes | none | Exact portfolio name. |
| `--reporting-currency` | Yes | none | Currency expected for all member accounts, NAVs, cash flows, and bridges. |
| `--database-url` | No | `DATABASE_URL` | One-run database URL override. |
| `--flow-timing` | No | `start` | Return convention: `start` or `end`. |
| `--start-date` | No | none | Inclusive date filter for NAV and cash-flow records. |
| `--end-date` | No | none | Inclusive date filter for NAV and cash-flow records. |
| `--daily-output` | No | none | Optional portfolio daily CSV path. |

Transfer bridges are fetched for the whole portfolio and applied only when their date window overlaps NAV dates in the requested range.

## Output

```text
Portfolio: All Accounts
Reporting currency: USD
Member accounts: 2
NAV rows: 44
Cash-flow records: 3
Transfer bridges: 1
Return periods: 21
Date range: 2026-01-01 to 2026-01-31
TWR: 2.345678%
Daily output written to output/portfolio-twr.csv
```

If any member account is missing a NAV snapshot on a portfolio NAV date, the summary includes:

```text
Missing NAV warnings:
  IBKR:U100: 3
```

Missing account NAV is treated as zero for that date, so warnings are important data-quality signals.

## Calculation behavior

1. Validate that all accounts, NAV rows, cash flows, and bridges match `--reporting-currency`.
2. Sum member account NAV by date.
3. Add active transfer bridge value on dates strictly between bridge departure and arrival.
4. Align each `Deposits/Withdrawals` cash flow to the first NAV date on or after the flow date.
5. Calculate linked TWR with the selected flow timing.

Unlike the single-account TWR CLI, portfolio TWR treats cash flows outside the NAV date range as an error.

## CSV output

When `--daily-output` is supplied, the CSV columns are:

| Column | Description |
| --- | --- |
| `date` | Portfolio NAV date. |
| `ending_nav_base` | Sum of member NAV plus active bridge value. |
| `net_cash_flow_base` | Net aligned external cash flow. |
| `bridge_value_base` | Transfer bridge value applied that day. |
| `missing_nav_accounts` | Semicolon-separated account labels with missing NAV. |
| `period_return` | Empty on the first row. |
| `cumulative_twr` | Linked cumulative TWR. |

The CSV includes absolute NAV and bridge values. Treat it as private.

## Limitations and gotchas

- Mixed-currency portfolios are not supported.
- `--reporting-currency` is supplied by the caller and validated against data; it is not inferred from the portfolio record.
- Cash flows are hard-filtered to `Deposits/Withdrawals`.
- Inactive accounts can still contribute historical portfolio data.
- A portfolio with no members or no NAV snapshots fails.
