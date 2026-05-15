# IBKR Flex Web Service Fetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Execution constraint:** Any subagent-driven execution of this plan must use `claude-sonnet-4.6` or a higher-capability model. Do not merge any branch back anywhere without explicit repository-owner approval.

**Goal:** Implement real IBKR Flex Web Service XML fetches behind the existing automated ingestion adapter boundary.

**Architecture:** Add a focused IBKR Flex Web Service client behind `IbkrFlexWebServiceAdapter`. Keep orchestration responsible for target resolution, credential loading, status aggregation, and per-account parsing/loading; keep the client responsible only for IBKR `SendRequest`/`GetStatement`, response classification, polling, and optional local debug XML saves.

**Tech Stack:** Python 3.12, `unittest`, `httpx`, PostgreSQL adapter boundaries already in `portfolio_engine.database`, existing Flex parser in `portfolio_engine.ingestion.dry_run`.

---

## File structure

- Create `portfolio_engine/automation/fetch_errors.py`
  - Owns `BrokerFetchError`, allowed fetch categories, and safe category extraction.
- Create `portfolio_engine/automation/ibkr_flex_client.py`
  - Owns IBKR v3 endpoint constants, `HttpTransport` protocol, `HttpxTransport`, response parsing, error-code mapping, polling, source name creation, and local debug XML saves.
- Modify `portfolio_engine/automation/types.py`
  - Add `debug_raw_xml_dir: str | None = None` to `AutomationRunRequest`.
- Modify `portfolio_engine/automation/adapters.py`
  - Wire `IbkrFlexWebServiceAdapter.fetch_feed_payload()` to `IbkrFlexWebServiceClient`.
  - Keep legacy `fetch_payload()` stubbed unless needed by old adapter-path tests.
- Modify `portfolio_engine/automation/orchestrator.py`
  - Preserve structured broker fetch categories in `feed_results`.
  - Refactor load multi-feed execution so overlap checks happen before any feed fetch and each feed is fetched once per connection/feed/run.
- Modify `portfolio_engine/automation/cli.py`
  - Add local-only `--debug-raw-xml-dir`.
  - Reject the flag when `GITHUB_ACTIONS=true`.
  - Pass the debug directory through `AutomationRunRequest`.
- Modify `requirements.txt`
  - Add `httpx>=0.27,<1`.
- Modify `docs/workflows/automated-ingestion.md` and `README.md`
  - Update "fetch not implemented" language and document local-only debug saves and IBKR query-template responsibilities.
- Add `tests/test_ibkr_flex_client.py`
  - Unit-test protocol shape, response classification, polling, error mapping, no secret/reference leaks, source names, and debug saves.
- Modify `tests/test_automation_orchestrator.py`
  - Add fetch-once load tests and structured `BrokerFetchError` propagation tests.
- Modify `tests/test_automation_cli.py`
  - Add debug raw XML CLI parsing and `GITHUB_ACTIONS=true` rejection tests.
- Modify `tests/test_automation_workflow.py`
  - Assert workflow does not expose or pass the debug raw XML option.

## Protocol validation notes for implementation

Before coding Task 1, verify the current public docs:

- IBKR Campus Flex Web Service: `https://www.interactivebrokers.com/campus/ibkr-api-page/flex-web-service/`
- IBKR Guides Client Portal setup: `https://www.ibkrguides.com/clientportal/performanceandstatements/flex-web-service.htm`

Record in Task 1 test comments and commit message:

- v3 base URL is `https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService`.
- `SendRequest` query params are `t`, `q`, `v=3`.
- `GetStatement` query params are `t`, `q`, `v=3`.
- `User-Agent` is required; SuperFolio uses `SuperFolio/1.0 (+https://github.com/aninditkarmakar/superfolio)`.
- `SendRequest` success shape is `FlexStatementResponse` with `Status=Success` and `ReferenceCode`.
- Service failure shape is `FlexStatementResponse` with `Status=Fail`, `ErrorCode`, and `ErrorMessage`.
- Existing parser fixtures use `FlexQueryResponse` as the accepted report root.

---

### Task 1: Add `httpx` dependency and structured fetch errors

**Files:**
- Modify: `requirements.txt`
- Create: `portfolio_engine/automation/fetch_errors.py`
- Test: `tests/test_ibkr_flex_client.py`

- [ ] **Step 1: Write the failing fetch-error tests**

Add `tests/test_ibkr_flex_client.py` with:

```python
from __future__ import annotations

import unittest

from portfolio_engine.automation.fetch_errors import (
    ALLOWED_BROKER_FETCH_CATEGORIES,
    BrokerFetchError,
    safe_fetch_error_category,
)


class BrokerFetchErrorTests(unittest.TestCase):
    def test_allowed_categories_include_ibkr_categories(self) -> None:
        self.assertIn("ibkr_auth_failed", ALLOWED_BROKER_FETCH_CATEGORIES)
        self.assertIn("ibkr_invalid_query", ALLOWED_BROKER_FETCH_CATEGORIES)
        self.assertIn("ibkr_pacing_limit", ALLOWED_BROKER_FETCH_CATEGORIES)
        self.assertIn("ibkr_report_not_ready", ALLOWED_BROKER_FETCH_CATEGORIES)
        self.assertIn("ibkr_fetch_failed", ALLOWED_BROKER_FETCH_CATEGORIES)

    def test_broker_fetch_error_stores_category_and_sanitized_message_source(self) -> None:
        exc = BrokerFetchError("ibkr_auth_failed", "Token has expired.")

        self.assertEqual(exc.category, "ibkr_auth_failed")
        self.assertEqual(str(exc), "Token has expired.")

    def test_safe_fetch_error_category_allows_known_category(self) -> None:
        exc = BrokerFetchError("ibkr_pacing_limit", "Too many requests.")

        self.assertEqual(safe_fetch_error_category(exc), "ibkr_pacing_limit")

    def test_safe_fetch_error_category_falls_back_for_unknown_category(self) -> None:
        exc = BrokerFetchError("new_future_category", "New future error.")

        self.assertEqual(safe_fetch_error_category(exc), "feed_fetch_failed")

    def test_safe_fetch_error_category_falls_back_for_non_fetch_exception(self) -> None:
        self.assertEqual(safe_fetch_error_category(RuntimeError("boom")), "feed_fetch_failed")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
python -m unittest tests.test_ibkr_flex_client.BrokerFetchErrorTests -v
```

Expected: fails with `ModuleNotFoundError: No module named 'portfolio_engine.automation.fetch_errors'`.

- [ ] **Step 3: Implement fetch errors**

Create `portfolio_engine/automation/fetch_errors.py`:

```python
from __future__ import annotations


ALLOWED_BROKER_FETCH_CATEGORIES = frozenset(
    {
        "ibkr_auth_failed",
        "ibkr_invalid_query",
        "ibkr_pacing_limit",
        "ibkr_report_not_ready",
        "ibkr_fetch_failed",
    }
)


class BrokerFetchError(RuntimeError):
    """Broker fetch failure with a privacy-safe category for automation summaries."""

    def __init__(self, category: str, message: str | None = None) -> None:
        self.category = category
        super().__init__(message or category)


def safe_fetch_error_category(exc: BaseException) -> str:
    """Return an allowlisted broker fetch category or the generic feed failure category."""
    if isinstance(exc, BrokerFetchError) and exc.category in ALLOWED_BROKER_FETCH_CATEGORIES:
        return exc.category
    return "feed_fetch_failed"
```

