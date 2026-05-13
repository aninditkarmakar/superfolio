"""Portfolio administration CLI."""

from __future__ import annotations

import argparse
import contextlib
import sys
from datetime import date
from decimal import Decimal
from typing import Callable, Protocol, TextIO

from .database import connect_database


def _decimal_arg(value: str) -> Decimal:
    try:
        return Decimal(value)
    except Exception as error:
        raise argparse.ArgumentTypeError(f"invalid decimal value: {value!r}") from error


class PortfolioAdminDatabase(Protocol):
    def __enter__(self) -> "PortfolioAdminDatabase": ...
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...
    def create_portfolio(self, *, name: str, reporting_currency: str) -> str: ...
    def attach_portfolio_account(self, *, portfolio_name: str, brokerage_code: str, account_external_id: str) -> str: ...
    def list_portfolios(self) -> list[object]: ...
    def fetch_portfolio_accounts(self, portfolio_name: str) -> list[object]: ...
    def create_portfolio_transfer_bridge(self, **kwargs: object) -> str: ...
    def fetch_portfolio_transfer_bridges(self, portfolio_name: str) -> list[object]: ...


DatabaseConnector = Callable[[str | None], PortfolioAdminDatabase]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage SuperFolio portfolios.")
    parser.add_argument("--database-url", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument("--reporting-currency", required=True)

    subparsers.add_parser("list")

    show = subparsers.add_parser("show")
    show.add_argument("--portfolio-name", required=True)

    attach = subparsers.add_parser("attach-account")
    attach.add_argument("--portfolio-name", required=True)
    attach.add_argument("--brokerage-code", required=True)
    attach.add_argument("--account-external-id", required=True)

    bridge = subparsers.add_parser("create-bridge")
    bridge.add_argument("--portfolio-name", required=True)
    bridge.add_argument("--source-brokerage-code", required=True)
    bridge.add_argument("--source-account-external-id", required=True)
    bridge.add_argument("--destination-brokerage-code", required=True)
    bridge.add_argument("--destination-account-external-id", required=True)
    bridge.add_argument("--departure-date", required=True, type=date.fromisoformat)
    bridge.add_argument("--arrival-date", required=True, type=date.fromisoformat)
    bridge.add_argument("--value", required=True, type=_decimal_arg)
    bridge.add_argument("--currency", required=True)
    bridge.add_argument("--note", default=None)

    bridges = subparsers.add_parser("list-bridges")
    bridges.add_argument("--portfolio-name", required=True)

    return parser


def run(
    argv: list[str] | None = None,
    *,
    database_connector: DatabaseConnector = connect_database,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    try:
        parser = build_parser()
        with contextlib.redirect_stderr(stderr):
            args = parser.parse_args(argv)
        with database_connector(args.database_url) as database:
            if args.command == "create":
                portfolio_id = database.create_portfolio(
                    name=args.name,
                    reporting_currency=args.reporting_currency,
                )
                stdout.write(f"Created portfolio: {portfolio_id}\n")
            elif args.command == "list":
                for portfolio in database.list_portfolios():
                    stdout.write(f"{portfolio.name}\t{portfolio.reporting_currency}\t{portfolio.is_active}\n")
            elif args.command == "show":
                for account in database.fetch_portfolio_accounts(args.portfolio_name):
                    stdout.write(f"{account.label}\t{account.base_currency}\t{account.display_name or ''}\n")
            elif args.command == "attach-account":
                membership_id = database.attach_portfolio_account(
                    portfolio_name=args.portfolio_name,
                    brokerage_code=args.brokerage_code,
                    account_external_id=args.account_external_id,
                )
                stdout.write(f"Attached account: {membership_id}\n")
            elif args.command == "create-bridge":
                bridge_id = database.create_portfolio_transfer_bridge(
                    portfolio_name=args.portfolio_name,
                    source_brokerage_code=args.source_brokerage_code,
                    source_account_external_id=args.source_account_external_id,
                    destination_brokerage_code=args.destination_brokerage_code,
                    destination_account_external_id=args.destination_account_external_id,
                    departure_date=args.departure_date,
                    arrival_date=args.arrival_date,
                    value=args.value,
                    currency=args.currency,
                    note=args.note,
                )
                stdout.write(f"Created transfer bridge: {bridge_id}\n")
            elif args.command == "list-bridges":
                for bridge in database.fetch_portfolio_transfer_bridges(args.portfolio_name):
                    stdout.write(
                        f"{bridge.source_account.label}->{bridge.destination_account.label}\t"
                        f"{bridge.departure_date}..{bridge.arrival_date}\t"
                        f"{bridge.value} {bridge.currency}\t{bridge.note or ''}\n"
                    )
        return 0
    except Exception as error:
        stderr.write(f"Error: {error}\n")
        return 1


def main(argv: list[str] | None = None) -> int:
    return run(argv)
