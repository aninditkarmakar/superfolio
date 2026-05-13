# Database-backed TWR CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. If using subagent-driven execution, dispatch every implementation and review subagent with minimum model capability `claude-sonnet-4.6`; do not use Haiku, mini, or any model of lesser capability.

**Goal:** Build a database-backed TWR CLI that calculates TWR for one selected brokerage account from PostgreSQL facts.

**Architecture:** Add read-only query methods to `portfolio_engine.database.SuperFolioDatabase` that map normalized database rows into existing `NavSnapshot` and `CashFlow` models. Add `portfolio_engine.db_twr` for argument parsing, orchestration, stdout formatting, and CSV export, then expose it through a thin `scripts/calculate_twr_from_db.py` wrapper.

**Tech Stack:** Python 3.12, stdlib `argparse`/`unittest`, PostgreSQL via existing `psycopg` adapter boundary, existing `portfolio_engine.twr` and `portfolio_engine.csv_export`.

---

## File structure

- Modify `portfolio_engine/database.py`: add `fetch_nav_snapshots` and `fetch_cash_flows` read methods, add `CursorLike.fetchall`, import existing domain models, and map query rows to `NavSnapshot`/`CashFlow`.
- Create `portfolio_engine/db_twr.py`: database-backed TWR CLI logic with injectable database connector for tests.
- Create `scripts/calculate_twr_from_db.py`: thin executable wrapper matching existing script wrapper style.
- Modify `tests/test_database_adapter.py`: add fake cursor support for multi-row reads and tests for new adapter methods.
- Create `tests/test_db_twr.py`: test CLI wiring, summaries, errors, CSV output, and hard-coded `Deposits/Withdrawals` behavior.
- Modify `README.md`: document the new database-backed TWR CLI.
- Modify `docs/workflows/twr-calculation.md`: split file-based and database-backed TWR workflows.

## Subagent execution constraint

If this plan is executed with `superpowers:subagent-driven-development`, every task subagent and every review subagent must be launched with `model: "claude-sonnet-4.6"` or a strictly higher-capability model. Do not use Haiku, mini, or any model below Claude Sonnet 4.6 for implementation, review, or verification work on this plan.

## Database-query security requirements

- Use static SQL strings with `%s` placeholders and a separate params tuple for all user-controlled values: brokerage code, account external id, cash-flow type, start date, and end date.
- Do not use f-strings, `.format(...)`, `%` string interpolation, string concatenation, or dynamic SQL identifiers for query construction.
- Keep table names, column names, joins, filters, and `ORDER BY` clauses hard-coded in `portfolio_engine/database.py`.
- Keep `cash_flow_type` parameterized even though the CLI hard-codes `Deposits/Withdrawals`; this preserves one query pattern and avoids future unsafe edits.
- Do not print or log `DATABASE_URL` or any connection string in success or error output.
- The plan intentionally does not add user-controllable sort fields, table names, column names, raw SQL filters, or limit/offset expressions.

## Task 1: Add adapter read-method tests

**Files:**
- Modify: `tests/test_database_adapter.py`
- Later implementation target: `portfolio_engine/database.py`

- [ ] **Step 1: Update fake cursor/connection test helpers for `fetchall`**

Replace the `FakeCursor` and `FakeConnection` constructors at the top of `tests/test_database_adapter.py` with row-list support while preserving existing single-row tests:

```python
class FakeCursor:
    def __init__(
        self,
        row: tuple[Any, ...] | None = None,
        rows: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.row = row
        self.rows = [] if rows is None else rows
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class FakeConnection:
    def __init__(
        self,
        row: tuple[Any, ...] | None = None,
        rows: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.cursor_instance = FakeCursor(row, rows)
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0
```

- [ ] **Step 2: Import models used in new assertions**

Add these imports near the existing imports in `tests/test_database_adapter.py`:

```python
from decimal import Decimal

from portfolio_engine.models import CashFlow, NavSnapshot
```

- [ ] **Step 3: Add NAV snapshot read test**

Add this test inside `DatabaseAdapterTests` after the ingestion tests:

