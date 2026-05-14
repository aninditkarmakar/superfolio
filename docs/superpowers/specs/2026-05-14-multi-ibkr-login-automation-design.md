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

Important constraints:

- `UNIQUE (brokerage_id, integration_key, name)`.
- `name` is non-blank and has a conservative maximum length.

Connection names are non-secret labels for humans and future UI surfaces. They
must not contain tokens, account numbers, query ids, or other sensitive values.
The management CLI warns or rejects obvious token/query/account-number patterns,
but operators remain responsible for treating labels as non-secret.

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

Important constraints:

- At most one active credential row may exist for a connection and credential
  name: `UNIQUE (connection_id, credential_name) WHERE is_active = true`.
- `credential_name` is a non-secret key chosen from adapter-defined names such
  as `flex_token` or `feed:<feed_key>:query_id`.
- Credential rotation inserts a new row and atomically marks the old active row
  for the same `(connection_id, credential_name)` as `is_active=false` with
  `rotated_at=now()`. Rotation does not update ciphertext in place.

Master-key rotation is a separate management operation. The CLI decrypts active
credential rows with the old `SUPERFOLIO_CREDENTIAL_MASTER_KEY`, re-encrypts
them with the new master key and key id, verifies they can be read, and only
then may the deployed environment secret be changed.

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

Important constraints:

- `UNIQUE (connection_id, feed_key)`.
- `feed_key` is non-blank, normalized, and must not contain `:` because feed
  query-id credentials use `feed:<feed_key>:query_id` as their credential name.

The first implementation stores a feed's sensitive query id as an encrypted
credential row attached to the same connection, with credential name
`feed:<feed_key>:query_id`. A dedicated feed-secret table is not part of this
design.

Feeds do not declare record categories such as cash flows or NAV snapshots.
Adapters fetch source payloads, and the existing parsing/ingestion layer
discovers supported records. Feed order has no semantic meaning for investment
results. Implementations run enabled feeds in stable `feed_key` order so
inserted-versus-duplicate summaries are reproducible.

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

This table intentionally stores one current assignment row per account and
updates it in place when the account changes connection. Assignment history is
not required for the first implementation; historical automation runs preserve
the connection actually used by snapshotting `connection_id` onto
`automation_job_accounts`.

Assignment validation must reject cross-brokerage mappings: the assigned
account's `brokerage_id` must match the connection's `brokerage_id`. An active
assignment also requires `integration_connections.is_active = true`; inactive
connections are treated as missing automation connectivity.

An account with no active assignment is still a valid registered account, but it
cannot be fetched automatically. During automation, that account becomes a
child-level failure with `error_category="missing_integration_connection"` while
other accounts continue.

### Automation child connection snapshot

`automation_job_accounts` gains a nullable `connection_id` reference to
`integration_connections(id)`. It is populated when the child row is created for
accounts with an active assignment. It remains null for missing-assignment fast
failures. This makes historical jobs stable if account assignments change later.

## Orchestration flow

The manual trigger shape remains portfolio-oriented or account-oriented:

- `target_type=portfolio` resolves all active accounts in the selected portfolio.
- `target_type=accounts` resolves the selected active external account ids.

Resolution then enriches each account with its active integration connection.
The user does not normally select a connection when triggering a run.

The target-resolution database boundary returns account rows plus a nullable
`connection_id`. The implementation replaces the current target-resolution
functions with one connection-aware resolver that handles both portfolio and
accounts targets. The resolver returns target accounts even when the assignment
is missing or inactive so the orchestrator can create child rows and record
explicit child-level failures.

Execution proceeds as follows:

1. Validate the request and create the parent automation job as before.
2. Resolve target accounts.
3. Insert `automation_job_accounts` child rows for all resolved accounts,
   snapshotting nullable `connection_id` on each child row.
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

Dry-run follows the same target resolution, credential decryption, connection
preflight, feed fetch, parse, and per-account filtering path as load. It skips
load-overlap checks, never creates `ingestion_runs`, and never writes normalized
facts. A dry-run child succeeds when all attempted feeds complete without
fetch/parse errors, even if zero supported records match that account.

Fast-fail paths such as missing assignment, missing credential, credential
decryption failure, and connection preflight failure may finalize child rows
directly from `pending` to `failed`; they do not need to mark the child
`running` first.

### Multi-feed child aggregation

A connection may have multiple enabled feeds. The orchestrator collapses those
feed outcomes into one `automation_job_accounts` status per requested account:

- `succeeded`: all attempted feeds completed without fetch/parse errors for
  that account, even if no supported records matched.
- `partially_succeeded`: at least one feed completed successfully for the
  account and at least one feed failed, or ingestion reported skipped/conflict
  conditions after one or more successful feeds.
- `failed`: no feed completed successfully for the account and at least one feed
  failed, or setup/preflight errors prevented all feed attempts for the account.

Record counts are summed across successful parsed feeds. Child summaries include
a non-secret `feed_results` array with feed key/display name, status, error
category when applicable, and per-feed record counts. When multiple feeds fail,
the child-level `error_category` uses the first failing feed in stable `feed_key`
order unless a higher-priority setup category applies.

Parent `error_message` remains null for mixed child-level outcomes. Detailed
connection/feed failures live on child rows and summaries, while the parent
summary aggregates counts and statuses.

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

The adapter protocol uses dataclasses with this shape:

