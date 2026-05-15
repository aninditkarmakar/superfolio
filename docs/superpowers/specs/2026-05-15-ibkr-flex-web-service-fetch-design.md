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
- Add `httpx` as the HTTP client dependency so the fetch client is future-ready
  while still keeping network I/O behind an injectable transport boundary.

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
- All requests must include
  `User-Agent: SuperFolio/1.0 (+https://github.com/aninditkarmakar/superfolio)`.
- Successful `SendRequest` responses are XML with `Status=Success` and a
  `ReferenceCode`.
- Failed service responses are XML with `Status=Fail`, `ErrorCode`, and
  `ErrorMessage`.
- IBKR documents a `SendRequest` pacing limit of one request per second and ten
  requests per minute per token.
- Report retrieval can require a delay or repeated attempts after
  `SendRequest`; temporary states include statement unavailable, incomplete, in
  progress, or server-load responses.

The implementation plan must include a protocol-validation task before coding.
That task records the checked public URLs, the verified request/response
assumptions, and any drift from this design.

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
   `BrokerPayload(xml_text=..., source_name="ibkr_flex_ws:<connection_id>:<feed_key>")`.
8. If `GetStatement` returns a documented temporary state, wait and retry until
   the bounded polling limit is reached.
9. If polling exhausts, raise a sanitized `ibkr_report_not_ready` fetch error.

Automation `requested_start_date` and `requested_end_date` are not sent to IBKR.
They continue to filter records locally after the configured Flex Query report is
retrieved.

A complete Flex report is a successful report payload accepted by the existing
Flex XML parser. The fetch layer must classify IBKR service envelopes before
returning payloads:

- `FlexStatementResponse` with `Status=Fail` is a service error and must not be
  returned as `BrokerPayload`.
- `FlexStatementResponse` without a usable successful report payload is malformed
  or unexpected unless current public docs prove otherwise.
- malformed XML, non-XML HTML/error content, missing required service-response
  fields, and unexpected XML roots are `ibkr_fetch_failed`.
- only recognized report XML proceeds to the existing parser and ingestion path.

## Fetch-once reuse

The fetcher must request each connection/feed report once per automation run and
reuse the resulting XML for every eligible account assigned to that connection.

This is necessary because IBKR receives only token, query id, and version. If a
Flex Query template includes three accounts, one fetch returns one XML report
containing records for those accounts. Fetching separately for each account would
usually regenerate the same report multiple times, waste IBKR capacity, and risk
violating documented pacing limits.

The orchestrator already groups accounts by connection and iterates feeds, but
load mode currently checks overlap per account and fetches inside the per-account
loop. The implementation must refactor the multi-feed execution path so payload
retrieval is per connection/feed/run in both dry-run and load mode, while parsing
and loading remain per account.

For load mode specifically:

1. Mark each account child as running.
2. Run the account/date overlap check for every account in the connection group.
3. Finalize overlapped accounts as `overlapping_load_job` without fetching.
4. Build the eligible account set from non-overlapped accounts.
5. If no accounts are eligible, do not fetch any feed for that connection group.
6. For each feed, fetch once and reuse the XML for every eligible account.
7. Preserve per-account `feed_results`, ingestion-run creation, summaries, and
   finalization semantics.

If a fetched and parsed report contains zero records for a target account, the
first version preserves current ingestion semantics: the account result may
succeed with zero counts. Users remain responsible for configuring Flex Query
templates to include the intended accounts and sections.

## Polling and pacing

The first implementation uses conservative fixed defaults. Retry knobs are not
user-configurable.

Policy:

- `SendRequest` is called once per connection/feed/run.
- `GetStatement` may be retried only for documented temporary states.
- After a successful `SendRequest`, wait 20 seconds before the first
  `GetStatement` attempt.
- Poll up to five `GetStatement` attempts, 20 seconds apart, for documented
  temporary states.
- Non-temporary service errors fail immediately.
- `SendRequest` network failures are not retried in the first version. If the
  response carrying the reference code is lost, the run fails safely with
  `ibkr_fetch_failed` and a later manual run can retry.
- `GetStatement` network failures after a reference code exists may be retried
  within the same bounded polling budget.

## Error categories

The adapter should raise typed or structured IBKR fetch errors internally, then
surface only sanitized messages through existing automation error handling.
The orchestrator must preserve broker fetch categories instead of collapsing all
adapter exceptions into `feed_fetch_failed`. Add a small structured exception
contract, for example `BrokerFetchError(category: str, message: str | None)`,
whose `category` is copied into `feed_results[].error_category` after validation
against an allowlist. Account-level summaries may still use `feed_fetch_failed`
when all feeds fail, but feed-level details must retain the IBKR category.

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

Initial IBKR service error mapping:

