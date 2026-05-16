# Register a Brokerage Account

Register each brokerage account before loading Flex XML records, assigning automation connections, or adding the account to a portfolio.

## Prerequisites

- Python dependencies are installed.
- The PostgreSQL schema is deployed.
- `DATABASE_URL` is set, or you pass `--database-url`.
- The brokerage code exists in the database. The current seed includes `IBKR`.

## Command

```bash
python scripts/register_account.py \
  --brokerage-code IBKR \
  --external-id U100 \
  --account-type Individual \
  --base-currency USD \
  --display-name "Main account"
```

## Options

| Flag | Required | Description |
| --- | --- | --- |
| `--brokerage-code` | Yes | Brokerage code, for example `IBKR`. |
| `--external-id` | Yes | Broker-assigned account identifier, for example `U100`. |
| `--account-type` | Yes | Account type label, for example `Individual`, `TFSA`, or `IRA`. |
| `--base-currency` | Yes | Account base currency, for example `USD` or `CAD`. |
| `--display-name` | No | Friendly account name shown in CLI output. |
| `--database-url` | No | One-run database URL override. Defaults to `DATABASE_URL`. |

## Interactive behavior

If the command is run in an interactive terminal and a field is missing, it prompts for that value. Required fields keep prompting on blank input. `--display-name` is optional; a blank value becomes `(none)`.

In non-interactive use, missing required values fail before any database call:

```text
Error: Missing required option(s): --external-id, --base-currency
```

## Success output

```text
Registered account: <account-uuid>
Brokerage: IBKR
External ID: U100
Account type: Individual
Base currency: USD
Display name: Main account
```

The command exits `0` on success and `1` on errors.

## Idempotency

Re-running the command with the same brokerage code, external ID, account type, and base currency returns the existing account ID. If an account already exists with the same brokerage code and external ID but different account type or base currency, the database function raises an error.

## Privacy notes

The command prints the brokerage code, external account ID, account type, currency, and display name. Use synthetic IDs in documentation and public logs.
