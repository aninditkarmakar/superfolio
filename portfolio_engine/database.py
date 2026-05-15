"""Database adapter for SuperFolio PostgreSQL functions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol

from portfolio_engine.models import (
    AccountRef,
    CashFlow,
    NavSnapshot,
    PortfolioCashFlow,
    PortfolioDailyInput,
    PortfolioSummary,
    TransferBridge,
)


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


@dataclass(frozen=True)
class AutomationJobStart:
    trigger_type: str
    target_type: str
    portfolio_id: str | None
    integration_key: str
    mode: str
    requested_start_date: date
    requested_end_date: date


@dataclass(frozen=True)
class AutomationJobFinalize:
    automation_job_id: str
    status: str
    summary: dict[str, Any] | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class AutomationJobAccountAdd:
    automation_job_id: str
    account_id: str
    connection_id: str | None = None


@dataclass(frozen=True)
class AutomationJobAccountFinalize:
    automation_job_account_id: str
    status: str
    ingestion_run_id: str | None = None
    summary: dict[str, Any] | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class AutomationAccountTarget:
    account_id: str
    brokerage_code: str
    account_external_id: str
    base_currency: str
    display_name: str | None


@dataclass(frozen=True)
class AutomationConnectionTarget:
    account_id: str
    brokerage_code: str
    account_external_id: str
    base_currency: str
    display_name: str | None
    connection_id: str | None
    connection_name: str | None


@dataclass(frozen=True)
class IntegrationConnectionCreate:
    integration_key: str
    brokerage_code: str
    name: str


@dataclass(frozen=True)
class IntegrationCredentialSet:
    connection_id: str
    credential_name: str
    ciphertext: bytes
    encryption_key_id: str
    encryption_version: int


@dataclass(frozen=True)
class IntegrationFeedCreate:
    connection_id: str
    feed_key: str
    display_name: str | None = None


@dataclass(frozen=True)
class AccountIntegrationAssignmentSet:
    brokerage_code: str
    account_external_id: str
    connection_id: str


@dataclass(frozen=True)
class IntegrationConnectionRecord:
    id: str
    integration_key: str
    brokerage_code: str
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class IntegrationFeedRecord:
    id: str
    connection_id: str
    feed_key: str
    display_name: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


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

    def create_automation_job(self, request: AutomationJobStart) -> str:
        row = self._fetch_one(
            "SELECT public.create_automation_job(%s, %s, %s, %s, %s, %s, %s)",
            (
                request.trigger_type,
                request.target_type,
                request.portfolio_id,
                request.integration_key,
                request.mode,
                request.requested_start_date,
                request.requested_end_date,
            ),
        )
        return str(row[0])

    def finalize_automation_job(self, request: AutomationJobFinalize) -> str:
        row = self._fetch_one(
            "SELECT public.finalize_automation_job(%s, %s, %s, %s)",
            (
                request.automation_job_id,
                request.status,
                _jsonb(request.summary),
                request.error_message,
            ),
        )
        return str(row[0])

    def add_automation_job_account(self, request: AutomationJobAccountAdd) -> str:
        row = self._fetch_one(
            "SELECT public.add_automation_job_account(%s, %s, %s)",
            (request.automation_job_id, request.account_id, request.connection_id),
        )
        return str(row[0])

    def mark_automation_job_account_running(self, automation_job_account_id: str) -> str:
        row = self._fetch_one(
            "SELECT public.mark_automation_job_account_running(%s)",
            (automation_job_account_id,),
        )
        return str(row[0])

    def finalize_automation_job_account(self, request: AutomationJobAccountFinalize) -> str:
        row = self._fetch_one(
            "SELECT public.finalize_automation_job_account(%s, %s, %s, %s, %s)",
            (
                request.automation_job_account_id,
                request.status,
                request.ingestion_run_id,
                _jsonb(request.summary),
                request.error_message,
            ),
        )
        return str(row[0])

    def get_portfolio_id_by_name(self, portfolio_name: str) -> str | None:
        """Return the UUID of an active portfolio by name, or None if not found."""
        rows = self._fetch_all(
            "SELECT id FROM public.portfolios WHERE name = %s AND is_active = true",
            (portfolio_name,),
        )
        if not rows:
            return None
        return str(rows[0][0])

    def resolve_automation_portfolio_accounts(
        self, *, portfolio_name: str, brokerage_code: str
    ) -> list[AutomationAccountTarget]:
        rows = self._fetch_all(
            "SELECT * FROM public.resolve_automation_portfolio_accounts(%s, %s)",
            (portfolio_name, brokerage_code),
        )
        return [_automation_account_target_from_row(row) for row in rows]

    def resolve_automation_account_targets(
        self, *, brokerage_code: str, account_external_ids: list[str]
    ) -> list[AutomationAccountTarget]:
        rows = self._fetch_all(
            "SELECT * FROM public.resolve_automation_account_targets(%s, %s)",
            (brokerage_code, account_external_ids),
        )
        return [_automation_account_target_from_row(row) for row in rows]

    def resolve_automation_targets_with_connections(
        self,
        *,
        target_type: str,
        portfolio_name: str | None,
        brokerage_code: str,
        account_external_ids: list[str],
    ) -> list[AutomationConnectionTarget]:
        rows = self._fetch_all(
            "SELECT * FROM public.resolve_automation_targets_with_connections(%s, %s, %s, %s)",
            (target_type, portfolio_name, brokerage_code, account_external_ids),
        )
        return [_automation_connection_target_from_row(row) for row in rows]

    def fail_stale_automation_runs(self, *, stale_before: datetime, error_message: str) -> int:
        row = self._fetch_one(
            "SELECT public.fail_stale_automation_runs(%s, %s)",
            (stale_before, error_message),
        )
        return int(row[0])

    def has_overlapping_automation_load(
        self,
        *,
        integration_key: str,
        account_id: str,
        requested_start_date: date,
        requested_end_date: date,
        exclude_automation_job_id: str,
    ) -> bool:
        row = self._fetch_one(
            "SELECT public.has_overlapping_automation_load(%s, %s, %s, %s, %s)",
            (integration_key, account_id, requested_start_date, requested_end_date, exclude_automation_job_id),
        )
        return bool(row[0])

    def create_integration_connection(self, request: IntegrationConnectionCreate) -> str:
        row = self._fetch_one(
            "SELECT public.create_integration_connection(%s, %s, %s)",
            (request.integration_key, request.brokerage_code, request.name),
        )
        return str(row[0])

    def set_integration_credential(self, request: IntegrationCredentialSet) -> str:
        row = self._fetch_one(
            "SELECT public.set_integration_credential(%s, %s, %s, %s, %s)",
            (
                request.connection_id,
                request.credential_name,
                request.ciphertext,
                request.encryption_key_id,
                request.encryption_version,
            ),
        )
        return str(row[0])

    def create_integration_feed(self, request: IntegrationFeedCreate) -> str:
        row = self._fetch_one(
            "SELECT public.create_integration_feed(%s, %s, %s)",
            (request.connection_id, request.feed_key, request.display_name),
        )
        return str(row[0])

    def set_account_integration_assignment(self, request: AccountIntegrationAssignmentSet) -> str:
        row = self._fetch_one(
            "SELECT public.set_account_integration_assignment(%s, %s, %s)",
            (request.brokerage_code, request.account_external_id, request.connection_id),
        )
        return str(row[0])

    def validate_account_integration_assignments(
        self,
        *,
        target_type: str,
        portfolio_name: str | None,
        brokerage_code: str,
        account_external_ids: list[str],
    ) -> list[str]:
        rows = self._fetch_all(
            "SELECT * FROM public.validate_account_integration_assignments(%s, %s, %s, %s)",
            (target_type, portfolio_name, brokerage_code, account_external_ids),
        )
        return [str(row[0]) for row in rows]

    def list_portfolio_account_external_ids(
        self, *, portfolio_name: str, brokerage_code: str
    ) -> list[str]:
        """Return broker-scoped account external IDs for a portfolio."""
        rows = self._fetch_all(
            """
            SELECT a.external_id
            FROM public.portfolio_accounts pa
            JOIN public.portfolios p ON p.id = pa.portfolio_id
            JOIN public.accounts a ON a.id = pa.account_id
            JOIN public.brokerages b ON b.id = a.brokerage_id
            WHERE p.name = %s AND b.code = %s
            AND p.is_active = true
            AND a.is_active = true
            AND b.is_active = true
            ORDER BY a.external_id
            """,
            (portfolio_name, brokerage_code),
        )
        return [str(row[0]) for row in rows]

    def list_integration_connections(self) -> list[IntegrationConnectionRecord]:
        rows = self._fetch_all(
            "SELECT * FROM public.list_integration_connections()",
            (),
        )
        return [_integration_connection_record_from_row(row) for row in rows]

    def list_integration_feeds(self, connection_id: str) -> list[IntegrationFeedRecord]:
        rows = self._fetch_all(
            "SELECT * FROM public.list_integration_feeds(%s)",
            (connection_id,),
        )
        return [_integration_feed_record_from_row(row) for row in rows]

    def list_active_connection_credentials(self, connection_id: str) -> dict[str, bytes]:
        rows = self._fetch_all(
            "SELECT credential_name, ciphertext FROM public.list_active_connection_credentials(%s)",
            (connection_id,),
        )
        return {str(row[0]): bytes(row[1]) for row in rows}

    def list_active_integration_feeds(self, connection_id: str) -> list[IntegrationFeedRecord]:
        rows = self._fetch_all(
            "SELECT * FROM public.list_active_integration_feeds(%s)",
            (connection_id,),
        )
        return [_integration_feed_record_from_row(row) for row in rows]

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

    def create_portfolio(self, *, name: str, reporting_currency: str) -> str:
        row = self._fetch_one(
            "SELECT public.create_portfolio(%s, %s)",
            (name, reporting_currency),
        )
        return str(row[0])

    def attach_portfolio_account(
        self,
        *,
        portfolio_name: str,
        brokerage_code: str,
        account_external_id: str,
    ) -> str:
        row = self._fetch_one(
            "SELECT public.attach_portfolio_account(%s, %s, %s)",
            (portfolio_name, brokerage_code, account_external_id),
        )
        return str(row[0])

    def create_portfolio_transfer_bridge(
        self,
        *,
        portfolio_name: str,
        source_brokerage_code: str,
        source_account_external_id: str,
        destination_brokerage_code: str,
        destination_account_external_id: str,
        departure_date: date,
        arrival_date: date,
        value: Decimal,
        currency: str,
        note: str | None,
    ) -> str:
        row = self._fetch_one(
            """
            SELECT public.create_portfolio_transfer_bridge(
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                portfolio_name,
                source_brokerage_code,
                source_account_external_id,
                destination_brokerage_code,
                destination_account_external_id,
                departure_date,
                arrival_date,
                value,
                currency,
                note,
            ),
        )
        return str(row[0])

    def list_portfolios(self) -> list[PortfolioSummary]:
        rows = self._fetch_all(
            """
            SELECT name, reporting_currency, is_active
            FROM public.portfolios
            ORDER BY name
            """,
            (),
        )
        return [
            PortfolioSummary(
                name=str(row[0]),
                reporting_currency=str(row[1]),
                is_active=bool(row[2]),
            )
            for row in rows
        ]

    def fetch_portfolio_accounts(self, portfolio_name: str) -> list[AccountRef]:
        rows = self._fetch_all(
            """
            SELECT b.code, a.external_id, a.base_currency, a.display_name
            FROM public.portfolio_accounts pa
            JOIN public.portfolios p ON p.id = pa.portfolio_id
            JOIN public.accounts a ON a.id = pa.account_id
            JOIN public.brokerages b ON b.id = a.brokerage_id
            WHERE p.name = %s
            ORDER BY b.code, a.external_id
            """,
            (portfolio_name,),
        )
        return [
            AccountRef(
                brokerage_code=str(row[0]),
                external_id=str(row[1]),
                base_currency=str(row[2]),
                display_name=None if row[3] is None else str(row[3]),
            )
            for row in rows
        ]

    def fetch_portfolio_nav_inputs(
        self,
        *,
        portfolio_name: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[PortfolioDailyInput]:
        rows = self._fetch_all(
            """
            SELECT b.code, a.external_id, a.base_currency, a.display_name,
                   d.snapshot_date, d.nav_base, d.base_currency
            FROM public.portfolio_accounts pa
            JOIN public.portfolios p ON p.id = pa.portfolio_id
            JOIN public.accounts a ON a.id = pa.account_id
            JOIN public.brokerages b ON b.id = a.brokerage_id
            JOIN public.daily_nav_snapshots d ON d.account_id = a.id
            WHERE p.name = %s
              AND (%s::date IS NULL OR d.snapshot_date >= %s::date)
              AND (%s::date IS NULL OR d.snapshot_date <= %s::date)
            ORDER BY d.snapshot_date, b.code, a.external_id
            """,
            (portfolio_name, start_date, start_date, end_date, end_date),
        )
        return [
            PortfolioDailyInput(
                account=AccountRef(str(row[0]), str(row[1]), str(row[2]), row[3]),
                report_date=row[4],
                nav_base=Decimal(row[5]),
                nav_currency=str(row[6]),
            )
            for row in rows
        ]

    def fetch_portfolio_cash_flows(
        self,
        *,
        portfolio_name: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[PortfolioCashFlow]:
        rows = self._fetch_all(
            """
            SELECT b.code, a.external_id, a.base_currency, a.display_name,
                   c.flow_date, c.amount_base
            FROM public.portfolio_accounts pa
            JOIN public.portfolios p ON p.id = pa.portfolio_id
            JOIN public.accounts a ON a.id = pa.account_id
            JOIN public.brokerages b ON b.id = a.brokerage_id
            JOIN public.cash_flows c ON c.account_id = a.id
            WHERE p.name = %s
              AND c.cash_flow_type = %s
              AND (%s::date IS NULL OR c.flow_date >= %s::date)
              AND (%s::date IS NULL OR c.flow_date <= %s::date)
            ORDER BY c.flow_date, b.code, a.external_id
            """,
            (portfolio_name, "Deposits/Withdrawals", start_date, start_date, end_date, end_date),
        )
        return [
            PortfolioCashFlow(
                account=AccountRef(str(row[0]), str(row[1]), str(row[2]), row[3]),
                effective_date=row[4],
                amount_base=Decimal(row[5]),
                base_currency=str(row[2]),
            )
            for row in rows
        ]

    def fetch_portfolio_transfer_bridges(self, portfolio_name: str) -> list[TransferBridge]:
        rows = self._fetch_all(
            """
            SELECT sb.code, sa.external_id, sa.base_currency, sa.display_name,
                   db.code, da.external_id, da.base_currency, da.display_name,
                   t.departure_date, t.arrival_date, t.value, t.currency, t.note
            FROM public.portfolio_transfer_bridges t
            JOIN public.portfolios p ON p.id = t.portfolio_id
            JOIN public.accounts sa ON sa.id = t.source_account_id
            JOIN public.brokerages sb ON sb.id = sa.brokerage_id
            JOIN public.accounts da ON da.id = t.destination_account_id
            JOIN public.brokerages db ON db.id = da.brokerage_id
            WHERE p.name = %s
            ORDER BY t.departure_date, t.arrival_date
            """,
            (portfolio_name,),
        )
        return [
            TransferBridge(
                source_account=AccountRef(str(row[0]), str(row[1]), str(row[2]), row[3]),
                destination_account=AccountRef(str(row[4]), str(row[5]), str(row[6]), row[7]),
                departure_date=row[8],
                arrival_date=row[9],
                value=Decimal(row[10]),
                currency=str(row[11]),
                note=row[12],
            )
            for row in rows
        ]

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
    if value is None:
        return None

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


def _automation_account_target_from_row(row: tuple[Any, ...]) -> AutomationAccountTarget:
    return AutomationAccountTarget(
        account_id=str(row[0]),
        brokerage_code=str(row[1]),
        account_external_id=str(row[2]),
        base_currency=str(row[3]),
        display_name=None if row[4] is None else str(row[4]),
    )


def _automation_connection_target_from_row(row: tuple[Any, ...]) -> AutomationConnectionTarget:
    return AutomationConnectionTarget(
        account_id=str(row[0]),
        brokerage_code=str(row[1]),
        account_external_id=str(row[2]),
        base_currency=str(row[3]),
        display_name=None if row[4] is None else str(row[4]),
        connection_id=None if row[5] is None else str(row[5]),
        connection_name=None if row[6] is None else str(row[6]),
    )


def _integration_connection_record_from_row(row: tuple[Any, ...]) -> IntegrationConnectionRecord:
    return IntegrationConnectionRecord(
        id=str(row[0]),
        integration_key=str(row[1]),
        brokerage_code=str(row[2]),
        name=str(row[3]),
        is_active=bool(row[4]),
        created_at=row[5],
        updated_at=row[6],
    )


def _integration_feed_record_from_row(row: tuple[Any, ...]) -> IntegrationFeedRecord:
    return IntegrationFeedRecord(
        id=str(row[0]),
        connection_id=str(row[1]),
        feed_key=str(row[2]),
        display_name=None if row[3] is None else str(row[3]),
        is_active=bool(row[4]),
        created_at=row[5],
        updated_at=row[6],
    )


def connect_database(database_url: str | None = None) -> SuperFolioDatabase:
    resolved_database_url = database_url if database_url is not None else os.environ.get("DATABASE_URL")
    if resolved_database_url is None or not resolved_database_url.strip():
        raise DatabaseConfigurationError(
            "DATABASE_URL is required. Set DATABASE_URL or pass database_url."
        )

    import psycopg

    return SuperFolioDatabase(psycopg.connect(resolved_database_url.strip()))
