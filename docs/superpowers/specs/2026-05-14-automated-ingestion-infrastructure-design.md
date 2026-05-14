# Automated Ingestion Infrastructure Design

## Problem

SuperFolio currently supports manual IBKR Flex XML ingestion from local files. The next step is ingestion infrastructure that can be manually triggered now, scheduled later, and eventually started from the UI at either portfolio level or account level.

The current database `ingestion_runs` table is intentionally account-scoped. That remains useful for one account ingestion attempt, but it does not represent a user-triggered operation that may expand into multiple accounts. This design adds a parent automation layer above existing ingestion runs.

## Scope

### In scope

- Add infrastructure for manual GitHub Actions ingestion triggers.
- Support two target types per run:
  - portfolio target: ingest all active accounts attached to one portfolio.
  - accounts target: ingest an explicitly selected set of accounts.
- Add database tables to record a parent automation job and its resolved account snapshot.
- Introduce a broker-agnostic Python orchestrator layer.
- Add an integration registry and adapter boundary with `ibkr_flex_ws` as the first integration key.
- Support `dry-run` and `load` execution modes.
- Continue processing remaining accounts after per-account failures.
- Record dry-run jobs and account outcomes without writing normalized cash-flow or NAV facts.
- Read secrets/config in GitHub Actions using the same key names as local `.env`.

### Out of scope

- Enabling a cron schedule in this phase.
- Building the UI trigger surfaces.
- Full low-level IBKR Flex Web Service fetch mechanics beyond the adapter contract.
- Non-IBKR broker implementations.

## Goals and constraints

- **UI-aligned audit trail:** the database records the user-triggered operation, not only each account-level ingestion attempt.
- **Historical stability:** portfolio/account selections are resolved and snapshotted at trigger time; later portfolio membership changes do not rewrite old jobs.
- **Extensibility first:** adding a broker should be mostly a new adapter plus registry/config entry.
- **Consistent run policy:** target resolution, mode handling, account iteration, and failure aggregation are centralized in the orchestrator.
- **No silent behavior:** invalid target type, unknown integration, invalid mode, missing config, or empty resolved account set fails explicitly.
- **Privacy-safe outputs:** summaries expose statuses and counts, not portfolio/account values.

## Database model

### `automation_jobs`

Parent record for one user-triggered ingestion operation.

Key fields:

- `id uuid primary key`
- `trigger_type text not null`
  - initially `manual`
  - future-ready for `scheduled`
- `target_type text not null`
  - `portfolio`
  - `accounts`
- `portfolio_id uuid null references portfolios(id)`
  - required when `target_type = 'portfolio'`
  - null when `target_type = 'accounts'`
- `integration_key text not null`
  - initially `ibkr_flex_ws`
- `mode text not null`
  - `dry-run`
  - `load`
- `status text not null`
  - reuse lifecycle vocabulary: `pending`, `running`, `succeeded`, `partially_succeeded`, `failed`
- `requested_start_date date null`
- `requested_end_date date null`
- `error_message text null`
- `started_at timestamptz not null default now()`
- `completed_at timestamptz null`
- `created_at timestamptz not null default now()`

Important constraints:

- `target_type` must be `portfolio` or `accounts`.
- `portfolio_id` must be present only for portfolio jobs.
- `mode` must be `dry-run` or `load`.
- requested date range must be ordered when both dates are present.
- completed jobs must have `completed_at >= started_at`.

### `automation_job_accounts`

Resolved account snapshot for one automation job. This table preserves which accounts were selected or resolved at trigger time.

Key fields:

- `id uuid primary key`
- `automation_job_id uuid not null references automation_jobs(id)`
- `account_id uuid not null references accounts(id)`
- `status text not null`
  - reuse lifecycle vocabulary: `pending`, `running`, `succeeded`, `partially_succeeded`, `failed`
- `ingestion_run_id uuid null references ingestion_runs(id)`
  - set when the orchestrator starts the existing per-account ingestion path.
- `summary jsonb null`
  - privacy-safe counts and diagnostics for this account.
- `error_message text null`
- `started_at timestamptz null`
- `completed_at timestamptz null`
- `created_at timestamptz not null default now()`

Important constraints:

- unique `(automation_job_id, account_id)`.
- account-level status uses the same lifecycle vocabulary as `automation_jobs`.
- completed account rows must have `completed_at >= started_at` when both are present.

### Relationship to existing `ingestion_runs`

Existing `ingestion_runs` remains account-scoped and continues to back normalized ingestion. Each `automation_job_accounts` row may link to one `ingestion_runs` row when actual account ingestion is attempted.

This gives two layers:

