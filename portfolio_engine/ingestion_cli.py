"""CLI helpers for manual Flex XML ingestion workflows."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import NoReturn, TextIO

from portfolio_engine.database import (
    BulkIngestionSummary,
    IngestionRunStart,
    SuperFolioDatabase,
    connect_database,
)
from portfolio_engine.ingestion.dry_run import (
    FlexAnalysisResult,
    FlexDryRunSummary,
    analyze_flex_xml_file,
    analyze_flex_xml_file_for_ingestion,
)


class IngestionCliError(RuntimeError):
    """Raised when ingestion CLI input is invalid."""


SOURCE_TYPE_MANUAL_FILE = "manual_file"

DatabaseConnector = Callable[[str | None], SuperFolioDatabase]


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

    load = subparsers.add_parser("load", help="Load supported Flex records into the database.")
    load.add_argument("file", type=Path, help="Flex XML file to load.")
    load.add_argument("--brokerage-code", required=True, help="Brokerage code for this file, e.g. IBKR.")
    load.add_argument("--database-url", help="Database URL override for this run.")
    load.add_argument("--start-date", type=_parse_iso_date, help="Inclusive reportDate filter start.")
    load.add_argument("--end-date", type=_parse_iso_date, help="Inclusive reportDate filter end.")
    return parser


def run(
    argv: list[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    database_connector: DatabaseConnector = connect_database,
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
        if args.command == "load":
            _validate_date_range(args.start_date, args.end_date)
            _load_flex_file(args, stdout, database_connector)
            return 0
    except Exception as error:
        stderr.write(f"Error: {error}\n")
        return 1
    raise AssertionError(f"unhandled command: {args.command!r}")


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


def _load_flex_file(
    args: argparse.Namespace,
    stdout: TextIO,
    database_connector: DatabaseConnector,
) -> None:
    analysis = analyze_flex_xml_file_for_ingestion(
        args.file,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    with database_connector(args.database_url) as database:
        ingestion_run_id: str | None = None
        try:
            ingestion_run_id = database.start_ingestion_run(
                IngestionRunStart(
                    brokerage_code=args.brokerage_code,
                    source_type=SOURCE_TYPE_MANUAL_FILE,
                    requested_start_date=_date_or_none(args.start_date),
                    requested_end_date=_date_or_none(args.end_date),
                    source_filename=args.file.name,
                )
            )
            cash_summary = _empty_bulk_summary()
            nav_summary = _empty_bulk_summary()
            if analysis.cash_flow_records:
                cash_summary = database.bulk_ingest_cash_flows(
                    ingestion_run_id,
                    list(analysis.cash_flow_records),
                )
            if analysis.daily_nav_records:
                nav_summary = database.bulk_ingest_daily_nav_snapshots(
                    ingestion_run_id,
                    list(analysis.daily_nav_records),
                )
            final_status, message = _derive_final_status(cash_summary, nav_summary)
            database.complete_ingestion_run(
                ingestion_run_id=ingestion_run_id,
                status=final_status,
                error_message=message,
            )
        except Exception as error:
            if ingestion_run_id is not None:
                _mark_run_failed(database, ingestion_run_id, error)
            raise

        _print_load_summary(
            args.file,
            ingestion_run_id,
            analysis,
            cash_summary,
            nav_summary,
            final_status,
            message,
            stdout,
        )


def _mark_run_failed(
    database: SuperFolioDatabase,
    ingestion_run_id: str,
    error: Exception,
) -> None:
    try:
        database.complete_ingestion_run(
            ingestion_run_id=ingestion_run_id,
            status="failed",
            error_message=str(error),
        )
    except Exception as finalization_error:
        raise IngestionCliError(
            f"{error}; additionally failed to mark ingestion run failed: {finalization_error}"
        ) from finalization_error


def _date_or_none(value: str | None) -> date | None:
    return date.fromisoformat(value) if value is not None else None


def _empty_bulk_summary() -> BulkIngestionSummary:
    return BulkIngestionSummary(
        inserted_count=0,
        duplicate_count=0,
        skipped_unknown_account_count=0,
        skipped_inactive_account_count=0,
        conflict_count=0,
        skipped_accounts=[],
        record_results=[],
    )


def _derive_final_status(
    cash_summary: BulkIngestionSummary,
    nav_summary: BulkIngestionSummary,
) -> tuple[str, str | None]:
    if _has_partial_conditions(cash_summary) or _has_partial_conditions(nav_summary):
        return "partially_succeeded", "skipped accounts or conflicts require review"
    return "succeeded", None


def _has_partial_conditions(summary: BulkIngestionSummary) -> bool:
    return (
        summary.skipped_unknown_account_count > 0
        or summary.skipped_inactive_account_count > 0
        or summary.conflict_count > 0
    )


def _print_load_summary(
    path: Path,
    ingestion_run_id: str,
    analysis: FlexAnalysisResult,
    cash_summary: BulkIngestionSummary,
    nav_summary: BulkIngestionSummary,
    final_status: str,
    message: str | None,
    stdout: TextIO,
) -> None:
    stdout.write(f"Load: {path}\n")
    stdout.write(f"Ingestion run: {ingestion_run_id}\n")
    stdout.write(f"Cash-flow records mapped: {analysis.cash_flow_count}\n")
    stdout.write(f"Daily NAV snapshots mapped: {analysis.daily_nav_count}\n")
    stdout.write(
        f"Unsupported CashTransaction records skipped: {analysis.unsupported_cash_transaction_count}\n"
    )
    stdout.write(f"Cash-flow results: {_format_bulk_summary(cash_summary)}\n")
    stdout.write(f"Daily NAV results: {_format_bulk_summary(nav_summary)}\n")
    stdout.write(f"Accounts seen: {_format_tuple(analysis.accounts_seen)}\n")
    stdout.write(f"Currencies seen: {_format_tuple(analysis.currencies_seen)}\n")
    skipped_accounts = _combined_skipped_accounts(cash_summary, nav_summary)
    if skipped_accounts:
        stdout.write(f"Skipped accounts: {_format_tuple(skipped_accounts)}\n")
    stdout.write(f"Final status: {final_status}\n")
    if message is not None:
        stdout.write(f"Message: {message}\n")


def _format_bulk_summary(summary: BulkIngestionSummary) -> str:
    return (
        f"inserted={summary.inserted_count} "
        f"duplicate={summary.duplicate_count} "
        f"skipped_unknown={summary.skipped_unknown_account_count} "
        f"skipped_inactive={summary.skipped_inactive_account_count} "
        f"conflicts={summary.conflict_count}"
    )


def _combined_skipped_accounts(
    cash_summary: BulkIngestionSummary,
    nav_summary: BulkIngestionSummary,
) -> tuple[str, ...]:
    return tuple(sorted(set(cash_summary.skipped_accounts + nav_summary.skipped_accounts)))


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
