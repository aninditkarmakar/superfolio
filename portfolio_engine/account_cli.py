"""Command-line helpers for registering brokerage accounts."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Callable, Protocol, TextIO

from portfolio_engine.database import AccountRegistration, connect_database


class AccountCliError(RuntimeError):
    """Raised when account CLI input is missing or invalid."""


class AccountDatabase(Protocol):
    def __enter__(self) -> "AccountDatabase": ...
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...
    def register_account(self, registration: AccountRegistration) -> str: ...


AdapterFactory = Callable[[str | None], AccountDatabase]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    flag: str
    prompt: str
    required: bool


FIELD_SPECS = (
    FieldSpec("brokerage_code", "--brokerage-code", "Brokerage code", True),
    FieldSpec("external_id", "--external-id", "External ID", True),
    FieldSpec("account_type", "--account-type", "Account type", True),
    FieldSpec("base_currency", "--base-currency", "Base currency", True),
    FieldSpec("display_name", "--display-name", "Display name", False),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register a brokerage account for ingestion.")
    parser.add_argument("--brokerage-code", help="Brokerage code, for example IBKR.")
    parser.add_argument("--external-id", help="Brokerage account identifier, for example U100.")
    parser.add_argument("--account-type", help="Account type label, for example Individual.")
    parser.add_argument("--base-currency", help="Account base currency, for example USD.")
    parser.add_argument("--display-name", help="Optional friendly account display name.")
    parser.add_argument(
        "--database-url",
        help="Optional PostgreSQL connection URL. Defaults to DATABASE_URL via the DB adapter.",
    )
    return parser


def run(
    argv: list[str] | None = None,
    *,
    adapter_factory: AdapterFactory = connect_database,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    interactive: bool | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    is_interactive = stdin.isatty() if interactive is None else interactive

    try:
        registration = resolve_registration(
            brokerage_code=args.brokerage_code,
            external_id=args.external_id,
            account_type=args.account_type,
            base_currency=args.base_currency,
            display_name=args.display_name,
            stdin=stdin,
            stdout=stdout,
            interactive=is_interactive,
        )
        with adapter_factory(args.database_url) as database:
            account_id = database.register_account(registration)
    except Exception as error:
        stderr.write(f"Error: {error}\n")
        return 1

    _print_success(account_id, registration, stdout)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(argv)


def resolve_registration(
    *,
    brokerage_code: str | None,
    external_id: str | None,
    account_type: str | None,
    base_currency: str | None,
    display_name: str | None,
    stdin: TextIO,
    stdout: TextIO,
    interactive: bool,
) -> AccountRegistration:
    values = {
        "brokerage_code": _clean_required_candidate(brokerage_code),
        "external_id": _clean_required_candidate(external_id),
        "account_type": _clean_required_candidate(account_type),
        "base_currency": _clean_required_candidate(base_currency),
        "display_name": _clean_optional_candidate(display_name),
    }

    missing_required = [
        spec.flag
        for spec in FIELD_SPECS
        if spec.required and values[spec.name] is None
    ]
    if missing_required and not interactive:
        joined = ", ".join(missing_required)
        raise AccountCliError(f"Missing required option(s): {joined}")

    if interactive:
        for spec in FIELD_SPECS:
            if values[spec.name] is not None:
                continue
            if spec.required:
                values[spec.name] = _prompt_required(spec.prompt, stdin, stdout)
            else:
                values[spec.name] = _prompt_optional(spec.prompt, stdin, stdout)

    return AccountRegistration(
        brokerage_code=_required_value(values["brokerage_code"], "--brokerage-code"),
        external_id=_required_value(values["external_id"], "--external-id"),
        account_type=_required_value(values["account_type"], "--account-type"),
        base_currency=_required_value(values["base_currency"], "--base-currency"),
        display_name=values["display_name"],
    )


def _clean_required_candidate(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _clean_optional_candidate(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _prompt_required(prompt: str, stdin: TextIO, stdout: TextIO) -> str:
    while True:
        stdout.write(f"{prompt}: ")
        stdout.flush()
        value = stdin.readline()
        if value == "":
            raise AccountCliError(f"{prompt} is required.")
        stripped = value.strip()
        if stripped:
            return stripped
        stdout.write(f"{prompt} value is required.\n")


def _prompt_optional(prompt: str, stdin: TextIO, stdout: TextIO) -> str | None:
    stdout.write(f"{prompt} (optional): ")
    stdout.flush()
    value = stdin.readline()
    if value == "":
        return None
    stripped = value.strip()
    return stripped or None


def _required_value(value: str | None, flag: str) -> str:
    if value is None:
        raise AccountCliError(f"Missing required option: {flag}")
    return value


def _print_success(account_id: str, registration: AccountRegistration, stdout: TextIO) -> None:
    stdout.write(f"Registered account: {account_id}\n")
    stdout.write(f"Brokerage: {registration.brokerage_code}\n")
    stdout.write(f"External ID: {registration.external_id}\n")
    stdout.write(f"Account type: {registration.account_type}\n")
    stdout.write(f"Base currency: {registration.base_currency}\n")
    stdout.write(f"Display name: {registration.display_name or '(none)'}\n")
