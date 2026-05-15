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
