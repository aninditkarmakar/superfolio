# Database-backed TWR CLI Design

## Problem

`scripts/calculate_twr.py` calculates Time-Weighted Return from local IBKR Flex XML files. SuperFolio now persists ingested cash-flow and daily NAV facts in PostgreSQL, so the project needs a similar CLI that calculates TWR from the database for a selected brokerage account.

## Goals

- Calculate TWR for one selected account identified by brokerage code and brokerage account id.
- Read normalized database facts instead of Flex XML files.
- Reuse the existing TWR engine and CSV export format.
- Include only `Deposits/Withdrawals` cash-flow records in the TWR calculation.
- Use all available database history by default, with optional inclusive `--start-date` and `--end-date` filters.
- Keep `--flow-timing` available with the existing `start` default.

## Non-goals

- Consolidated multi-account portfolio TWR.
- User-selectable cash-flow type filtering.
- Changes to the TWR math.
- New output columns in the daily CSV.
- Dashboard, API, or scheduled automation work.

## Proposed approach

Add read-only query methods to `portfolio_engine.database.SuperFolioDatabase`, then create a new CLI at `scripts/calculate_twr_from_db.py`.

This follows the existing database boundary: scripts call the Python adapter instead of embedding database access directly. The CLI mirrors the file-based script where possible, but replaces XML parser inputs with database rows mapped to the existing `NavSnapshot` and `CashFlow` dataclasses.

## CLI interface

Example:

```bash
python scripts/calculate_twr_from_db.py \
  --brokerage-code IBKR \
  --account-external-id U100 \
  --start-date 2026-01-01 \
  --end-date 2026-01-31 \
  --daily-output output/twr.csv
```

Options:

| Flag | Default | Purpose |
| --- | --- | --- |
| `--brokerage-code` | required | Brokerage code used to resolve the account, for example `IBKR`. |
| `--account-external-id` | required | Brokerage account id used to resolve the account. |
| `--database-url` | `DATABASE_URL` | Optional one-run database URL override. |
| `--flow-timing` | `start` | Return convention; same choices as the XML CLI: `start` or `end`. |
| `--start-date` | none | Inclusive date filter in `YYYY-MM-DD` format. |
| `--end-date` | none | Inclusive date filter in `YYYY-MM-DD` format. |
| `--daily-output` | none | Optional CSV path using the existing daily TWR CSV schema. |

## Database reads

The adapter will expose two focused methods:

- `fetch_nav_snapshots(...) -> list[NavSnapshot]`
- `fetch_cash_flows(...) -> list[CashFlow]`

Both methods resolve data through `brokerages.code` and `accounts.external_id`. Queries use the selected account and optional date window. Historical reads do not filter on `accounts.is_active`; inactive accounts may still have valid past performance history.

NAV rows come from `daily_nav_snapshots`:

- `snapshot_date` maps to `NavSnapshot.report_date`
- `nav_base` maps to `NavSnapshot.total_base`
- rows are ordered by `snapshot_date`

Cash-flow rows come from `cash_flows`:

- `flow_date` maps to `CashFlow.effective_date`
- `amount_base` maps to `CashFlow.amount_base`
- rows are restricted to `cash_flow_type = 'Deposits/Withdrawals'`
- rows are ordered by `flow_date`

## Calculation flow

1. Parse CLI arguments.
2. Connect with `connect_database(args.database_url)`.
3. Fetch ordered NAV snapshots for the selected brokerage account and date window.
4. Fail if no NAV snapshots exist for that selection.
5. Fetch matching deposit/withdrawal cash flows for the same account and date window.
6. Align cash flows to NAV dates with `align_flows_to_nav_dates`.
7. Calculate rows with `calculate_twr`.
8. Print a summary to stdout.
9. If requested, write daily rows with `write_daily_twr_csv`.

The stdout summary should stay close to `calculate_twr.py`, but replace file-specific lines with database/account context:

```text
Brokerage: IBKR
Account: U100
NAV snapshots: 83
Cash-flow records: 4
Return periods: 82
Date range: 2026-01-02 to 2026-04-25
Cash-flow type: Deposits/Withdrawals
Cash-flow timing: start
TWR: 12.345678%
Daily output written to output/twr.csv
```

If aligned cash flows are dropped after the final NAV date, print the existing warning pattern.

## Error handling

- Missing or blank database configuration raises the existing `DatabaseConfigurationError` message.
- Invalid dates fail during argument parsing with the existing date parser behavior.
- Unknown brokerage/account selection returns no NAV rows and the CLI exits with the same no-snapshots message used for empty date windows.
- No NAV snapshots for the selected account and date range exits with: `No NAV snapshots found for the selected account and date range.`
- Zero matching deposit/withdrawal cash flows is valid and calculates TWR with zero flows.
- Database errors are not swallowed; they propagate after the adapter rolls back consistently with existing write methods.

## Testing

Add focused `unittest` coverage:

- Adapter read methods execute the expected parameterized SQL and map returned rows to `NavSnapshot` and `CashFlow`.
- Adapter read methods support absent `start_date` and `end_date`.
- CLI prints the expected summary using fake database data.
- CLI fails clearly when no NAV snapshots are returned.
- CLI writes the same CSV schema through `write_daily_twr_csv`.
- CLI uses only `Deposits/Withdrawals` by construction; no user-facing cash-flow type option is added.

The existing TWR math remains tested through `portfolio_engine.twr`; CLI tests should verify wiring and output rather than duplicate return calculations exhaustively.

## Documentation updates

Update README and the TWR workflow documentation to describe the database-backed command separately from the XML-file workflow. The docs should mention the required account selection, `DATABASE_URL`, the hard-coded deposit/withdrawal cash-flow filter, optional date filters, and CSV output parity.
