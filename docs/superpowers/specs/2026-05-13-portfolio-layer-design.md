# Portfolio Layer Design

## Problem

SuperFolio needs to calculate one consolidated performance history across multiple brokerage accounts. The immediate use case is an investor who moved from Canada to the United States and now has separate Canadian and US IBKR accounts. IBKR account-level performance history is fragmented by account, but the investor wants a single portfolio-level TWR curve.

The design must also support future multi-account comparison views and brokerages where transferred assets can be out of both account NAV values for several days.

## Goals

- Add a logical portfolio layer above brokerage accounts.
- Allow one brokerage account to belong to multiple portfolios for comparison views.
- Calculate portfolio-level daily TWR from existing account NAV and cash-flow facts.
- Treat missing account NAV as zero with warnings, while preserving explicit zero NAV as valid data.
- Support explicit in-transit transfer bridge adjustments for multi-day internal transfer gaps.
- Preserve inactive legacy account history when an inactive account is attached to a portfolio.
- Keep the first version CLI-managed and compatible with the current Python/PostgreSQL architecture.

## Non-goals

- No frontend or API implementation in this feature.
- No automatic FX conversion for mixed-currency portfolios.
- No position-level transfer valuation or security price ingestion.
- No account membership date windows in the first version.
- No expansion of supported external cash-flow types beyond the current `Deposits/Withdrawals` behavior.
- No special handling for zero or undefined portfolio-level TWR periods until a real-world use case requires it.

## Portfolio model

Add a portfolio layer that stores saved calculation/view definitions. A portfolio has a stable identifier, display name, reporting currency, and active flag. A portfolio references existing registered brokerage accounts through a membership table. It does not duplicate or own broker-ingested data.

Accounts can belong to multiple portfolios. This allows views such as "all accounts", "public taxable portfolio", "IBKR-only", or "Canada+US relocation history" to share the same underlying account facts without duplicating ingestion.

Membership has no date window in the first version. If an account belongs to a portfolio, its entire available NAV and supported cash-flow history contributes whenever the calculation date range includes those records.

Inactive accounts still contribute historical data when they are portfolio members. Account activity status controls whether new operational workflows should treat an account as active, but it must not remove legacy account NAV from portfolio history.

## Portfolio daily NAV and TWR

For a requested portfolio/date range, the calculator:

1. Resolves the portfolio and member accounts.
2. Loads member account daily NAV snapshots.
3. Loads supported member account external cash flows.
4. Builds the portfolio daily series from the union of all member account NAV dates.
5. Calculates portfolio TWR using the existing daily valuation method.

On each portfolio date:

- Portfolio account NAV is the sum of member account NAV rows for that date.
- If a member account has no NAV row for that date, it contributes zero and the row records a missing-NAV warning.
- If a member account has an explicit zero NAV row, that is valid data and is not a warning.
- Portfolio NAV adds any active transfer bridge value for that date.
- Net external cash flow is the sum of supported external cash flows across member accounts.

The CLI prints an aggregate portfolio TWR summary to stdout, similar to the current database-backed single-account TWR CLI. The summary must include missing-NAV warning counts grouped by portfolio member account so partially ingested account histories are visible. A detailed daily CSV is optional. When requested, the CSV should include portfolio NAV, net external cash flow, transfer bridge value, missing-NAV diagnostics, period return, and cumulative TWR.

## Transfer bridges

A transfer bridge is an explicit portfolio-level adjustment for assets temporarily outside account NAV during an internal transfer. It records:

- Portfolio
- Source account
- Destination account
- Departure date
- Arrival date
- Value
- Currency

The first version requires the bridge currency to equal the portfolio reporting currency. The value is carried unchanged across the gap.

A bridge contributes to portfolio NAV only on dates strictly after the departure date and strictly before the arrival date. It does not contribute on the departure date or arrival date because those dates should be represented by source or destination account NAV. Same-day transfers naturally add no bridge value.

Transfer bridges are not cash flows. They do not affect net external flow; they only prevent artificial NAV drops while assets are in transit.

Bridge source and destination accounts must both be members of the target portfolio. A bridge cannot overlap the open interval of another bridge for the same source account and destination account pair. This prevents accidentally double-counting one transfer path while still allowing distinct non-overlapping transfers between the same accounts.

## Currency behavior

The first version requires every member account's stored NAV and cash-flow base values to already match the portfolio reporting currency. Portfolio TWR calculation must validate both account metadata and the actual included facts: member account `base_currency`, daily NAV snapshot `base_currency`, and cash-flow base assumptions must all be compatible with the portfolio reporting currency. If any included account or fact differs from the portfolio reporting currency, calculation fails with a clear unsupported-currency error.

This keeps the first implementation correct for the IBKR use case where both account histories can be exported and loaded in USD. Daily FX tables and automatic mixed-currency conversion are future work.

## CLI scope

The first version is CLI-managed. It should support:

- Creating portfolios with a display name and reporting currency.
- Listing portfolios.
- Showing one portfolio and its member accounts.
- Attaching existing registered accounts by brokerage code and external account id.
- Listing portfolio accounts.
- Creating transfer bridges for a portfolio.
- Listing transfer bridges for a portfolio.
- Calculating portfolio TWR by portfolio identifier.

The CLI should follow the current account and database TWR command style: explicit arguments for non-interactive use, clear validation errors, stdout summaries, and optional CSV output where applicable.

## Validation and error handling

Strict validation is required where silent math would be dangerous:

- Unknown portfolio fails.
- Unknown account fails.
- Empty portfolio fails.
- Unsupported mixed-currency portfolio fails.
- Bridge currency mismatch fails.
- Bridge source or destination account outside the portfolio fails.
- Bridge overlap for the same source/destination pair fails.
- Invalid bridge date range fails.
- No NAV data fails.

Missing NAV for a member account on a portfolio date does not fail. It contributes zero and emits warnings in the CLI summary and optional CSV diagnostics.

Supported external cash flows remain limited to `Deposits/Withdrawals`, matching the current implementation. Cash-transaction classification is the responsibility of ingestion. Brokers that emit internal transfers as cash transactions must classify those records as `Transfer` instead of `Deposits/Withdrawals` before they reach portfolio TWR calculation, so internal movement does not distort external-flow-adjusted returns.

## Testing

Database and adapter tests should verify:

- Portfolio creation.
- Account attachment.
- One account attached to multiple portfolios.
- Transfer bridge storage.
- Bridge member-account validation.
- Bridge overlap validation.
- Duplicate handling.
- Validation failures.

Calculation tests should use synthetic data for:

- IBKR-style same-day transfer where account NAV changes offset without a bridge.
- Multi-day transfer gap covered by a constant-value bridge.
- Missing NAV treated as zero with warnings.
- Missing NAV warning counts grouped by member account in the CLI summary.
- Explicit zero NAV treated as valid data.
- Unsupported mixed-currency calculation failure.
- Optional daily CSV output.

Existing account ingestion and single-account TWR behavior should remain intact.
