# Automated Ingestion

Automated ingestion runs through the manual GitHub Actions workflow `.github/workflows/manual-ingestion.yml`. No cron schedule is enabled yet; all runs are triggered manually via the GitHub Actions `workflow_dispatch` event.

## Required secrets

| Secret | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection string for automation job tracking and ingestion writes. |
| `IBKR_FLEX_TOKEN` | IBKR Flex Web Service authentication token. |
| `IBKR_FLEX_QUERY_ID` | IBKR Flex query id used to request the Flex report. |

These must be configured as repository secrets before triggering the workflow.

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

> **⚠️ Adapter fetch not yet implemented.** `IbkrFlexWebServiceAdapter.fetch_payload()` currently raises `NotImplementedError`. The full IBKR Flex Web Service HTTP fetch (token exchange, polling, XML retrieval) is out of scope for the current infrastructure release. Target resolution, overlap detection, lifecycle tracking, per-account summaries, and workflow/CLI infrastructure are all functional, but no broker payloads are fetched or written by the `ibkr_flex_ws` adapter yet. The dry-run and load semantics below describe intended behavior once adapter fetch is implemented.

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

## Known limitations

- **No schedule:** The workflow is `workflow_dispatch` only. Scheduled daily automation is planned but not yet enabled.
- **Flex Web Service fetch internals:** The `ibkr_flex_ws` integration boundary is defined in `portfolio_engine/automation/adapters.py`. The full IBKR Flex Web Service HTTP fetch implementation (token exchange, polling, XML retrieval) is out of scope for the current infrastructure release and remains a future task.
- **Supported record types:** Only `Deposits/Withdrawals` cash transactions and `EquitySummaryByReportDateInBase` daily NAV records are supported by the ingestion functions. Other `CashTransaction` types are counted as unsupported and skipped.
