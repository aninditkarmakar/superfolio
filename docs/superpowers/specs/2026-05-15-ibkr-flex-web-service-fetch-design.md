# IBKR Flex Web Service Fetch Design

## Problem

SuperFolio has automation infrastructure for manually triggered portfolio and
account ingestion, including connection assignment, encrypted credentials, feeds,
job tracking, dry-run/load behavior, and privacy-safe summaries. The remaining
gap is the low-level IBKR Flex Web Service HTTP fetch: the IBKR adapter can
preflight credentials, but `fetch_feed_payload()` still raises
`NotImplementedError`.

This design adds a focused IBKR fetch implementation that retrieves configured
Flex Query XML reliably enough for manual testing and later scheduled use,
without expanding into a full scheduling or observability system.

## Scope

### In scope

- Implement IBKR Flex Web Service report retrieval for configured connection
  feeds.
- Use the public IBKR Flex Web Service Version 3 protocol:
  `SendRequest` followed by `GetStatement`.
- Validate request and response shapes against current public IBKR
  documentation before implementation.
- Fetch once per connection/feed/automation run and reuse the returned XML for
  all eligible accounts assigned to that connection.
- Use bounded polling for documented temporary report-generation states.
- Map IBKR failures to a small set of sanitized categories.
- Keep raw XML in memory by default.
- Add local CLI-only, explicit opt-in raw XML debug saves for manual testing.
- Test through an injected fake HTTP transport with synthetic XML fixtures.

### Out of scope

- Enabling cron scheduling.
- Persisting raw payloads in PostgreSQL or object storage.
- User-configurable retry policies.
- Per-feed endpoint/base-URL configuration.
- GitHub Actions support for raw XML debug saves.
- Client Portal Gateway, OAuth, or trading Client Portal API support.
- Passing automation `start_date`/`end_date` dynamically to IBKR.
- Supporting non-IBKR brokers.

## Public protocol assumptions to verify

Implementation must verify these assumptions against the latest public IBKR Flex
Web Service documentation before coding and encode them in request-shape and
response-shape tests.

Sources used for this design:

- IBKR Campus, "Flex Web Service":
  `https://www.interactivebrokers.com/campus/ibkr-api-page/flex-web-service/`
- IBKR Guides, "Flex Web Service Version 2":
  `https://www.ibkrguides.com/complianceportal/complianceportal/flexwebserviceversion2.htm`
- IBKR Guides, Client Portal "Flex Web Service":
  `https://www.ibkrguides.com/clientportal/performanceandstatements/flex-web-service.htm`

Assumptions from those docs:

- Flex Web Service retrieves pre-configured Flex Queries over HTTPS without
  logging into Client Portal at fetch time.
- The request is driven by a token and query id; it does not accept a runtime
  list of accounts. Account inclusion is defined by the Flex Query template in
  Client Portal.
- Version 3 should be used for new requests.
- The Version 3 base URL is
  `https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService`.
- `SendRequest` is called with query params `t=<token>`, `q=<query_id>`, and
  `v=3`.
- `GetStatement` is called with query params `t=<token>`,
  `q=<reference_code>`, and `v=3`.
- All requests must include a `User-Agent` header.
- Successful `SendRequest` responses are XML with `Status=Success` and a
  `ReferenceCode`.
- Failed service responses are XML with `Status=Fail`, `ErrorCode`, and
  `ErrorMessage`.
- IBKR documents a `SendRequest` pacing limit of one request per second and ten
  requests per minute per token.
- Report retrieval can require a delay or repeated attempts after
  `SendRequest`; temporary states include statement unavailable, incomplete, in
  progress, or server-load responses.

## Architecture boundary

The existing orchestration boundary stays intact:

1. User triggers automation by portfolio or account list.
2. The orchestrator resolves target accounts and connection assignments.
3. The orchestrator decrypts connection/feed credentials.
4. The orchestrator calls the IBKR adapter with
   `IntegrationConnectionContext`, `IntegrationFeedContext`, and
   `AutomationRunRequest`.
5. The adapter returns `BrokerPayload(xml_text, source_name)`.
6. Existing dry-run/load parsing filters the report per account and date range.

The new code should sit behind the adapter boundary as a small IBKR Flex Web
Service client plus adapter glue. The client knows only how to turn
`flex_token + query_id` into raw XML. It does not know about portfolios,
account assignments, database writes, ingestion modes, or parser behavior.

## Fetch flow

For each connection/feed in one automation run:

1. Read `flex_token` from the connection credentials and `query_id` from the
   feed secrets.
2. Call `SendRequest` with token, query id, version `3`, and required
   `User-Agent`.
3. Parse the `SendRequest` XML response.
4. If `Status=Success`, extract `ReferenceCode`.
5. If `Status=Fail`, map `ErrorCode` to a sanitized fetch category and raise an
   adapter-level fetch error.
6. Call `GetStatement` with token, reference code, version `3`, and required
   `User-Agent`.
7. If `GetStatement` returns a complete Flex report, return it as
   `BrokerPayload`.
8. If `GetStatement` returns a documented temporary state, wait and retry until
   the bounded polling limit is reached.
9. If polling exhausts, raise a sanitized `ibkr_report_not_ready` fetch error.

