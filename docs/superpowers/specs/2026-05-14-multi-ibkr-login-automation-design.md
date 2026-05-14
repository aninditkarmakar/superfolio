# Multi-Login Automation Design

## Problem

The first automated ingestion infrastructure assumes one global credential set for
`ibkr_flex_ws`: `IBKR_FLEX_TOKEN` and `IBKR_FLEX_QUERY_ID`. That is not enough for
portfolios containing IBKR accounts under different IBKR logins. It also mixes two
separate concepts: the authentication context for a brokerage login and the data
request used to fetch a report.

This follow-up refactors automation around broker-agnostic integration
connections, feeds, and explicit account assignments. The goal is to support
multiple IBKR logins now while preserving a model that can work for future
brokerage APIs.

## Scope

### In scope

- Add persistent integration connection metadata.
- Store encrypted broker credential values in PostgreSQL, with encryption and
  decryption performed by Python using a master key from the environment or
  GitHub Secrets.
- Add integration feeds under a connection. For IBKR Flex Web Service, a feed is
  a Flex query definition.
- Explicitly assign brokerage accounts to an active integration connection.
- Refactor target resolution and orchestration so portfolio and multi-account
  runs automatically use each account's assigned connection.
- Group automation work by connection, preflight each connection independently,
  and isolate failures to accounts assigned to that connection.
- Update adapter interfaces so broker adapters receive connection and feed
  context rather than reading a single global token/query pair.
- Add Python CLI/database commands for connection, feed, credential, and account
  assignment management.
- Update workflow and documentation to require only the master encryption key
  secret for stored broker credentials.

### Out of scope

- Building UI management surfaces.
- Enabling a cron schedule.
- Implementing the full IBKR Flex Web Service HTTP fetch flow. The adapter
  remains allowed to raise `NotImplementedError` until the fetch design is
  implemented.
- Supporting credential discovery by trying every connection/feed for an account.
- Declaring feed record categories up front. Feeds are generic source requests;
  parsing discovers supported record types.

## Core model

### Integration connection

An integration connection represents one brokerage authentication context. For
IBKR, this corresponds to one IBKR login/Flex token. For a future OAuth broker,
it may correspond to one OAuth account or one API application authorization.

Key fields:

- `id uuid primary key`
- `integration_key text not null`
- `brokerage_id uuid not null references brokerages(id)`
- `name text not null`
- `is_active boolean not null default true`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Connection names are non-secret labels for humans and future UI surfaces. They
must not contain tokens, account numbers, query ids, or other sensitive values.

### Integration connection credentials

Credentials are stored separately from connection metadata. This keeps account
assignments and feed definitions stable across credential rotation, supports
multiple credential values per connection, and gives a clean place for encryption
metadata.

Key fields:

- `id uuid primary key`
- `connection_id uuid not null references integration_connections(id)`
- `credential_name text not null`
- `ciphertext bytea not null`
- `encryption_key_id text not null`
- `encryption_version integer not null`
- `is_active boolean not null default true`
- `created_at timestamptz not null default now()`
- `rotated_at timestamptz null`

Python encrypts plaintext before persistence and decrypts only inside the
automation or management code path that needs it. PostgreSQL stores ciphertext
and metadata only. Query ids are treated as sensitive because they can function
as broker data-access handles.

### Integration feeds

An integration feed represents a data request under a connection. For IBKR Flex
Web Service, an enabled feed contains an encrypted Flex query id and optional
non-secret labels. A single connection may have multiple enabled feeds served by
one token.

Key fields:

- `id uuid primary key`
- `connection_id uuid not null references integration_connections(id)`
- `feed_key text not null`
- `display_name text null`
- `is_active boolean not null default true`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

The first implementation may store a feed's sensitive query id as a credential
row with a name such as `feed:<feed_key>:query_id`, or use a dedicated encrypted
feed-secret table if that proves clearer during planning. The important design
boundary is that query ids are not stored in plaintext and feed rows remain safe
to display.

Feeds do not declare record categories such as cash flows or NAV snapshots.
Adapters fetch source payloads, and the existing parsing/ingestion layer
discovers supported records.

### Account assignment

Each brokerage account may be assigned to one active integration connection for
automation. The assignment is explicit; automation does not discover ownership by
trying every connection.

Key fields:

- `account_id uuid primary key references accounts(id)`
- `connection_id uuid not null references integration_connections(id)`
- `is_active boolean not null default true`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

An account with no active assignment is still a valid registered account, but it
cannot be fetched automatically. During automation, that account becomes a
child-level failure with `error_category="missing_integration_connection"` while
other accounts continue.

## Orchestration flow

The manual trigger shape remains portfolio-oriented or account-oriented:

- `target_type=portfolio` resolves all active accounts in the selected portfolio.
- `target_type=accounts` resolves the selected active external account ids.

Resolution then enriches each account with its active integration connection.
The user does not normally select a connection when triggering a run.

Execution proceeds as follows:

1. Validate the request and create the parent automation job as before.
2. Resolve target accounts.
3. Insert `automation_job_accounts` child rows for all resolved accounts.
4. Mark accounts with no active connection assignment as failed with
   `missing_integration_connection`.
