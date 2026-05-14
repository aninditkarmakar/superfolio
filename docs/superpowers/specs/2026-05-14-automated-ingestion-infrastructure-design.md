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
- **Safe manual fetches:** manual automated runs require an explicit requested start and end date to avoid accidental unbounded broker pulls.

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
- `requested_start_date` and `requested_end_date` are required for manual automated ingestion.
- requested date range must be ordered.
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
  - privacy-safe counts, status labels, and sanitized diagnostics for this account.
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

Dry-run jobs do not create account-scoped `ingestion_runs`; their child `ingestion_run_id` values remain null. Load jobs set `ingestion_run_id` when the orchestrator starts the existing per-account ingestion path.

This gives two layers:

- `automation_jobs`: "What did the user/workflow ask to run?"
- `ingestion_runs`: "What happened while ingesting this one account?"

## Trigger semantics

Manual trigger supports exactly one target type per run.

### Portfolio target

The trigger identifies one active portfolio. Inactive portfolios are rejected as invalid automation targets.

The orchestrator resolves all active accounts attached to that portfolio on active brokerages/integrations at trigger time and inserts those accounts into `automation_job_accounts`. This active-only rule is specific to ingestion. Portfolio reporting and historical TWR calculations may still include inactive accounts that remain portfolio members.

Historical jobs do not change if the portfolio membership changes later.

### Accounts target

The initial GitHub Actions trigger accepts a comma-separated `account_external_ids` input scoped to the selected integration. The orchestrator trims whitespace, rejects empty tokens, deduplicates repeated ids, and resolves those external ids into active registered account rows for the integration's brokerage before job execution.

Unknown, inactive, or wrong-brokerage accounts fail preflight before account processing starts. The database stores resolved `account_id` child rows, not the raw user input text.

### Dry-run and load

Both modes create `automation_jobs` and `automation_job_accounts` rows.

- `dry-run`: fetches and parses broker payloads, records account summaries/errors, and does not write normalized facts or account-scoped `ingestion_runs`.
- `load`: fetches, parses, and writes supported normalized records through existing ingestion boundaries.

If fetch and parse complete successfully but no supported records are found for an account in the requested date range, that child account row is `succeeded` with zero counts.

### Preflight audit behavior

Valid-looking manual trigger attempts should create an `automation_jobs` row when the database is reachable, even if later preflight validation fails before account processing. Examples include unknown portfolio, inactive portfolio, invalid account ids, empty resolved account set, missing integration config, or missing required broker credentials.

Those jobs are finalized as `failed` with a sanitized error category/message. If the database is unavailable before a parent job can be created, the workflow fails without a persisted job.

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
- `partially_succeeded`: at least one account row partially succeeded, or at least one account row succeeded while another failed.
- `failed`: all account rows failed, or no account rows were created because preflight failed before target resolution completed.

Child account status semantics:

- `succeeded`: fetch/parse completed and, for load mode, ingestion completed without skipped-account or conflict conditions. Zero supported records is still success when fetch/parse completed cleanly.
- `partially_succeeded`: fetch/parse/load completed, but ingestion reported skipped records, inactive/unknown source records, or canonical-data conflicts that require review.
- `failed`: fetch, parse, or account-level ingestion failed.

Zero resolved child accounts is a preflight failure, not a successful empty job.

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

Broker payloads may contain records for accounts other than the requested account. The orchestrator and ingestion handoff remain account-scoped: records for other accounts must be ignored/skipped with sanitized counts, not written under the requested account.

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

Required content for each integration:

- `integration_key`
- `brokerage_code`
- `source_type`
- `adapter_path` or registry key
- `supported_modes`
- `required_env_keys`

Initial mapping:

- `integration_key`: `ibkr_flex_ws`
- `brokerage_code`: `IBKR`
- `source_type`: `FLEX_WEB_SERVICE`
- `supported_modes`: `dry-run`, `load`

### Secret and environment config

Use GitHub Actions secrets/variables with the same key names as local `.env`.

Required keys include:

- `DATABASE_URL`
- IBKR-specific Flex Web Service credentials required by the adapter.

## Database mutation boundary

Automation lifecycle writes follow the existing database boundary pattern: Python code calls `SuperFolioDatabase` methods, which call PostgreSQL functions. The orchestrator should not write directly to automation tables.

Required function/adapter responsibilities:

- create an automation job.
- finalize an automation job.
- insert resolved automation job account rows.
- mark an automation job account running.
- finalize an automation job account with status, optional linked `ingestion_run_id`, sanitized summary, and sanitized error message.
- resolve active portfolio target accounts for ingestion.
- resolve active account target selections for an integration.

## Error handling

Fail before account processing for:

- invalid target type.
- invalid target identifier.
- empty resolved account set.
- unknown integration key.
- invalid mode.
- missing required config or secrets.
- invalid date range.

When the database is reachable and a valid-looking manual trigger has already created an `automation_jobs` row, preflight failures finalize that parent row as `failed`.

Continue account processing for per-account errors:

- fetch failure.
- parse failure.
- account-specific ingestion failure.

The orchestrator records the account failure, continues remaining accounts, and then derives the parent final status from child outcomes.

## Privacy and diagnostics

Database `summary` and `error_message` fields must contain sanitized metadata only:

- counts.
- status labels.
- error categories.
- short sanitized messages.

They must not contain:

- raw Flex XML or raw broker payloads.
- credentials, tokens, query ids that function as secrets, or database URLs.
- account values, NAV values, cash amounts, or other absolute financial values.
- full broker response bodies.

During manual testing, detailed diagnostics may be kept outside the database in local logs or workflow artifacts when needed, but those artifacts must still avoid credentials and connection strings.

## Concurrency and recovery

Overlapping concurrent `load` jobs for the same integration, account, and requested date range should be blocked. Dry-run jobs may overlap with other dry-runs or load jobs because they do not write normalized facts or account-scoped `ingestion_runs`.

The implementation should use a database-backed locking strategy, such as PostgreSQL advisory locks, so concurrent workflow runs cannot both load the same account/date window. Locking failures should mark the affected child account row as `failed` or fail preflight when no account processing has started.

If the orchestrator crashes or the workflow is cancelled after marking a parent or child row `running`, a later run or maintenance routine must be able to mark stale `running` rows as `failed` with a sanitized timeout/cancellation reason.

## Testing strategy

### Database migration tests / verification

- verify `automation_jobs` and `automation_job_accounts` constraints.
- verify portfolio target requires `portfolio_id`.
- verify account target rejects `portfolio_id`.
- verify duplicate account child rows are rejected.
- verify manual jobs require both requested start and end dates.
- verify dry-run child rows do not link to `ingestion_runs`.
- verify automation lifecycle writes are available through PostgreSQL functions.

### Orchestrator unit tests

- target resolution for portfolio and account targets.
- inactive portfolio rejection.
- active-only ingestion resolution for portfolio targets.
- account target trimming, deduplication, and unknown/inactive account rejection.
- snapshot behavior for resolved accounts.
- dry-run versus load routing.
- child status aggregation into parent status.
- continue-on-error account loop.
- preflight failure persistence as failed parent job when DB is reachable.
- empty supported-record result as success with zero counts.
- sanitized summary/error storage.
- overlapping load job blocking.
- stale-running cleanup/finalization behavior.

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
