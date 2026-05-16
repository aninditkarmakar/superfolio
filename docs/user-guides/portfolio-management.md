# Manage Portfolios

Use `scripts/manage_portfolio.py` to create logical portfolios, list them, show member accounts, and attach registered accounts.

## Prerequisites

- The database schema is deployed through the portfolio layer.
- `DATABASE_URL` is set, or you pass `--database-url`.
- Accounts are registered before you attach them.

`--database-url` is a global option and must appear before the subcommand when used:

```bash
python scripts/manage_portfolio.py --database-url "<postgres-url>" list
```

## Create a portfolio

```bash
python scripts/manage_portfolio.py create \
  --name "All Accounts" \
  --reporting-currency USD
```

Output:

```text
Created portfolio: <portfolio-uuid>
```

Creating a portfolio is idempotent when the name and reporting currency match an existing portfolio. If the name exists with a different currency, the database raises an error.

## List portfolios

```bash
python scripts/manage_portfolio.py list
```

Output is tab-separated:

```text
All Accounts	USD	True
```

Columns are `name`, `reporting_currency`, and `is_active`.

## Show portfolio members

```bash
python scripts/manage_portfolio.py show \
  --portfolio-name "All Accounts"
```

Output is tab-separated:

```text
IBKR:U100	USD	Main account
```

Columns are account label, base currency, and display name. The label format is `brokerage_code:external_id`.

## Attach an account

```bash
python scripts/manage_portfolio.py attach-account \
  --portfolio-name "All Accounts" \
  --brokerage-code IBKR \
  --account-external-id U100
```

Output:

```text
Attached account: <membership-uuid>
```

The database validates that the account base currency matches the portfolio reporting currency. Mixed-currency portfolios are not supported.

## Error behavior

Successful commands exit `0`. Exceptions exit `1` and print:

```text
Error: <message>
```

Argument validation errors, such as an invalid subcommand, are handled by argparse.
