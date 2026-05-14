# Automated Ingestion Infrastructure Design (Manual Trigger First)

## Problem

SuperFolio currently supports manual IBKR Flex XML ingestion from local files. We need infrastructure for automated ingestion that can be manually triggered now, can support scheduling later, and can extend to additional broker APIs without redesigning orchestration.

## Scope

### In Scope

- Build automation infrastructure with GitHub Actions manual trigger.
- Introduce a broker-agnostic Python orchestrator layer.
- Implement an integration registry and adapter boundary with `ibkr_flex_ws` as the first integration key.
- Support `dry-run` and `load` execution modes.
- Default account scope to all active accounts for the selected integration, with optional single-account override.
- Continue processing after per-account failures and report partial failure in final status.
- Read secrets/config in GitHub Actions using the same key names as local `.env`.

### Out of Scope

- Enabling cron schedule in this phase.
- Full low-level IBKR Web Service fetch mechanics (auth/session/token details beyond adapter contract).
- Non-IBKR broker implementations.

## Goals and Constraints

- **Extensibility first:** adding a broker should be mostly a new adapter + config entry.
- **Consistent run policy:** account resolution, mode handling, and failure policy are centralized.
- **No silent behavior:** invalid integration/mode/missing required config fails explicitly.
- **Privacy-safe outputs:** summaries expose counts/statuses, not absolute portfolio values.

## Proposed Architecture

### 1. Trigger Layer (GitHub Actions)

- Add a manual workflow (`workflow_dispatch`) for ingestion test runs.
- Inputs:
  - `integration` (default `ibkr_flex_ws`)
  - `mode` (`dry-run` or `load`)
  - optional `account_external_id`
- Workflow is thin orchestration only: validate input presence, pass execution to Python orchestrator, and publish run summary.

### 2. Orchestrator Layer (Python, broker-agnostic)

- Add an automation package under `portfolio_engine` (for example, `portfolio_engine/automation/`).
- Responsibilities:
  - Parse/validate run parameters.
  - Resolve accounts to process (all active for integration by default; optional override).
  - Resolve adapter via registry.
  - Execute per-account processing loop.
  - Aggregate outcomes and return final run result.
  - Exit non-zero when any account fails (partial failure), while still processing all accounts.

### 3. Broker Adapter Boundary

- Define adapter interface focused on broker-specific concerns only:
  - `preflight_validate_config(run_context)` (optional but recommended)
  - `fetch_payload(account, run_context)` -> normalized broker payload/raw Flex XML content for ingestion handoff
- Adapter does **not** own run policy (mode routing, account iteration, partial-failure strategy).

### 4. Integration Registry

- Add integration mapping (`integration_key -> adapter`) in orchestrator layer.
- Start with:
  - `ibkr_flex_ws` -> `IbkrFlexWebServiceAdapter`
- Future brokers extend by adding adapter module + registry entry, without changing orchestrator control flow.

## Configuration Model

### Versioned Non-Secret Config (Repo)

- Store non-secret defaults and integration metadata in `portfolio_engine/automation/integrations.yaml`.
- Example content:
  - enabled integration keys
  - default account selection strategy
  - mode defaults / validation rules

### Secret and Environment Config (GitHub)

- Use GitHub Actions secrets/variables with the same key names as local `.env`.
- Required keys include `DATABASE_URL` and IBKR-specific credentials needed by the adapter.

## End-to-End Data Flow

1. User manually triggers workflow with integration/mode inputs.
2. Workflow loads required env/secrets and calls orchestrator entrypoint.
3. Orchestrator validates integration/mode/config and resolves target accounts.
4. For each account:
   - Adapter fetches broker payload.
   - Orchestrator invokes existing ingestion path in selected mode (`dry-run`/`load`).
   - Result is recorded as success/failure with privacy-safe counters.
5. Orchestrator emits aggregated summary:
   - total accounts attempted
   - succeeded/failed counts
   - per-account status entries
6. Workflow marks run failed if any account failed.

## Error Handling

- **Fail fast before loop** for:
  - unknown integration key
  - invalid mode
  - missing required config/secrets
- **Continue on per-account errors**:
  - capture account-level failure details
  - proceed with remaining accounts
- **Final status**:
  - success only if all accounts succeed
  - partial failure otherwise (non-zero exit)

## Testing Strategy

- Unit tests for orchestrator:
  - account resolution logic
  - mode validation/routing
  - failure aggregation and final exit status behavior
- Adapter-level tests:
  - mock broker responses/errors
  - config preflight failure behavior
- Wiring smoke path:
  - manual workflow execution path without cron
  - verifies trigger -> orchestrator -> summary flow

## Future-Schedule Readiness

- No schedule is enabled now.
- Architecture remains schedule-ready: later cron support should only add trigger stanza and reuse the same orchestrator path.

## Open Follow-Up Design Item

- Create a dedicated implementation-time design for IBKR Flex Web Service fetch internals:
  - auth/session lifecycle
  - request/response contract specifics
  - retry/backoff and rate-limit handling
  - timeout and idempotency details
