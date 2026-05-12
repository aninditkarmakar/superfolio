"""Command-line helpers for registering brokerage accounts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TextIO

from portfolio_engine.database import AccountRegistration


class AccountCliError(RuntimeError):
    """Raised when account CLI input is missing or invalid."""


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