```python
    def test_fetch_nav_snapshots_returns_ordered_models(self) -> None:
        connection = FakeConnection(
            rows=[
                (date(2026, 1, 2), Decimal("10000.00")),
                (date(2026, 1, 3), Decimal("10100.00")),
            ]
        )
        database = SuperFolioDatabase(connection)

        snapshots = database.fetch_nav_snapshots(
            brokerage_code="IBKR",
            account_external_id="U100",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        self.assertEqual(
            snapshots,
            [
                NavSnapshot(report_date=date(2026, 1, 2), total_base=Decimal("10000.00")),
                NavSnapshot(report_date=date(2026, 1, 3), total_base=Decimal("10100.00")),
            ],
        )
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("FROM daily_nav_snapshots", sql)
        self.assertIn("JOIN accounts", sql)
        self.assertIn("JOIN brokerages", sql)
        self.assertIn("ORDER BY d.snapshot_date", sql)
        self.assertEqual(
            params,
            (
                "IBKR",
                "U100",
                date(2026, 1, 1),
                date(2026, 1, 1),
                date(2026, 1, 31),
                date(2026, 1, 31),
            ),
        )
```

- [ ] **Step 4: Add cash-flow read test**

Add this test inside `DatabaseAdapterTests`:

```python
    def test_fetch_cash_flows_returns_deposit_withdrawal_models(self) -> None:
        connection = FakeConnection(
            rows=[
                (date(2026, 1, 3), Decimal("1000.00")),
                (date(2026, 1, 5), Decimal("-250.00")),
            ]
        )
        database = SuperFolioDatabase(connection)

        flows = database.fetch_cash_flows(
            brokerage_code="IBKR",
            account_external_id="U100",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        self.assertEqual(
            flows,
            [
                CashFlow(effective_date=date(2026, 1, 3), amount_base=Decimal("1000.00")),
                CashFlow(effective_date=date(2026, 1, 5), amount_base=Decimal("-250.00")),
            ],
        )
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("FROM cash_flows", sql)
        self.assertIn("c.cash_flow_type = %s", sql)
        self.assertIn("ORDER BY c.flow_date", sql)
        self.assertEqual(
            params,
            (
                "IBKR",
                "U100",
                "Deposits/Withdrawals",
                date(2026, 1, 1),
                date(2026, 1, 1),
                date(2026, 1, 31),
                date(2026, 1, 31),
            ),
        )
```

- [ ] **Step 5: Add SQL-injection guard test**

Add this test inside `DatabaseAdapterTests`:

```python
    def test_fetch_queries_keep_user_inputs_out_of_sql_text(self) -> None:
        connection = FakeConnection(rows=[])
        database = SuperFolioDatabase(connection)
        malicious_brokerage = "IBKR'; DROP TABLE accounts; --"
        malicious_account = "U100' OR TRUE --"

        database.fetch_nav_snapshots(
            brokerage_code=malicious_brokerage,
            account_external_id=malicious_account,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
        database.fetch_cash_flows(
            brokerage_code=malicious_brokerage,
            account_external_id=malicious_account,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        for sql, params in connection.cursor_instance.executed:
            self.assertNotIn("DROP TABLE", sql)
            self.assertNotIn("OR TRUE", sql)
            self.assertNotIn(malicious_account, sql)
            self.assertIn("%s", sql)
            self.assertIn(malicious_brokerage, params)
            self.assertIn(malicious_account, params)
```

- [ ] **Step 6: Add optional date test**

Add this test inside `DatabaseAdapterTests`:

```python
    def test_fetch_methods_allow_absent_date_filters(self) -> None:
        connection = FakeConnection(rows=[])
        database = SuperFolioDatabase(connection)

        self.assertEqual(
            database.fetch_nav_snapshots(
                brokerage_code="IBKR",
                account_external_id="U100",
            ),
            [],
        )
        self.assertEqual(
            database.fetch_cash_flows(
                brokerage_code="IBKR",
                account_external_id="U100",
            ),
            [],
        )

        self.assertEqual(connection.commit_count, 2)
        self.assertEqual(connection.rollback_count, 0)
        self.assertEqual(connection.cursor_instance.executed[0][1], ("IBKR", "U100", None, None, None, None))
        self.assertEqual(
            connection.cursor_instance.executed[1][1],
            ("IBKR", "U100", "Deposits/Withdrawals", None, None, None, None),
        )
```

