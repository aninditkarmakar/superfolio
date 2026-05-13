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


if __name__ == "__main__":
    unittest.main()
