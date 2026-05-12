# Python Database Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a shared Python database adapter that wraps SuperFolio's existing PostgreSQL account and ingestion functions for later CLIs.

**Architecture:** Create a small `portfolio_engine.database` module with request/result dataclasses and a `SuperFolioDatabase` adapter that accepts an injected connection for tests. Add a lazy `connect_database(...)` factory that imports `psycopg` only for real database use, so unit tests can validate SQL calls with fakes. Keep this block free of command-line parsing, Flex XML parsing changes, and TWR logic.

**Tech Stack:** Python 3.12, `dataclasses`, standard-library `os`, `typing`, `unittest`, and `psycopg[binary]` for PostgreSQL connections.

---

## File structure

- Create: `requirements.txt`  
  Declares the Python PostgreSQL client dependency used by real DB connections.
- Create: `portfolio_engine/database.py`  
  Defines request/result dataclasses, connection factory, JSONB parameter helper, and the database adapter methods.
- Create: `tests/test_database_adapter.py`  
  Unit-tests adapter behavior with fake connections and cursors. These tests do not require a live database.
- Modify: `docs/database-functions.md`  
  Add a short note that Python clients should use `portfolio_engine.database.SuperFolioDatabase` instead of calling SQL directly.

## Assumptions locked by this block

- The adapter calls existing PostgreSQL functions only. It does not create tables, write direct `INSERT` statements, or change migrations.
- `DATABASE_URL` remains the default environment variable for PostgreSQL connections.
- Real DB use requires installing `requirements.txt`.
- Unit tests use fake connection/cursor objects, not a live PostgreSQL database.
- The adapter commits after each successful public method call and rolls back before re-raising on failure.
- Returned UUID values are converted to strings for CLI-friendly output.
- Bulk ingestion payloads are the dictionaries produced by Block 1 mappers.
- CLI argument parsing and interactive prompts belong to the later account-registration CLI block.

### Task 1: Add dependency manifest and account registration adapter

**Files:**
- Create: `requirements.txt`
- Create: `portfolio_engine/database.py`
- Test: `tests/test_database_adapter.py`

- [ ] **Step 1: Add the PostgreSQL dependency manifest**

Create `requirements.txt`:

```text
psycopg[binary]>=3.2,<4
```

- [ ] **Step 2: Write failing account adapter tests**

Create `tests/test_database_adapter.py`:

```python
from __future__ import annotations

import os
import unittest
from dataclasses import FrozenInstanceError
from typing import Any

from portfolio_engine.database import (
    AccountRegistration,
    DatabaseConfigurationError,
    SuperFolioDatabase,
    connect_database,
)


class FakeCursor:
    def __init__(self, row: tuple[Any, ...] | None = None) -> None:
        self.row = row
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row


class FakeConnection:
    def __init__(self, row: tuple[Any, ...] | None = None) -> None:
        self.cursor_instance = FakeCursor(row)
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


class FailingConnection(FakeConnection):
    def __init__(self) -> None:
        super().__init__(None)

    def cursor(self) -> FakeCursor:
        raise RuntimeError("database unavailable")


class DatabaseAdapterTests(unittest.TestCase):
    def test_account_registration_is_immutable(self) -> None:
        registration = AccountRegistration(
            brokerage_code="IBKR",
            external_id="U100",
            account_type="Individual",
            base_currency="USD",
            display_name="Main account",
        )

        with self.assertRaises(FrozenInstanceError):
            registration.external_id = "U200"

    def test_register_account_calls_database_function_and_commits(self) -> None:
        connection = FakeConnection(("account-uuid",))
        database = SuperFolioDatabase(connection)

        account_id = database.register_account(
            AccountRegistration(
                brokerage_code="IBKR",
                external_id="U100",
                account_type="Individual",
                base_currency="USD",
                display_name="Main account",
            )
        )

        self.assertEqual(account_id, "account-uuid")
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        self.assertEqual(
            connection.cursor_instance.executed,
            [
                (
                    "SELECT public.register_account(%s, %s, %s, %s, %s)",
                    ("IBKR", "U100", "Individual", "USD", "Main account"),
                )
            ],
        )

    def test_register_account_allows_missing_display_name(self) -> None:
        connection = FakeConnection(("account-uuid",))
        database = SuperFolioDatabase(connection)

        database.register_account(
            AccountRegistration(
                brokerage_code="IBKR",
                external_id="U100",
                account_type="Individual",
                base_currency="USD",
            )
        )

        self.assertEqual(
            connection.cursor_instance.executed[0][1],
            ("IBKR", "U100", "Individual", "USD", None),
        )

    def test_register_account_rolls_back_and_reraises_on_failure(self) -> None:
        connection = FailingConnection()
        database = SuperFolioDatabase(connection)

        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            database.register_account(
                AccountRegistration(
                    brokerage_code="IBKR",
                    external_id="U100",
                    account_type="Individual",
                    base_currency="USD",
                )
            )

        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 1)

    def test_connect_database_requires_database_url(self) -> None:
        original = os.environ.pop("DATABASE_URL", None)
        try:
            with self.assertRaisesRegex(DatabaseConfigurationError, "DATABASE_URL"):
                connect_database()
        finally:
            if original is not None:
                os.environ["DATABASE_URL"] = original


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the account adapter tests to verify they fail**

Run:

```bash
python -m unittest tests.test_database_adapter -v
```

Expected: FAIL with `ModuleNotFoundError` or import errors because `portfolio_engine.database` does not exist.

- [ ] **Step 4: Implement the account adapter**

Create `portfolio_engine/database.py`:

```python
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
    resolved_database_url = database_url or os.environ.get("DATABASE_URL")
    if not resolved_database_url:
        raise DatabaseConfigurationError(
            "DATABASE_URL is required. Set DATABASE_URL or pass database_url."
        )

    import psycopg

    return SuperFolioDatabase(psycopg.connect(resolved_database_url))
