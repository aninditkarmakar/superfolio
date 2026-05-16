# Automated Ingestion

Automated ingestion runs through the manual GitHub Actions workflow `.github/workflows/manual-ingestion.yml`. No cron schedule is enabled yet; all runs are triggered manually via the GitHub Actions `workflow_dispatch` event.

## Required secrets

| Secret | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection string for automation job tracking and ingestion writes. |
| `SUPERFOLIO_CREDENTIAL_MASTER_KEY` | Fernet master key used to decrypt integration credentials stored in the database at runtime. Must be a valid URL-safe base-64 encoded 32-byte key. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |

Per-login broker tokens and query ids are **not** configured as GitHub repository secrets. They are stored encrypted in `integration_connection_credentials` rows in the database and decrypted at runtime using `SUPERFOLIO_CREDENTIAL_MASTER_KEY`. See [Multi-login setup](#multi-login-setup-connection-feed-and-assignment-configuration) below.

These secrets must be configured before triggering the workflow.

## Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `target_type` | Yes | — | `portfolio` or `accounts` |
| `integration` | No | `ibkr_flex_ws` | Integration key; currently only `ibkr_flex_ws` is supported. |
| `mode` | Yes | — | `dry-run` or `load` |
| `start_date` | Yes | — | Start of the requested date range (`YYYY-MM-DD`). |
| `end_date` | Yes | — | End of the requested date range (`YYYY-MM-DD`). |
| `portfolio_name` | Conditional | `""` | Required when `target_type=portfolio`. Must match a registered portfolio name. |
| `account_external_ids` | Conditional | `""` | Comma-separated brokerage external account ids. Required when `target_type=accounts`. |

## Target selection

- **`portfolio`** — resolves all active accounts that are members of the named portfolio. `portfolio_name` must be provided and the portfolio must already exist in the database.
- **`accounts`** — resolves the listed external account ids. `account_external_ids` must be provided as a comma-separated list. Every id must be registered before the workflow runs.

## Behavior

The `ibkr_flex_ws` adapter fetches Flex XML through IBKR Flex Web Service v3. On each run (dry-run or load) it sends a `SendRequest` call using the encrypted `flex_token` and `query_id` credentials, then polls `GetStatement` until the report is ready. The XML is fetched once per connection/feed/run and reused for all eligible accounts in that run.

Key behavioral properties:
- **Date filtering is local.** The `--start-date` and `--end-date` arguments filter records after the XML is retrieved; they are not sent to IBKR. The Flex Query template configured in the IBKR portal controls which date range and accounts are included in the response.
- **Zero-count success does not prove template account inclusion.** A run that completes with zero records for an account is not proof that the Flex Query template covers that account. If an expected account has no records, verify the template configuration in the IBKR Flex portal.
- **Raw XML stays in memory by default** and is not logged or stored. A local debug option is available (see [Local debug](#local-debug) below).
- **No schedule is enabled.** All runs are triggered manually via `workflow_dispatch`.

### Dry-run mode

Dry-run records automation job metadata and per-account outcomes in `automation_jobs` and `automation_job_accounts` but does not create account-scoped `ingestion_runs` rows or write any normalized facts (cash flows, daily NAV snapshots). Use dry-run to validate target resolution and date range selection before committing a load.

### Load mode

Load mode creates one account-scoped `ingestion_runs` row per resolved account, fetches supported Flex records through the `ibkr_flex_ws` integration, and writes normalized cash-flow and daily NAV records through the existing bulk ingestion functions. Each account-level outcome references its `ingestion_runs.id` for traceability.

Load mode checks for overlap during processing of each account: if an active pending or running load job for the same integration and account already covers an intersecting date range, that account's `automation_job_accounts` row is set to `failed` with `error_category="overlapping_load_job"` in the child summary JSON, rather than creating a duplicate run.

### Job outcomes

| Status | Meaning |
| --- | --- |
| `succeeded` | All resolved accounts completed without errors. |
| `partially_succeeded` | One or more accounts were skipped, blocked, or completed with partial data. The workflow exits successfully with a prominent warning summary for review. |
| `failed` | One or more accounts failed with an unrecoverable error, or the job itself failed. The workflow exits with a non-zero status. |

### Privacy posture

Database summaries and workflow step output are privacy-safe. They contain only counts, statuses, and sanitized error categories. Raw amounts, NAV values, account balances, and raw Flex payloads are never written to workflow logs or automation job rows.

## Multi-login setup: connection, feed, and assignment configuration

Before running automated ingestion against a broker login, create the connection record, store its credentials, define its feeds, and assign accounts to it. Use `scripts/manage_integration_connections.py` for all setup steps.

### 1. Generate the master key (once per environment)

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store the output as the `SUPERFOLIO_CREDENTIAL_MASTER_KEY` repository secret and as the same environment variable locally.

### 2. Create an integration connection

```bash
python scripts/manage_integration_connections.py create \
  --integration ibkr_flex_ws \
  --brokerage-code IBKR \
  --name "Primary login"
```

The command prints the new connection id. Record it for the following steps.

### 3. Store credentials for the connection

Credentials are encrypted with the master key before being written to the database. Pass the plaintext value through an environment variable; the `--value-from-env` flag names the variable to read:

```bash
MY_FLEX_TOKEN="<token>" \
  python scripts/manage_integration_connections.py set-credential \
    --connection-id <connection-id> \
    --credential-name flex_token \
    --value-from-env MY_FLEX_TOKEN

MY_FLEX_QUERY_ID="<query-id>" \
  python scripts/manage_integration_connections.py set-credential \
    --connection-id <connection-id> \
    --credential-name feed:primary:query_id \
    --value-from-env MY_FLEX_QUERY_ID
```

> **Credential naming for per-feed query IDs:** The orchestrator looks up each feed's Flex query ID using the key pattern `feed:{feed_key}:query_id`, where `{feed_key}` matches the value passed to `add-feed --feed-key` (e.g. `primary`). Using any other name (such as `flex_query_id`) will cause the orchestrator to skip the feed at runtime.

Setting the same `credential_name` again rotates the previous value: the old row is deactivated and a new active row is inserted.

### 4. Register feeds for the connection

Each feed represents one distinct Flex query configuration associated with the connection:

```bash
python scripts/manage_integration_connections.py add-feed \
  --connection-id <connection-id> \
  --feed-key primary \
  --display-name "Primary Flex feed"
```

### 5. Assign accounts to the connection

Each registered account must be assigned to the connection that will fetch its data.

Assign one account:

```bash
python scripts/manage_integration_connections.py assign-account \
  --connection-id <connection-id> \
  --brokerage-code IBKR \
  --account-external-id U100
```

Assign multiple accounts in one call:

```bash
python scripts/manage_integration_connections.py assign-accounts \
  --connection-id <connection-id> \
  --brokerage-code IBKR \
  --account-external-id U100 \
  --account-external-id U200
```

Assign all accounts in a named portfolio to a connection:

```bash
python scripts/manage_integration_connections.py assign-portfolio \
  --connection-id <connection-id> \
  --portfolio-name "All Accounts" \
  --brokerage-code IBKR
```

Only one active assignment per account is supported; re-assigning an account to a different connection updates the existing assignment.

### 6. Validate assignments before running

```bash
python scripts/manage_integration_connections.py validate-assignments \
  --target-type portfolio \
  --portfolio-name "All Accounts" \
  --brokerage-code IBKR
```

Exits `0` with `assignments validated: all accounts assigned` when every active account in the target has an active assignment. Exits `1` and prints unassigned account ids if any are missing.

For an account-list target:

```bash
python scripts/manage_integration_connections.py validate-assignments \
  --target-type account_list \
  --brokerage-code IBKR \
  --account-external-id U100 \
  --account-external-id U200
```

### 7. List connections and feeds

```bash
python scripts/manage_integration_connections.py list-connections

python scripts/manage_integration_connections.py list-feeds \
  --connection-id <connection-id>
```

### Cutover checklist

When migrating from a single-login setup to a multi-login setup, complete these steps before the first automated run:

1. **Remove old per-login secrets** — delete `IBKR_FLEX_TOKEN` and `IBKR_FLEX_QUERY_ID` repository secrets if they were previously configured. They are no longer read by the workflow.
2. **Add `SUPERFOLIO_CREDENTIAL_MASTER_KEY`** — generate and store the Fernet master key as a repository secret (step 1 above).
3. **Deploy the latest migrations** — ensure `create_automation_layer` is deployed. It includes `integration_connections`, `integration_connection_credentials`, `integration_feeds`, and `account_integration_assignments`.
4. **Create connections and store credentials** — run steps 2–4 above for each distinct broker login.
5. **Assign all automation-target accounts** — run step 5 above so every account that will be resolved by the workflow has an active assignment.
6. **Validate assignments** — run step 6 above for each configured target before triggering the workflow.
7. **Trigger a dry-run** — confirm target resolution, assignment lookup, and credential loading succeed. Job lifecycle and per-account outcomes are recorded. No facts are written in dry-run mode. Note: dry-run makes a live IBKR Flex Web Service call (`SendRequest`/`GetStatement`), so the stored credentials and Flex query must be valid and API-enabled before running.

## CLI entry point

The workflow calls:

```bash
python scripts/run_automated_ingestion.py \
  --target-type portfolio \
  --integration ibkr_flex_ws \
  --mode dry-run \
  --start-date 2026-01-01 \
  --end-date 2026-01-31 \
  --portfolio-name "All Accounts"
```

The CLI is implemented in `scripts/run_automated_ingestion.py` with orchestration logic in `portfolio_engine/automation/cli.py` and `portfolio_engine/automation/orchestrator.py`.

## Local debug

The CLI accepts a `--debug-raw-xml-dir` flag that saves the fetched Flex XML to a local directory for inspection:

```bash
python scripts/run_automated_ingestion.py \
  --target-type accounts \
  --integration ibkr_flex_ws \
  --mode dry-run \
  --start-date 2026-01-01 \
  --end-date 2026-01-31 \
  --account-external-ids U100 \
  --debug-raw-xml-dir scratch/ibkr-debug
```

> **⚠️ Local use only.** The `--debug-raw-xml-dir` flag is intended for local development only. The GitHub Actions workflow does not accept or pass this argument. Passing it in the workflow would expose raw broker XML in workflow artifacts, which is prohibited. The `scratch/` directory is git-ignored; keep debug output there and never commit it.

## Known limitations

- **No schedule:** The workflow is `workflow_dispatch` only. Scheduled daily runs are not enabled yet.
- **Supported record types:** Only `Deposits/Withdrawals` cash transactions and `EquitySummaryByReportDateInBase` daily NAV records are supported by the ingestion functions. Other `CashTransaction` types are counted as unsupported and skipped.