```python
@dataclass(frozen=True)
class SecretValue:
    """Redacted wrapper around decrypted secret material."""
    value: str

    def reveal(self) -> str: ...
    def __repr__(self) -> str: return "<redacted>"
    def __str__(self) -> str: return "<redacted>"


@dataclass(frozen=True)
class IntegrationConnectionContext:
    connection_id: str
    integration_key: str
    brokerage_code: str
    name: str
    credentials: Mapping[str, SecretValue]


@dataclass(frozen=True)
class IntegrationFeedContext:
    feed_id: str
    feed_key: str
    display_name: str | None
    secrets: Mapping[str, SecretValue]


class BrokerAdapter(Protocol):
    def preflight_connection(
        self,
        connection: IntegrationConnectionContext,
        feeds: tuple[IntegrationFeedContext, ...],
    ) -> None: ...

    def fetch_feed_payload(
        self,
        connection: IntegrationConnectionContext,
        feed: IntegrationFeedContext,
        request: AutomationRunRequest,
    ) -> BrokerPayload: ...
```

`preflight_connection` validates decrypted credential presence and shape for one
connection and its enabled feeds. Missing credential rows and decryption failures
are detected before the adapter receives contexts and are mapped to their
specific error categories. Broker-specific preflight errors raised by the adapter
map to `connection_preflight_failed`.

## Load overlap blocking

Overlap protection remains account/date based. A pending or running load blocks
another load only when all of these match:

- same account id;
- intersecting inclusive requested date ranges;
- mode is `load`;
- active parent and child status are `pending` or `running`.

Connection id is intentionally not part of the overlap discriminator. The
normalized data owner is `account_id`; if an account is reassigned while a load
is pending or running, a second overlapping load for the same account/date range
must still be blocked. The current automation job id still must be excluded from
the overlap query because parent and child rows are created before per-account
execution.

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

New management CLIs support:

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

The `ibkr_flex_ws` static integration config no longer lists
`IBKR_FLEX_TOKEN` or `IBKR_FLEX_QUERY_ID` as required environment keys. Static
runtime env validation requires only generic runtime secrets such as
`DATABASE_URL` and `SUPERFOLIO_CREDENTIAL_MASTER_KEY`; broker token/query
validation moves to credential-aware connection/feed preflight.

Management CLIs also include:

- bulk assignment by comma-separated account ids;
- bulk assignment by portfolio when all selected accounts belong to one
  connection;
- assignment validation for a portfolio or account list, reporting accounts with
  no active connection assignment or inactive connections before automation is
  triggered.

## Security and privacy

- Plaintext credentials and query ids must never be stored in PostgreSQL.
- Plaintext credentials and query ids must never be written to logs,
  automation summaries, workflow output, or exception messages.
- Encryption uses Python app-level authenticated encryption with
  `cryptography.fernet.Fernet`.
- `SUPERFOLIO_CREDENTIAL_MASTER_KEY` must be a Fernet-compatible URL-safe
  base64-encoded 32-byte key. The helper validates this at startup and raises a
  sanitized configuration error if the key is missing or malformed.
- Decryption authentication failures are surfaced as sanitized
  `credential_decryption_failed` errors, not broker fetch errors.
- Decryption occurs only inside credential-aware management and automation code
  paths. Decrypted values are wrapped in a `SecretValue` type whose string and
  repr forms are redacted; plaintext is exposed only through an explicit method
  at the adapter boundary.
- The encryption helper supports `encryption_key_id` and `encryption_version` so
  future key rotation can be introduced without rewriting account assignments.
- Connection and feed display names are treated as non-secret but must be
  documented as labels only, not a place to paste account numbers or tokens.
- Automation summaries may include non-secret connection/feed names or ids only
  when useful for diagnosis. They must not include raw XML, tokens, query ids,
  account values, NAV values, cash amounts, or full broker responses.
- The sanitizer must redact values associated with `query_id`, `flex_query_id`,
  `credential`, `ciphertext`, `master_key`, `token`, `password`, `secret`, and
  `api_key` labels before any message is persisted or printed.

## Error handling

New child-level error categories:

- `missing_integration_connection`
- `missing_connection_credential`
- `missing_feed_secret`
- `credential_decryption_failed`
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

The implementation includes focused tests for:

- encrypted credential round trips without plaintext persistence;
- encrypted credential tamper detection;
- missing master key errors;
- malformed master key errors;
- credential redaction in errors/loggable messages;
- creating and rotating credentials;
- master-key rotation workflow;
- multiple feeds under one connection;
- explicit account-to-connection assignment;
- rejecting cross-brokerage account assignments;
- account targets spanning multiple connections;
- portfolio targets spanning multiple connections;
- missing assignment as child failure;
- connection preflight failure isolated to that connection's accounts;
- missing credential/decryption failures isolated to one connection's accounts;
- all enabled feeds run for a connection;
- multi-feed success/failure aggregation;
- load overlap checks are account/date scoped and exclude the current job id;
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
6. Keep overlap detection account/date scoped while snapshotting connection id
   on child rows for audit.
7. Update workflow/docs to require the master encryption key instead of
   per-login IBKR secrets.

Existing accounts will need explicit assignments before automated fetch can run
successfully. That setup is handled by the new management CLI.

Before removing old per-login IBKR secrets or relying on the new workflow path,
run the management CLI assignment validator for each portfolio/account group you
plan to automate. Cutover should proceed only when every expected account has an
active same-brokerage connection assignment, each connection has required active
credentials, and each connection has at least one enabled feed.