| Error code | Message summary | Category | Retry? |
| --- | --- | --- | --- |
| `1001` | Statement could not be generated now | `ibkr_report_not_ready` | yes, within `GetStatement` polling budget |
| `1003` | Statement is not available | `ibkr_report_not_ready` | yes |
| `1004` | Statement is incomplete | `ibkr_report_not_ready` | yes |
| `1005` | Settlement data is not ready | `ibkr_report_not_ready` | yes |
| `1006` | FIFO P/L data is not ready | `ibkr_report_not_ready` | yes |
| `1007` | MTM P/L data is not ready | `ibkr_report_not_ready` | yes |
| `1008` | MTM and FIFO P/L data is not ready | `ibkr_report_not_ready` | yes |
| `1009` | Server under heavy load | `ibkr_report_not_ready` | yes |
| `1010` | Legacy Flex Queries unsupported | `ibkr_invalid_query` | no |
| `1011` | Service account inactive | `ibkr_auth_failed` | no |
| `1012` | Token expired | `ibkr_auth_failed` | no |
| `1013` | IP restriction | `ibkr_auth_failed` | no |
| `1014` | Query invalid | `ibkr_invalid_query` | no |
| `1015` | Token invalid | `ibkr_auth_failed` | no |
| `1016` | Account invalid | `ibkr_invalid_query` | no |
| `1017` | Reference code invalid | `ibkr_invalid_query` | no |
| `1018` | Too many requests | `ibkr_pacing_limit` | no |
| `1019` | Statement generation in progress | `ibkr_report_not_ready` | yes |
| `1020` | Invalid request or unable to validate | `ibkr_invalid_query` | no |
| `1021` | Statement could not be retrieved now | `ibkr_report_not_ready` | yes |

If a retriable code is returned by `SendRequest`, the first version still fails
safely rather than reissuing `SendRequest`, because retrying `SendRequest` can
generate duplicate reports and increase pacing risk. Retriable behavior applies
to `GetStatement` after a reference code has been received.

## Raw XML debug saves

Default behavior keeps fetched XML in memory only.

For manual local testing, the CLI will accept an explicit debug output directory.
When provided, the fetch layer writes retrieved XML under that directory using
non-secret UUID-based filenames. Filenames may include non-sensitive context such
as connection id and feed key, but must not include tokens, query ids, reference
codes, raw account numbers, or report contents.

This option is local CLI-only:

- GitHub Actions workflow inputs must not expose raw XML debug saving.
- Runtime must reject debug-save paths when `GITHUB_ACTIONS=true`, even if a
  caller somehow passes the local-only flag.
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
- Required header:
  `User-Agent: SuperFolio/1.0 (+https://github.com/aninditkarmakar/superfolio)`
- HTTP client dependency: `httpx`

The implementation should wrap `httpx` behind an injected transport boundary so
tests can provide a fake transport and make no real network calls. Runtime
configuration should not expose a production base-URL override in the first
version; this avoids accidentally pointing real automation at untrusted
endpoints.

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
- `SendRequest` network failures are not retried.
- `GetStatement` service-response XML is classified before returning payloads to
  the parser.
- Malformed XML and missing required fields return `ibkr_fetch_failed`.
- Network failures return sanitized `ibkr_fetch_failed`.
- Structured `BrokerFetchError` categories appear in `feed_results`.
- Tokens and query ids do not appear in exceptions or summaries.
- Multi-account connection/feed execution fetches once and reuses XML per account
  in both dry-run and load mode.
- Load mode does not fetch feeds when all accounts in a connection group are
  blocked by overlap.
- Local debug XML save writes synthetic XML only when explicitly enabled.
- GitHub Actions/manual workflow does not expose raw XML debug-save inputs, and
  `GITHUB_ACTIONS=true` rejects debug saves at runtime.
- Fetched reports use safe `source_name` values in the form
  `ibkr_flex_ws:<connection_id>:<feed_key>`.

## Documentation updates

Update `docs/workflows/automated-ingestion.md` and `README.md` after
implementation to remove or narrow the "fetch not implemented" limitation.

Documentation should explain:

- IBKR Flex Web Service must be enabled in Client Portal.
- A Flex Web Service token and feed query id must be stored as encrypted
  credentials.
- The query template controls which accounts and sections IBKR returns.
- A fetched report with zero records for an account is treated as a zero-count
  result; users must validate Flex Query account inclusion during setup.
- Automation date inputs filter locally; they do not reconfigure the IBKR query.
- Raw XML debug saving is local-only, opt-in, private, and disabled by default.

## Implementation notes

- Preserve the existing `BrokerPayload` contract.
- Prefer a small dedicated client module over placing HTTP and XML parsing logic
  directly in `adapters.py`.
- Use a structured XML parser for IBKR service responses and Flex payloads.
- Add `httpx` to `requirements.txt` during implementation and use an injected
  transport boundary for tests.
- Keep the adapter free of database access.
- Keep future broker extensibility by avoiding IBKR-specific behavior in generic
  orchestration code except where fetch-once reuse is necessary for feed payload
  execution.
- Do not merge any branch back anywhere without explicit repository-owner
  approval.
