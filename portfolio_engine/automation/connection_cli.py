from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from io import StringIO
from typing import Any

from portfolio_engine.automation.credentials import (
    CredentialMasterKeyError,
    encrypt_secret,
    load_master_key,
)
from portfolio_engine.database import (
    AccountIntegrationAssignmentSet,
    DatabaseConfigurationError,
    IntegrationConnectionCreate,
    IntegrationCredentialSet,
    IntegrationFeedCreate,
)

_KNOWN_COMMANDS = {
    "create",
    "set-credential",
    "add-feed",
    "assign-account",
    "assign-accounts",
    "assign-portfolio",
    "validate-assignments",
    "list-connections",
    "list-feeds",
}

_SANITIZED_ERROR = "a database error occurred"


def _print_database_error(exc: Exception, *, stderr: Any) -> None:
    if isinstance(exc, DatabaseConfigurationError):
        print(f"error: {exc}", file=stderr)
        return
    print(_SANITIZED_ERROR, file=stderr)


def run(
    argv: list[str],
    *,
    stdout: Any = None,
    stderr: Any = None,
    database_connector: Callable[[], Any],
    environ: dict[str, str],
) -> int:
    if stdout is None:
        stdout = sys.stdout
    if stderr is None:
        stderr = sys.stderr

    if not argv:
        print("error: no command provided", file=stderr)
        return 1

    command = argv[0]
    if command not in _KNOWN_COMMANDS:
        print(f"error: unknown command {command!r}", file=stderr)
        return 1

    try:
        if command == "create":
            return _cmd_create(argv[1:], stdout=stdout, stderr=stderr, database_connector=database_connector)
        elif command == "set-credential":
            return _cmd_set_credential(argv[1:], stdout=stdout, stderr=stderr, database_connector=database_connector, environ=environ)
        elif command == "add-feed":
            return _cmd_add_feed(argv[1:], stdout=stdout, stderr=stderr, database_connector=database_connector)
        elif command == "assign-account":
            return _cmd_assign_account(argv[1:], stdout=stdout, stderr=stderr, database_connector=database_connector)
        elif command == "assign-accounts":
            return _cmd_assign_accounts(argv[1:], stdout=stdout, stderr=stderr, database_connector=database_connector)
        elif command == "assign-portfolio":
            return _cmd_assign_portfolio(argv[1:], stdout=stdout, stderr=stderr, database_connector=database_connector)
        elif command == "validate-assignments":
            return _cmd_validate_assignments(argv[1:], stdout=stdout, stderr=stderr, database_connector=database_connector)
        elif command == "list-connections":
            return _cmd_list_connections(argv[1:], stdout=stdout, stderr=stderr, database_connector=database_connector)
        elif command == "list-feeds":
            return _cmd_list_feeds(argv[1:], stdout=stdout, stderr=stderr, database_connector=database_connector)
    except SystemExit:
        raise
    except Exception as exc:
        _print_database_error(exc, stderr=stderr)
        return 1

    return 0  # unreachable but satisfies type checker


def _parse_args(parser: argparse.ArgumentParser, args: list[str], *, stderr: Any) -> argparse.Namespace | None:
    buf = StringIO()
    parser.print_usage = lambda file=None: None  # suppress default usage prints
    try:
        return parser.parse_args(args)
    except SystemExit:
        print(f"error: invalid arguments for this command", file=stderr)
        return None


