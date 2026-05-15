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


from dataclasses import dataclass

from portfolio_engine.automation.ibkr_flex_client import (
    IBKR_FLEX_BASE_URL,
    IBKR_FLEX_USER_AGENT,
    HttpxTransport,
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


class FakeHttpxClient:
    """Minimal fake for httpx.Client that tracks whether close() was called."""

    def __init__(self) -> None:
        self.closed = False

    def get(self, url: str, **kwargs: object) -> FakeHttpResponse:
        return FakeHttpResponse(200, "")

    def close(self) -> None:
        self.closed = True


class CloseableTransport:
    """A fake transport that exposes close() — simulates a real closeable transport."""

    def __init__(self) -> None:
        self.closed = False

    def get(self, url: str, *, params: dict[str, str], headers: dict[str, str], timeout: float) -> FakeHttpResponse:
        return FakeHttpResponse(200, "")

    def close(self) -> None:
        self.closed = True


class HttpxTransportLifecycleTests(unittest.TestCase):
    def test_close_closes_underlying_client(self) -> None:
        fake_client = FakeHttpxClient()
        transport = HttpxTransport(client=fake_client)  # type: ignore[arg-type]

        transport.close()

        self.assertTrue(fake_client.closed)

    def test_context_manager_closes_client_on_exit(self) -> None:
        fake_client = FakeHttpxClient()
        transport = HttpxTransport(client=fake_client)  # type: ignore[arg-type]

        with transport:
            self.assertFalse(fake_client.closed)

        self.assertTrue(fake_client.closed)

    def test_context_manager_returns_self(self) -> None:
        fake_client = FakeHttpxClient()
        transport = HttpxTransport(client=fake_client)  # type: ignore[arg-type]

        with transport as ctx:
            self.assertIs(ctx, transport)


class IbkrFlexClientLifecycleTests(unittest.TestCase):
    def test_close_calls_transport_close_when_available(self) -> None:
        transport = CloseableTransport()
        client = IbkrFlexWebServiceClient(transport=transport)

        client.close()

        self.assertTrue(transport.closed)

    def test_close_does_not_raise_when_transport_has_no_close(self) -> None:
        transport = FakeTransport([])  # FakeTransport has no close()
        client = IbkrFlexWebServiceClient(transport=transport)

        # Must not raise even though transport lacks close()
        client.close()

    def test_context_manager_closes_transport_on_exit(self) -> None:
        transport = CloseableTransport()
        client = IbkrFlexWebServiceClient(transport=transport)

        with client:
            self.assertFalse(transport.closed)

        self.assertTrue(transport.closed)

    def test_context_manager_returns_self(self) -> None:
        transport = CloseableTransport()
        client = IbkrFlexWebServiceClient(transport=transport)

        with client as ctx:
            self.assertIs(ctx, client)


if __name__ == "__main__":
    unittest.main()
