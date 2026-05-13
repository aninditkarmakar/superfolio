from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

from portfolio_engine.models import (
    AccountRef,
    PortfolioCashFlow,
    PortfolioDailyInput,
    PortfolioTwrRow,
    TransferBridge,
)


class PortfolioModelTests(unittest.TestCase):
    def test_portfolio_models_are_immutable_value_objects(self) -> None:
        account = AccountRef(
            brokerage_code="IBKR",
            external_id="U100",
            base_currency="USD",
            display_name="US account",
        )
        daily_input = PortfolioDailyInput(
            account=account,
            report_date=date(2026, 1, 2),
            nav_base=Decimal("100.00"),
            nav_currency="USD",
        )
        flow = PortfolioCashFlow(
            account=account,
            effective_date=date(2026, 1, 2),
            amount_base=Decimal("10.00"),
            base_currency="USD",
        )
        bridge = TransferBridge(
            source_account=account,
            destination_account=AccountRef("IBKR", "U200", "USD", "Canada account"),
            departure_date=date(2026, 1, 2),
            arrival_date=date(2026, 1, 4),
            value=Decimal("50.00"),
            currency="USD",
            note="move",
        )
        row = PortfolioTwrRow(
            report_date=date(2026, 1, 3),
            ending_nav_base=Decimal("150.00"),
            net_cash_flow_base=Decimal("0"),
            bridge_value_base=Decimal("50.00"),
            missing_nav_accounts=("IBKR:U100",),
            period_return=None,
            cumulative_twr=Decimal("0"),
        )

        self.assertEqual(daily_input.account, account)
        self.assertEqual(flow.base_currency, "USD")
        self.assertEqual(bridge.note, "move")
        self.assertEqual(row.missing_nav_accounts, ("IBKR:U100",))

        with self.assertRaises(FrozenInstanceError):
            setattr(account, "base_currency", "CAD")
        with self.assertRaises(FrozenInstanceError):
            setattr(flow, "amount_base", Decimal("99.00"))
        with self.assertRaises(FrozenInstanceError):
            setattr(daily_input, "nav_base", Decimal("0"))
        with self.assertRaises(FrozenInstanceError):
            setattr(bridge, "arrival_date", date(2026, 1, 3))
        with self.assertRaises(FrozenInstanceError):
            setattr(row, "cumulative_twr", Decimal("1"))

    def test_portfolio_cash_flow_rejects_currency_mismatch(self) -> None:
        account = AccountRef("IBKR", "U100", "USD", None)

        with self.assertRaisesRegex(ValueError, "cash-flow base currency"):
            PortfolioCashFlow(
                account=account,
                effective_date=date(2026, 1, 2),
                amount_base=Decimal("10.00"),
                base_currency="CAD",
            )

    def test_transfer_bridge_rejects_arrival_before_departure(self) -> None:
        account = AccountRef("IBKR", "U100", "USD", None)

        with self.assertRaisesRegex(ValueError, "arrival_date must be on or after departure_date"):
            TransferBridge(
                source_account=account,
                destination_account=AccountRef("IBKR", "U200", "USD", None),
                departure_date=date(2026, 1, 4),
                arrival_date=date(2026, 1, 2),
                value=Decimal("50.00"),
                currency="USD",
            )

    def test_portfolio_daily_input_rejects_currency_mismatch(self) -> None:
        account = AccountRef("IBKR", "U100", "USD", None)

        with self.assertRaisesRegex(ValueError, "NAV currency"):
            PortfolioDailyInput(
                account=account,
                report_date=date(2026, 1, 2),
                nav_base=Decimal("100.00"),
                nav_currency="CAD",
            )

    def test_transfer_bridge_rejects_non_positive_value(self) -> None:
        account = AccountRef("IBKR", "U100", "USD", None)

        with self.assertRaisesRegex(ValueError, "transfer bridge value must be positive"):
            TransferBridge(
                source_account=account,
                destination_account=AccountRef("IBKR", "U200", "USD", None),
                departure_date=date(2026, 1, 2),
                arrival_date=date(2026, 1, 4),
                value=Decimal("0"),
                currency="USD",
            )

    def test_transfer_bridge_rejects_same_source_and_destination(self) -> None:
        account = AccountRef("IBKR", "U100", "USD", None)

        with self.assertRaisesRegex(ValueError, "source and destination accounts must differ"):
            TransferBridge(
                source_account=account,
                destination_account=account,
                departure_date=date(2026, 1, 2),
                arrival_date=date(2026, 1, 4),
                value=Decimal("50.00"),
                currency="USD",
            )


from portfolio_engine.portfolio_twr import PortfolioTwrError, calculate_portfolio_twr


class PortfolioTwrCalculationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ca = AccountRef("IBKR", "UCA", "USD", "Canada")
        self.us = AccountRef("IBKR", "UUS", "USD", "US")

    def test_same_day_transfer_offsets_without_bridge(self) -> None:
        rows = calculate_portfolio_twr(
            reporting_currency="USD",
            accounts=[self.ca, self.us],
            nav_inputs=[
                PortfolioDailyInput(self.ca, date(2026, 1, 1), Decimal("100"), "USD"),
                PortfolioDailyInput(self.us, date(2026, 1, 1), Decimal("0"), "USD"),
                PortfolioDailyInput(self.ca, date(2026, 1, 2), Decimal("40"), "USD"),
                PortfolioDailyInput(self.us, date(2026, 1, 2), Decimal("60"), "USD"),
            ],
            cash_flows=[],
            transfer_bridges=[],
        )

        self.assertEqual(rows[-1].ending_nav_base, Decimal("100"))
        self.assertEqual(rows[-1].period_return, Decimal("0"))
        self.assertEqual(rows[-1].bridge_value_base, Decimal("0"))

    def test_bridge_fills_multi_day_gap(self) -> None:
        rows = calculate_portfolio_twr(
            reporting_currency="USD",
            accounts=[self.ca, self.us],
            nav_inputs=[
                PortfolioDailyInput(self.ca, date(2026, 1, 1), Decimal("100"), "USD"),
                PortfolioDailyInput(self.us, date(2026, 1, 1), Decimal("0"), "USD"),
                PortfolioDailyInput(self.ca, date(2026, 1, 2), Decimal("0"), "USD"),
                PortfolioDailyInput(self.us, date(2026, 1, 2), Decimal("0"), "USD"),
                PortfolioDailyInput(self.ca, date(2026, 1, 3), Decimal("0"), "USD"),
                PortfolioDailyInput(self.us, date(2026, 1, 3), Decimal("0"), "USD"),
                PortfolioDailyInput(self.ca, date(2026, 1, 4), Decimal("0"), "USD"),
                PortfolioDailyInput(self.us, date(2026, 1, 4), Decimal("100"), "USD"),
            ],
            cash_flows=[],
            transfer_bridges=[
                TransferBridge(
                    self.ca,
                    self.us,
                    date(2026, 1, 1),
                    date(2026, 1, 4),
                    Decimal("100"),
                    "USD",
                    "relocation",
                )
            ],
        )

        by_date = {row.report_date: row for row in rows}
        self.assertEqual(by_date[date(2026, 1, 2)].bridge_value_base, Decimal("100"))
        self.assertEqual(by_date[date(2026, 1, 3)].bridge_value_base, Decimal("100"))
        self.assertEqual(by_date[date(2026, 1, 4)].bridge_value_base, Decimal("0"))
        self.assertEqual(rows[-1].cumulative_twr, Decimal("0"))

    def test_missing_nav_is_zero_and_grouped_by_account(self) -> None:
        rows = calculate_portfolio_twr(
            reporting_currency="USD",
            accounts=[self.ca, self.us],
            nav_inputs=[
                PortfolioDailyInput(self.ca, date(2026, 1, 1), Decimal("100"), "USD"),
                PortfolioDailyInput(self.us, date(2026, 1, 1), Decimal("0"), "USD"),
                PortfolioDailyInput(self.ca, date(2026, 1, 2), Decimal("101"), "USD"),
            ],
            cash_flows=[],
            transfer_bridges=[],
        )

        self.assertEqual(rows[-1].ending_nav_base, Decimal("101"))
        self.assertEqual(rows[-1].missing_nav_accounts, ("IBKR:UUS",))

    def test_explicit_zero_nav_is_not_missing(self) -> None:
        rows = calculate_portfolio_twr(
            reporting_currency="USD",
            accounts=[self.ca, self.us],
            nav_inputs=[
                PortfolioDailyInput(self.ca, date(2026, 1, 1), Decimal("100"), "USD"),
                PortfolioDailyInput(self.us, date(2026, 1, 1), Decimal("0"), "USD"),
            ],
            cash_flows=[],
            transfer_bridges=[],
        )

        self.assertEqual(rows[0].ending_nav_base, Decimal("100"))
        self.assertEqual(rows[0].missing_nav_accounts, ())

    def test_mixed_nav_currency_fails(self) -> None:
        cad_account = AccountRef("IBKR", "UCAD", "CAD", "CAD account")
        with self.assertRaisesRegex(PortfolioTwrError, "Account IBKR:UCAD base currency CAD"):
            calculate_portfolio_twr(
                reporting_currency="USD",
                accounts=[cad_account],
                nav_inputs=[
                    PortfolioDailyInput(cad_account, date(2026, 1, 1), Decimal("100"), "CAD"),
                ],
                cash_flows=[],
                transfer_bridges=[],
            )


if __name__ == "__main__":
    unittest.main()
