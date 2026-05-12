"""Database adapter for SuperFolio PostgreSQL functions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol


class DatabaseConfigurationError(RuntimeError):
    """Raised when database connection configuration is missing or invalid."""


class CursorLike(Protocol):
    def __enter__(self) -> "CursorLike": ...
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...
    def execute(self, sql: str, params: tuple[Any, ...]) -> None: ...
    def fetchone(self) -> tuple[Any, ...] | None: ...


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


def connect_database(database_url: str | None = None) -> SuperFolioDatabase:
    resolved_database_url = database_url if database_url is not None else os.environ.get("DATABASE_URL")
    if resolved_database_url is None or not resolved_database_url.strip():
        raise DatabaseConfigurationError(
            "DATABASE_URL is required. Set DATABASE_URL or pass database_url."
        )

    import psycopg

    return SuperFolioDatabase(psycopg.connect(resolved_database_url.strip()))