```

- [ ] **Step 5: Run the account adapter tests to verify they pass**

Run:

```bash
python -m unittest tests.test_database_adapter -v
```

Expected: PASS for the account adapter tests.

- [ ] **Step 6: Commit Task 1**

Run:

```bash
git add requirements.txt portfolio_engine/database.py tests/test_database_adapter.py
git commit -m "feat: add Python database account adapter" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Add ingestion run lifecycle methods

**Files:**
- Modify: `portfolio_engine/database.py`
- Modify: `tests/test_database_adapter.py`

- [ ] **Step 1: Add failing ingestion-run lifecycle tests**

Append these imports and tests to `tests/test_database_adapter.py`.

Add imports:

```python
from datetime import date
```

Add `IngestionRunStart` to the existing import from `portfolio_engine.database`.

Append inside `DatabaseAdapterTests`:

```python
    def test_start_ingestion_run_calls_database_function(self) -> None:
        connection = FakeConnection(("run-uuid",))
        database = SuperFolioDatabase(connection)

        run_id = database.start_ingestion_run(
            IngestionRunStart(
                brokerage_code="IBKR",
                source_type="MANUAL_FILE",
                requested_start_date=date(2026, 5, 1),
                requested_end_date=date(2026, 5, 31),
                source_filename="Cash_Flows.xml",
            )
        )

        self.assertEqual(run_id, "run-uuid")
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(
            connection.cursor_instance.executed,
            [
                (
                    "SELECT public.start_ingestion_run(%s, %s, %s, %s, %s)",
                    (
                        "IBKR",
                        "MANUAL_FILE",
                        date(2026, 5, 1),
                        date(2026, 5, 31),
                        "Cash_Flows.xml",
                    ),
                )
            ],
        )

    def test_start_ingestion_run_allows_optional_fields(self) -> None:
        connection = FakeConnection(("run-uuid",))
        database = SuperFolioDatabase(connection)

        database.start_ingestion_run(
            IngestionRunStart(
                brokerage_code="IBKR",
                source_type="MANUAL_FILE",
            )
        )

        self.assertEqual(
            connection.cursor_instance.executed[0][1],
            ("IBKR", "MANUAL_FILE", None, None, None),
        )

    def test_complete_ingestion_run_calls_database_function(self) -> None:
        connection = FakeConnection(("run-uuid",))
        database = SuperFolioDatabase(connection)

        run_id = database.complete_ingestion_run(
            ingestion_run_id="run-uuid",
            status="partially_succeeded",
            error_message="Skipped unknown accounts: U404",
        )

        self.assertEqual(run_id, "run-uuid")
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(
            connection.cursor_instance.executed,
            [
                (
                    "SELECT public.complete_ingestion_run(%s, %s, %s)",
                    ("run-uuid", "partially_succeeded", "Skipped unknown accounts: U404"),
                )
            ],
        )
```

- [ ] **Step 2: Run lifecycle tests to verify they fail**

Run:

```bash
python -m unittest tests.test_database_adapter.DatabaseAdapterTests.test_start_ingestion_run_calls_database_function tests.test_database_adapter.DatabaseAdapterTests.test_start_ingestion_run_allows_optional_fields tests.test_database_adapter.DatabaseAdapterTests.test_complete_ingestion_run_calls_database_function -v
```

Expected: FAIL with import or attribute errors because `IngestionRunStart`, `start_ingestion_run`, and `complete_ingestion_run` do not exist.

