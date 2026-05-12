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
            "dateTime": "20260512;143000",
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
            "dateTime": "20260512;143000",
            "currency": "USD",
            "amount": "10.00",
            "description": "Deposit",
        }

        self.assertEqual(
            build_cash_transaction_dedupe_key(raw),
            "IBKR:U100:CASH_TRANSACTION:20260512:20260512;143000:USD:10.00",
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

    def test_payload_dataclasses_are_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

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

        with self.assertRaises(FrozenInstanceError):
            cash_payload.flow_date = "2026-05-13"
        with self.assertRaises(FrozenInstanceError):
            nav_payload.nav_base = "2000.00"

    def test_map_cash_transactions_uses_report_date_as_flow_date(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U100" fromDate="20260501" toDate="20260531">
      <CashTransactions>
        <CashTransaction accountId="U100" transactionID="987654" reportDate="20260512"
          dateTime="20260510;120000" settleDate="20260513" availableForTradingDate="20260514"
          type="Deposits/Withdrawals" currency="CAD" amount="100.00" fxRateToBase="0.730000"
          description="Synthetic deposit" />
      </CashTransactions>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

        from portfolio_engine.ingestion.flex_mappers import (
            map_cash_transactions_from_flex_xml_text,
        )

        records = map_cash_transactions_from_flex_xml_text(xml)

        self.assertEqual(
            records,
            [
                {
                    "account_external_id": "U100",
                    "external_record_id": "987654",
                    "dedupe_key": "IBKR:U100:CASH_TRANSACTION:987654",
                    "source_report_date": "2026-05-12",
                    "source_currency": "CAD",
                    "raw_payload": {
                        "accountId": "U100",
                        "transactionID": "987654",
                        "reportDate": "20260512",
                        "dateTime": "20260510;120000",
                        "settleDate": "20260513",
                        "availableForTradingDate": "20260514",
                        "type": "Deposits/Withdrawals",
                        "currency": "CAD",
                        "amount": "100.00",
                        "fxRateToBase": "0.730000",
                        "description": "Synthetic deposit",
                    },
                    "flow_date": "2026-05-12",
                    "cash_flow_type": "Deposits/Withdrawals",
                    "currency": "CAD",
                    "amount": "100.00",
                    "amount_base": "73.00000000",
                    "fx_rate_to_base": "0.730000",
                    "description": "Synthetic deposit",
                }
            ],
        )

    def test_map_cash_transactions_filters_to_deposits_withdrawals_by_default(
        self,
    ) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <CashTransactions>
    <CashTransaction accountId="U100" transactionID="1" reportDate="20260512"
      type="Deposits/Withdrawals" currency="USD" amount="100.00" fxRateToBase="1"
      description="Synthetic deposit" />
    <CashTransaction accountId="U100" transactionID="2" reportDate="20260512"
      type="Dividends" currency="USD" amount="5.00" fxRateToBase="1"
      description="Synthetic dividend" />
  </CashTransactions>
</FlexQueryResponse>
"""

        from portfolio_engine.ingestion.flex_mappers import (
            map_cash_transactions_from_flex_xml_text,
        )

        records = map_cash_transactions_from_flex_xml_text(xml)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["external_record_id"], "1")

    def test_map_cash_transactions_uses_datetime_fallback_without_transaction_id(
        self,
    ) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <CashTransactions>
    <CashTransaction accountId="U100" reportDate="20260512" dateTime="20260512;143000"
      type="Deposits/Withdrawals" currency="USD" amount="10.00" fxRateToBase="1" />
  </CashTransactions>
</FlexQueryResponse>
"""

        from portfolio_engine.ingestion.flex_mappers import (
            map_cash_transactions_from_flex_xml_text,
        )

        records = map_cash_transactions_from_flex_xml_text(xml)

        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0]["external_record_id"])
        self.assertIsNone(records[0]["description"])
        self.assertEqual(
            records[0]["dedupe_key"],
            "IBKR:U100:CASH_TRANSACTION:20260512:20260512;143000:USD:10.00",
        )
        self.assertEqual(records[0]["flow_date"], "2026-05-12")

    def test_map_cash_transactions_requires_datetime_without_transaction_id(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <CashTransactions>
    <CashTransaction accountId="U100" reportDate="20260512"
      type="Deposits/Withdrawals" currency="USD" amount="10.00" fxRateToBase="1" />
  </CashTransactions>
</FlexQueryResponse>
"""

        from portfolio_engine.ingestion.flex_mappers import (
            map_cash_transactions_from_flex_xml_text,
        )

        with self.assertRaisesRegex(
            ValueError, "missing required Flex attribute: dateTime"
        ):
            map_cash_transactions_from_flex_xml_text(xml)

    def test_map_cash_transactions_allows_date_range_filter(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <CashTransactions>
    <CashTransaction accountId="U100" transactionID="1" reportDate="20260501"
      type="Deposits/Withdrawals" currency="USD" amount="100.00" fxRateToBase="1"
      description="Before range" />
    <CashTransaction accountId="U100" transactionID="2" reportDate="20260512"
      type="Deposits/Withdrawals" currency="USD" amount="200.00" fxRateToBase="1"
      description="Inside range" />
  </CashTransactions>
</FlexQueryResponse>
"""

        from portfolio_engine.ingestion.flex_mappers import (
            map_cash_transactions_from_flex_xml_text,
        )

        records = map_cash_transactions_from_flex_xml_text(
            xml,
            start_date=date(2026, 5, 10),
            end_date=date(2026, 5, 20),
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["external_record_id"], "2")

    def test_map_daily_nav_snapshots_maps_total_to_nav_base(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U100" fromDate="20260501" toDate="20260531">
      <EquitySummaryInBase>
        <EquitySummaryByReportDateInBase accountId="U100" reportDate="20260512"
          currency="USD" total="12345.6700" cash="100.00" stock="12245.67" />
      </EquitySummaryInBase>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

        from portfolio_engine.ingestion.flex_mappers import map_daily_nav_snapshots_from_flex_xml_text

        records = map_daily_nav_snapshots_from_flex_xml_text(xml)

        self.assertEqual(
            records,
            [
                {
                    "account_external_id": "U100",
                    "external_record_id": "NAV:U100:20260512",
                    "dedupe_key": "IBKR:U100:DAILY_NAV:20260512",
                    "source_report_date": "2026-05-12",
                    "source_currency": "USD",
                    "raw_payload": {
                        "accountId": "U100",
                        "reportDate": "20260512",
                        "currency": "USD",
                        "total": "12345.6700",
                        "cash": "100.00",
                        "stock": "12245.67",
                    },
                    "snapshot_date": "2026-05-12",
                    "base_currency": "USD",
                    "nav_base": "12345.6700",
                }
            ],
        )

    def test_map_daily_nav_snapshots_allows_date_range_filter(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <EquitySummaryInBase>
    <EquitySummaryByReportDateInBase accountId="U100" reportDate="20260501"
      currency="USD" total="100.00" />
    <EquitySummaryByReportDateInBase accountId="U100" reportDate="20260512"
      currency="USD" total="200.00" />
  </EquitySummaryInBase>
</FlexQueryResponse>
"""

        from portfolio_engine.ingestion.flex_mappers import map_daily_nav_snapshots_from_flex_xml_text

        records = map_daily_nav_snapshots_from_flex_xml_text(
            xml,
            start_date=date(2026, 5, 10),
            end_date=date(2026, 5, 20),
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["snapshot_date"], "2026-05-12")

    def test_map_daily_nav_snapshots_raises_for_missing_total(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <EquitySummaryInBase>
    <EquitySummaryByReportDateInBase accountId="U100" reportDate="20260512"
      currency="USD" />
  </EquitySummaryInBase>
</FlexQueryResponse>
"""

        from portfolio_engine.ingestion.flex_mappers import map_daily_nav_snapshots_from_flex_xml_text

        with self.assertRaisesRegex(ValueError, "missing required Flex attribute: total"):
            map_daily_nav_snapshots_from_flex_xml_text(xml)

    def test_map_cash_transactions_raises_for_missing_report_date(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <CashTransactions>
    <CashTransaction accountId="U100" transactionID="1"
      type="Deposits/Withdrawals" currency="USD" amount="100.00" fxRateToBase="1"
      description="Missing date" />
  </CashTransactions>
</FlexQueryResponse>
"""

        from portfolio_engine.ingestion.flex_mappers import (
            map_cash_transactions_from_flex_xml_text,
        )

        with self.assertRaisesRegex(
            ValueError, "missing required Flex attribute: reportDate"
        ):
            map_cash_transactions_from_flex_xml_text(xml)

    def test_scratch_cash_flow_file_shape_when_available(self) -> None:
        from pathlib import Path

        from portfolio_engine.ingestion.flex_mappers import (
            map_cash_transactions_from_flex_xml_file,
        )

        sample_path = Path("scratch/Cash_Flows.xml")
        if not sample_path.exists():
            self.skipTest("scratch/Cash_Flows.xml is not available")

        records = map_cash_transactions_from_flex_xml_file(sample_path)

        self.assertGreater(len(records), 0)
        first = records[0]
        self.assertIn("account_external_id", first)
        self.assertIn("dedupe_key", first)
        self.assertIn("flow_date", first)
        self.assertIn("amount_base", first)
        self.assertIn("raw_payload", first)

    def test_scratch_daily_nav_file_shape_when_available(self) -> None:
        from pathlib import Path

        from portfolio_engine.ingestion.flex_mappers import (
            map_daily_nav_snapshots_from_flex_xml_file,
        )

        sample_path = Path("scratch/Daily_NAV.xml")
        if not sample_path.exists():
            self.skipTest("scratch/Daily_NAV.xml is not available")

        records = map_daily_nav_snapshots_from_flex_xml_file(sample_path)

        self.assertGreater(len(records), 0)
        first = records[0]
        self.assertIn("account_external_id", first)
        self.assertIn("dedupe_key", first)
        self.assertIn("snapshot_date", first)
        self.assertIn("nav_base", first)
        self.assertIn("raw_payload", first)


if __name__ == "__main__":
    unittest.main()
