# Run Automated Ingestion

Use automated ingestion to fetch IBKR Flex XML through Flex Web Service and either dry-run or load supported records for selected accounts.

Automated ingestion is available through:

- Local CLI: `scripts/run_automated_ingestion.py`
- Manual GitHub Actions workflow: `.github/workflows/manual-ingestion.yml`

No schedule is enabled. The GitHub Actions workflow is manual only.

## Prerequisites

- Database schema is deployed through `create_automation_layer`.
- `DATABASE_URL` is set locally or configured as a GitHub Actions secret.
- `SUPERFOLIO_CREDENTIAL_MASTER_KEY` is set locally or configured as a GitHub Actions secret.
- Integration connections, credentials, feeds, and account assignments are configured.
- The IBKR Flex Query template is configured in the IBKR portal and API-enabled.

## Local CLI

Portfolio target:

```bash
python scripts/run_automated_ingestion.py \
  --target-type portfolio \
  --integration ibkr_flex_ws \
  --mode dry-run \
  --start-date 2026-01-01 \
  --end-date 2026-01-31 \
  --portfolio-name "All Accounts"
```

Account-list target:

```bash
python scripts/run_automated_ingestion.py \
  --target-type accounts \
  --integration ibkr_flex_ws \
  --mode load \
  --start-date 2026-01-01 \
  --end-date 2026-01-31 \
  --account-external-ids U100,U200
```

## Options

| Flag | Required | Default | Description |
| --- | --- | --- | --- |
| `--target-type` | Yes | none | `portfolio` or `accounts`. |
| `--integration` | No | `ibkr_flex_ws` | Integration key. |
| `--mode` | Yes | none | `dry-run` or `load`. |
| `--start-date` | Yes | none | Local record filter start date. |
| `--end-date` | Yes | none | Local record filter end date. |
| `--portfolio-name` | Conditional | none | Required for `--target-type portfolio`. |
| `--account-external-ids` | Conditional | none | Comma-separated IDs required for `--target-type accounts`. |
| `--debug-raw-xml-dir` | No | none | Local-only debug output directory. Blocked in GitHub Actions. |

For `portfolio`, do not pass `--account-external-ids`. For `accounts`, do not pass `--portfolio-name`.

## Dry-run mode

Dry-run mode:

- Makes live IBKR Flex Web Service calls.
- Creates automation job and account outcome rows.
- Does not create account-scoped ingestion runs.
- Does not write normalized cash flows or daily NAV snapshots.
- Records privacy-safe counts and statuses.

Use dry-run before the first load for a new connection or target.

## Load mode

Load mode:

- Checks for overlapping active load jobs for each account and integration.
- Creates one ingestion run per resolved account.
- Writes supported cash-flow and daily NAV records through the same bulk ingestion functions used by manual file loading.
- Links account-level automation outcomes to ingestion run IDs.

Supported records are `Deposits/Withdrawals` cash transactions and `EquitySummaryByReportDateInBase` daily NAV snapshots.

## Date behavior

`--start-date` and `--end-date` filter records after XML is fetched. They are not sent to IBKR. The Flex Query template in the IBKR portal controls the actual report window and account scope.

A zero-record success does not prove the IBKR template includes the account.

## Status and exit codes

| Automation status | Meaning | CLI exit |
| --- | --- | --- |
| `succeeded` | All resolved accounts completed. | `0` |
| `partially_succeeded` | At least one account succeeded and at least one failed or was partial. | `0` with warning |
| `failed` | The job failed or all accounts failed. | `1` |

Partial success prints a warning that some accounts may have failed.

The CLI always prints:

```text
Automation status: <status>
```

## GitHub Actions workflow

The manual workflow accepts these `workflow_dispatch` inputs:

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `target_type` | Yes | none | `portfolio` or `accounts`. |
| `integration` | No | `ibkr_flex_ws` | Integration key. |
| `mode` | Yes | none | `dry-run` or `load`. |
| `start_date` | Yes | none | `YYYY-MM-DD`. |
| `end_date` | Yes | none | `YYYY-MM-DD`. |
| `portfolio_name` | Conditional | empty | Required for portfolio target. |
| `account_external_ids` | Conditional | empty | Comma-separated IDs for account target. |

The workflow runs on `ubuntu-latest`, installs Python 3.12, installs `requirements.txt`, runs the CLI, and appends the combined CLI output to the GitHub step summary.

## IBKR fetch behavior

The `ibkr_flex_ws` adapter uses IBKR Flex Web Service v3:

1. `SendRequest` with the encrypted `flex_token` and feed query ID.
2. Waits before polling.
3. `GetStatement` retries until the report is ready or attempts are exhausted.

Fetch errors are reduced to sanitized categories such as `ibkr_auth_failed`, `ibkr_invalid_query`, `ibkr_pacing_limit`, `ibkr_report_not_ready`, or `ibkr_fetch_failed`.

## Common gotchas

- Dry-run still calls IBKR and needs valid credentials.
- Per-feed query ID credentials must be named `feed:{feed_key}:query_id`.
- `validate-assignments` uses `account_list`; ingestion uses `accounts`.
- Stale running jobs older than the integration timeout can be marked failed at the start of a later run.
- Raw XML is not logged or stored unless you use the local debug flag.