def _cmd_create(args: list[str], *, stdout: Any, stderr: Any, database_connector: Callable[[], Any]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--integration", required=True)
    parser.add_argument("--brokerage-code", required=True)
    parser.add_argument("--name", required=True)
    ns = _parse_args(parser, args, stderr=stderr)
    if ns is None:
        return 1

    request = IntegrationConnectionCreate(
        integration_key=ns.integration,
        brokerage_code=ns.brokerage_code,
        name=ns.name,
    )
    try:
        db = database_connector()
        connection_id = db.create_integration_connection(request)
    except Exception as exc:
        _print_database_error(exc, stderr=stderr)
        return 1

    print(f"created connection: {connection_id}", file=stdout)
    return 0


def _cmd_set_credential(
    args: list[str],
    *,
    stdout: Any,
    stderr: Any,
    database_connector: Callable[[], Any],
    environ: dict[str, str],
) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--connection-id", required=True)
    parser.add_argument("--credential-name", required=True)
    parser.add_argument("--value-from-env", required=True, dest="value_from_env",
                        metavar="VARNAME", help="Name of env var containing the plaintext credential")
    ns = _parse_args(parser, args, stderr=stderr)
    if ns is None:
        return 1

    plaintext = environ.get(ns.value_from_env)
    if not plaintext:
        print(f"error: env var {ns.value_from_env!r} is missing or blank", file=stderr)
        return 1

    raw_key = environ.get("SUPERFOLIO_CREDENTIAL_MASTER_KEY")
    try:
        master_key = load_master_key(raw_key)
    except CredentialMasterKeyError as exc:
        print(f"error: master key error: {exc}", file=stderr)
        return 1

    ciphertext = encrypt_secret(plaintext, master_key)
    request = IntegrationCredentialSet(
        connection_id=ns.connection_id,
        credential_name=ns.credential_name,
        ciphertext=ciphertext,
        encryption_key_id=master_key.key_id,
        encryption_version=1,
    )
    try:
        db = database_connector()
        credential_id = db.set_integration_credential(request)
    except Exception as exc:
        _print_database_error(exc, stderr=stderr)
        return 1

    print(f"set credential: {credential_id}", file=stdout)
    return 0


def _cmd_add_feed(args: list[str], *, stdout: Any, stderr: Any, database_connector: Callable[[], Any]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--connection-id", required=True)
    parser.add_argument("--feed-key", required=True)
    parser.add_argument("--display-name", default=None)
    ns = _parse_args(parser, args, stderr=stderr)
    if ns is None:
        return 1

    request = IntegrationFeedCreate(
        connection_id=ns.connection_id,
        feed_key=ns.feed_key,
        display_name=ns.display_name,
    )
    try:
        db = database_connector()
        feed_id = db.create_integration_feed(request)
    except Exception as exc:
        _print_database_error(exc, stderr=stderr)
        return 1

    print(f"created feed: {feed_id}", file=stdout)
    return 0


def _cmd_assign_account(args: list[str], *, stdout: Any, stderr: Any, database_connector: Callable[[], Any]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--connection-id", required=True)
    parser.add_argument("--brokerage-code", required=True)
    parser.add_argument("--account-external-id", required=True)
    ns = _parse_args(parser, args, stderr=stderr)
    if ns is None:
        return 1

    request = AccountIntegrationAssignmentSet(
        brokerage_code=ns.brokerage_code,
        account_external_id=ns.account_external_id,
        connection_id=ns.connection_id,
    )
    try:
        db = database_connector()
        assignment_id = db.set_account_integration_assignment(request)
    except Exception as exc:
        _print_database_error(exc, stderr=stderr)
        return 1

    print(f"assigned account: {assignment_id}", file=stdout)
    return 0


def _cmd_assign_accounts(args: list[str], *, stdout: Any, stderr: Any, database_connector: Callable[[], Any]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--connection-id", required=True)
    parser.add_argument("--brokerage-code", required=True)
    parser.add_argument("--account-external-id", action="append", required=True, dest="account_external_ids")
    ns = _parse_args(parser, args, stderr=stderr)
    if ns is None:
        return 1

    try:
        db = database_connector()
    except Exception as exc:
        _print_database_error(exc, stderr=stderr)
        return 1

    for external_id in ns.account_external_ids:
        request = AccountIntegrationAssignmentSet(
            brokerage_code=ns.brokerage_code,
            account_external_id=external_id,
            connection_id=ns.connection_id,
        )
        try:
            assignment_id = db.set_account_integration_assignment(request)
            print(f"assigned account {external_id}: {assignment_id}", file=stdout)
        except Exception as exc:
            if isinstance(exc, DatabaseConfigurationError):
                print(f"error: failed to assign account {external_id!r}: {exc}", file=stderr)
            else:
                print(f"error: failed to assign account {external_id!r}: {_SANITIZED_ERROR}", file=stderr)
            return 1

    return 0


def _cmd_assign_portfolio(args: list[str], *, stdout: Any, stderr: Any, database_connector: Callable[[], Any]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--connection-id", required=True)
    parser.add_argument("--portfolio-name", required=True)
    parser.add_argument("--brokerage-code", required=True)
    ns = _parse_args(parser, args, stderr=stderr)
    if ns is None:
        return 1

    try:
        db = database_connector()
        account_external_ids = db.list_portfolio_account_external_ids(
            portfolio_name=ns.portfolio_name,
            brokerage_code=ns.brokerage_code,
        )
    except Exception as exc:
        _print_database_error(exc, stderr=stderr)
        return 1

    if not account_external_ids:
        print(
            f"error: no accounts found for portfolio {ns.portfolio_name!r} with brokerage code {ns.brokerage_code!r}",
            file=stderr,
        )
        return 1

    for external_id in account_external_ids:
        request = AccountIntegrationAssignmentSet(
            brokerage_code=ns.brokerage_code,
            account_external_id=external_id,
            connection_id=ns.connection_id,
        )
        try:
            assignment_id = db.set_account_integration_assignment(request)
            print(f"assigned account {external_id}: {assignment_id}", file=stdout)
        except Exception as exc:
            if isinstance(exc, DatabaseConfigurationError):
                print(f"error: failed to assign account {external_id!r}: {exc}", file=stderr)
            else:
                print(f"error: failed to assign account {external_id!r}: {_SANITIZED_ERROR}", file=stderr)
            return 1

    print(f"portfolio assigned: {ns.portfolio_name}", file=stdout)
    return 0


def _cmd_validate_assignments(args: list[str], *, stdout: Any, stderr: Any, database_connector: Callable[[], Any]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--target-type", required=True, choices=["account_list", "portfolio"])
    parser.add_argument("--brokerage-code", required=True)
    parser.add_argument("--portfolio-name", default=None)
    parser.add_argument("--account-external-id", action="append", default=[], dest="account_external_ids")
    ns = _parse_args(parser, args, stderr=stderr)
    if ns is None:
        return 1

    if ns.target_type == "account_list" and not ns.account_external_ids:
        print("error: --target-type account_list requires at least one --account-external-id", file=stderr)
        return 1

    if ns.target_type == "portfolio" and not ns.portfolio_name:
        print("error: --target-type portfolio requires --portfolio-name", file=stderr)
        return 1

    try:
        db = database_connector()
        missing = db.validate_account_integration_assignments(
            target_type=ns.target_type,
            portfolio_name=ns.portfolio_name,
            brokerage_code=ns.brokerage_code,
            account_external_ids=ns.account_external_ids,
        )
    except Exception as exc:
        _print_database_error(exc, stderr=stderr)
        return 1

    if missing:
        for account_id in missing:
            print(f"missing assignment: {account_id}", file=stderr)
        return 1

    print("assignments validated: all accounts assigned", file=stdout)
    return 0


def _cmd_list_connections(args: list[str], *, stdout: Any, stderr: Any, database_connector: Callable[[], Any]) -> int:
    try:
        db = database_connector()
        connections = db.list_integration_connections()
    except Exception as exc:
        _print_database_error(exc, stderr=stderr)
        return 1

    for conn in connections:
        print(
            f"id={conn.id} integration={conn.integration_key} brokerage={conn.brokerage_code} "
            f"name={conn.name!r} active={conn.is_active}",
            file=stdout,
        )
    return 0


def _cmd_list_feeds(args: list[str], *, stdout: Any, stderr: Any, database_connector: Callable[[], Any]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--connection-id", required=True)
    ns = _parse_args(parser, args, stderr=stderr)
    if ns is None:
        return 1

    try:
        db = database_connector()
        feeds = db.list_integration_feeds(ns.connection_id)
    except Exception as exc:
        _print_database_error(exc, stderr=stderr)
        return 1

    for feed in feeds:
        print(
            f"id={feed.id} feed_key={feed.feed_key} display_name={feed.display_name!r} active={feed.is_active}",
            file=stdout,
        )
    return 0


def main(argv: list[str]) -> int:
    import os

    def _database_connector() -> Any:
        from portfolio_engine.database import connect_database

        return connect_database()

    return run(
        argv,
        database_connector=_database_connector,
        environ=dict(os.environ),
    )
