"""CLI helpers for manual Flex XML ingestion workflows."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import NoReturn, TextIO

from portfolio_engine.ingestion.dry_run import FlexDryRunSummary, analyze_flex_xml_file


class IngestionCliError(RuntimeError):
    """Raised when ingestion CLI input is invalid."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise IngestionCliError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(description="Manual Flex XML ingestion utilities.")
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=_ArgumentParser)

    dry_run = subparsers.add_parser("dry-run", help="Preview supported Flex records without database writes.")
    dry_run.add_argument("file", type=Path, help="Flex XML file to inspect.")
    dry_run.add_argument("--start-date", type=_parse_iso_date, help="Inclusive reportDate filter start.")
    dry_run.add_argument("--end-date", type=_parse_iso_date, help="Inclusive reportDate filter end.")
    return parser


def run(
    argv: list[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "dry-run":
            _validate_date_range(args.start_date, args.end_date)
            summary = analyze_flex_xml_file(
                args.file,
                start_date=args.start_date,
                end_date=args.end_date,
            )
            _print_dry_run_summary(args.file, summary, stdout)
            return 0
    except Exception as error:
        stderr.write(f"Error: {error}\n")
        return 1


def main(argv: list[str] | None = None) -> int:
    return run(argv)


def _parse_iso_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as error:
        raise IngestionCliError(f"invalid date {value!r}; expected YYYY-MM-DD") from error


def _validate_date_range(start_date: str | None, end_date: str | None) -> None:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise IngestionCliError("--start-date must be on or before --end-date")


def _print_dry_run_summary(path: Path, summary: FlexDryRunSummary, stdout: TextIO) -> None:
    stdout.write(f"Dry run: {path}\n")
    stdout.write(f"Cash-flow records mapped: {summary.cash_flow_count}\n")
    stdout.write(f"Daily NAV snapshots mapped: {summary.daily_nav_count}\n")
    stdout.write(
        f"Unsupported CashTransaction records skipped: {summary.unsupported_cash_transaction_count}\n"
    )
    stdout.write(f"Accounts seen: {_format_tuple(summary.accounts_seen)}\n")
    stdout.write(f"Currencies seen: {_format_tuple(summary.currencies_seen)}\n")
    stdout.write(f"Cash-flow date range: {_format_range(summary.cash_flow_date_range)}\n")
    stdout.write(f"Daily NAV date range: {_format_range(summary.daily_nav_date_range)}\n")
    stdout.write(f"Duplicate dedupe keys: {len(summary.duplicate_dedupe_keys)}\n")
    stdout.write("No database writes performed.\n")


def _format_tuple(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "(none)"


def _format_range(value: tuple[str, str] | None) -> str:
    if value is None:
        return "(none)"
    return f"{value[0]} to {value[1]}"
