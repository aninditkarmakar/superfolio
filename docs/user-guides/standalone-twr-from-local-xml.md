# Calculate TWR from Local XML

Use `scripts/calculate_twr.py` to calculate daily linked Time-Weighted Return for one account from local IBKR Flex XML files without querying PostgreSQL.

## Inputs

| Input | Default path | Flex element |
| --- | --- | --- |
| `--cash-flows` | `scratch/Cash_Flows.xml` | `CashTransaction` |
| `--daily-nav` | `scratch/Daily_NAV.xml` | `EquitySummaryByReportDateInBase` |

NAV values come from the Flex `total` attribute in base currency. Cash-flow base values are calculated from `amount * fxRateToBase`.

## Command

```bash
python scripts/calculate_twr.py \
  --cash-flows scratch/Cash_Flows.xml \
  --daily-nav scratch/Daily_NAV.xml \
  --flow-date-field reportDate \
  --flow-timing start \
  --cash-flow-type "Deposits/Withdrawals" \
  --start-date 2026-01-01 \
  --end-date 2026-01-31 \
  --daily-output output/twr.csv
```

## Options

| Flag | Default | Description |
| --- | --- | --- |
| `--cash-flows` | `scratch/Cash_Flows.xml` | Flex XML file containing cash transactions. |
| `--daily-nav` | `scratch/Daily_NAV.xml` | Flex XML file containing daily NAV snapshots. |
| `--flow-date-field` | `reportDate` | Cash transaction date attribute used for alignment. Choices: `reportDate`, `dateTime`, `settleDate`, `availableForTradingDate`. |
| `--flow-timing` | `start` | Return convention: `start` or `end`. |
| `--cash-flow-type` | `Deposits/Withdrawals` | Cash transaction type filter. Pass `""` to include all types. |
| `--start-date` | none | Inclusive date filter in `YYYY-MM-DD` format. |
| `--end-date` | none | Inclusive date filter in `YYYY-MM-DD` format. |
| `--daily-output` | none | Optional CSV path for daily rows. |

## Output

```text
NAV snapshots: 83
Cash-flow records: 4
Return periods: 82
Date range: 2026-01-02 to 2026-04-25
Cash-flow date field: reportDate
Cash-flow timing: start
TWR: 12.345678%
Daily output written to output/twr.csv
```

Cash flows after the final NAV date are dropped and reported:

```text
Warning: dropped 1 cash flow(s) after the final NAV date.
```

## Cash-flow alignment

The engine treats NAV dates as the canonical timeline. Each cash flow is aligned to the first NAV date on or after the flow's effective date. Multiple flows aligned to the same NAV date are summed.

## Return math

With `--flow-timing start`:

```text
period_return = ending_nav / (previous_nav + net_flow) - 1
```

With `--flow-timing end`:

```text
period_return = (ending_nav - net_flow) / previous_nav - 1
```

The first row has no period return because there is no previous NAV. Cumulative TWR is linked multiplicatively.

## CSV output

When `--daily-output` is supplied, the CSV columns are:

| Column | Description |
| --- | --- |
| `date` | NAV report date. |
| `ending_nav_base` | Ending NAV in base currency. |
| `net_cash_flow_base` | Net aligned cash flow in base currency. |
| `period_return` | Empty on the first row. |
| `cumulative_twr` | Linked cumulative TWR. |

CSV files include absolute NAV and cash-flow values. Treat them as private.

## Limitations

- This command does not query PostgreSQL.
- It uses Flex-provided base-currency values and does not fetch external FX rates.
- Missing or zero `fxRateToBase` can make a cash-flow base value zero.
- Holdings, attribution, benchmark comparison, and portfolio aggregation are not included.