- `automation_jobs`: "What did the user/workflow ask to run?"
- `ingestion_runs`: "What happened while ingesting this one account?"

## Trigger semantics

Manual trigger supports exactly one target type per run.

### Portfolio target

The trigger identifies one portfolio. The orchestrator resolves all active accounts attached to that portfolio at trigger time and inserts those accounts into `automation_job_accounts`.

Historical jobs do not change if the portfolio membership changes later.

### Accounts target

The initial GitHub Actions trigger accepts a comma-separated `account_external_ids` input scoped to the selected integration. The orchestrator resolves those external ids into registered internal account rows before job execution. The database stores resolved `account_id` child rows, not the raw user input text.

### Dry-run and load

Both modes create `automation_jobs` and `automation_job_accounts` rows.

- `dry-run`: fetches and parses broker payloads, records account summaries/errors, and does not write normalized facts.
- `load`: fetches, parses, and writes supported normalized records through existing ingestion boundaries.

## Orchestrator architecture

Add a broker-agnostic Python automation package under `portfolio_engine`, for example `portfolio_engine/automation/`.

Responsibilities:

- validate run parameters.
- create the parent `automation_jobs` row.
- resolve target accounts and insert `automation_job_accounts` snapshot rows.
- resolve adapter by `integration_key`.
- preflight adapter configuration.
- execute account processing loop.
- call existing ingestion path for each account in the selected mode.
- update child and parent statuses.
- emit a privacy-safe summary and process exit code.

Parent final status:

- `succeeded`: all account rows succeeded.
- `partially_succeeded`: at least one account succeeded and at least one account failed or partially succeeded.
- `failed`: no account succeeded.

## Broker adapter boundary

Adapters are narrow and broker-specific. They do not decide target resolution, mode behavior, or failure aggregation.

Initial adapter:

- `ibkr_flex_ws` -> `IbkrFlexWebServiceAdapter`

Adapter responsibilities:

- validate required broker-specific config and credentials.
- fetch source payload for one resolved account.
- return raw or normalized payload suitable for the existing ingestion handoff.
- surface broker-specific fetch/config errors clearly.

Future broker integrations should add a new adapter and registry/config entry without rewriting orchestrator control flow.

## GitHub Actions workflow

Add a manual `workflow_dispatch` workflow only. No schedule is enabled in this phase.

Workflow responsibilities:

- accept trigger inputs for target type, integration, mode, date range, `portfolio_name` for portfolio targets, and comma-separated `account_external_ids` for accounts targets.
- expose required secrets/variables using the same key names as local `.env`.
- call the Python orchestrator entrypoint.
- publish the orchestrator's privacy-safe summary.
- fail the workflow when the parent job final status is `failed` or `partially_succeeded`.

The workflow remains schedule-ready: a future cron trigger should call the same orchestrator path and produce the same database records.

## Configuration model

### Versioned non-secret config

Store non-secret integration defaults in `portfolio_engine/automation/integrations.yaml`.

Example content:

- enabled integration keys.
- adapter import path or registry key.
- supported modes.
- source type mapping such as `ibkr_flex_ws -> FLEX_WEB_SERVICE`.

### Secret and environment config

Use GitHub Actions secrets/variables with the same key names as local `.env`.

Required keys include:

- `DATABASE_URL`
- IBKR-specific Flex Web Service credentials required by the adapter.

## Error handling

Fail before account processing for:

- invalid target type.
- invalid target identifier.
- empty resolved account set.
- unknown integration key.
- invalid mode.
- missing required config or secrets.
- invalid date range.

Continue account processing for per-account errors:

- fetch failure.
- parse failure.
- account-specific ingestion failure.

The orchestrator records the account failure, continues remaining accounts, and then derives the parent final status from child outcomes.

## Testing strategy

### Database migration tests / verification

- verify `automation_jobs` and `automation_job_accounts` constraints.
- verify portfolio target requires `portfolio_id`.
- verify account target rejects `portfolio_id`.
- verify duplicate account child rows are rejected.

### Orchestrator unit tests

- target resolution for portfolio and account targets.
- snapshot behavior for resolved accounts.
- dry-run versus load routing.
- child status aggregation into parent status.
- continue-on-error account loop.

### Adapter tests

- mock successful IBKR payload fetch.
- mock missing config.
- mock broker fetch failure.

### Workflow wiring

- manual trigger invokes the orchestrator with representative inputs.
- no cron trigger is enabled.

## Future IBKR fetch-internals design

This spec intentionally defines the adapter contract but not every low-level IBKR Web Service detail.

A follow-up design should cover:

- auth/session lifecycle.
- request and response contract specifics.
- retry/backoff and rate-limit handling.
- timeout behavior.
- idempotency and duplicate response handling.
