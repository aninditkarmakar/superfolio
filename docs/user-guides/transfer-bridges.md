# Manage Transfer Bridges

A transfer bridge models value that is temporarily outside account NAV while moving between two accounts in the same portfolio. It prevents portfolio TWR from showing a false loss while assets are in transit.

## When to use a bridge

Use a bridge when:

- Money or assets leave one portfolio account on one NAV date.
- The same value does not arrive in the destination account until a later NAV date.
- Both accounts are members of the same portfolio.

Do not use a bridge for same-day transfers or transfers that naturally offset in account NAV snapshots.

## Create a bridge

```bash
python scripts/manage_portfolio.py create-bridge \
  --portfolio-name "All Accounts" \
  --source-brokerage-code IBKR \
  --source-account-external-id U100 \
  --destination-brokerage-code IBKR \
  --destination-account-external-id U200 \
  --departure-date 2026-01-15 \
  --arrival-date 2026-01-20 \
  --value 50000.00 \
  --currency USD \
  --note "Account relocation"
```

`--note` is optional. All other flags are required.

Output:

```text
Created transfer bridge: <bridge-uuid>
```

## List bridges

```bash
python scripts/manage_portfolio.py list-bridges \
  --portfolio-name "All Accounts"
```

Output is tab-separated:

```text
IBKR:U100->IBKR:U200	2026-01-15..2026-01-20	50000.00 USD	Account relocation
```

## Date behavior

The bridge value is added only on NAV dates strictly between the departure and arrival dates:

```text
departure_date < nav_date < arrival_date
```

For a Jan 15 to Jan 20 bridge:

| Date | Bridge applied? |
| --- | --- |
| Jan 15 | No |
| Jan 16-19 | Yes |
| Jan 20 | No |

If departure and arrival are the same date, the bridge window is empty.

## Validation

- `--value` must be a finite decimal.
- The model requires bridge value to be positive.
- Source and destination accounts must differ.
- Arrival date must be on or after departure date.
- Bridge currency must match the portfolio TWR reporting currency when calculating TWR.
- Overlapping bridges for the same source-to-destination pair can raise an error during TWR calculation.

## Privacy notes

Bridge values are absolute account values. Treat bridge listings and portfolio CSVs as private.