Automation `requested_start_date` and `requested_end_date` are not sent to IBKR.
They continue to filter records locally after the configured Flex Query report is
retrieved.

## Fetch-once reuse

The fetcher must request each connection/feed report once per automation run and
reuse the resulting XML for every eligible account assigned to that connection.

This is necessary because IBKR receives only token, query id, and version. If a
Flex Query template includes three accounts, one fetch returns one XML report
containing records for those accounts. Fetching separately for each account would
usually regenerate the same report multiple times, waste IBKR capacity, and risk
violating documented pacing limits.

The orchestrator already groups accounts by connection and iterates feeds. The
implementation should adjust the multi-feed execution path so payload retrieval
is per connection/feed/run, while parsing and loading remain per account.

## Polling and pacing

The first implementation uses conservative fixed defaults. Retry knobs are not
user-configurable.

Policy:

- `SendRequest` is called once per connection/feed/run.
- `GetStatement` may be retried only for documented temporary states.
- Polling uses a bounded attempt count and fixed or simple backoff delay.
- Polling delays should be conservative enough to avoid active polling against
  IBKR.
- Non-temporary service errors fail immediately.
- Network errors may be retried only if doing so cannot create additional
  `SendRequest` report-generation requests. In practice, retrying
  `GetStatement` after a reference code is safer than blindly retrying
  `SendRequest`.

The exact default attempt count and delay belong in the implementation plan, but
they must be small and suitable for manual test runs.

## Error categories

The adapter should raise typed or structured IBKR fetch errors internally, then
surface only sanitized messages through existing automation error handling.

Initial categories:

- `ibkr_auth_failed`: invalid token, expired token, inactive service account, or
  IP restriction.
- `ibkr_invalid_query`: invalid query id, invalid reference code, invalid
  account, legacy query, or invalid request.
- `ibkr_pacing_limit`: too many requests from the token.
- `ibkr_report_not_ready`: documented temporary report-generation state remained
  unresolved after polling.
- `ibkr_fetch_failed`: network failure, malformed response, missing required XML
  fields, unexpected status, or unclassified IBKR error.

Secrets, query ids, tokens, raw XML, financial amounts, and account values must
not appear in exceptions, job summaries, workflow output, or logs.

## Raw XML debug saves

Default behavior keeps fetched XML in memory only.

For manual local testing, the CLI will accept an explicit debug output directory.
When provided, the fetch layer writes retrieved XML under that directory using
non-secret filenames. Filenames may include non-sensitive context such as
connection id, feed key, automation job id when available, and a timestamp-like
or collision-resistant suffix. Filenames must not include tokens, query ids, raw
account numbers, or report contents.

This option is local CLI-only:

- GitHub Actions workflow inputs must not expose raw XML debug saving.
- Debug XML must not be uploaded as artifacts.
- XML contents must not be printed.
- Documentation must treat the output directory as private local data, similar
  to `scratch/`.

## Configuration

Production endpoint configuration should remain code-owned for this first
version:

- Default base URL:
  `https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService`
- Flex Web Service version: `3`
- Required header: `User-Agent`

Unit tests should inject an HTTP transport into the client rather than override
the production base URL through environment variables. This keeps runtime
configuration small and avoids accidentally pointing real automation at
untrusted endpoints.

## Testing strategy

Tests must use synthetic XML and fake HTTP transports. They must never call IBKR
or require real credentials.

Required coverage:

- `SendRequest` request shape: method, URL, query params, version, and
  `User-Agent`.
- `GetStatement` request shape: method, URL, query params, version, and
  `User-Agent`.
- Successful `SendRequest` followed by successful `GetStatement`.
- `GetStatement` temporary failure followed by success.
- Polling exhaustion returns `ibkr_report_not_ready`.
- Known IBKR error-code mappings for auth, invalid query, pacing, and temporary
  states.
- Malformed XML and missing required fields return `ibkr_fetch_failed`.
- Network failures return sanitized `ibkr_fetch_failed`.
- Tokens and query ids do not appear in exceptions or summaries.
- Multi-account connection/feed execution fetches once and reuses XML per
  account.
- Local debug XML save writes synthetic XML only when explicitly enabled.
- GitHub Actions/manual workflow does not expose raw XML debug-save inputs.

## Documentation updates

Update `docs/workflows/automated-ingestion.md` and `README.md` after
implementation to remove or narrow the "fetch not implemented" limitation.

Documentation should explain:

- IBKR Flex Web Service must be enabled in Client Portal.
- A Flex Web Service token and feed query id must be stored as encrypted
  credentials.
- The query template controls which accounts and sections IBKR returns.
- Automation date inputs filter locally; they do not reconfigure the IBKR query.
- Raw XML debug saving is local-only, opt-in, private, and disabled by default.

## Implementation notes

- Preserve the existing `BrokerPayload` contract.
- Prefer a small dedicated client module over placing HTTP and XML parsing logic
  directly in `adapters.py`.
- Use a structured XML parser for IBKR service responses and Flex payloads.
- Keep the adapter free of database access.
- Keep future broker extensibility by avoiding IBKR-specific behavior in generic
  orchestration code except where fetch-once reuse is necessary for feed payload
  execution.
- Do not merge any branch back anywhere without explicit repository-owner
  approval.
