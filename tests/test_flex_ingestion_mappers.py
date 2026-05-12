from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from portfolio_engine.ingestion.flex_mappers import (
    FlexCashTransactionPayload,
    FlexDailyNavPayload,
    build_cash_transaction_dedupe_key,
    build_daily_nav_dedupe_key,
    decimal_to_payload,
    flex_date_to_payload,
)


class FlexIngestionMapperTests(unittest.TestCase):
    def test_flex_date_to_payload_formats_iso_date(self) -> None:
        self.assertEqual(flex_date_to_payload("20260512"), "2026-05-12")

    def test_decimal_to_payload_preserves_decimal_string(self) -> None:
        self.assertEqual(decimal_to_payload(Decimal("123.4500")), "123.4500")

    def test_cash_dedupe_key_prefers_transaction_id(self) -> None:
        raw = {
            "accountId": "U100",
            "transactionID": "987654",
            "reportDate": "20260512",
            "currency": "USD",
            "amount": "10.00",
            "description": "Deposit",
        }

        self.assertEqual(
            build_cash_transaction_dedupe_key(raw),
            "IBKR:U100:CASH_TRANSACTION:987654",
        )

    def test_cash_dedupe_key_has_stable_fallback_without_transaction_id(self) -> None:
        raw = {
            "accountId": "U100",
            "reportDate": "20260512",
            "currency": "USD",
            "amount": "10.00",
            "description": "Deposit",
        }

        self.assertEqual(
            build_cash_transaction_dedupe_key(raw),
            "IBKR:U100:CASH_TRANSACTION:20260512:USD:10.00:Deposit",
        )

    def test_daily_nav_dedupe_key_uses_account_and_report_date(self) -> None:
        raw = {"accountId": "U100", "reportDate": "20260512"}

        self.assertEqual(
            build_daily_nav_dedupe_key(raw),
            "IBKR:U100:DAILY_NAV:20260512",
        )

    def test_payload_dataclasses_are_available_for_type_boundaries(self) -> None:
        cash_payload = FlexCashTransactionPayload(
            account_external_id="U100",
            external_record_id="987654",
            dedupe_key="IBKR:U100:CASH_TRANSACTION:987654",
            source_report_date="2026-05-12",
            source_currency="USD",
            raw_payload={"accountId": "U100"},
            flow_date="2026-05-12",
            cash_flow_type="Deposits/Withdrawals",
            currency="USD",
            amount="10.00",
            amount_base="13.5000",
            fx_rate_to_base="1.3500",
            description="Deposit",
        )
        nav_payload = FlexDailyNavPayload(
            account_external_id="U100",
            external_record_id="NAV:U100:20260512",
            dedupe_key="IBKR:U100:DAILY_NAV:20260512",
            source_report_date="2026-05-12",
            source_currency="USD",
            raw_payload={"accountId": "U100"},
            snapshot_date="2026-05-12",
            base_currency="USD",
            nav_base="1000.00",
        )

        self.assertEqual(cash_payload.flow_date, "2026-05-12")
        self.assertEqual(nav_payload.nav_base, "1000.00")


if __name__ == "__main__":
    unittest.main()
