from __future__ import annotations

import unittest
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


if __name__ == "__main__":
    unittest.main()
