from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from uuid import uuid4
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

_SAFE_FILENAME_CHARS_RE = re.compile(r"[^A-Za-z0-9_.-]+")


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

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpxTransport:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


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

    def close(self) -> None:
        close = getattr(self._transport, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> IbkrFlexWebServiceClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

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

    def _send_request(self, *, token: str, query_id: str) -> str:
        try:
            response = self._transport.get(
                f"{IBKR_FLEX_BASE_URL}/SendRequest",
                params={"t": token, "q": query_id, "v": IBKR_FLEX_VERSION},
                headers={"User-Agent": IBKR_FLEX_USER_AGENT},
                timeout=HTTP_TIMEOUT_SECONDS,
            )
        except Exception:
            raise BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed") from None
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
            except Exception:
                last_error = BrokerFetchError("ibkr_fetch_failed", "ibkr_fetch_failed")
                if attempt == GETSTATEMENT_TOTAL_ATTEMPTS - 1:
                    raise last_error from None

            if attempt < GETSTATEMENT_TOTAL_ATTEMPTS - 1:
                self._sleep(GETSTATEMENT_RETRY_WAIT_SECONDS)

        raise last_error or BrokerFetchError("ibkr_report_not_ready", "ibkr_report_not_ready")


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


def _safe_filename_part(value: str) -> str:
    safe = _SAFE_FILENAME_CHARS_RE.sub("-", value.strip())
    return safe.strip("-") or "unknown"
