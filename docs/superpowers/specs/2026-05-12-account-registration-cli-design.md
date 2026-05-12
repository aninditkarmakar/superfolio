# Account Registration CLI Design

## Problem

Manual Flex XML ingestion requires accounts to exist before cash-flow and daily-NAV records are loaded. The database already exposes `register_account(...)` as the canonical account creation boundary, but there is no Python command-line workflow for registering an account before ingestion.

## Proposed approach

Add an account-registration CLI after the Python database adapter block and before the manual-file ingestion dry-run block. The CLI should use the shared Python database adapter from Block 2 instead of opening its own database connection or shelling out to `psql`.

This keeps account setup, ingestion loading, and future TWR database reads on the same connection/error-handling foundation.

## Scope

In scope:

- A Python CLI for registering one account at a time.
- CLI parameters for every `register_account(...)` input:
  - `brokerage_code`
  - `external_id`
  - `account_type`
  - `base_currency`
  - optional `display_name`
- Interactive prompting for missing values when stdin is interactive.
- Clear failure when required values are missing and stdin is not interactive.
- Calling the Block 2 Python database adapter rather than duplicating SQL connection logic.
- Clear success and error output.
- Unit tests for argument handling, prompting behavior, non-interactive failures, and adapter calls.

Out of scope:

- Bulk account import.
- Account metadata update or activation/deactivation commands.
- Direct `psql` subprocess integration.
- Flex XML ingestion, dry-run summaries, or load mode.
- TWR calculation.

## Architecture

The CLI should be a thin command layer over the database adapter:

1. Parse command-line arguments.
2. Prompt for missing fields when running interactively.
3. Validate required fields are not blank.
4. Build an account-registration request object.
5. Call the Block 2 adapter method that wraps `public.register_account(...)`.
6. Print a concise result containing the registered account id and safe account metadata.

The database adapter remains responsible for PostgreSQL connection details, SQL execution, transaction handling, and translating database failures into surfaced exceptions. The CLI remains responsible for user interaction and formatting.

## Command interface

The command should accept these options:

```text
--brokerage-code TEXT
--external-id TEXT
--account-type TEXT
--base-currency TEXT
--display-name TEXT
--database-url TEXT
```

`--database-url` should follow the Block 2 adapter convention. If the adapter uses `DATABASE_URL` by default, the CLI should do the same.

`display_name` is optional. In interactive mode, the prompt should allow an empty answer for no display name.

## Interactive behavior

When stdin is interactive:

- Missing required fields are prompted one at a time.
- Missing optional `display_name` is also prompted, with an empty response meaning `None`.
- Blank responses for required fields are rejected and re-prompted.

When stdin is not interactive:

- Missing required fields cause a clear error listing the missing option names.
- Missing `display_name` is accepted as `None`.
- The command exits non-zero without attempting a database call.

## Validation and normalization

The CLI should reject blank required values before calling the adapter. It may trim surrounding whitespace before validation.

The database function already normalizes brokerage code and base currency to uppercase. The CLI may display normalized values in its output, but it should not attempt to implement separate business rules that could drift from the database contract.

## Error handling

Expected database errors should be shown clearly, including:

- Unknown or inactive brokerage code.
- Existing account with conflicting account type or base currency.
- Database connection failure.

The CLI should not swallow exceptions or print success-shaped output after a failure.

## Testing

Tests should cover:

- All parameters supplied: no prompts, adapter called once with expected values.
- Missing required parameter in interactive mode: prompts and uses supplied response.
- Missing `display_name` in interactive mode: empty response becomes `None`.
- Missing required parameter in non-interactive mode: fails before adapter call.
- Blank required prompt response: re-prompts until non-blank.
- Adapter/database exception: command exits non-zero and prints the error.

The tests should use a fake adapter rather than a real database. Block 2 owns database integration tests for the adapter itself.

## Implementation order

This block should run after Block 2 because it depends on the Python database adapter. It should run before the manual-file ingestion dry-run block because account readiness is part of the ingestion workflow.

## Open decisions

No open product decisions remain. The CLI will use the Block 2 Python database adapter, and non-interactive runs will fail clearly when required values are missing.