- [ ] **Step 7: Run adapter tests to verify failure**

Run:

```bash
python -m unittest tests.test_database_adapter -v
```

Expected: FAIL with `AttributeError: 'SuperFolioDatabase' object has no attribute 'fetch_nav_snapshots'`.

## Task 2: Implement database read methods

**Files:**
- Modify: `portfolio_engine/database.py`
- Test: `tests/test_database_adapter.py`

- [ ] **Step 1: Add imports and protocol method**

In `portfolio_engine/database.py`, add imports:

```python
from decimal import Decimal

from portfolio_engine.models import CashFlow, NavSnapshot
```

Update `CursorLike`:

```python
class CursorLike(Protocol):
    def __enter__(self) -> "CursorLike": ...
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...
    def execute(self, sql: str, params: tuple[Any, ...]) -> None: ...
    def fetchone(self) -> tuple[Any, ...] | None: ...
    def fetchall(self) -> list[tuple[Any, ...]]: ...
```

- [ ] **Step 2: Add read methods to `SuperFolioDatabase`**

Add these methods after `bulk_ingest_daily_nav_snapshots`:

```python
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
```

- [ ] **Step 3: Add `_fetch_all` helper**

Add this method after `_fetch_one`:

```python
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
```

- [ ] **Step 4: Run adapter tests**

Run:

```bash
python -m unittest tests.test_database_adapter -v
```

Expected: all tests in `tests.test_database_adapter` pass.

- [ ] **Step 5: Commit adapter work**

Run:

```bash
git add portfolio_engine/database.py tests/test_database_adapter.py
git commit -m "feat: add database TWR read queries" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 3: Add database-backed TWR CLI tests

**Files:**
- Create: `tests/test_db_twr.py`
- Later implementation targets: `portfolio_engine/db_twr.py`, `scripts/calculate_twr_from_db.py`

- [ ] **Step 1: Create CLI test file with fakes**

Create `tests/test_db_twr.py`:

```python
from __future__ import annotations

import io
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from portfolio_engine.models import CashFlow, NavSnapshot


