# Set Up Integration Connections

Use `scripts/manage_integration_connections.py` to configure broker login connections, encrypted credentials, feeds, and account assignments for automated ingestion.

## Prerequisites

- Database migrations are deployed through `create_automation_layer`.
- `DATABASE_URL` is set.
- `SUPERFOLIO_CREDENTIAL_MASTER_KEY` is set locally.
- Accounts are registered.
- Portfolios are created if you plan to assign a whole portfolio.

Generate the master key once per environment:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store it as `SUPERFOLIO_CREDENTIAL_MASTER_KEY` locally and as a GitHub Actions repository secret.

## Create a connection

```bash
python scripts/manage_integration_connections.py create \
  --integration ibkr_flex_ws \
  --brokerage-code IBKR \
  --name "Primary login"
```

Output:

```text
created connection: <connection-uuid>
```

## Store credentials

Pass plaintext credentials through environment variables, never inline as flag values.

```bash
MY_FLEX_TOKEN="<token>" \
  python scripts/manage_integration_connections.py set-credential \
    --connection-id <connection-uuid> \
    --credential-name flex_token \
    --value-from-env MY_FLEX_TOKEN
```

For each feed query ID, the credential name must be `feed:{feed_key}:query_id`:

```bash
MY_FLEX_QUERY_ID="<query-id>" \
  python scripts/manage_integration_connections.py set-credential \
    --connection-id <connection-uuid> \
    --credential-name feed:primary:query_id \
    --value-from-env MY_FLEX_QUERY_ID
```

Setting the same credential name again rotates the credential by deactivating the previous row and inserting a new encrypted value.

## Add a feed

```bash
python scripts/manage_integration_connections.py add-feed \
  --connection-id <connection-uuid> \
  --feed-key primary \
  --display-name "Primary Flex feed"
```

Output:

```text
created feed: <feed-uuid>
```

The `feed_key` must match the credential-name segment in `feed:{feed_key}:query_id`.

## Assign accounts

Assign one account:

```bash
python scripts/manage_integration_connections.py assign-account \
  --connection-id <connection-uuid> \
  --brokerage-code IBKR \
  --account-external-id U100
```

Assign multiple accounts:

```bash
python scripts/manage_integration_connections.py assign-accounts \
  --connection-id <connection-uuid> \
  --brokerage-code IBKR \
  --account-external-id U100 \
  --account-external-id U200
```

Assign all accounts in a portfolio:

```bash
python scripts/manage_integration_connections.py assign-portfolio \
  --connection-id <connection-uuid> \
  --portfolio-name "All Accounts" \
  --brokerage-code IBKR
```

Only one active assignment per account is maintained. Re-assigning an account updates the active assignment.

## Validate assignments

For a portfolio target:

```bash
python scripts/manage_integration_connections.py validate-assignments \
  --target-type portfolio \
  --portfolio-name "All Accounts" \
  --brokerage-code IBKR
```

For an account-list target:

```bash
python scripts/manage_integration_connections.py validate-assignments \
  --target-type account_list \
  --brokerage-code IBKR \
  --account-external-id U100 \
  --account-external-id U200
```

Success prints:

```text
assignments validated: all accounts assigned
```

Missing assignments print one line per account to stderr:

```text
missing assignment: U100
```

Note the target type difference: setup validation uses `account_list`, while automated ingestion uses `accounts`.

## List configuration

```bash
python scripts/manage_integration_connections.py list-connections
python scripts/manage_integration_connections.py list-feeds --connection-id <connection-uuid>
```

Example output:

```text
id=<connection-uuid> integration=ibkr_flex_ws brokerage=IBKR name='Primary login' active=True
id=<feed-uuid> feed_key=primary display_name='Primary Flex feed' active=True
```

## Error and privacy behavior

- Missing or blank plaintext env vars fail before database writes.
- Missing or invalid master keys fail with a master-key error.
- Database configuration errors are printed verbatim.
- Other database errors are sanitized as `a database error occurred`.
- Plaintext credentials are never printed and are stored encrypted.