Modify `requirements.txt`:

```text
psycopg[binary]>=3.2,<4
PyYAML>=6.0,<7
cryptography>=42,<46
httpx>=0.27,<1
```

- [ ] **Step 4: Run the focused test to verify it passes**

Run:

```bash
python -m unittest tests.test_ibkr_flex_client.BrokerFetchErrorTests -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Install updated requirements**

Run:

```bash
python -m pip install -r requirements.txt
```

Expected: installs successfully and includes `httpx`.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt portfolio_engine/automation/fetch_errors.py tests/test_ibkr_flex_client.py
git commit -m "feat: add broker fetch error categories" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Implement IBKR Flex client request shape and service-response parsing

**Files:**
- Create: `portfolio_engine/automation/ibkr_flex_client.py`
- Modify: `tests/test_ibkr_flex_client.py`

- [ ] **Step 1: Add failing client tests for request shape and success flow**

Append to `tests/test_ibkr_flex_client.py`:

```python
from dataclasses import dataclass

from portfolio_engine.automation.ibkr_flex_client import (
    IBKR_FLEX_BASE_URL,
    IBKR_FLEX_USER_AGENT,
    IbkrFlexWebServiceClient,
)


VALID_FLEX_XML = """<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement>
      <CashTransactions>
        <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="1000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" />
      </CashTransactions>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""


@dataclass(frozen=True)
class FakeHttpResponse:
    status_code: int
    text: str


class FakeTransport:
    def __init__(self, responses: list[FakeHttpResponse | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, params: dict[str, str], headers: dict[str, str], timeout: float) -> FakeHttpResponse:
        self.calls.append({"url": url, "params": dict(params), "headers": dict(headers), "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class IbkrFlexClientRequestTests(unittest.TestCase):
    def test_fetch_report_uses_documented_send_and_get_request_shapes(self) -> None:
        transport = FakeTransport(
            [
                FakeHttpResponse(
                    200,
                    """<FlexStatementResponse><Status>Success</Status><ReferenceCode>1234567890</ReferenceCode><url>ignored</url></FlexStatementResponse>""",
                ),
                FakeHttpResponse(200, VALID_FLEX_XML),
            ]
        )
        sleeps: list[float] = []
        client = IbkrFlexWebServiceClient(transport=transport, sleep=sleeps.append)

        xml = client.fetch_report(token="token-123", query_id="query-456")

        self.assertEqual(xml, VALID_FLEX_XML)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(transport.calls[0]["url"], f"{IBKR_FLEX_BASE_URL}/SendRequest")
        self.assertEqual(transport.calls[0]["params"], {"t": "token-123", "q": "query-456", "v": "3"})
        self.assertEqual(transport.calls[0]["headers"], {"User-Agent": IBKR_FLEX_USER_AGENT})
        self.assertEqual(transport.calls[1]["url"], f"{IBKR_FLEX_BASE_URL}/GetStatement")
        self.assertEqual(transport.calls[1]["params"], {"t": "token-123", "q": "1234567890", "v": "3"})
        self.assertEqual(transport.calls[1]["headers"], {"User-Agent": IBKR_FLEX_USER_AGENT})
        self.assertEqual(sleeps, [20.0])
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```bash
python -m unittest tests.test_ibkr_flex_client.IbkrFlexClientRequestTests.test_fetch_report_uses_documented_send_and_get_request_shapes -v
```

Expected: fails with `ModuleNotFoundError` or missing `IbkrFlexWebServiceClient`.

- [ ] **Step 3: Implement minimal client success path**

Create `portfolio_engine/automation/ibkr_flex_client.py`:

```python
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol
from xml.etree import ElementTree

import httpx

from portfolio_engine.automation.fetch_errors import BrokerFetchError


IBKR_FLEX_BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
IBKR_FLEX_VERSION = "3"
IBKR_FLEX_USER_AGENT = "SuperFolio/1.0 (+https://github.com/aninditkarmakar/superfolio)"
HTTP_TIMEOUT_SECONDS = 30.0
INITIAL_GETSTATEMENT_WAIT_SECONDS = 20.0
GETSTATEMENT_RETRY_WAIT_SECONDS = 20.0
GETSTATEMENT_TOTAL_ATTEMPTS = 5
ACCEPTED_REPORT_ROOTS = frozenset({"FlexQueryResponse"})


class HttpResponse(Protocol):
    status_code: int
    text: str


class HttpTransport(Protocol):
    def get(self, url: str, *, params: dict[str, str], headers: dict[str, str], timeout: float) -> HttpResponse: ...


class HttpxTransport:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client()

    def get(self, url: str, *, params: dict[str, str], headers: dict[str, str], timeout: float) -> httpx.Response:
        return self._client.get(url, params=params, headers=headers, timeout=timeout)


class IbkrFlexWebServiceClient:
    def __init__(
        self,
        *,
        transport: HttpTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport or HttpxTransport()
        self._sleep = sleep

    def fetch_report(self, *, token: str, query_id: str) -> str:
        reference_code = self._send_request(token=token, query_id=query_id)
        self._sleep(INITIAL_GETSTATEMENT_WAIT_SECONDS)
        return self._get_statement(token=token, reference_code=reference_code)

    def _send_request(self, *, token: str, query_id: str) -> str:
        response = self._transport.get(
            f"{IBKR_FLEX_BASE_URL}/SendRequest",
            params={"t": token, "q": query_id, "v": IBKR_FLEX_VERSION},
            headers={"User-Agent": IBKR_FLEX_USER_AGENT},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed")
        root = _parse_xml(response.text)
        if root.tag != "FlexStatementResponse":
            raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed")
        status = _child_text(root, "Status")
        if status == "Fail":
            raise _error_from_service_response(root)
        if status != "Success":
            raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed")
        reference_code = _child_text(root, "ReferenceCode")
        if not reference_code:
            raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed")
        return reference_code

    def _get_statement(self, *, token: str, reference_code: str) -> str:
        response = self._transport.get(
            f"{IBKR_FLEX_BASE_URL}/GetStatement",
            params={"t": token, "q": reference_code, "v": IBKR_FLEX_VERSION},
            headers={"User-Agent": IBKR_FLEX_USER_AGENT},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed")
        root = _parse_xml(response.text)
        if root.tag == "FlexStatementResponse":
            status = _child_text(root, "Status")
            if status == "Fail":
                raise _error_from_service_response(root)
            raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed")
        if root.tag not in ACCEPTED_REPORT_ROOTS:
            raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed")
        return response.text


def _parse_xml(xml_text: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as error:
        raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed") from error


def _child_text(root: ElementTree.Element, tag: str) -> str | None:
    child = root.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _error_from_service_response(root: ElementTree.Element) -> BrokerFetchError:
    code = _child_text(root, "ErrorCode")
    category = _category_for_error_code(code)
    return BrokerFetchError(category, category)


def _category_for_error_code(code: str | None) -> str:
    if code in {"1011", "1012", "1013", "1015"}:
        return "ibkr_auth_failed"
    if code in {"1010", "1014", "1016", "1017", "1020"}:
        return "ibkr_invalid_query"
    if code == "1018":
        return "ibkr_pacing_limit"
    if code in {"1001", "1003", "1004", "1005", "1006", "1007", "1008", "1009", "1019", "1021"}:
        return "ibkr_report_not_ready"
    return "ibkr_fetch_failed"
```

- [ ] **Step 4: Run the focused request-shape test**

Run:

```bash
python -m unittest tests.test_ibkr_flex_client.IbkrFlexClientRequestTests.test_fetch_report_uses_documented_send_and_get_request_shapes -v
```

Expected: passes.

- [ ] **Step 5: Commit**

```bash
git add portfolio_engine/automation/ibkr_flex_client.py tests/test_ibkr_flex_client.py
git commit -m "feat: add IBKR flex request client" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Add IBKR error mapping, polling, and response-classification tests

**Files:**
- Modify: `portfolio_engine/automation/ibkr_flex_client.py`
- Modify: `tests/test_ibkr_flex_client.py`

- [ ] **Step 1: Add failing tests for errors, polling, and classification**

Append these test methods to `IbkrFlexClientRequestTests`:

```python
    def test_getstatement_temporary_error_polls_then_succeeds(self) -> None:
        transport = FakeTransport(
            [
                FakeHttpResponse(200, """<FlexStatementResponse><Status>Success</Status><ReferenceCode>123</ReferenceCode></FlexStatementResponse>"""),
                FakeHttpResponse(200, """<FlexStatementResponse><Status>Fail</Status><ErrorCode>1019</ErrorCode><ErrorMessage>Statement generation in progress.</ErrorMessage></FlexStatementResponse>"""),
                FakeHttpResponse(200, VALID_FLEX_XML),
            ]
        )
        sleeps: list[float] = []
        client = IbkrFlexWebServiceClient(transport=transport, sleep=sleeps.append)

        self.assertEqual(client.fetch_report(token="token", query_id="query"), VALID_FLEX_XML)
        self.assertEqual(len([c for c in transport.calls if str(c["url"]).endswith("/GetStatement")]), 2)
        self.assertEqual(sleeps, [20.0, 20.0])

    def test_getstatement_polls_five_total_attempts_then_report_not_ready(self) -> None:
        responses = [
            FakeHttpResponse(200, """<FlexStatementResponse><Status>Success</Status><ReferenceCode>123</ReferenceCode></FlexStatementResponse>"""),
        ] + [
            FakeHttpResponse(200, """<FlexStatementResponse><Status>Fail</Status><ErrorCode>1019</ErrorCode><ErrorMessage>Statement generation in progress.</ErrorMessage></FlexStatementResponse>""")
            for _ in range(5)
        ]
        transport = FakeTransport(responses)
        client = IbkrFlexWebServiceClient(transport=transport, sleep=lambda seconds: None)

        with self.assertRaises(BrokerFetchError) as ctx:
            client.fetch_report(token="token", query_id="query")

        self.assertEqual(ctx.exception.category, "ibkr_report_not_ready")
        self.assertEqual(len([c for c in transport.calls if str(c["url"]).endswith("/GetStatement")]), 5)

    def test_sendrequest_network_failure_is_not_retried(self) -> None:
        transport = FakeTransport([OSError("token=secret query_id=secret")])
        client = IbkrFlexWebServiceClient(transport=transport, sleep=lambda seconds: None)

        with self.assertRaises(BrokerFetchError) as ctx:
            client.fetch_report(token="secret-token", query_id="secret-query")

        self.assertEqual(ctx.exception.category, "ibkr_fetch_failed")
        self.assertEqual(len(transport.calls), 1)
        self.assertNotIn("secret-token", str(ctx.exception))
        self.assertNotIn("secret-query", str(ctx.exception))

    def test_known_error_codes_map_to_categories(self) -> None:
        cases = {
            "1012": "ibkr_auth_failed",
            "1014": "ibkr_invalid_query",
            "1018": "ibkr_pacing_limit",
            "1019": "ibkr_report_not_ready",
            "9999": "ibkr_fetch_failed",
            "not-a-number": "ibkr_fetch_failed",
        }
        for code, category in cases.items():
            with self.subTest(code=code):
                transport = FakeTransport(
                    [
                        FakeHttpResponse(
                            200,
                            f"""<FlexStatementResponse><Status>Fail</Status><ErrorCode>{code}</ErrorCode><ErrorMessage>Message</ErrorMessage></FlexStatementResponse>""",
                        )
                    ]
                )
                client = IbkrFlexWebServiceClient(transport=transport, sleep=lambda seconds: None)

                with self.assertRaises(BrokerFetchError) as ctx:
                    client.fetch_report(token="token", query_id="query")

                self.assertEqual(ctx.exception.category, category)

    def test_getstatement_service_error_xml_is_not_returned_to_parser(self) -> None:
        transport = FakeTransport(
            [
                FakeHttpResponse(200, """<FlexStatementResponse><Status>Success</Status><ReferenceCode>123</ReferenceCode></FlexStatementResponse>"""),
                FakeHttpResponse(200, """<FlexStatementResponse><Status>Fail</Status><ErrorCode>1012</ErrorCode><ErrorMessage>Token expired.</ErrorMessage></FlexStatementResponse>"""),
            ]
        )
        client = IbkrFlexWebServiceClient(transport=transport, sleep=lambda seconds: None)

        with self.assertRaises(BrokerFetchError) as ctx:
            client.fetch_report(token="token", query_id="query")

        self.assertEqual(ctx.exception.category, "ibkr_auth_failed")

    def test_unknown_xml_root_and_html_are_fetch_failed(self) -> None:
        for body in ("<UnexpectedRoot />", "<html>maintenance</html>"):
            with self.subTest(body=body):
                transport = FakeTransport(
                    [
                        FakeHttpResponse(200, """<FlexStatementResponse><Status>Success</Status><ReferenceCode>123</ReferenceCode></FlexStatementResponse>"""),
                        FakeHttpResponse(200, body),
                    ]
                )
                client = IbkrFlexWebServiceClient(transport=transport, sleep=lambda seconds: None)

                with self.assertRaises(BrokerFetchError) as ctx:
                    client.fetch_report(token="token", query_id="query")

                self.assertEqual(ctx.exception.category, "ibkr_fetch_failed")
```

- [ ] **Step 2: Run the new tests to verify at least polling fails**

Run:

```bash
python -m unittest tests.test_ibkr_flex_client.IbkrFlexClientRequestTests -v
```

Expected: polling tests fail because `_get_statement()` does not yet retry.

- [ ] **Step 3: Implement polling and safe network handling**

Update `IbkrFlexWebServiceClient` in `portfolio_engine/automation/ibkr_flex_client.py`:

```python
    def _send_request(self, *, token: str, query_id: str) -> str:
        try:
            response = self._transport.get(
                f"{IBKR_FLEX_BASE_URL}/SendRequest",
                params={"t": token, "q": query_id, "v": IBKR_FLEX_VERSION},
                headers={"User-Agent": IBKR_FLEX_USER_AGENT},
                timeout=HTTP_TIMEOUT_SECONDS,
            )
        except Exception as error:
            raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed") from error
        return _reference_code_from_send_response(response)

    def _get_statement(self, *, token: str, reference_code: str) -> str:
        last_error: BrokerFetchError | None = None
        for attempt in range(GETSTATEMENT_TOTAL_ATTEMPTS):
            try:
                response = self._transport.get(
                    f"{IBKR_FLEX_BASE_URL}/GetStatement",
                    params={"t": token, "q": reference_code, "v": IBKR_FLEX_VERSION},
                    headers={"User-Agent": IBKR_FLEX_USER_AGENT},
                    timeout=HTTP_TIMEOUT_SECONDS,
                )
                return _report_xml_from_get_response(response)
            except BrokerFetchError as error:
                if error.category != "ibkr_report_not_ready":
                    raise
                last_error = error
            except Exception as error:
                last_error = BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed")
                if attempt == GETSTATEMENT_TOTAL_ATTEMPTS - 1:
                    raise last_error from error

            if attempt < GETSTATEMENT_TOTAL_ATTEMPTS - 1:
                self._sleep(GETSTATEMENT_RETRY_WAIT_SECONDS)

        raise last_error or BrokerFetchError("ibkr_report_not_ready", "ibkr_report_not_ready")
```

Add helper functions below `_child_text()`:

```python
def _reference_code_from_send_response(response: HttpResponse) -> str:
    if response.status_code >= 400:
        raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed")
    root = _parse_xml(response.text)
    if root.tag != "FlexStatementResponse":
        raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed")
    status = _child_text(root, "Status")
    if status == "Fail":
        raise _error_from_service_response(root)
    if status != "Success":
        raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed")
    reference_code = _child_text(root, "ReferenceCode")
    if not reference_code:
        raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed")
    return reference_code


def _report_xml_from_get_response(response: HttpResponse) -> str:
    if response.status_code >= 400:
        raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed")
    root = _parse_xml(response.text)
    if root.tag == "FlexStatementResponse":
        status = _child_text(root, "Status")
        if status == "Fail":
            raise _error_from_service_response(root)
        raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed")
    if root.tag not in ACCEPTED_REPORT_ROOTS:
        raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed")
    return response.text
```

Then simplify `_send_request()` and `_get_statement()` to call these helpers. Ensure `_category_for_error_code()` already returns `ibkr_fetch_failed` for unknown, missing, or non-numeric codes.

- [ ] **Step 4: Run focused client tests**

Run:

```bash
python -m unittest tests.test_ibkr_flex_client -v
```

Expected: all `test_ibkr_flex_client` tests pass.

- [ ] **Step 5: Commit**

```bash
git add portfolio_engine/automation/ibkr_flex_client.py tests/test_ibkr_flex_client.py
git commit -m "feat: classify IBKR flex service responses" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Add local debug XML save support

**Files:**
- Modify: `portfolio_engine/automation/ibkr_flex_client.py`
- Modify: `tests/test_ibkr_flex_client.py`

- [ ] **Step 1: Add failing debug-save tests**

Append to `tests/test_ibkr_flex_client.py`:

```python
import os
import tempfile
from pathlib import Path
from unittest import mock


class IbkrFlexClientDebugSaveTests(unittest.TestCase):
    def _client_with_success(self, tmp_path: Path) -> tuple[IbkrFlexWebServiceClient, FakeTransport]:
        transport = FakeTransport(
            [
                FakeHttpResponse(200, """<FlexStatementResponse><Status>Success</Status><ReferenceCode>secret-ref</ReferenceCode></FlexStatementResponse>"""),
                FakeHttpResponse(200, VALID_FLEX_XML),
            ]
        )
        client = IbkrFlexWebServiceClient(
            transport=transport,
            sleep=lambda seconds: None,
            debug_raw_xml_dir=tmp_path,
        )
        return client, transport

    def test_debug_save_writes_uuid_filename_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            client, _ = self._client_with_success(tmp_path)

            client.fetch_report(
                token="secret-token",
                query_id="secret-query",
                connection_id="conn/one",
                feed_key="primary:feed",
            )

            files = list(tmp_path.glob("*.xml"))
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].name.startswith("conn-one-primary-feed-"))
            self.assertNotIn("secret-token", files[0].name)
            self.assertNotIn("secret-query", files[0].name)
            self.assertNotIn("secret-ref", files[0].name)
            self.assertEqual(files[0].read_text(encoding="utf-8"), VALID_FLEX_XML)

    def test_debug_save_rejected_in_github_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
                with self.assertRaisesRegex(RuntimeError, "raw XML debug saves are not allowed"):
                    IbkrFlexWebServiceClient(
                        transport=FakeTransport([]),
                        debug_raw_xml_dir=Path(tmp),
                    )
```

- [ ] **Step 2: Run debug-save tests to verify failure**

Run:

```bash
python -m unittest tests.test_ibkr_flex_client.IbkrFlexClientDebugSaveTests -v
```

Expected: fails because `debug_raw_xml_dir`, `connection_id`, and `feed_key` are not supported yet.

- [ ] **Step 3: Implement debug-save support**

Update `IbkrFlexWebServiceClient.__init__()` and `fetch_report()`:

```python
from pathlib import Path
from uuid import uuid4
import os
import re


_SAFE_FILENAME_CHARS_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class IbkrFlexWebServiceClient:
    def __init__(
        self,
        *,
        transport: HttpTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        debug_raw_xml_dir: Path | None = None,
    ) -> None:
        if debug_raw_xml_dir is not None and os.environ.get("GITHUB_ACTIONS") == "true":
            raise RuntimeError("raw XML debug saves are not allowed in GitHub Actions environments")
        self._transport = transport or HttpxTransport()
        self._sleep = sleep
        self._debug_raw_xml_dir = debug_raw_xml_dir

    def fetch_report(
        self,
        *,
        token: str,
        query_id: str,
        connection_id: str = "connection",
        feed_key: str = "feed",
    ) -> str:
        reference_code = self._send_request(token=token, query_id=query_id)
        self._sleep(INITIAL_GETSTATEMENT_WAIT_SECONDS)
        xml_text = self._get_statement(token=token, reference_code=reference_code)
        self._save_debug_xml(xml_text, connection_id=connection_id, feed_key=feed_key)
        return xml_text

    def _save_debug_xml(self, xml_text: str, *, connection_id: str, feed_key: str) -> None:
        if self._debug_raw_xml_dir is None:
            return
        if os.environ.get("GITHUB_ACTIONS") == "true":
            raise RuntimeError("raw XML debug saves are not allowed in GitHub Actions environments")
        self._debug_raw_xml_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{_safe_filename_part(connection_id)}-{_safe_filename_part(feed_key)}-{uuid4()}.xml"
        (self._debug_raw_xml_dir / filename).write_text(xml_text, encoding="utf-8")


def _safe_filename_part(value: str) -> str:
    safe = _SAFE_FILENAME_CHARS_RE.sub("-", value.strip())
    return safe.strip("-") or "unknown"
```

- [ ] **Step 4: Run debug-save tests**

Run:

```bash
python -m unittest tests.test_ibkr_flex_client.IbkrFlexClientDebugSaveTests -v
```

Expected: tests pass.

- [ ] **Step 5: Run all client tests**

Run:

```bash
python -m unittest tests.test_ibkr_flex_client -v
```

Expected: all client tests pass.

- [ ] **Step 6: Commit**

```bash
git add portfolio_engine/automation/ibkr_flex_client.py tests/test_ibkr_flex_client.py
git commit -m "feat: add local IBKR XML debug saves" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Wire adapter to the IBKR client

**Files:**
- Modify: `portfolio_engine/automation/adapters.py`
- Modify: `tests/test_automation_orchestrator.py`
- Modify: `tests/test_ibkr_flex_client.py`

- [ ] **Step 1: Add failing adapter tests**

Add to `tests/test_ibkr_flex_client.py`:

```python
from datetime import date

from portfolio_engine.automation.adapters import IbkrFlexWebServiceAdapter
from portfolio_engine.automation.credentials import SecretValue
from portfolio_engine.automation.types import AutomationRunRequest, IntegrationConnectionContext, IntegrationFeedContext


class FakeIbkrClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def fetch_report(self, *, token: str, query_id: str, connection_id: str = "connection", feed_key: str = "feed") -> str:
        self.calls.append(
            {
                "token": token,
                "query_id": query_id,
                "connection_id": connection_id,
                "feed_key": feed_key,
            }
        )
        return VALID_FLEX_XML


class IbkrAdapterFetchTests(unittest.TestCase):
    def test_fetch_feed_payload_uses_decrypted_token_and_feed_query_id(self) -> None:
        client = FakeIbkrClient()
        adapter = IbkrFlexWebServiceAdapter(client=client)
        connection = IntegrationConnectionContext(
            connection_id="connection-uuid",
            integration_key="ibkr_flex_ws",
            brokerage_code="IBKR",
            name="IBKR Login",
            credentials={"flex_token": SecretValue("plain-token")},
        )
        feed = IntegrationFeedContext(
            feed_id="feed-uuid",
            feed_key="primary",
            display_name="Primary",
            secrets={"query_id": SecretValue("plain-query")},
        )
        request = AutomationRunRequest(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2025, 1, 1),
            requested_end_date=date(2025, 1, 31),
            account_external_ids=("U100",),
        )

        payload = adapter.fetch_feed_payload(connection, feed, request)

        self.assertEqual(payload.xml_text, VALID_FLEX_XML)
        self.assertEqual(payload.source_name, "ibkr_flex_ws:connection-uuid:primary")
        self.assertEqual(
            client.calls,
            [
                {
                    "token": "plain-token",
                    "query_id": "plain-query",
                    "connection_id": "connection-uuid",
                    "feed_key": "primary",
                }
            ],
        )
```

- [ ] **Step 2: Run adapter test to verify failure**

Run:

```bash
python -m unittest tests.test_ibkr_flex_client.IbkrAdapterFetchTests -v
```

Expected: fails because `IbkrFlexWebServiceAdapter(client=...)` or fetch implementation is missing.

- [ ] **Step 3: Implement adapter wiring**

Update `portfolio_engine/automation/adapters.py`:

```python
from pathlib import Path

from portfolio_engine.automation.ibkr_flex_client import IbkrFlexWebServiceClient
```

Change the adapter class:

```python
class IbkrFlexWebServiceAdapter:
    """Adapter for the IBKR Flex Web Service data source."""

    def __init__(self, *, client: IbkrFlexWebServiceClient | None = None) -> None:
        self._client = client or IbkrFlexWebServiceClient()
```

Replace `fetch_feed_payload()` body:

```python
    def fetch_feed_payload(
        self,
        connection: IntegrationConnectionContext,
        feed: IntegrationFeedContext,
        request: AutomationRunRequest,
    ) -> BrokerPayload:
        """Fetch one Flex XML report for one connection feed."""
        token = connection.credentials["flex_token"].reveal()
        query_id = feed.secrets["query_id"].reveal()
        xml_text = self._client.fetch_report(
            token=token,
            query_id=query_id,
            connection_id=connection.connection_id,
            feed_key=feed.feed_key,
        )
        return BrokerPayload(
            xml_text=xml_text,
            source_name=f"ibkr_flex_ws:{connection.connection_id}:{feed.feed_key}",
        )
```

- [ ] **Step 4: Run adapter tests**

Run:

```bash
python -m unittest tests.test_ibkr_flex_client.IbkrAdapterFetchTests -v
```

Expected: tests pass.

- [ ] **Step 5: Update or remove the old NotImplemented test**

In `tests/test_automation_orchestrator.py`, replace `test_ibkr_adapter_fetch_feed_payload_raises_not_implemented_without_secret_leak` with a test that verifies the implemented adapter does not leak secrets on `BrokerFetchError`:

```python
    def test_ibkr_adapter_fetch_feed_payload_error_does_not_leak_secrets(self) -> None:
        from portfolio_engine.automation.adapters import IbkrFlexWebServiceAdapter
        from portfolio_engine.automation.fetch_errors import BrokerFetchError
        from portfolio_engine.automation.types import AutomationRunRequest, IntegrationConnectionContext, IntegrationFeedContext
        from portfolio_engine.automation.credentials import SecretValue
        from datetime import date

        class FailingClient:
            def fetch_report(self, *, token, query_id, connection_id="connection", feed_key="feed"):
                raise BrokerFetchError("ibkr_auth_failed", "ibkr_auth_failed")

        adapter = IbkrFlexWebServiceAdapter(client=FailingClient())
        connection = IntegrationConnectionContext(
            connection_id="connection-uuid",
            integration_key="ibkr_flex_ws",
            brokerage_code="IBKR",
            name="IBKR Personal",
            credentials={"flex_token": SecretValue("supersecrettoken")},
        )
        feed = IntegrationFeedContext(
            feed_id="feed-uuid",
            feed_key="daily",
            display_name="Daily",
            secrets={"query_id": SecretValue("myprivatequery")},
        )
        request = AutomationRunRequest(
            target_type="portfolio",
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
        )

        with self.assertRaises(BrokerFetchError) as ctx:
            adapter.fetch_feed_payload(connection, feed, request)

        error_msg = str(ctx.exception)
        self.assertNotIn("supersecrettoken", error_msg)
        self.assertNotIn("myprivatequery", error_msg)
```

- [ ] **Step 6: Run related tests**

Run:

```bash
python -m unittest tests.test_ibkr_flex_client tests.test_automation_orchestrator.TestAutomationConnectionContexts -v
```

Expected: all selected tests pass. If the exact class name differs, run:

```bash
python -m unittest tests.test_automation_orchestrator -v
```

- [ ] **Step 7: Commit**

```bash
git add portfolio_engine/automation/adapters.py tests/test_ibkr_flex_client.py tests/test_automation_orchestrator.py
git commit -m "feat: wire IBKR adapter to flex client" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Preserve structured fetch categories in orchestration summaries

**Files:**
- Modify: `portfolio_engine/automation/orchestrator.py`
- Modify: `tests/test_automation_orchestrator.py`

- [ ] **Step 1: Add failing structured category tests**

Add to the multi-feed tests in `tests/test_automation_orchestrator.py`:

```python
class StructuredFetchCategoryAdapter(FakeMultiFeedAdapter):
    def fetch_feed_payload(self, connection_context, feed_context, request):
        from portfolio_engine.automation.fetch_errors import BrokerFetchError
        if feed_context.feed_key == "cash":
            raise BrokerFetchError("ibkr_auth_failed", "ibkr_auth_failed")
        if feed_context.feed_key == "nav":
            raise BrokerFetchError("untrusted_category", "untrusted_category")
        return super().fetch_feed_payload(connection_context, feed_context, request)
```

Add tests:

```python
    def test_dry_run_feed_result_preserves_allowed_broker_fetch_category(self) -> None:
        db = _configured_db_with_connection_feeds(["cash"])
        adapter = StructuredFetchCategoryAdapter()

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertEqual(child.summary["feed_results"][0]["error_category"], "ibkr_auth_failed")

    def test_dry_run_unknown_broker_fetch_category_falls_back(self) -> None:
        db = _configured_db_with_connection_feeds(["nav"])
        adapter = StructuredFetchCategoryAdapter()

        self._run(_make_accounts_dry_run_request("U100"), db=db, adapter=adapter)

        child = self._find_child(db, "child-1")
        self.assertEqual(child.summary["feed_results"][0]["error_category"], "feed_fetch_failed")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.DryRunMultiFeedTests -v
```

Expected: new category tests fail because orchestrator hardcodes `feed_fetch_failed`.

- [ ] **Step 3: Implement safe category extraction**

Update imports in `portfolio_engine/automation/orchestrator.py`:

```python
from portfolio_engine.automation.fetch_errors import safe_fetch_error_category
```

In `_execute_dry_run_multi_feed()` and `_execute_load_multi_feed()`, replace:

```python
"error_category": "feed_fetch_failed",
```

inside generic feed exception blocks with:

```python
"error_category": safe_fetch_error_category(exc),
```

Keep child-level `child_error_category = "feed_fetch_failed"` when all feeds fail.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.DryRunMultiFeedTests -v
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add portfolio_engine/automation/orchestrator.py tests/test_automation_orchestrator.py
git commit -m "feat: preserve broker fetch categories" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 7: Refactor load multi-feed execution for fetch-once reuse

**Files:**
- Modify: `portfolio_engine/automation/orchestrator.py`
- Modify: `tests/test_automation_orchestrator.py`

- [ ] **Step 1: Add failing load-mode fetch-once tests**

Add helpers near existing multi-feed helpers:

```python
def _make_accounts_load_request(*external_ids: str):
    from portfolio_engine.automation.types import AutomationRunRequest
    return AutomationRunRequest(
        target_type="accounts",
        integration_key="ibkr_flex_ws",
        mode="load",
        requested_start_date=date(2024, 1, 1),
        requested_end_date=date(2024, 1, 31),
        account_external_ids=tuple(external_ids),
    )
```

Add tests:

```python
class LoadMultiFeedFetchOnceTests(unittest.TestCase):
    def _run(self, request, db, adapter):
        from portfolio_engine.automation.orchestrator import run_automation
        with mock.patch.dict(os.environ, {"SUPERFOLIO_CREDENTIAL_MASTER_KEY": _TEST_MASTER_KEY}):
            return run_automation(request, database=db, adapter=adapter)

    def test_load_fetches_each_feed_once_for_multiple_accounts(self) -> None:
        db = _configured_db_with_connection_feeds(["cash"])
        db.connection_targets = [
            _make_connection_target("account-uuid-1", "U100", connection_id="test-connection-id"),
            _make_connection_target("account-uuid-2", "U200", connection_id="test-connection-id"),
        ]
        adapter = FakeMultiFeedAdapter(payload_by_feed={"cash": _MULTI_FEED_CASH_XML})

        self._run(_make_accounts_load_request("U100", "U200"), db=db, adapter=adapter)

        self.assertEqual(adapter.fetched_feed_keys, ["cash"])

    def test_load_does_not_fetch_when_all_accounts_overlap(self) -> None:
        db = _configured_db_with_connection_feeds(["cash"])
        db.overlapping_load_accounts = {"account-uuid"}
        adapter = FakeMultiFeedAdapter(payload_by_feed={"cash": _MULTI_FEED_CASH_XML})

        self._run(_make_accounts_load_request("U100"), db=db, adapter=adapter)

        self.assertEqual(adapter.fetched_feed_keys, [])
```

If `FakeAutomationDatabase` does not have `overlapping_load_accounts`, add it and implement `has_overlapping_automation_load()` to return true when `account_id` is present.

- [ ] **Step 2: Run load tests to verify failure**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.LoadMultiFeedFetchOnceTests -v
```

Expected: first test fails because load mode fetches once per account.

- [ ] **Step 3: Refactor `_execute_load_multi_feed()`**

Replace `_execute_load_multi_feed()` with this structure, preserving existing summary aggregation code:

```python
def _execute_load_multi_feed(
    *,
    fetch_groups: list[tuple[Any, list[Any], list[tuple[str, Any]]]],
    adapter: Any,
    request: Any,
    database: Any,
    config: Any,
    job_id: str,
    child_statuses: list[str],
    child_summaries: list[dict[str, Any]],
) -> None:
    for connection_ctx, feed_ctxs, group_pairs in fetch_groups:
        if not feed_ctxs:
            failed_summary = build_child_summary(error_category="no_active_feeds")
            for child_id, _ in group_pairs:
                database.mark_automation_job_account_running(child_id)
                database.finalize_automation_job_account(
                    AutomationJobAccountFinalize(
                        automation_job_account_id=child_id,
                        status="failed",
                        ingestion_run_id=None,
                        summary=failed_summary,
                        error_message="no_active_feeds",
                    )
                )
                child_statuses.append("failed")
                child_summaries.append(failed_summary)
            continue

        eligible_pairs: list[tuple[str, Any]] = []
        account_feed_results: dict[str, list[dict[str, Any]]] = {}
        for child_id, account in group_pairs:
            database.mark_automation_job_account_running(child_id)
            if database.has_overlapping_automation_load(
                integration_key=request.integration_key,
                account_id=account.account_id,
                requested_start_date=request.requested_start_date,
                requested_end_date=request.requested_end_date,
                exclude_automation_job_id=job_id,
            ):
                overlap_summary = build_child_summary(error_category="overlapping_load_job")
                database.finalize_automation_job_account(
                    AutomationJobAccountFinalize(
                        automation_job_account_id=child_id,
                        status="failed",
                        ingestion_run_id=None,
                        summary=overlap_summary,
                        error_message="overlapping_load_job",
                    )
                )
                child_statuses.append("failed")
                child_summaries.append(overlap_summary)
            else:
                eligible_pairs.append((child_id, account))
                account_feed_results[child_id] = []

        if not eligible_pairs:
            continue

        for feed_ctx in sorted(feed_ctxs, key=lambda f: f.feed_key):
            try:
                payload = adapter.fetch_feed_payload(connection_ctx, feed_ctx, request)
            except Exception as exc:
                err_msg = sanitize_error_message(str(exc))
                for child_id, _ in eligible_pairs:
                    account_feed_results[child_id].append({
                        "feed_key": feed_ctx.feed_key,
                        "display_name": feed_ctx.display_name or feed_ctx.feed_key,
                        "status": "failed",
                        "error_category": safe_fetch_error_category(exc),
                        "record_counts": empty_record_counts(),
                        "message": err_msg,
                    })
                continue

            for child_id, account in eligible_pairs:
                try:
                    _ingestion_run_id, feed_status, feed_summary, _feed_msg = load_payload(
                        payload.xml_text,
                        database=database,
                        brokerage_code=config.brokerage_code,
                        account_external_id=account.account_external_id,
                        source_type=config.source_type,
                        source_name=payload.source_name,
                        start_date=str(request.requested_start_date),
                        end_date=str(request.requested_end_date),
                    )
                    account_feed_results[child_id].append({
                        "feed_key": feed_ctx.feed_key,
                        "display_name": feed_ctx.display_name or feed_ctx.feed_key,
                        "status": feed_status,
                        "record_counts": feed_summary["record_counts"],
                    })
                except Exception as exc:
                    err_msg = sanitize_error_message(str(exc))
                    account_feed_results[child_id].append({
                        "feed_key": feed_ctx.feed_key,
                        "display_name": feed_ctx.display_name or feed_ctx.feed_key,
                        "status": "failed",
                        "error_category": "feed_fetch_failed",
                        "record_counts": empty_record_counts(),
                        "message": err_msg,
                    })

        for child_id, _ in eligible_pairs:
            feed_results = account_feed_results[child_id]
            feed_statuses = [fr["status"] for fr in feed_results]
            if all(s == "succeeded" for s in feed_statuses):
                child_status = "succeeded"
                child_error_category: str | None = None
            elif all(s == "failed" for s in feed_statuses):
                child_status = "failed"
                child_error_category = "feed_fetch_failed"
            else:
                child_status = "partially_succeeded"
                child_error_category = None

            agg = empty_record_counts()
            for fr in feed_results:
                if fr["status"] in ("succeeded", "partially_succeeded"):
                    rc = fr.get("record_counts", {})
                    for rt in RECORD_TYPES:
                        for key in COUNT_KEYS:
                            agg[rt][key] += rc.get(rt, {}).get(key, 0)

            child_summary = build_child_summary(
                cash_supported=agg["cash_flows"]["supported"],
                cash_inserted=agg["cash_flows"]["inserted"],
                cash_duplicates=agg["cash_flows"]["duplicates"],
                cash_skipped_unknown_account=agg["cash_flows"]["skipped_unknown_account"],
                cash_skipped_inactive_account=agg["cash_flows"]["skipped_inactive_account"],
                cash_skipped_other_account=agg["cash_flows"]["skipped_other_account"],
                cash_conflicts=agg["cash_flows"]["conflicts"],
                nav_supported=agg["daily_nav_snapshots"]["supported"],
                nav_inserted=agg["daily_nav_snapshots"]["inserted"],
                nav_duplicates=agg["daily_nav_snapshots"]["duplicates"],
                nav_skipped_unknown_account=agg["daily_nav_snapshots"]["skipped_unknown_account"],
                nav_skipped_inactive_account=agg["daily_nav_snapshots"]["skipped_inactive_account"],
                nav_skipped_other_account=agg["daily_nav_snapshots"]["skipped_other_account"],
                nav_conflicts=agg["daily_nav_snapshots"]["conflicts"],
                error_category=child_error_category,
                feed_results=feed_results,
            )

            database.finalize_automation_job_account(
                AutomationJobAccountFinalize(
                    automation_job_account_id=child_id,
                    status=child_status,
                    ingestion_run_id=None,
                    summary=child_summary,
                    error_message=None,
                )
            )
            child_statuses.append(child_status)
            child_summaries.append(child_summary)
```

- [ ] **Step 4: Run load fetch-once tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.LoadMultiFeedFetchOnceTests -v
```

Expected: tests pass.

- [ ] **Step 5: Run full orchestrator tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator -v
```

Expected: all orchestrator tests pass.

- [ ] **Step 6: Commit**

```bash
git add portfolio_engine/automation/orchestrator.py tests/test_automation_orchestrator.py
git commit -m "feat: fetch IBKR feeds once in load mode" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 8: Add local-only debug XML CLI plumbing

**Files:**
- Modify: `portfolio_engine/automation/types.py`
- Modify: `portfolio_engine/automation/cli.py`
- Modify: `tests/test_automation_cli.py`
- Modify: `tests/test_automation_workflow.py`

- [ ] **Step 1: Add failing CLI tests**

Append to `tests/test_automation_cli.py`:

```python
from unittest import mock


    def test_debug_raw_xml_dir_passes_to_request_locally(self) -> None:
        calls = []

        def fake_runner(request, database):
            calls.append(request)
            return _result("succeeded")

        exit_code = run(
            [
                "--target-type", "accounts",
                "--integration", "ibkr_flex_ws",
                "--mode", "dry-run",
                "--start-date", "2026-05-01",
                "--end-date", "2026-05-14",
                "--account-external-ids", "U100",
                "--debug-raw-xml-dir", "scratch/debug-xml",
            ],
            runner=fake_runner,
            database_connector=lambda: object(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls[0].debug_raw_xml_dir, "scratch/debug-xml")

    def test_debug_raw_xml_dir_rejected_in_github_actions(self) -> None:
        stderr = StringIO()
        with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}):
            exit_code = run(
                [
                    "--target-type", "accounts",
                    "--integration", "ibkr_flex_ws",
                    "--mode", "dry-run",
                    "--start-date", "2026-05-01",
                    "--end-date", "2026-05-14",
                    "--account-external-ids", "U100",
                    "--debug-raw-xml-dir", "scratch/debug-xml",
                ],
                stderr=stderr,
                runner=lambda request, database: _result("succeeded"),
                database_connector=lambda: object(),
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("raw XML debug saves are not allowed", stderr.getvalue())
```

Add to `tests/test_automation_workflow.py`:

```python
    def test_workflow_does_not_expose_raw_xml_debug_save(self) -> None:
        text = self._text()

        self.assertNotIn("debug_raw_xml", text)
        self.assertNotIn("--debug-raw-xml-dir", text)
```

- [ ] **Step 2: Run CLI/workflow tests to verify failure**

Run:

```bash
python -m unittest tests.test_automation_cli tests.test_automation_workflow -v
```

Expected: CLI test fails because parser does not know `--debug-raw-xml-dir`.

- [ ] **Step 3: Add request field and CLI flag**

Update `AutomationRunRequest` in `portfolio_engine/automation/types.py`:

```python
@dataclass(frozen=True)
class AutomationRunRequest:
    target_type: str
    integration_key: str
    mode: str
    requested_start_date: date
    requested_end_date: date
    portfolio_name: str | None = None
    account_external_ids: tuple[str, ...] = ()
    debug_raw_xml_dir: str | None = None
```

Update imports in `portfolio_engine/automation/cli.py`:

```python
import os
```

Add parser argument:

```python
    parser.add_argument(
        "--debug-raw-xml-dir",
        default=None,
        help="Local-only private directory for raw fetched XML debug files. Rejected in GitHub Actions.",
    )
```

Before creating `AutomationRunRequest`, add:

```python
        if args.debug_raw_xml_dir and os.environ.get("GITHUB_ACTIONS") == "true":
            raise RuntimeError("raw XML debug saves are not allowed in GitHub Actions environments")
```

Pass field:

```python
            debug_raw_xml_dir=args.debug_raw_xml_dir,
```

- [ ] **Step 4: Run CLI/workflow tests**

Run:

```bash
python -m unittest tests.test_automation_cli tests.test_automation_workflow -v
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add portfolio_engine/automation/types.py portfolio_engine/automation/cli.py tests/test_automation_cli.py tests/test_automation_workflow.py
git commit -m "feat: add local raw XML debug flag" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 9: Pass debug directory from request into adapter/client

**Files:**
- Modify: `portfolio_engine/automation/adapters.py`
- Modify: `tests/test_ibkr_flex_client.py`

- [ ] **Step 1: Add failing adapter debug-dir test**

Append to `IbkrAdapterFetchTests`:

```python
    def test_fetch_feed_payload_passes_debug_dir_to_client_factory(self) -> None:
        created_debug_dirs: list[str | None] = []

        class RecordingClient(FakeIbkrClient):
            def __init__(self, debug_raw_xml_dir=None):
                super().__init__()
                created_debug_dirs.append(str(debug_raw_xml_dir) if debug_raw_xml_dir is not None else None)

        adapter = IbkrFlexWebServiceAdapter(client_factory=RecordingClient)
        connection = IntegrationConnectionContext(
            connection_id="connection-uuid",
            integration_key="ibkr_flex_ws",
            brokerage_code="IBKR",
            name="IBKR Login",
            credentials={"flex_token": SecretValue("plain-token")},
        )
        feed = IntegrationFeedContext(
            feed_id="feed-uuid",
            feed_key="primary",
            display_name="Primary",
            secrets={"query_id": SecretValue("plain-query")},
        )
        request = AutomationRunRequest(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2025, 1, 1),
            requested_end_date=date(2025, 1, 31),
            account_external_ids=("U100",),
            debug_raw_xml_dir="scratch/debug-xml",
        )

        adapter.fetch_feed_payload(connection, feed, request)

        self.assertEqual(created_debug_dirs, ["scratch/debug-xml"])
```

- [ ] **Step 2: Run adapter tests to verify failure**

Run:

```bash
python -m unittest tests.test_ibkr_flex_client.IbkrAdapterFetchTests -v
```

Expected: fails because `client_factory` is not supported.

- [ ] **Step 3: Implement client factory**

Update `IbkrFlexWebServiceAdapter.__init__()`:

```python
from pathlib import Path
from typing import Callable


class IbkrFlexWebServiceAdapter:
    def __init__(
        self,
        *,
        client: IbkrFlexWebServiceClient | None = None,
        client_factory: Callable[..., IbkrFlexWebServiceClient] = IbkrFlexWebServiceClient,
    ) -> None:
        self._client = client
        self._client_factory = client_factory

    def _client_for_request(self, request: AutomationRunRequest) -> IbkrFlexWebServiceClient:
        if self._client is not None:
            return self._client
        debug_dir = Path(request.debug_raw_xml_dir) if request.debug_raw_xml_dir else None
        return self._client_factory(debug_raw_xml_dir=debug_dir)
```

Update `fetch_feed_payload()` to call:

```python
        client = self._client_for_request(request)
        xml_text = client.fetch_report(...)
```

- [ ] **Step 4: Run adapter tests**

Run:

```bash
python -m unittest tests.test_ibkr_flex_client.IbkrAdapterFetchTests -v
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add portfolio_engine/automation/adapters.py tests/test_ibkr_flex_client.py
git commit -m "feat: pass debug XML directory to IBKR client" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 10: Update docs for implemented fetch behavior

**Files:**
- Modify: `docs/workflows/automated-ingestion.md`
- Modify: `README.md`
- Test: existing docs are not linted; use targeted grep and full Python tests after docs update.

- [ ] **Step 1: Update automated ingestion docs**

In `docs/workflows/automated-ingestion.md`:

- Replace "Adapter fetch not yet implemented" with a section that says the IBKR adapter now retrieves configured Flex Query XML through Flex Web Service v3.
- State no schedule is enabled.
- State Flex Query templates control included accounts and report sections.
- State automation dates filter locally.
- State zero-count success does not prove the query included every target account.
- Add local-only debug command example:

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

- Explain that GitHub Actions rejects raw XML debug saves.

- [ ] **Step 2: Update README limitations**

In `README.md`:

- Remove or narrow the claim that actual IBKR HTTP fetch is not implemented.
- Add a short note that automated ingestion uses encrypted connection/feed credentials and IBKR Flex Web Service v3.
- Keep privacy-first wording: raw XML is not logged or stored by default.

- [ ] **Step 3: Verify docs no longer say fetch is unimplemented**

Run:

```bash
rg "fetch not yet implemented|Adapter fetch not yet implemented|NotImplementedError" README.md docs/workflows/automated-ingestion.md
```

Expected: no stale user-facing "fetch not implemented" limitation remains. It is okay if design docs or source code comments still mention historical `NotImplementedError`.

- [ ] **Step 4: Commit docs**

```bash
git add README.md docs/workflows/automated-ingestion.md
git commit -m "docs: document IBKR flex fetch behavior" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 11: Full verification

**Files:**
- No new source files unless fixing failures found by verification.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Verify workflow does not expose debug raw XML**

Run:

```bash
rg "debug-raw-xml|debug_raw_xml|raw XML debug" .github/workflows/manual-ingestion.yml
```

Expected: no matches.

- [ ] **Step 3: Verify no obvious secret-bearing debug filenames are documented**

Run:

```bash
rg "token|query_id|ReferenceCode|reference_code" docs/workflows/automated-ingestion.md README.md
```

Expected: mentions are explanatory only; no command or filename includes a token, query id value, reference code value, or raw account data.

- [ ] **Step 4: Commit any verification fixes**

If any fixes were required:

```bash
git add <changed-files>
git commit -m "fix: address IBKR fetch verification issues" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

If no fixes were required, do not create an empty commit.

---

## Self-review checklist

- Spec coverage:
  - IBKR v3 protocol validation: Task 2 and protocol notes.
  - Request/response shape tests: Tasks 2 and 3.
  - Fetch once per connection/feed/run: Tasks 6 and 7.
  - Load overlap-before-fetch: Task 7.
  - Local date filtering only: Task 10 docs; existing parser path preserved.
  - Zero-count semantics: Task 10 docs; existing parser path preserved.
  - Structured fetch categories: Tasks 1 and 6.
  - No `SendRequest` retry: Task 3.
  - Five total `GetStatement` calls: Task 3.
  - Reference code non-persistence: Task 3 tests and Task 10 docs.
  - `httpx` injected transport: Tasks 1 and 2.
  - Raw XML debug save local-only: Tasks 4, 8, 9, 10.
  - Workflow excludes debug save: Task 8 and Task 11.
  - Safe source name: Task 5.
- Placeholder scan:
  - The only implementation warning about reusing current aggregation in Task 7 must be resolved by moving existing code during execution; do not commit that comment as source code.
- Type consistency:
  - `AutomationRunRequest.debug_raw_xml_dir` is `str | None`.
  - `IbkrFlexWebServiceClient(debug_raw_xml_dir=Path | None)` accepts a `Path`.
  - `IbkrFlexWebServiceAdapter._client_for_request()` converts request string to `Path`.
  - `BrokerFetchError.category` is allowlisted via `safe_fetch_error_category()`.