- [ ] **Step 3: Implement lifecycle dataclass and methods**

In `portfolio_engine/database.py`, add:

```python
from datetime import date
```

Add after `AccountRegistration`:

```python
@dataclass(frozen=True)
class IngestionRunStart:
    brokerage_code: str
    source_type: str
    requested_start_date: date | None = None
    requested_end_date: date | None = None
    source_filename: str | None = None
```

Add methods to `SuperFolioDatabase` after `register_account`:

```python
    def start_ingestion_run(self, request: IngestionRunStart) -> str:
        row = self._fetch_one(
            "SELECT public.start_ingestion_run(%s, %s, %s, %s, %s)",
            (
                request.brokerage_code,
                request.source_type,
                request.requested_start_date,
                request.requested_end_date,
                request.source_filename,
            ),
        )
        return str(row[0])

    def complete_ingestion_run(
        self,
        *,
        ingestion_run_id: str,
        status: str,
        error_message: str | None = None,
    ) -> str:
        row = self._fetch_one(
            "SELECT public.complete_ingestion_run(%s, %s, %s)",
            (ingestion_run_id, status, error_message),
        )
        return str(row[0])
```

- [ ] **Step 4: Run database adapter tests**

Run:

```bash
python -m unittest tests.test_database_adapter -v
```

Expected: PASS for all current database adapter tests.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add portfolio_engine/database.py tests/test_database_adapter.py
git commit -m "feat: add ingestion run database adapter" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Add bulk ingestion adapter methods

**Files:**
- Modify: `portfolio_engine/database.py`
- Modify: `tests/test_database_adapter.py`

- [ ] **Step 1: Add failing bulk ingestion tests**

Add `BulkIngestionSummary` to the existing import from `portfolio_engine.database`.

Append inside `DatabaseAdapterTests`:

```python
    def test_bulk_ingest_cash_flows_returns_summary(self) -> None:
        row = (
            2,
            1,
            1,
            0,
            0,
            ["U404"],
            [{"account_external_id": "U404", "record_status": "skipped_unknown_account"}],
        )
        connection = FakeConnection(row)
        database = SuperFolioDatabase(connection)
        records = [{"account_external_id": "U100", "dedupe_key": "cash-1"}]

        summary = database.bulk_ingest_cash_flows("run-uuid", records)

        self.assertEqual(
            summary,
            BulkIngestionSummary(
                inserted_count=2,
                duplicate_count=1,
                skipped_unknown_account_count=1,
                skipped_inactive_account_count=0,
                conflict_count=0,
                skipped_accounts=["U404"],
                record_results=[
                    {
                        "account_external_id": "U404",
                        "record_status": "skipped_unknown_account",
                    }
                ],
            ),
        )
        self.assertEqual(
            connection.cursor_instance.executed,
            [
                (
                    "SELECT * FROM public.bulk_ingest_cash_flows(%s, %s)",
                    ("run-uuid", records),
                )
            ],
        )

    def test_bulk_ingest_daily_nav_snapshots_returns_summary(self) -> None:
        row = (1, 0, 0, 0, 1, [], [{"record_status": "conflict_existing_snapshot"}])
        connection = FakeConnection(row)
        database = SuperFolioDatabase(connection)
        records = [{"account_external_id": "U100", "dedupe_key": "nav-1"}]

        summary = database.bulk_ingest_daily_nav_snapshots("run-uuid", records)

        self.assertEqual(summary.inserted_count, 1)
        self.assertEqual(summary.conflict_count, 1)
        self.assertEqual(summary.record_results, [{"record_status": "conflict_existing_snapshot"}])
        self.assertEqual(
            connection.cursor_instance.executed,
            [
                (
                    "SELECT * FROM public.bulk_ingest_daily_nav_snapshots(%s, %s)",
                    ("run-uuid", records),
                )
            ],
        )

    def test_bulk_summary_converts_null_collections_to_empty_lists(self) -> None:
        connection = FakeConnection((0, 0, 0, 0, 0, None, None))
        database = SuperFolioDatabase(connection)

        summary = database.bulk_ingest_cash_flows("run-uuid", [])

        self.assertEqual(summary.skipped_accounts, [])
        self.assertEqual(summary.record_results, [])
```

- [ ] **Step 2: Run bulk tests to verify they fail**

Run:

```bash
python -m unittest tests.test_database_adapter.DatabaseAdapterTests.test_bulk_ingest_cash_flows_returns_summary tests.test_database_adapter.DatabaseAdapterTests.test_bulk_ingest_daily_nav_snapshots_returns_summary tests.test_database_adapter.DatabaseAdapterTests.test_bulk_summary_converts_null_collections_to_empty_lists -v
```