class FakeDatabase:
    def __init__(
        self,
        *,
        snapshots: list[NavSnapshot] | None = None,
        flows: list[CashFlow] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.snapshots = [] if snapshots is None else snapshots
        self.flows = [] if flows is None else flows
        self.error = error
        self.nav_calls: list[dict[str, object]] = []
        self.flow_calls: list[dict[str, object]] = []
        self.close_count = 0

    def __enter__(self) -> "FakeDatabase":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self.close_count += 1

    def fetch_nav_snapshots(
        self,
        *,
        brokerage_code: str,
        account_external_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[NavSnapshot]:
        if self.error is not None:
            raise self.error
        self.nav_calls.append(
            {
                "brokerage_code": brokerage_code,
                "account_external_id": account_external_id,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return self.snapshots

    def fetch_cash_flows(
        self,
        *,
        brokerage_code: str,
        account_external_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[CashFlow]:
        self.flow_calls.append(
            {
                "brokerage_code": brokerage_code,
                "account_external_id": account_external_id,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return self.flows


class FakeDatabaseConnector:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database
        self.database_urls: list[str | None] = []

    def __call__(self, database_url: str | None = None) -> FakeDatabase:
        self.database_urls.append(database_url)
        return self.database
```

- [ ] **Step 2: Add successful summary test**

Add:

```python
class DatabaseTwrCliTests(unittest.TestCase):
    def test_run_calculates_twr_from_database_and_prints_summary(self) -> None:
        database = FakeDatabase(
            snapshots=[
                NavSnapshot(report_date=date(2026, 1, 2), total_base=Decimal("10000.00")),
                NavSnapshot(report_date=date(2026, 1, 3), total_base=Decimal("11100.00")),
            ],
            flows=[CashFlow(effective_date=date(2026, 1, 3), amount_base=Decimal("1000.00"))],
        )
        connector = FakeDatabaseConnector(database)
        stdout = io.StringIO()
        stderr = io.StringIO()

        from portfolio_engine.db_twr import run

        exit_code = run(
            [
                "--brokerage-code", "IBKR",
                "--account-external-id", "U100",
                "--database-url", "postgresql://example",
                "--start-date", "2026-01-01",
                "--end-date", "2026-01-31",
            ],
            database_connector=connector,
            stdout=stdout,
            stderr=stderr,
        )

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertEqual(connector.database_urls, ["postgresql://example"])
        self.assertEqual(database.close_count, 1)
        self.assertEqual(
            database.nav_calls,
            [
                {
                    "brokerage_code": "IBKR",
                    "account_external_id": "U100",
                    "start_date": date(2026, 1, 1),
                    "end_date": date(2026, 1, 31),
                }
            ],
        )
        self.assertEqual(database.flow_calls, database.nav_calls)
        self.assertIn("Brokerage: IBKR", output)
        self.assertIn("Account: U100", output)
        self.assertIn("NAV snapshots: 2", output)
        self.assertIn("Cash-flow records: 1", output)
        self.assertIn("Return periods: 1", output)
        self.assertIn("Date range: 2026-01-02 to 2026-01-03", output)
        self.assertIn("Cash-flow type: Deposits/Withdrawals", output)
        self.assertIn("Cash-flow timing: start", output)
        self.assertIn("TWR: 0.909091%", output)
        self.assertEqual(stderr.getvalue(), "")
```

- [ ] **Step 3: Add zero-flow success test**

Add:

```python
    def test_run_allows_no_cash_flows(self) -> None:
        database = FakeDatabase(
            snapshots=[
                NavSnapshot(report_date=date(2026, 1, 2), total_base=Decimal("10000.00")),
                NavSnapshot(report_date=date(2026, 1, 3), total_base=Decimal("10100.00")),
            ],
            flows=[],
        )
        stdout = io.StringIO()

        from portfolio_engine.db_twr import run

        exit_code = run(
            ["--brokerage-code", "IBKR", "--account-external-id", "U100"],
            database_connector=FakeDatabaseConnector(database),
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("Cash-flow records: 0", stdout.getvalue())
        self.assertIn("TWR: 1.000000%", stdout.getvalue())
```

- [ ] **Step 4: Add no-NAV failure test**

Add:

```python
    def test_run_fails_when_no_nav_snapshots_are_found(self) -> None:
        database = FakeDatabase(snapshots=[], flows=[])
        stderr = io.StringIO()

        from portfolio_engine.db_twr import run

        exit_code = run(
            ["--brokerage-code", "IBKR", "--account-external-id", "U404"],
            database_connector=FakeDatabaseConnector(database),
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn(
            "Error: No NAV snapshots found for the selected account and date range.",
            stderr.getvalue(),
        )
```

- [ ] **Step 5: Add invalid date range and database error tests**

Add:

```python
    def test_run_rejects_start_date_after_end_date(self) -> None:
        stderr = io.StringIO()

        from portfolio_engine.db_twr import run

        exit_code = run(
            [
                "--brokerage-code", "IBKR",
                "--account-external-id", "U100",
                "--start-date", "2026-02-01",
                "--end-date", "2026-01-31",
            ],
            database_connector=FakeDatabaseConnector(FakeDatabase()),
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: --start-date must be on or before --end-date", stderr.getvalue())

    def test_run_prints_database_errors(self) -> None:
        stderr = io.StringIO()

        from portfolio_engine.db_twr import run

        exit_code = run(
            ["--brokerage-code", "IBKR", "--account-external-id", "U100"],
            database_connector=FakeDatabaseConnector(FakeDatabase(error=RuntimeError("database unavailable"))),
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: database unavailable", stderr.getvalue())
```

- [ ] **Step 6: Add CSV output and wrapper import tests**

Add:

```python
    def test_run_writes_daily_output_csv(self) -> None:
        database = FakeDatabase(
            snapshots=[
                NavSnapshot(report_date=date(2026, 1, 2), total_base=Decimal("10000.00")),
                NavSnapshot(report_date=date(2026, 1, 3), total_base=Decimal("10100.00")),
            ],
            flows=[],
        )

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "twr.csv"
            stdout = io.StringIO()

            from portfolio_engine.db_twr import run

            exit_code = run(
                [
                    "--brokerage-code", "IBKR",
                    "--account-external-id", "U100",
                    "--daily-output", str(output_path),
                ],
                database_connector=FakeDatabaseConnector(database),
                stdout=stdout,
                stderr=io.StringIO(),
            )

            csv_text = output_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("Daily output written to", stdout.getvalue())
        self.assertIn("date,ending_nav_base,net_cash_flow_base,period_return,cumulative_twr", csv_text)
        self.assertIn("2026-01-02,10000.00,0,,0", csv_text)
        self.assertIn("2026-01-03,10100.00,0,0.01,0.01", csv_text)

    def test_script_wrapper_imports_main(self) -> None:
        import scripts.calculate_twr_from_db as calculate_twr_from_db_script

        self.assertEqual(calculate_twr_from_db_script.main.__module__, "portfolio_engine.db_twr")
```

- [ ] **Step 7: Run new CLI tests to verify failure**

Run:

```bash
python -m unittest tests.test_db_twr -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'portfolio_engine.db_twr'`.

## Task 4: Implement database-backed TWR CLI

**Files:**
- Create: `portfolio_engine/db_twr.py`
- Create: `scripts/calculate_twr_from_db.py`
- Test: `tests/test_db_twr.py`

- [ ] **Step 1: Create `portfolio_engine/db_twr.py`**

Create this file:

```python
"""Database-backed Time-Weighted Return CLI."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import NoReturn, Protocol, TextIO

from portfolio_engine.csv_export import write_daily_twr_csv
from portfolio_engine.database import connect_database
from portfolio_engine.models import CashFlow, NavSnapshot, TwrRow
from portfolio_engine.twr import align_flows_to_nav_dates, calculate_twr


DEPOSIT_WITHDRAWAL_CASH_FLOW_TYPE = "Deposits/Withdrawals"


class DatabaseTwrCliError(RuntimeError):
    """Raised when database-backed TWR CLI input or data is invalid."""


class TwrDatabase(Protocol):
    def __enter__(self) -> "TwrDatabase": ...
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def fetch_nav_snapshots(
        self,
        *,
        brokerage_code: str,
        account_external_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[NavSnapshot]: ...

    def fetch_cash_flows(
        self,
        *,
        brokerage_code: str,
        account_external_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[CashFlow]: ...


DatabaseConnector = Callable[[str | None], TwrDatabase]


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise DatabaseTwrCliError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(description="Calculate daily linked TWR from SuperFolio database data.")
    parser.add_argument("--brokerage-code", required=True, help="Brokerage code, for example IBKR.")
    parser.add_argument("--account-external-id", required=True, help="Brokerage account identifier, for example U100.")
    parser.add_argument(
        "--database-url",
        help="Optional PostgreSQL connection URL. Defaults to DATABASE_URL via the DB adapter.",
    )
    parser.add_argument(
        "--flow-timing",
        choices=("end", "start"),
        default="start",
        help=(
            "Daily return convention. 'end' uses (ending NAV - flow) / beginning NAV - 1. "
            "'start' uses ending NAV / (beginning NAV + flow) - 1."
        ),
    )
    parser.add_argument("--start-date", type=_parse_iso_date, help="Inclusive date filter start.")
    parser.add_argument("--end-date", type=_parse_iso_date, help="Inclusive date filter end.")
    parser.add_argument(
        "--daily-output",
        type=Path,
        help="Optional CSV path for daily NAV, cash-flow, period-return, and cumulative-TWR rows.",
    )
    return parser


def run(
    argv: list[str] | None = None,
    *,
    database_connector: DatabaseConnector = connect_database,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        _validate_date_range(args.start_date, args.end_date)
        with database_connector(args.database_url) as database:
            snapshots = database.fetch_nav_snapshots(
                brokerage_code=args.brokerage_code,
                account_external_id=args.account_external_id,
                start_date=args.start_date,
                end_date=args.end_date,
            )
            if not snapshots:
                raise DatabaseTwrCliError("No NAV snapshots found for the selected account and date range.")
            flows = database.fetch_cash_flows(
                brokerage_code=args.brokerage_code,
                account_external_id=args.account_external_id,
                start_date=args.start_date,
                end_date=args.end_date,
            )

        flows_by_date, dropped_flow_count = align_flows_to_nav_dates(
            flows,
            [snapshot.report_date for snapshot in snapshots],
        )
        rows = calculate_twr(snapshots, flows_by_date, flow_timing=args.flow_timing)
        if args.daily_output:
            write_daily_twr_csv(args.daily_output, rows)
        _print_summary(
            brokerage_code=args.brokerage_code,
            account_external_id=args.account_external_id,
            snapshots=snapshots,
            flows=flows,
            rows=rows,
            flow_timing=args.flow_timing,
            dropped_flow_count=dropped_flow_count,
            daily_output=args.daily_output,
            stdout=stdout,
        )
    except Exception as error:
        stderr.write(f"Error: {error}\n")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(argv)


def _parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise DatabaseTwrCliError(f"invalid date {value!r}; expected YYYY-MM-DD") from error


def _validate_date_range(start_date: date | None, end_date: date | None) -> None:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise DatabaseTwrCliError("--start-date must be on or before --end-date")


def _format_percent(value: Decimal) -> str:
    return f"{value * Decimal('100'):.6f}%"


def _print_summary(
    *,
    brokerage_code: str,
    account_external_id: str,
    snapshots: list[NavSnapshot],
    flows: list[CashFlow],
    rows: list[TwrRow],
    flow_timing: str,
    dropped_flow_count: int,
    daily_output: Path | None,
    stdout: TextIO,
) -> None:
    completed_rows = [row for row in rows if row.period_return is not None]
    final_row = rows[-1]
    stdout.write(f"Brokerage: {brokerage_code}\n")
    stdout.write(f"Account: {account_external_id}\n")
    stdout.write(f"NAV snapshots: {len(snapshots)}\n")
    stdout.write(f"Cash-flow records: {len(flows)}\n")
    stdout.write(f"Return periods: {len(completed_rows)}\n")
    stdout.write(f"Date range: {snapshots[0].report_date.isoformat()} to {snapshots[-1].report_date.isoformat()}\n")
    stdout.write(f"Cash-flow type: {DEPOSIT_WITHDRAWAL_CASH_FLOW_TYPE}\n")
    stdout.write(f"Cash-flow timing: {flow_timing}\n")
    if dropped_flow_count:
        stdout.write(f"Warning: dropped {dropped_flow_count} cash flow(s) after the final NAV date.\n")
    stdout.write(f"TWR: {_format_percent(final_row.cumulative_twr)}\n")
    if daily_output:
        stdout.write(f"Daily output written to {daily_output}\n")
```

- [ ] **Step 2: Create script wrapper**

Create `scripts/calculate_twr_from_db.py`:

```python
#!/usr/bin/env python3
"""CLI for calculating Time-Weighted Return from SuperFolio database rows."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from portfolio_engine.db_twr import main


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run database TWR CLI tests**

Run:

```bash
python -m unittest tests.test_db_twr -v
```

Expected: all tests in `tests.test_db_twr` pass.

- [ ] **Step 4: Run adapter and CLI tests together**

Run:

```bash
python -m unittest tests.test_database_adapter tests.test_db_twr -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit CLI work**

Run:

```bash
git add portfolio_engine/db_twr.py scripts/calculate_twr_from_db.py tests/test_db_twr.py
git commit -m "feat: add database TWR CLI" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 5: Update documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/workflows/twr-calculation.md`

- [ ] **Step 1: Update README project structure**

In `README.md`, update the script list around the current `calculate_twr.py` entry to include:

```text
  calculate_twr.py          # End-to-end CLI: Flex XML -> TWR -> optional CSV export
  calculate_twr_from_db.py  # Database CLI: PostgreSQL facts -> TWR -> optional CSV export
```

- [ ] **Step 2: Add README database-backed command section**

After the existing "Running the TWR CLI" section, add:

````markdown
### Running the database-backed TWR CLI

After registering an account and loading Flex XML records into PostgreSQL, calculate TWR from normalized database facts:

```bash
python scripts/calculate_twr_from_db.py \
  --brokerage-code IBKR \
  --account-external-id U100 \
  --start-date 2026-01-01 \
  --end-date 2026-01-31 \
  --daily-output output/twr.csv
```

The command uses `DATABASE_URL` by default. Pass `--database-url` to override it for one run. It calculates one selected brokerage account at a time, reads daily NAV snapshots and `Deposits/Withdrawals` cash flows from the database, and writes the same optional daily CSV schema as `scripts/calculate_twr.py`.
````

- [ ] **Step 3: Update README CLI options table**

Add a short table after the new section:

```markdown
Database-backed options:

| Flag | Default | Description |
| :--- | :--- | :--- |
| `--brokerage-code` | required | Brokerage code for the selected account, for example `IBKR`. |
| `--account-external-id` | required | Brokerage account id to calculate. |
| `--database-url` | `DATABASE_URL` | Optional database URL override. |
| `--flow-timing` | `start` | Return convention: `start` = flow at beginning of period; `end` = flow at end. |
| `--start-date` | *(none)* | Filter window start (`YYYY-MM-DD`). |
| `--end-date` | *(none)* | Filter window end (`YYYY-MM-DD`). |
| `--daily-output` | *(none)* | Optional CSV path for daily TWR rows. |
```

- [ ] **Step 4: Update workflow doc**

In `docs/workflows/twr-calculation.md`, replace the opening sentence with:

```markdown
SuperFolio supports two TWR calculation workflows:

- `scripts/calculate_twr.py` calculates daily linked TWR from local IBKR Flex XML reports and does not query PostgreSQL.
- `scripts/calculate_twr_from_db.py` calculates daily linked TWR from normalized PostgreSQL facts for one selected brokerage account.
```

Add this database section after the current file-based command:

````markdown
## Database-backed command

```bash
python scripts/calculate_twr_from_db.py \
  --brokerage-code IBKR \
  --account-external-id U100 \
  --start-date 2026-01-01 \
  --end-date 2026-01-31 \
  --daily-output output/twr.csv
```

The database-backed command uses `DATABASE_URL` by default and accepts `--database-url` for a one-run override. It reads `daily_nav_snapshots` and only `cash_flows` rows whose `cash_flow_type` is `Deposits/Withdrawals`. It does not accept a cash-flow type option.
````

- [ ] **Step 5: Review docs for stale "current limit" language**

Change the current limit line:

```markdown
- The standalone TWR CLI reads local XML files and does not query the database.
```

to:

```markdown
- The XML TWR CLI reads local XML files and does not query the database; use `calculate_twr_from_db.py` after records have been loaded into PostgreSQL.
```

- [ ] **Step 6: Commit documentation**

Run:

```bash
git add README.md docs/workflows/twr-calculation.md
git commit -m "docs: document database TWR workflow" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 6: Final verification

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Verify CLI help works**

Run:

```bash
python scripts/calculate_twr_from_db.py --help
```

Expected: output includes `Calculate daily linked TWR from SuperFolio database data.`, `--brokerage-code`, `--account-external-id`, `--flow-timing`, and `--daily-output`.

- [ ] **Step 3: Verify database query construction has no obvious interpolation**

Run:

```bash
! rg 'f"""|f"SELECT|\.format\(|SELECT .*\+' portfolio_engine/database.py
```

Expected: no matches. The read queries should be static strings with `%s` placeholders and separate params tuples.

- [ ] **Step 4: Verify git state**

Run:

```bash
git --no-pager status --short
git --no-pager log --oneline -5
```

Expected: status is clean except for intentional untracked local files outside this feature, and recent commits include the adapter, CLI, docs, and design commits.

## Self-review notes

- Spec coverage: adapter read methods, one-account CLI, `DATABASE_URL` override, date filters, `Deposits/Withdrawals` restriction, flow timing, CSV parity, docs, and tests are each mapped to tasks above.
- Scope: the plan excludes consolidated portfolio TWR, dashboard/API work, cash-flow type selection, and TWR math changes.
- Type consistency: adapter methods accept `date | None`; CLI parser returns `date`; tests assert `NavSnapshot`, `CashFlow`, and `TwrRow` behavior through existing public models.
- Security review: the planned database reads use static SQL with `%s` placeholders and params tuples, hard-coded identifiers and `ORDER BY`, no user-supplied raw SQL fragments, and no connection-string logging. The plan now includes an injection guard test and a final interpolation scan.