5. Group remaining accounts by integration connection.
6. For each connection:
   - decrypt required credentials;
   - load enabled feeds;
   - preflight that connection once;
   - fail only that connection's accounts if preflight fails;
   - run all enabled feeds for the connection;
   - parse fetched payloads and filter records per requested account.
7. Finalize each child row and derive the parent status from all child outcomes.

Connection-level failures must not stop other connections in the same job. For
example, if a portfolio includes accounts under two IBKR logins and one token is
invalid, accounts assigned to the other login should still run.

## Adapter boundary

The current adapter receives only account, request, and static integration
config. The refactor introduces runtime connection and feed context:

- connection metadata;
- decrypted connection credentials;
- feed metadata;
- decrypted feed secrets when needed.

Adapters remain broker-specific and narrow. They validate connection/feed
configuration and fetch payloads. They do not decide target resolution, account
grouping, mode behavior, parent aggregation, or privacy policy.

For IBKR Flex Web Service:

- the connection credential includes the Flex token;
- each enabled feed supplies a Flex query id;
- the adapter fetches one payload per feed when fetch internals are implemented;
- the orchestrator/ingestion path filters parsed records to each requested
  account.

Until the IBKR fetch follow-up is implemented, the adapter may continue raising
`NotImplementedError` after validating connection/feed shape.

## Load overlap blocking

Overlap protection remains account/date based but must include connection
context. A pending or running load blocks another load only when all of these
match:

- same integration key;
- same connection id;
- same account id;
- intersecting inclusive requested date ranges;
- active parent and child status are `pending` or `running`.

Including connection id prevents different IBKR logins from blocking each other
for unrelated account assignments. The current automation job id still must be
excluded from the overlap query because parent and child rows are created before
per-account execution.

## CLI and workflow

The manual automation CLI and GitHub Actions workflow keep the same normal
trigger inputs:

- `target_type`
- `integration`
- `mode`
- `start_date`
- `end_date`
- `portfolio_name`
- `account_external_ids`

They do not require an IBKR login/connection selector for normal use. Connection
choice comes from account assignments.

New management CLIs should support:

- creating/listing/disabling integration connections;
- setting or rotating connection credentials;
- adding/listing/disabling feeds;
- assigning accounts to connections;
- listing account assignments.

GitHub Actions no longer needs per-login IBKR token/query secrets for normal
operation. It needs:

- `DATABASE_URL`
- `SUPERFOLIO_CREDENTIAL_MASTER_KEY`

`SUPERFOLIO_CREDENTIAL_MASTER_KEY` is the canonical local `.env` and GitHub
Actions secret name for the credential encryption master key.

## Security and privacy

- Plaintext credentials and query ids must never be stored in PostgreSQL.
- Plaintext credentials and query ids must never be written to logs,
  automation summaries, workflow output, or exception messages.
- Encryption is performed in Python before persistence. Decryption occurs only
  inside credential-aware management and automation code paths.
- The encryption helper must support key identifiers or versions so future key
  rotation can be introduced without rewriting account assignments.
- Connection and feed display names are treated as non-secret but should be
  documented as labels only, not a place to paste account numbers or tokens.
- Automation summaries may include non-secret connection/feed names or ids only
  when useful for diagnosis. They must not include raw XML, tokens, query ids,
  account values, NAV values, cash amounts, or full broker responses.

## Error handling

New child-level error categories:

- `missing_integration_connection`
- `connection_preflight_failed`
- `feed_fetch_failed`
- `feed_parse_failed`

Existing categories such as `fetch_or_parse_error`, `overlapping_load_job`, and
ingestion conflict/skipped counts remain valid where they apply.

Parent status rules remain unchanged:

- `succeeded`: all child rows succeeded.
- `partially_succeeded`: mixed child outcomes or any child partial success.
- `failed`: all child rows failed or no child rows were created.

## Testing expectations

The implementation should include focused tests for:

- encrypted credential round trips without plaintext persistence;
- missing master key errors;
- credential redaction in errors/loggable messages;
- creating and rotating credentials;
- multiple feeds under one connection;
- explicit account-to-connection assignment;
- account targets spanning multiple connections;
- portfolio targets spanning multiple connections;
- missing assignment as child failure;
- connection preflight failure isolated to that connection's accounts;
- all enabled feeds run for a connection;
- load overlap checks include connection id and exclude the current job id;
- manual workflow no longer requiring per-login IBKR token/query secrets.

## Migration from current automation infrastructure

The current automation branch can be migrated without changing existing
portfolio/account target semantics:

1. Add the connection/feed/assignment tables and database functions.
2. Add encrypted credential helpers and management CLI support.
3. Replace global `IBKR_FLEX_TOKEN` and `IBKR_FLEX_QUERY_ID` assumptions in the
   automation config and adapter boundary.
4. Update target resolution to attach connection context or fail missing
   assignments at child level.
5. Refactor orchestration to group by connection and run feeds.
6. Update overlap detection to include connection id.
7. Update workflow/docs to require the master encryption key instead of
   per-login IBKR secrets.

Existing accounts will need explicit assignments before automated fetch can run
successfully. That setup should be handled by the new management CLI.
