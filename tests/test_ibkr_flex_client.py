from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
        self.assertIsNone(ctx.exception.__cause__)

    def test_getstatement_network_failure_is_retried_then_succeeds(self) -> None:
        transport = FakeTransport(
            [
                FakeHttpResponse(200, """<FlexStatementResponse><Status>Success</Status><ReferenceCode>ref-secret</ReferenceCode></FlexStatementResponse>"""),
                OSError("reference=ref-secret token=token-secret"),
                FakeHttpResponse(200, VALID_FLEX_XML),
            ]
        )
        sleeps: list[float] = []
        client = IbkrFlexWebServiceClient(transport=transport, sleep=sleeps.append)

        result = client.fetch_report(token="token-secret", query_id="query-secret")

        self.assertEqual(result, VALID_FLEX_XML)
        get_calls = [c for c in transport.calls if str(c["url"]).endswith("/GetStatement")]
        self.assertEqual(len(get_calls), 2)
        self.assertEqual(sleeps, [20.0, 20.0])

    def test_getstatement_final_network_failure_has_no_cause(self) -> None:
        """All GetStatement attempts fail with network errors; raised BrokerFetchError must not chain the OSError."""
        transport = FakeTransport(
            [
                FakeHttpResponse(200, """<FlexStatementResponse><Status>Success</Status><ReferenceCode>ref-secret</ReferenceCode></FlexStatementResponse>"""),
            ] + [OSError("reference=ref-secret token=token-secret") for _ in range(5)]
        )
        client = IbkrFlexWebServiceClient(transport=transport, sleep=lambda seconds: None)

        with self.assertRaises(BrokerFetchError) as ctx:
            client.fetch_report(token="token-secret", query_id="query-secret")

        self.assertEqual(ctx.exception.category, "ibkr_fetch_failed")
        self.assertIsNone(ctx.exception.__cause__)
        self.assertNotIn("ref-secret", str(ctx.exception))
        self.assertNotIn("token-secret", str(ctx.exception))

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

    def test_debug_save_disk_write_failure_raises_broker_fetch_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            not_a_dir = tmp_path / "not-a-dir"
            not_a_dir.write_text("I am a file, not a directory", encoding="utf-8")
            transport = FakeTransport(
                [
                    FakeHttpResponse(200, """<FlexStatementResponse><Status>Success</Status><ReferenceCode>secret-ref</ReferenceCode></FlexStatementResponse>"""),
                    FakeHttpResponse(200, VALID_FLEX_XML),
                ]
            )
            client = IbkrFlexWebServiceClient(
                transport=transport,
                sleep=lambda seconds: None,
                debug_raw_xml_dir=not_a_dir,
            )

            with self.assertRaises(BrokerFetchError) as ctx:
                client.fetch_report(token="secret-token", query_id="secret-query", connection_id="conn", feed_key="feed")

            self.assertEqual(ctx.exception.category, "ibkr_fetch_failed")
            self.assertIsNone(ctx.exception.__cause__)
            self.assertNotIn("secret-token", str(ctx.exception))
            self.assertNotIn("secret-query", str(ctx.exception))
            self.assertNotIn("secret-ref", str(ctx.exception))
            self.assertNotIn(VALID_FLEX_XML, str(ctx.exception))

    def test_debug_save_github_actions_guard_is_checked_at_fetch_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transport = FakeTransport(
                [
                    FakeHttpResponse(200, """<FlexStatementResponse><Status>Success</Status><ReferenceCode>ref-123</ReferenceCode></FlexStatementResponse>"""),
                    FakeHttpResponse(200, VALID_FLEX_XML),
                ]
            )
            client = IbkrFlexWebServiceClient(
                transport=transport,
                sleep=lambda seconds: None,
                debug_raw_xml_dir=Path(tmp),
            )

            with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
                with self.assertRaisesRegex(RuntimeError, "raw XML debug saves are not allowed"):
                    client.fetch_report(token="token", query_id="query", connection_id="conn", feed_key="feed")


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


if __name__ == "__main__":
    unittest.main()
