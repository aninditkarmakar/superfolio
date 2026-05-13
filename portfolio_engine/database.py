"""Database adapter for SuperFolio PostgreSQL functions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from portfolio_engine.models import CashFlow, NavSnapshot


class DatabaseConfigurationError(RuntimeError):
    """Raised when database connection configuration is missing or invalid."""


class CursorLike(Protocol):
    def __enter__(self) -> "CursorLike": ...
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...
    def execute(self, sql: str, params: tuple[Any, ...]) -> None: ...
    def fetchone(self) -> tuple[Any, ...] | None: ...
    def fetchall(self) -> list[tuple[Any, ...]]: ...


class ConnectionLike(Protocol):
    def cursor(self) -> CursorLike: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class AccountRegistration:
    brokerage_code: str
    external_id: str
    account_type: str
    base_currency: str
    display_name: str | None = None


@dataclass(frozen=True)
class IngestionRunStart:
    brokerage_code: str
    account_external_id: str
    source_type: str
    requested_start_date: date | None = None
    requested_end_date: date | None = None
    source_filename: str | None = None


@dataclass(frozen=True)
class BulkIngestionSummary:
    inserted_count: int
    duplicate_count: int
    skipped_unknown_account_count: int
    skipped_inactive_account_count: int
    conflict_count: int
    skipped_accounts: list[str]
    record_results: list[dict[str, Any]]


class SuperFolioDatabase:
    def __init__(self, connection: ConnectionLike) -> None:
        self._connection = connection

    def __enter__(self) -> "SuperFolioDatabase":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def register_account(self, registration: AccountRegistration) -> str:
        row = self._fetch_one(
            "SELECT public.register_account(%s, %s, %s, %s, %s)",
            (
                registration.brokerage_code,
                registration.external_id,
                registration.account_type,
                registration.base_currency,
                registration.display_name,
            ),
        )
        return str(row[0])

    def start_ingestion_run(self, request: IngestionRunStart) -> str:
        row = self._fetch_one(
            "SELECT public.start_ingestion_run(%s, %s, %s, %s, %s, %s)",
            (
                request.brokerage_code,
                request.account_external_id,
                request.source_type,
                request.requested_start_date,
                request.requested_end_date,
                request.source_filename,
            ),
        )
        return str(row[0])

    def complete_ingestion_run(
        self, *, ingestion_run_id: str, status: str, error_message: str | None = None
    ) -> str:
        row = self._fetch_one(
            "SELECT public.complete_ingestion_run(%s, %s, %s)",
            (ingestion_run_id, status, error_message),
        )
        return str(row[0])

    def bulk_ingest_cash_flows(
        self, ingestion_run_id: str, records: list[dict[str, Any]]
    ) -> BulkIngestionSummary:
        row = self._fetch_one(
            "SELECT * FROM public.bulk_ingest_cash_flows(%s, %s)",
            (ingestion_run_id, _jsonb(records)),
        )
        return _bulk_summary_from_row(row)

    def bulk_ingest_daily_nav_snapshots(
        self, ingestion_run_id: str, records: list[dict[str, Any]]
    ) -> BulkIngestionSummary:
        row = self._fetch_one(
            "SELECT * FROM public.bulk_ingest_daily_nav_snapshots(%s, %s)",
            (ingestion_run_id, _jsonb(records)),
        )
        return _bulk_summary_from_row(row)

    def fetch_nav_snapshots(
        self,
        *,
        brokerage_code: str,
        account_external_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[NavSnapshot]:
        rows = self._fetch_all(
            """
            SELECT d.snapshot_date, d.nav_base
            FROM daily_nav_snapshots d
            JOIN accounts a ON a.id = d.account_id
            JOIN brokerages b ON b.id = a.brokerage_id
            WHERE b.code = %s
              AND a.external_id = %s
              AND (%s::date IS NULL OR d.snapshot_date >= %s::date)
              AND (%s::date IS NULL OR d.snapshot_date <= %s::date)
            ORDER BY d.snapshot_date
            """,
            (
                brokerage_code,
                account_external_id,
                start_date,
                start_date,
                end_date,
                end_date,
            ),
        )
        return [
            NavSnapshot(report_date=row[0], total_base=Decimal(row[1]))
            for row in rows
        ]

    def fetch_cash_flows(
        self,
        *,
        brokerage_code: str,
        account_external_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[CashFlow]:
        rows = self._fetch_all(
            """
            SELECT c.flow_date, c.amount_base
            FROM cash_flows c
            JOIN accounts a ON a.id = c.account_id
            JOIN brokerages b ON b.id = a.brokerage_id
            WHERE b.code = %s
              AND a.external_id = %s
              AND c.cash_flow_type = %s
              AND (%s::date IS NULL OR c.flow_date >= %s::date)
              AND (%s::date IS NULL OR c.flow_date <= %s::date)
            ORDER BY c.flow_date
            """,
            (
                brokerage_code,
                account_external_id,
                "Deposits/Withdrawals",
                start_date,
                start_date,
                end_date,
                end_date,
            ),
        )
        return [
            CashFlow(effective_date=row[0], amount_base=Decimal(row[1]))
            for row in rows
        ]

    def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
            if row is None:
                raise RuntimeError("database function returned no rows")
            self._connection.commit()
            return row
        except Exception:
            self._connection.rollback()
            raise

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
            self._connection.commit()
            return rows
        except Exception:
            self._connection.rollback()
            raise


def _jsonb(value: Any) -> Any:
    try:
        from psycopg.types.json import Jsonb
    except ImportError:
        return value

    return Jsonb(value)


def _bulk_summary_from_row(row: tuple[Any, ...]) -> BulkIngestionSummary:
    return BulkIngestionSummary(
        inserted_count=int(row[0]),
        duplicate_count=int(row[1]),
        skipped_unknown_account_count=int(row[2]),
        skipped_inactive_account_count=int(row[3]),
        conflict_count=int(row[4]),
        skipped_accounts=list(row[5] or []),
        record_results=list(row[6] or []),
    )


def connect_database(database_url: str | None = None) -> SuperFolioDatabase:
    resolved_database_url = database_url if database_url is not None else os.environ.get("DATABASE_URL")
    if resolved_database_url is None or not resolved_database_url.strip():
        raise DatabaseConfigurationError(
            "DATABASE_URL is required. Set DATABASE_URL or pass database_url."
        )

    import psycopg

    return SuperFolioDatabase(psycopg.connect(resolved_database_url.strip()))