Expected: FAIL with import or attribute errors because `BulkIngestionSummary` and bulk methods do not exist.

- [ ] **Step 3: Implement bulk summary and methods**

In `portfolio_engine/database.py`, add after `IngestionRunStart`:

```python
@dataclass(frozen=True)
class BulkIngestionSummary:
    inserted_count: int
    duplicate_count: int
    skipped_unknown_account_count: int
    skipped_inactive_account_count: int
    conflict_count: int
    skipped_accounts: list[str]
    record_results: list[dict[str, Any]]
```

Add these methods to `SuperFolioDatabase`:

```python
    def bulk_ingest_cash_flows(
        self,
        ingestion_run_id: str,
        records: list[dict[str, Any]],
    ) -> BulkIngestionSummary:
        row = self._fetch_one(
            "SELECT * FROM public.bulk_ingest_cash_flows(%s, %s)",
            (ingestion_run_id, _jsonb(records)),
        )
        return _bulk_summary_from_row(row)

    def bulk_ingest_daily_nav_snapshots(
        self,
        ingestion_run_id: str,
        records: list[dict[str, Any]],
    ) -> BulkIngestionSummary:
        row = self._fetch_one(
            "SELECT * FROM public.bulk_ingest_daily_nav_snapshots(%s, %s)",
            (ingestion_run_id, _jsonb(records)),
        )
        return _bulk_summary_from_row(row)
```

Add helper functions after `connect_database(...)`:

```python
def _jsonb(value: Any) -> Any:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
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
```

If `psycopg` is installed in the environment, `_jsonb(records)` returns a `Jsonb` wrapper. In that case, the fake test expectations should compare `connection.cursor_instance.executed[0][0]` to the SQL string and inspect `connection.cursor_instance.executed[0][1][0]`, not the exact second parameter object. If `psycopg` is not installed, the exact tuple expectations above pass unchanged.

- [ ] **Step 4: Run database adapter tests**

Run:

```bash
python -m unittest tests.test_database_adapter -v
```

Expected: PASS for all database adapter tests.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add portfolio_engine/database.py tests/test_database_adapter.py
git commit -m "feat: add bulk ingestion database adapter" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Document adapter usage and run final verification

**Files:**
- Modify: `docs/database-functions.md`
- Test: `tests/test_database_adapter.py`

- [ ] **Step 1: Add adapter documentation**

In `docs/database-functions.md`, add this section after the opening paragraph:

```markdown
## Python adapter

Python code should use `portfolio_engine.database.SuperFolioDatabase` as the database boundary instead of calling SQL directly. Construct it with `connect_database()` for real PostgreSQL usage or inject a connection-like object in tests.

The adapter wraps:

- `register_account(...)`
- `start_ingestion_run(...)`
- `complete_ingestion_run(...)`
- `bulk_ingest_cash_flows(...)`
- `bulk_ingest_daily_nav_snapshots(...)`
```

- [ ] **Step 2: Add a documentation smoke test for public imports**

Append inside `DatabaseAdapterTests`:

```python
    def test_public_database_adapter_imports_are_available(self) -> None:
        from portfolio_engine.database import (
            AccountRegistration,
            BulkIngestionSummary,
            DatabaseConfigurationError,
            IngestionRunStart,
            SuperFolioDatabase,
            connect_database,
        )

        self.assertIsNotNone(AccountRegistration)
        self.assertIsNotNone(BulkIngestionSummary)
        self.assertIsNotNone(DatabaseConfigurationError)
        self.assertIsNotNone(IngestionRunStart)
        self.assertIsNotNone(SuperFolioDatabase)
        self.assertIsNotNone(connect_database)
```

- [ ] **Step 3: Run final Python verification**

Run:

```bash
python -m unittest tests.test_database_adapter tests.test_flex_ingestion_mappers -v
python -m compileall portfolio_engine tests
```

Expected: all database adapter and Flex mapper tests pass, and compileall succeeds.

- [ ] **Step 4: Commit Task 4**

Run:

```bash
git add docs/database-functions.md tests/test_database_adapter.py
git commit -m "docs: document Python database adapter" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Self-review notes

- Spec coverage: This plan covers the Block 2 database adapter needed by the account-registration CLI and later ingestion load mode. It includes account registration, ingestion-run lifecycle, and bulk cash/NAV ingestion calls.
- Out-of-scope check: The plan does not add CLI argument parsing, prompts, Flex XML parser changes, DB-to-TWR reads, or migration changes.
- Placeholder scan: The plan contains no deferred implementation placeholders.
- Type consistency: Dataclass and method names are consistent across tests and implementation snippets.
