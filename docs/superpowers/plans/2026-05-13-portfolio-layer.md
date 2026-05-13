# Portfolio Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI-managed portfolio layer that calculates consolidated TWR across multiple brokerage accounts.

**Architecture:** Add PostgreSQL tables and functions for portfolios, portfolio-account membership, and transfer bridges. Extend the Python database adapter with portfolio administration and read methods, add a focused portfolio aggregation engine that reuses the existing TWR math, then expose administration and calculation through CLI wrappers.

**Tech Stack:** Python 3.12, stdlib `argparse`/`csv`/`unittest`, PostgreSQL + Sqitch, existing `psycopg` adapter boundary, existing `portfolio_engine.twr`.

---

## File structure

- Create `migrations/deploy/create_portfolio_layer.sql`: portfolio tables, constraints, indexes, and mutation/query helper functions.
- Create `migrations/revert/create_portfolio_layer.sql`: revert the portfolio-layer migration.
- Create `migrations/verify/create_portfolio_layer.sql`: verify portfolio-layer tables/functions exist.
- Modify `migrations/sqitch.plan`: add the `create_portfolio_layer` change after `create_mvp_schema`.
- Modify `docs/database/schema.md`: document portfolio-layer tables and constraints.
- Modify `docs/database/functions.md`: document new PostgreSQL function contracts and adapter methods.
- Modify `portfolio_engine/models.py`: add immutable portfolio domain dataclasses used by adapter, aggregation, CSV, and CLI code.
- Modify `portfolio_engine/database.py`: add portfolio administration methods and portfolio TWR read methods.
- Create `portfolio_engine/portfolio_twr.py`: pure portfolio aggregation logic; no database calls and no CLI parsing.
- Modify `portfolio_engine/csv_export.py`: add portfolio daily CSV writer.
- Create `portfolio_engine/portfolio_cli.py`: CLI helpers for create/list/show/attach/list-accounts/create-bridge/list-bridges workflows.
- Create `portfolio_engine/portfolio_db_twr.py`: database-backed portfolio TWR CLI.
- Create `scripts/manage_portfolio.py`: thin wrapper for `portfolio_engine.portfolio_cli.main`.
- Create `scripts/calculate_portfolio_twr_from_db.py`: thin wrapper for `portfolio_engine.portfolio_db_twr.main`.
- Modify `tests/test_migrations.py`: verify the new Sqitch migration files and plan entry.
- Modify `tests/test_database_adapter.py`: add adapter tests for portfolio methods and currency-aware fact reads.
- Create `tests/test_portfolio_twr.py`: test pure aggregation, transfer bridge behavior, missing NAV warnings, and currency validation.
- Create `tests/test_portfolio_cli.py`: test portfolio administration CLI parsing, outputs, and error handling.
- Create `tests/test_portfolio_db_twr.py`: test portfolio TWR CLI orchestration, summary output, optional CSV, and script wrapper.
- Modify `README.md`: document portfolio management and portfolio TWR commands.

## Task 1: Add portfolio-layer migration

**Files:**
- Create: `migrations/deploy/create_portfolio_layer.sql`
- Create: `migrations/revert/create_portfolio_layer.sql`
- Create: `migrations/verify/create_portfolio_layer.sql`
- Modify: `migrations/sqitch.plan`
- Modify: `tests/test_migrations.py`

- [ ] **Step 1: Write failing migration tests**

Add these tests to `tests/test_migrations.py`:

```python
    def test_portfolio_layer_migration_files_exist(self) -> None:
        migration_name = "create_portfolio_layer.sql"

        self.assertTrue((MIGRATIONS_DIR / "deploy" / migration_name).exists())
        self.assertTrue((MIGRATIONS_DIR / "revert" / migration_name).exists())
        self.assertTrue((MIGRATIONS_DIR / "verify" / migration_name).exists())

    def test_portfolio_layer_migration_is_in_sqitch_plan(self) -> None:
        plan_text = (MIGRATIONS_DIR / "sqitch.plan").read_text()

        self.assertIn("create_portfolio_layer", plan_text)
        self.assertLess(
            plan_text.index("create_mvp_schema"),
            plan_text.index("create_portfolio_layer"),
        )
```

- [ ] **Step 2: Run migration tests and verify failure**

Run:

```bash
python -m unittest tests.test_migrations -v
```

Expected: the new tests fail because the migration files and plan entry do not exist.

- [ ] **Step 3: Add Sqitch plan entry**

Append this line to `migrations/sqitch.plan` after `create_mvp_schema`:

```text
create_portfolio_layer 2026-05-13T19:32:36Z node <node@portfolio-layer> # Create portfolio aggregation schema
```

- [ ] **Step 4: Create deploy migration**

Create `migrations/deploy/create_portfolio_layer.sql` with this content:

```sql
-- Deploy superfolio:create_portfolio_layer to pg

BEGIN;

CREATE TABLE public.portfolios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    reporting_currency CHAR(3) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT portfolios_name_not_blank_check CHECK (btrim(name) <> ''),
    CONSTRAINT portfolios_reporting_currency_uppercase_check CHECK (reporting_currency ~ '^[A-Z]{3}$')
);

CREATE TABLE public.portfolio_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT portfolio_accounts_unique_membership UNIQUE (portfolio_id, account_id)
);

CREATE TABLE public.portfolio_transfer_bridges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    source_account_id UUID NOT NULL REFERENCES public.accounts(id),
    destination_account_id UUID NOT NULL REFERENCES public.accounts(id),
    departure_date DATE NOT NULL,
    arrival_date DATE NOT NULL,
    value NUMERIC(20, 8) NOT NULL,
    currency CHAR(3) NOT NULL,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT portfolio_transfer_bridges_distinct_accounts_check CHECK (source_account_id <> destination_account_id),
    CONSTRAINT portfolio_transfer_bridges_ordered_dates_check CHECK (departure_date <= arrival_date),
    CONSTRAINT portfolio_transfer_bridges_positive_value_check CHECK (value > 0),
    CONSTRAINT portfolio_transfer_bridges_currency_uppercase_check CHECK (currency ~ '^[A-Z]{3}$')
);

CREATE INDEX portfolio_accounts_account_id_idx ON public.portfolio_accounts (account_id);
CREATE INDEX portfolio_transfer_bridges_portfolio_dates_idx
    ON public.portfolio_transfer_bridges (portfolio_id, departure_date, arrival_date);

CREATE FUNCTION public.create_portfolio(
    p_name TEXT,
    p_reporting_currency TEXT
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_portfolio_id UUID;
    v_name TEXT;
    v_reporting_currency TEXT;
    v_existing_reporting_currency TEXT;
BEGIN
    IF p_name IS NULL OR btrim(p_name) = '' THEN
        RAISE EXCEPTION 'portfolio name must not be NULL or blank';
    END IF;
    IF p_reporting_currency IS NULL OR btrim(p_reporting_currency) = '' THEN
        RAISE EXCEPTION 'reporting_currency must not be NULL or blank';
    END IF;

    v_name := btrim(p_name);
    v_reporting_currency := upper(btrim(p_reporting_currency));

    INSERT INTO public.portfolios (name, reporting_currency)
    VALUES (v_name, v_reporting_currency)
    ON CONFLICT (name) DO NOTHING
    RETURNING id INTO v_portfolio_id;

    IF v_portfolio_id IS NOT NULL THEN
        RETURN v_portfolio_id;
    END IF;

    SELECT id, reporting_currency
    INTO v_portfolio_id, v_existing_reporting_currency
    FROM public.portfolios
    WHERE name = v_name;

    IF v_portfolio_id IS NULL THEN
        RAISE EXCEPTION 'Portfolio % disappeared after conflict', v_name;
    END IF;

    IF v_existing_reporting_currency <> v_reporting_currency THEN
        RAISE EXCEPTION 'Portfolio % already exists with reporting_currency %',
            v_name,
            v_existing_reporting_currency;
    END IF;

    RETURN v_portfolio_id;
END;
$$;

CREATE FUNCTION public.attach_portfolio_account(
    p_portfolio_name TEXT,
    p_brokerage_code TEXT,
    p_account_external_id TEXT
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_portfolio_id UUID;
    v_account_id UUID;
    v_membership_id UUID;
BEGIN
    SELECT id INTO v_portfolio_id
    FROM public.portfolios
    WHERE name = btrim(p_portfolio_name);

    IF v_portfolio_id IS NULL THEN
        RAISE EXCEPTION 'Unknown portfolio: %', p_portfolio_name;
    END IF;

    SELECT a.id INTO v_account_id
    FROM public.accounts a
    JOIN public.brokerages b ON b.id = a.brokerage_id
    WHERE b.code = upper(btrim(p_brokerage_code))
      AND a.external_id = btrim(p_account_external_id);

    IF v_account_id IS NULL THEN
        RAISE EXCEPTION 'Unknown account: % %', p_brokerage_code, p_account_external_id;
    END IF;

    INSERT INTO public.portfolio_accounts (portfolio_id, account_id)
    VALUES (v_portfolio_id, v_account_id)
    ON CONFLICT (portfolio_id, account_id) DO UPDATE
      SET portfolio_id = EXCLUDED.portfolio_id
    RETURNING id INTO v_membership_id;

    RETURN v_membership_id;
END;
$$;

CREATE FUNCTION public.create_portfolio_transfer_bridge(
    p_portfolio_name TEXT,
    p_source_brokerage_code TEXT,
    p_source_account_external_id TEXT,
    p_destination_brokerage_code TEXT,
    p_destination_account_external_id TEXT,
    p_departure_date DATE,
    p_arrival_date DATE,
    p_value NUMERIC,
    p_currency TEXT,
    p_note TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_portfolio_id UUID;
    v_reporting_currency CHAR(3);
    v_source_account_id UUID;
    v_destination_account_id UUID;
    v_bridge_id UUID;
BEGIN
    SELECT id, reporting_currency INTO v_portfolio_id, v_reporting_currency
    FROM public.portfolios
    WHERE name = btrim(p_portfolio_name);

    IF v_portfolio_id IS NULL THEN
        RAISE EXCEPTION 'Unknown portfolio: %', p_portfolio_name;
    END IF;
    IF p_departure_date IS NULL OR p_arrival_date IS NULL OR p_departure_date > p_arrival_date THEN
        RAISE EXCEPTION 'Invalid bridge date range';
    END IF;
    IF p_value IS NULL OR p_value <= 0 THEN
        RAISE EXCEPTION 'Bridge value must be positive';
    END IF;
    IF p_currency IS NULL OR btrim(p_currency) = '' THEN
        RAISE EXCEPTION 'Bridge currency must not be NULL or blank';
    END IF;
    IF upper(btrim(p_currency)) <> v_reporting_currency THEN
        RAISE EXCEPTION 'Bridge currency % does not match portfolio reporting currency %',
            p_currency,
            v_reporting_currency;
    END IF;

    SELECT a.id INTO v_source_account_id
    FROM public.accounts a
    JOIN public.brokerages b ON b.id = a.brokerage_id
    WHERE b.code = upper(btrim(p_source_brokerage_code))
      AND a.external_id = btrim(p_source_account_external_id);

    SELECT a.id INTO v_destination_account_id
    FROM public.accounts a
    JOIN public.brokerages b ON b.id = a.brokerage_id
    WHERE b.code = upper(btrim(p_destination_brokerage_code))
      AND a.external_id = btrim(p_destination_account_external_id);

    IF v_source_account_id IS NULL OR v_destination_account_id IS NULL THEN
        RAISE EXCEPTION 'Unknown bridge source or destination account';
    END IF;
    IF v_source_account_id = v_destination_account_id THEN
        RAISE EXCEPTION 'Bridge source and destination accounts must differ';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.portfolio_accounts
        WHERE portfolio_id = v_portfolio_id AND account_id = v_source_account_id
    ) OR NOT EXISTS (
        SELECT 1 FROM public.portfolio_accounts
        WHERE portfolio_id = v_portfolio_id AND account_id = v_destination_account_id
    ) THEN
        RAISE EXCEPTION 'Bridge source and destination accounts must both belong to the portfolio';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM public.portfolio_transfer_bridges
        WHERE portfolio_id = v_portfolio_id
          AND source_account_id = v_source_account_id
          AND destination_account_id = v_destination_account_id
          AND (
              (departure_date = p_departure_date AND arrival_date = p_arrival_date)
              OR (
                  CASE WHEN departure_date < arrival_date
                       THEN daterange(departure_date + 1, arrival_date, '[)')
                       ELSE 'empty'::daterange
                  END
                  &&
                  CASE WHEN p_departure_date < p_arrival_date
                       THEN daterange(p_departure_date + 1, p_arrival_date, '[)')
                       ELSE 'empty'::daterange
                  END
              )
          )
    ) THEN
        RAISE EXCEPTION 'Bridge overlaps an existing bridge for this source and destination account';
    END IF;

    INSERT INTO public.portfolio_transfer_bridges (
        portfolio_id,
        source_account_id,
        destination_account_id,
        departure_date,
        arrival_date,
        value,
        currency,
        note
    )
    VALUES (
        v_portfolio_id,
        v_source_account_id,
        v_destination_account_id,
        p_departure_date,
        p_arrival_date,
        p_value,
        upper(btrim(p_currency)),
        NULLIF(btrim(p_note), '')
    )
    RETURNING id INTO v_bridge_id;

    RETURN v_bridge_id;
END;
$$;

COMMIT;
```

- [ ] **Step 5: Create revert migration**

Create `migrations/revert/create_portfolio_layer.sql` with this content:

```sql
-- Revert superfolio:create_portfolio_layer from pg

BEGIN;

DROP FUNCTION IF EXISTS public.create_portfolio_transfer_bridge(
    TEXT, TEXT, TEXT, TEXT, TEXT, DATE, DATE, NUMERIC, TEXT, TEXT
);
DROP FUNCTION IF EXISTS public.attach_portfolio_account(TEXT, TEXT, TEXT);
DROP FUNCTION IF EXISTS public.create_portfolio(TEXT, TEXT);
DROP TABLE IF EXISTS public.portfolio_transfer_bridges;
DROP TABLE IF EXISTS public.portfolio_accounts;
DROP TABLE IF EXISTS public.portfolios;

COMMIT;
```

- [ ] **Step 6: Create verify migration**

Create `migrations/verify/create_portfolio_layer.sql` with this content:

```sql
-- Verify superfolio:create_portfolio_layer on pg

BEGIN;

SELECT id, name, reporting_currency, is_active, created_at, updated_at
FROM public.portfolios
WHERE false;

SELECT id, portfolio_id, account_id, created_at
FROM public.portfolio_accounts
WHERE false;

SELECT id, portfolio_id, source_account_id, destination_account_id,
       departure_date, arrival_date, value, currency, note, created_at
FROM public.portfolio_transfer_bridges
WHERE false;

SELECT has_function_privilege('public.create_portfolio(text, text)', 'execute');
SELECT has_function_privilege('public.attach_portfolio_account(text, text, text)', 'execute');
SELECT has_function_privilege(
    'public.create_portfolio_transfer_bridge(text, text, text, text, text, date, date, numeric, text, text)',
    'execute'
);

ROLLBACK;
```

- [ ] **Step 7: Run migration tests and commit**

Run:

```bash
python -m unittest tests.test_migrations -v
```

Expected: all migration tests pass.

Commit:

```bash
git add migrations/sqitch.plan migrations/deploy/create_portfolio_layer.sql migrations/revert/create_portfolio_layer.sql migrations/verify/create_portfolio_layer.sql tests/test_migrations.py
git commit -m "feat: add portfolio layer schema migration" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 2: Add portfolio domain models

**Files:**
- Modify: `portfolio_engine/models.py`
- Create: `tests/test_portfolio_twr.py`

- [ ] **Step 1: Write failing model import test**

Create `tests/test_portfolio_twr.py` with this content:

```python
from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

from portfolio_engine.models import (
    AccountRef,
    PortfolioCashFlow,
    PortfolioDailyInput,
    PortfolioTwrRow,
    TransferBridge,
)


class PortfolioModelTests(unittest.TestCase):
    def test_portfolio_models_are_immutable_value_objects(self) -> None:
        account = AccountRef(
            brokerage_code="IBKR",
            external_id="U100",
            base_currency="USD",
            display_name="US account",
        )
        daily_input = PortfolioDailyInput(
            account=account,
            report_date=date(2026, 1, 2),
            nav_base=Decimal("100.00"),
            nav_currency="USD",
        )
        flow = PortfolioCashFlow(
            account=account,
            effective_date=date(2026, 1, 2),
            amount_base=Decimal("10.00"),
            base_currency="USD",
        )
        bridge = TransferBridge(
            source_account=account,
            destination_account=AccountRef("IBKR", "U200", "USD", "Canada account"),
            departure_date=date(2026, 1, 2),
            arrival_date=date(2026, 1, 4),
            value=Decimal("50.00"),
            currency="USD",
            note="move",
        )
        row = PortfolioTwrRow(
            report_date=date(2026, 1, 3),
            ending_nav_base=Decimal("150.00"),
            net_cash_flow_base=Decimal("0"),
            bridge_value_base=Decimal("50.00"),
            missing_nav_accounts=("IBKR:U100",),
            period_return=None,
            cumulative_twr=Decimal("0"),
        )

        self.assertEqual(daily_input.account, account)
        self.assertEqual(flow.base_currency, "USD")
        self.assertEqual(bridge.note, "move")
        self.assertEqual(row.missing_nav_accounts, ("IBKR:U100",))

        with self.assertRaises(FrozenInstanceError):
            setattr(account, "base_currency", "CAD")
        with self.assertRaises(FrozenInstanceError):
            setattr(flow, "amount_base", Decimal("99.00"))
        with self.assertRaises(FrozenInstanceError):
            setattr(daily_input, "nav_base", Decimal("0"))
        with self.assertRaises(FrozenInstanceError):
            setattr(bridge, "arrival_date", date(2026, 1, 3))
        with self.assertRaises(FrozenInstanceError):
            setattr(row, "cumulative_twr", Decimal("1"))

    def test_portfolio_cash_flow_rejects_currency_mismatch(self) -> None:
        account = AccountRef("IBKR", "U100", "USD", None)

        with self.assertRaisesRegex(ValueError, "cash-flow base currency"):
            PortfolioCashFlow(
                account=account,
                effective_date=date(2026, 1, 2),
                amount_base=Decimal("10.00"),
                base_currency="CAD",
            )

    def test_transfer_bridge_rejects_arrival_before_departure(self) -> None:
        account = AccountRef("IBKR", "U100", "USD", None)

        with self.assertRaisesRegex(ValueError, "arrival_date must be on or after departure_date"):
            TransferBridge(
                source_account=account,
                destination_account=AccountRef("IBKR", "U200", "USD", None),
                departure_date=date(2026, 1, 4),
                arrival_date=date(2026, 1, 2),
                value=Decimal("50.00"),
                currency="USD",
            )

    def test_portfolio_daily_input_rejects_currency_mismatch(self) -> None:
        account = AccountRef("IBKR", "U100", "USD", None)

        with self.assertRaisesRegex(ValueError, "NAV currency"):
            PortfolioDailyInput(
                account=account,
                report_date=date(2026, 1, 2),
                nav_base=Decimal("100.00"),
                nav_currency="CAD",
            )

    def test_transfer_bridge_rejects_non_positive_value(self) -> None:
        account = AccountRef("IBKR", "U100", "USD", None)

        with self.assertRaisesRegex(ValueError, "transfer bridge value must be positive"):
            TransferBridge(
                source_account=account,
                destination_account=AccountRef("IBKR", "U200", "USD", None),
                departure_date=date(2026, 1, 2),
                arrival_date=date(2026, 1, 4),
                value=Decimal("0"),
                currency="USD",
            )

    def test_transfer_bridge_rejects_same_source_and_destination(self) -> None:
        account = AccountRef("IBKR", "U100", "USD", None)

        with self.assertRaisesRegex(ValueError, "source and destination accounts must differ"):
            TransferBridge(
                source_account=account,
                destination_account=account,
                departure_date=date(2026, 1, 2),
                arrival_date=date(2026, 1, 4),
                value=Decimal("50.00"),
                currency="USD",
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
python -m unittest tests.test_portfolio_twr -v
```

Expected: import fails because portfolio models do not exist.

- [ ] **Step 3: Add portfolio models**

Add these dataclasses to `portfolio_engine/models.py` after `TwrRow`:

```python

@dataclass(frozen=True)
class AccountRef:
    brokerage_code: str
    external_id: str
    base_currency: str
    display_name: str | None = None

    @property
    def label(self) -> str:
        return f"{self.brokerage_code}:{self.external_id}"


@dataclass(frozen=True)
class PortfolioSummary:
    name: str
    reporting_currency: str
    is_active: bool


@dataclass(frozen=True)
class PortfolioCashFlow:
    account: AccountRef
    effective_date: date
    amount_base: Decimal
    base_currency: str

    def __post_init__(self) -> None:
        if self.base_currency != self.account.base_currency:
            raise ValueError(
                f"cash-flow base currency {self.base_currency} does not match "
                f"account base currency {self.account.base_currency}"
            )


@dataclass(frozen=True)
class PortfolioDailyInput:
    account: AccountRef
    report_date: date
    nav_base: Decimal
    nav_currency: str

    def __post_init__(self) -> None:
        if self.nav_currency != self.account.base_currency:
            raise ValueError(
                f"NAV currency {self.nav_currency} does not match "
                f"account base currency {self.account.base_currency}"
            )


@dataclass(frozen=True)
class TransferBridge:
    source_account: AccountRef
    destination_account: AccountRef
    departure_date: date
    arrival_date: date
    value: Decimal
    currency: str
    note: str | None = None

    def __post_init__(self) -> None:
        if self.source_account == self.destination_account:
            raise ValueError("transfer bridge source and destination accounts must differ")
        if self.arrival_date < self.departure_date:
            raise ValueError("arrival_date must be on or after departure_date")
        if self.value <= 0:
            raise ValueError("transfer bridge value must be positive")


@dataclass(frozen=True)
class PortfolioTwrRow:
    report_date: date
    ending_nav_base: Decimal
    net_cash_flow_base: Decimal
    bridge_value_base: Decimal
    missing_nav_accounts: tuple[str, ...]
    period_return: Decimal | None
    cumulative_twr: Decimal
```

- [ ] **Step 4: Run test and commit**

Run:

```bash
python -m unittest tests.test_portfolio_twr -v
```

Expected: model test passes.

Commit:

```bash
git add portfolio_engine/models.py tests/test_portfolio_twr.py
git commit -m "feat: add portfolio domain models" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 3: Add database adapter portfolio administration methods

**Files:**
- Modify: `portfolio_engine/database.py`
- Modify: `tests/test_database_adapter.py`

- [ ] **Step 1: Write failing adapter tests**

Add imports near the top of `tests/test_database_adapter.py`:

```python
from datetime import date
from decimal import Decimal

from portfolio_engine.models import AccountRef, PortfolioDailyInput, PortfolioSummary, TransferBridge
```

Add these tests inside `DatabaseAdapterTests`:

```python
    def test_create_portfolio_calls_database_function(self) -> None:
        connection = FakeConnection(row=("portfolio-uuid",))
        database = SuperFolioDatabase(connection)

        portfolio_id = database.create_portfolio(
            name="All Accounts",
            reporting_currency="USD",
        )

        self.assertEqual(portfolio_id, "portfolio-uuid")
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("public.create_portfolio", sql)
        self.assertEqual(params, ("All Accounts", "USD"))
        self.assertEqual(connection.commit_count, 1)

    def test_attach_portfolio_account_calls_database_function(self) -> None:
        connection = FakeConnection(row=("membership-uuid",))
        database = SuperFolioDatabase(connection)

        membership_id = database.attach_portfolio_account(
            portfolio_name="All Accounts",
            brokerage_code="IBKR",
            account_external_id="U100",
        )

        self.assertEqual(membership_id, "membership-uuid")
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("public.attach_portfolio_account", sql)
        self.assertEqual(params, ("All Accounts", "IBKR", "U100"))

    def test_create_transfer_bridge_calls_database_function(self) -> None:
        connection = FakeConnection(row=("bridge-uuid",))
        database = SuperFolioDatabase(connection)

        bridge_id = database.create_portfolio_transfer_bridge(
            portfolio_name="All Accounts",
            source_brokerage_code="IBKR",
            source_account_external_id="U100",
            destination_brokerage_code="IBKR",
            destination_account_external_id="U200",
            departure_date=date(2026, 1, 2),
            arrival_date=date(2026, 1, 4),
            value=Decimal("5000.00"),
            currency="USD",
            note="relocation",
        )

        self.assertEqual(bridge_id, "bridge-uuid")
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("public.create_portfolio_transfer_bridge", sql)
        self.assertEqual(
            params,
            (
                "All Accounts",
                "IBKR",
                "U100",
                "IBKR",
                "U200",
                date(2026, 1, 2),
                date(2026, 1, 4),
                Decimal("5000.00"),
                "USD",
                "relocation",
            ),
        )

    def test_list_portfolios_maps_rows(self) -> None:
        connection = FakeConnection(
            rows=[
                ("All Accounts", "USD", True),
                ("IBKR Only", "USD", False),
            ]
        )
        database = SuperFolioDatabase(connection)

        portfolios = database.list_portfolios()

        self.assertEqual(
            portfolios,
            [
                PortfolioSummary("All Accounts", "USD", True),
                PortfolioSummary("IBKR Only", "USD", False),
            ],
        )
```

- [ ] **Step 2: Run adapter tests and verify failure**

Run:

```bash
python -m unittest tests.test_database_adapter -v
```

Expected: tests fail because adapter methods do not exist.

- [ ] **Step 3: Add imports to database adapter**

Replace the existing model import in `portfolio_engine/database.py`:

```python
from portfolio_engine.models import CashFlow, NavSnapshot
```

with:

```python
from portfolio_engine.models import (
    AccountRef,
    CashFlow,
    NavSnapshot,
    PortfolioSummary,
    TransferBridge,
)
```

- [ ] **Step 4: Add portfolio administration methods**

Add these methods inside `SuperFolioDatabase` after `bulk_ingest_daily_nav_snapshots`:

```python
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
            FROM portfolios
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
```

- [ ] **Step 5: Run adapter tests and commit**

Run:

```bash
python -m unittest tests.test_database_adapter -v
```

Expected: adapter tests pass.

Commit:

```bash
git add portfolio_engine/database.py tests/test_database_adapter.py
git commit -m "feat: add portfolio administration adapter methods" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 4: Add portfolio calculation engine

**Files:**
- Create: `portfolio_engine/portfolio_twr.py`
- Modify: `tests/test_portfolio_twr.py`

- [ ] **Step 1: Add failing calculation tests**

Append these imports to `tests/test_portfolio_twr.py`:

```python
from portfolio_engine.portfolio_twr import PortfolioTwrError, calculate_portfolio_twr
```

Append this test class:

```python
class PortfolioTwrCalculationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ca = AccountRef("IBKR", "UCA", "USD", "Canada")
        self.us = AccountRef("IBKR", "UUS", "USD", "US")

    def test_same_day_transfer_offsets_without_bridge(self) -> None:
        rows = calculate_portfolio_twr(
            reporting_currency="USD",
            accounts=[self.ca, self.us],
            nav_inputs=[
                PortfolioDailyInput(self.ca, date(2026, 1, 1), Decimal("100"), "USD"),
                PortfolioDailyInput(self.us, date(2026, 1, 1), Decimal("0"), "USD"),
                PortfolioDailyInput(self.ca, date(2026, 1, 2), Decimal("40"), "USD"),
                PortfolioDailyInput(self.us, date(2026, 1, 2), Decimal("60"), "USD"),
            ],
            cash_flows=[],
            transfer_bridges=[],
        )

        self.assertEqual(rows[-1].ending_nav_base, Decimal("100"))
        self.assertEqual(rows[-1].period_return, Decimal("0"))
        self.assertEqual(rows[-1].bridge_value_base, Decimal("0"))

    def test_bridge_fills_multi_day_gap(self) -> None:
        rows = calculate_portfolio_twr(
            reporting_currency="USD",
            accounts=[self.ca, self.us],
            nav_inputs=[
                PortfolioDailyInput(self.ca, date(2026, 1, 1), Decimal("100"), "USD"),
                PortfolioDailyInput(self.us, date(2026, 1, 1), Decimal("0"), "USD"),
                PortfolioDailyInput(self.ca, date(2026, 1, 2), Decimal("0"), "USD"),
                PortfolioDailyInput(self.us, date(2026, 1, 2), Decimal("0"), "USD"),
                PortfolioDailyInput(self.ca, date(2026, 1, 3), Decimal("0"), "USD"),
                PortfolioDailyInput(self.us, date(2026, 1, 3), Decimal("0"), "USD"),
                PortfolioDailyInput(self.ca, date(2026, 1, 4), Decimal("0"), "USD"),
                PortfolioDailyInput(self.us, date(2026, 1, 4), Decimal("100"), "USD"),
            ],
            cash_flows=[],
            transfer_bridges=[
                TransferBridge(
                    self.ca,
                    self.us,
                    date(2026, 1, 1),
                    date(2026, 1, 4),
                    Decimal("100"),
                    "USD",
                    "relocation",
                )
            ],
        )

        by_date = {row.report_date: row for row in rows}
        self.assertEqual(by_date[date(2026, 1, 2)].bridge_value_base, Decimal("100"))
        self.assertEqual(by_date[date(2026, 1, 3)].bridge_value_base, Decimal("100"))
        self.assertEqual(by_date[date(2026, 1, 4)].bridge_value_base, Decimal("0"))
        self.assertEqual(rows[-1].cumulative_twr, Decimal("0"))

    def test_missing_nav_is_zero_and_grouped_by_account(self) -> None:
        rows = calculate_portfolio_twr(
            reporting_currency="USD",
            accounts=[self.ca, self.us],
            nav_inputs=[
                PortfolioDailyInput(self.ca, date(2026, 1, 1), Decimal("100"), "USD"),
                PortfolioDailyInput(self.us, date(2026, 1, 1), Decimal("0"), "USD"),
                PortfolioDailyInput(self.ca, date(2026, 1, 2), Decimal("101"), "USD"),
            ],
            cash_flows=[],
            transfer_bridges=[],
        )

        self.assertEqual(rows[-1].ending_nav_base, Decimal("101"))
        self.assertEqual(rows[-1].missing_nav_accounts, ("IBKR:UUS",))

    def test_explicit_zero_nav_is_not_missing(self) -> None:
        rows = calculate_portfolio_twr(
            reporting_currency="USD",
            accounts=[self.ca, self.us],
            nav_inputs=[
                PortfolioDailyInput(self.ca, date(2026, 1, 1), Decimal("100"), "USD"),
                PortfolioDailyInput(self.us, date(2026, 1, 1), Decimal("0"), "USD"),
            ],
            cash_flows=[],
            transfer_bridges=[],
        )

        self.assertEqual(rows[0].ending_nav_base, Decimal("100"))
        self.assertEqual(rows[0].missing_nav_accounts, ())

    def test_mixed_nav_currency_fails(self) -> None:
        # Use _malformed_portfolio_daily_input to bypass __post_init__ so we can
        # reach the calculation-layer NAV-currency guard with a mismatched currency.
        with self.assertRaisesRegex(PortfolioTwrError, "NAV currency CAD"):
            calculate_portfolio_twr(
                reporting_currency="USD",
                accounts=[self.ca],
                nav_inputs=[
                    _malformed_portfolio_daily_input(
                        self.ca,
                        date(2026, 1, 1),
                        Decimal("100"),
                        "CAD",
                    ),
                ],
                cash_flows=[],
                transfer_bridges=[],
            )

    def test_mixed_account_currency_fails(self) -> None:
        cad_account = AccountRef("IBKR", "UCAD", "CAD", "CAD account")
        with self.assertRaisesRegex(PortfolioTwrError, "Account IBKR:UCAD base currency CAD"):
            calculate_portfolio_twr(
                reporting_currency="USD",
                accounts=[cad_account],
                nav_inputs=[
                    PortfolioDailyInput(cad_account, date(2026, 1, 1), Decimal("100"), "CAD"),
                ],
                cash_flows=[],
                transfer_bridges=[],
            )
```

> **Note (2026-05-13 follow-up):** `PortfolioDailyInput.__post_init__` enforces
> `nav_currency == account.base_currency`, so naively constructing
> `PortfolioDailyInput(self.ca, ..., "CAD")` raises `ValueError` before
> `calculate_portfolio_twr` is called and the calculation-layer NAV-currency guard
> is never exercised. The private helper `_malformed_portfolio_daily_input` uses
> `object.__new__` / `object.__setattr__` to bypass `__post_init__`, simulating
> bad data that could arrive from unsafe callers (raw DB reads, pickle, etc.).
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m unittest tests.test_portfolio_twr -v
```

Expected: import fails because `portfolio_engine.portfolio_twr` does not exist.

- [ ] **Step 3: Create calculation module**

Create `portfolio_engine/portfolio_twr.py` with this content:

```python
"""Portfolio-level TWR aggregation."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

from .models import (
    AccountRef,
    CashFlow,
    NavSnapshot,
    PortfolioCashFlow,
    PortfolioDailyInput,
    PortfolioTwrRow,
    TransferBridge,
)
from .twr import align_flows_to_nav_dates, calculate_twr
from .models import NavSnapshot


class PortfolioTwrError(RuntimeError):
    """Raised when portfolio TWR inputs are invalid."""


def calculate_portfolio_twr(
    *,
    reporting_currency: str,
    accounts: list[AccountRef],
    nav_inputs: list[PortfolioDailyInput],
    cash_flows: list[PortfolioCashFlow],
    transfer_bridges: list[TransferBridge],
    flow_timing: str = "start",
) -> list[PortfolioTwrRow]:
    if not accounts:
        raise PortfolioTwrError("Portfolio has no member accounts.")

    normalized_reporting_currency = reporting_currency.upper()
    for account in accounts:
        if account.base_currency.upper() != normalized_reporting_currency:
            raise PortfolioTwrError(
                f"Account {account.label} base currency {account.base_currency} "
                f"does not match portfolio reporting currency {normalized_reporting_currency}."
            )

    nav_by_date_account: dict[date, dict[str, Decimal]] = defaultdict(dict)
    for nav in nav_inputs:
        if nav.nav_currency.upper() != normalized_reporting_currency:
            raise PortfolioTwrError(
                f"NAV currency {nav.nav_currency} for {nav.account.label} does not match "
                f"portfolio reporting currency {normalized_reporting_currency}."
            )
        nav_by_date_account[nav.report_date][nav.account.label] = nav.nav_base

    if not nav_by_date_account:
        raise PortfolioTwrError("No NAV snapshots found for the selected portfolio and date range.")

    aligned_flow_inputs: list[CashFlow] = []
    for flow in cash_flows:
        if flow.base_currency.upper() != normalized_reporting_currency:
            raise PortfolioTwrError(
                f"Cash-flow currency {flow.base_currency} for {flow.account.label} does not match "
                f"portfolio reporting currency {normalized_reporting_currency}."
            )
        aligned_flow_inputs.append(CashFlow(flow.effective_date, flow.amount_base))

    bridge_value_by_date: defaultdict[date, Decimal] = defaultdict(Decimal)
    nav_dates = sorted(nav_by_date_account)
    flows_by_date, _dropped_flow_count = align_flows_to_nav_dates(aligned_flow_inputs, nav_dates)
    for bridge in transfer_bridges:
        if bridge.currency.upper() != normalized_reporting_currency:
            raise PortfolioTwrError(
                f"Bridge currency {bridge.currency} does not match portfolio reporting currency "
                f"{normalized_reporting_currency}."
            )
        for nav_date in nav_dates:
            if bridge.departure_date < nav_date < bridge.arrival_date:
                bridge_value_by_date[nav_date] += bridge.value

    account_labels = tuple(account.label for account in accounts)
    portfolio_snapshots: list[NavSnapshot] = []
    missing_by_date: dict[date, tuple[str, ...]] = {}
    bridge_by_date: dict[date, Decimal] = {}

    for nav_date in nav_dates:
        account_navs = nav_by_date_account[nav_date]
        missing = tuple(label for label in account_labels if label not in account_navs)
        missing_by_date[nav_date] = missing
        bridge_value = bridge_value_by_date.get(nav_date, Decimal("0"))
        bridge_by_date[nav_date] = bridge_value
        total_nav = sum(account_navs.values(), Decimal("0")) + bridge_value
        portfolio_snapshots.append(NavSnapshot(report_date=nav_date, total_base=total_nav))

    twr_rows = calculate_twr(
        portfolio_snapshots,
        flows_by_date,
        flow_timing=flow_timing,
    )

    return [
        PortfolioTwrRow(
            report_date=row.report_date,
            ending_nav_base=row.ending_nav_base,
            net_cash_flow_base=row.net_cash_flow_base,
            bridge_value_base=bridge_by_date[row.report_date],
            missing_nav_accounts=missing_by_date[row.report_date],
            period_return=row.period_return,
            cumulative_twr=row.cumulative_twr,
        )
        for row in twr_rows
    ]


def missing_nav_counts(rows: list[PortfolioTwrRow]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(row.missing_nav_accounts)
    return counts
```

- [ ] **Step 4: Run tests and commit**

> **Follow-up fix (flow alignment):** The original implementation aggregated cash flows by raw
> `effective_date` and passed them directly to `calculate_twr`. `calculate_twr` only consumes flows
> whose date exactly equals a NAV snapshot date, so flows between snapshot dates were silently
> ignored. The fix imports `CashFlow` and `align_flows_to_nav_dates` from `.models` / `.twr`,
> converts validated portfolio flows to `CashFlow` objects, then calls
> `align_flows_to_nav_dates(aligned_flow_inputs, nav_dates)` before `calculate_twr`, matching the
> single-account path in `db_twr.py`. `_dropped_flow_count` intentionally captures the dropped-
> flow count without surfacing it (a future CLI task may expose it).
> The regression test `test_cash_flow_between_nav_dates_aligns_to_next_nav_date` covers this case.

Run:

```bash
python -m unittest tests.test_portfolio_twr -v
```

Expected: all portfolio TWR tests pass.

Commit:

```bash
git add portfolio_engine/portfolio_twr.py tests/test_portfolio_twr.py
git commit -m "feat: add portfolio TWR aggregation" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 5: Add portfolio daily CSV export

**Files:**
- Modify: `portfolio_engine/csv_export.py`
- Modify: `tests/test_portfolio_twr.py`

- [ ] **Step 1: Add failing CSV test**

Add imports to `tests/test_portfolio_twr.py`:

```python
import tempfile
from pathlib import Path

from portfolio_engine.csv_export import write_portfolio_daily_twr_csv
```

Add this test inside `PortfolioTwrCalculationTests`:

```python
    def test_write_portfolio_daily_twr_csv(self) -> None:
        rows = [
            PortfolioTwrRow(
                report_date=date(2026, 1, 2),
                ending_nav_base=Decimal("100.00"),
                net_cash_flow_base=Decimal("0"),
                bridge_value_base=Decimal("50.00"),
                missing_nav_accounts=("IBKR:UUS",),
                period_return=None,
                cumulative_twr=Decimal("0"),
            )
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "portfolio.csv"
            write_portfolio_daily_twr_csv(path, rows)

            self.assertEqual(
                path.read_text().strip(),
                "date,ending_nav_base,net_cash_flow_base,bridge_value_base,missing_nav_accounts,period_return,cumulative_twr\n"
                "2026-01-02,100.00,0,50.00,IBKR:UUS,,0",
            )
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
python -m unittest tests.test_portfolio_twr -v
```

Expected: import fails because `write_portfolio_daily_twr_csv` does not exist.

- [ ] **Step 3: Add CSV writer**

Modify `portfolio_engine/csv_export.py` imports:

```python
from .models import PortfolioTwrRow, TwrRow
```

Add this function after `write_daily_twr_csv`:

```python

def write_portfolio_daily_twr_csv(path: Path, rows: list[PortfolioTwrRow]) -> None:
    with path.open("w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            [
                "date",
                "ending_nav_base",
                "net_cash_flow_base",
                "bridge_value_base",
                "missing_nav_accounts",
                "period_return",
                "cumulative_twr",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.report_date.isoformat(),
                    row.ending_nav_base,
                    row.net_cash_flow_base,
                    row.bridge_value_base,
                    ";".join(row.missing_nav_accounts),
                    "" if row.period_return is None else row.period_return,
                    row.cumulative_twr,
                ]
            )
```

- [ ] **Step 4: Run tests and commit**

Run:

```bash
python -m unittest tests.test_portfolio_twr -v
```

Expected: tests pass.

Commit:

```bash
git add portfolio_engine/csv_export.py tests/test_portfolio_twr.py
git commit -m "feat: add portfolio daily CSV export" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 6: Add portfolio fact read methods

**Files:**
- Modify: `portfolio_engine/database.py`
- Modify: `tests/test_database_adapter.py`

- [ ] **Step 1: Add failing read-method tests**

Add this test inside `DatabaseAdapterTests`:

```python
    def test_fetch_portfolio_accounts_maps_rows_including_inactive_accounts(self) -> None:
        connection = FakeConnection(
            rows=[
                ("IBKR", "UCA", "USD", "Canada account"),
                ("IBKR", "UUS", "USD", "US account"),
            ]
        )
        database = SuperFolioDatabase(connection)

        accounts = database.fetch_portfolio_accounts("All Accounts")

        self.assertEqual(
            accounts,
            [
                AccountRef("IBKR", "UCA", "USD", "Canada account"),
                AccountRef("IBKR", "UUS", "USD", "US account"),
            ],
        )
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("portfolio_accounts", sql)
        self.assertNotIn("a.is_active = true", sql)
        self.assertEqual(params, ("All Accounts",))
```

Add this test:

```python
    def test_fetch_portfolio_nav_inputs_maps_currency_aware_rows(self) -> None:
        connection = FakeConnection(
            rows=[
                ("IBKR", "UCA", "USD", "Canada account", date(2026, 1, 2), Decimal("100.00"), "USD"),
            ]
        )
        database = SuperFolioDatabase(connection)

        inputs = database.fetch_portfolio_nav_inputs(
            portfolio_name="All Accounts",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        self.assertEqual(
            inputs,
            [
                PortfolioDailyInput(
                    AccountRef("IBKR", "UCA", "USD", "Canada account"),
                    date(2026, 1, 2),
                    Decimal("100.00"),
                    "USD",
                )
            ],
        )
```

- [ ] **Step 2: Run adapter tests and verify failure**

Run:

```bash
python -m unittest tests.test_database_adapter -v
```

Expected: tests fail because portfolio fact methods do not exist.

- [ ] **Step 3: Add imports**

Add `PortfolioCashFlow` and `PortfolioDailyInput` to the model import list in `portfolio_engine/database.py`.

- [ ] **Step 4: Add read methods**

Add these methods inside `SuperFolioDatabase` after `list_portfolios`:

```python
    def fetch_portfolio_accounts(self, portfolio_name: str) -> list[AccountRef]:
        rows = self._fetch_all(
            """
            SELECT b.code, a.external_id, a.base_currency, a.display_name
            FROM portfolio_accounts pa
            JOIN portfolios p ON p.id = pa.portfolio_id
            JOIN accounts a ON a.id = pa.account_id
            JOIN brokerages b ON b.id = a.brokerage_id
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
            FROM portfolio_accounts pa
            JOIN portfolios p ON p.id = pa.portfolio_id
            JOIN accounts a ON a.id = pa.account_id
            JOIN brokerages b ON b.id = a.brokerage_id
            JOIN daily_nav_snapshots d ON d.account_id = a.id
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
```

- [ ] **Step 5: Add cash-flow and bridge methods**

Add these methods in the same class:

```python
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
            FROM portfolio_accounts pa
            JOIN portfolios p ON p.id = pa.portfolio_id
            JOIN accounts a ON a.id = pa.account_id
            JOIN brokerages b ON b.id = a.brokerage_id
            JOIN cash_flows c ON c.account_id = a.id
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
            FROM portfolio_transfer_bridges t
            JOIN portfolios p ON p.id = t.portfolio_id
            JOIN accounts sa ON sa.id = t.source_account_id
            JOIN brokerages sb ON sb.id = sa.brokerage_id
            JOIN accounts da ON da.id = t.destination_account_id
            JOIN brokerages db ON db.id = da.brokerage_id
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
```

- [ ] **Step 6: Run adapter tests and commit**

Run:

```bash
python -m unittest tests.test_database_adapter -v
```

Expected: adapter tests pass.

Commit:

```bash
git add portfolio_engine/database.py tests/test_database_adapter.py
git commit -m "feat: add portfolio TWR read methods" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 7: Add portfolio administration CLI

**Files:**
- Create: `portfolio_engine/portfolio_cli.py`
- Create: `scripts/manage_portfolio.py`
- Create: `tests/test_portfolio_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_portfolio_cli.py` with this content:

```python
from __future__ import annotations

import io
import unittest
from datetime import date
from decimal import Decimal

from portfolio_engine.models import AccountRef, PortfolioSummary, TransferBridge


class FakePortfolioDatabase:
    def __init__(self) -> None:
        self.close_count = 0
        self.created: list[tuple[str, str]] = []
        self.attached: list[tuple[str, str, str]] = []
        self.bridges: list[dict] = []
        self.portfolios = [PortfolioSummary("All Accounts", "USD", True)]
        self.accounts = [AccountRef("IBKR", "U100", "USD", "Main")]
        self.transfer_bridges: list[TransferBridge] = []

    def __enter__(self) -> "FakePortfolioDatabase":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self.close_count += 1

    def create_portfolio(self, *, name: str, reporting_currency: str) -> str:
        self.created.append((name, reporting_currency))
        return "portfolio-uuid"

    def attach_portfolio_account(self, *, portfolio_name: str, brokerage_code: str, account_external_id: str) -> str:
        self.attached.append((portfolio_name, brokerage_code, account_external_id))
        return "membership-uuid"

    def list_portfolios(self) -> list[PortfolioSummary]:
        return self.portfolios

    def fetch_portfolio_accounts(self, portfolio_name: str) -> list[AccountRef]:
        return self.accounts

    def create_portfolio_transfer_bridge(self, **kwargs: object) -> str:
        self.bridges.append(kwargs)
        return "bridge-uuid"

    def fetch_portfolio_transfer_bridges(self, portfolio_name: str) -> list[TransferBridge]:
        return self.transfer_bridges


class FakeFactory:
    def __init__(self, database: FakePortfolioDatabase) -> None:
        self.database = database
        self.database_urls: list[str | None] = []

    def __call__(self, database_url: str | None = None) -> FakePortfolioDatabase:
        self.database_urls.append(database_url)
        return self.database


class PortfolioCliTests(unittest.TestCase):
    def test_create_portfolio(self) -> None:
        from portfolio_engine.portfolio_cli import run

        database = FakePortfolioDatabase()
        stdout = io.StringIO()

        exit_code = run(
            ["create", "--name", "All Accounts", "--reporting-currency", "USD"],
            database_connector=FakeFactory(database),
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(database.created, [("All Accounts", "USD")])
        self.assertIn("Created portfolio: portfolio-uuid", stdout.getvalue())

    def test_attach_account(self) -> None:
        from portfolio_engine.portfolio_cli import run

        database = FakePortfolioDatabase()

        exit_code = run(
            ["attach-account", "--portfolio-name", "All Accounts", "--brokerage-code", "IBKR", "--account-external-id", "U100"],
            database_connector=FakeFactory(database),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(database.attached, [("All Accounts", "IBKR", "U100")])

    def test_script_wrapper_imports_main(self) -> None:
        import scripts.manage_portfolio as manage_portfolio_script

        self.assertEqual(manage_portfolio_script.main.__module__, "portfolio_engine.portfolio_cli")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m unittest tests.test_portfolio_cli -v
```

Expected: imports fail because CLI files do not exist.

- [ ] **Step 3: Create CLI module**

Create `portfolio_engine/portfolio_cli.py` with this content:

```python
"""Portfolio administration CLI."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal
from typing import Callable, Protocol, TextIO

from .database import connect_database


class PortfolioAdminDatabase(Protocol):
    def __enter__(self) -> "PortfolioAdminDatabase": ...
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...
    def create_portfolio(self, *, name: str, reporting_currency: str) -> str: ...
    def attach_portfolio_account(self, *, portfolio_name: str, brokerage_code: str, account_external_id: str) -> str: ...
    def list_portfolios(self) -> list[object]: ...
    def fetch_portfolio_accounts(self, portfolio_name: str) -> list[object]: ...
    def create_portfolio_transfer_bridge(self, **kwargs: object) -> str: ...
    def fetch_portfolio_transfer_bridges(self, portfolio_name: str) -> list[object]: ...


DatabaseConnector = Callable[[str | None], PortfolioAdminDatabase]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage SuperFolio portfolios.")
    parser.add_argument("--database-url", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument("--reporting-currency", required=True)

    subparsers.add_parser("list")

    show = subparsers.add_parser("show")
    show.add_argument("--portfolio-name", required=True)

    attach = subparsers.add_parser("attach-account")
    attach.add_argument("--portfolio-name", required=True)
    attach.add_argument("--brokerage-code", required=True)
    attach.add_argument("--account-external-id", required=True)

    bridge = subparsers.add_parser("create-bridge")
    bridge.add_argument("--portfolio-name", required=True)
    bridge.add_argument("--source-brokerage-code", required=True)
    bridge.add_argument("--source-account-external-id", required=True)
    bridge.add_argument("--destination-brokerage-code", required=True)
    bridge.add_argument("--destination-account-external-id", required=True)
    bridge.add_argument("--departure-date", required=True, type=date.fromisoformat)
    bridge.add_argument("--arrival-date", required=True, type=date.fromisoformat)
    bridge.add_argument("--value", required=True, type=Decimal)
    bridge.add_argument("--currency", required=True)
    bridge.add_argument("--note", default=None)

    bridges = subparsers.add_parser("list-bridges")
    bridges.add_argument("--portfolio-name", required=True)

    return parser


def run(
    argv: list[str] | None = None,
    *,
    database_connector: DatabaseConnector = connect_database,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        with database_connector(args.database_url) as database:
            if args.command == "create":
                portfolio_id = database.create_portfolio(
                    name=args.name,
                    reporting_currency=args.reporting_currency,
                )
                stdout.write(f"Created portfolio: {portfolio_id}\n")
            elif args.command == "list":
                for portfolio in database.list_portfolios():
                    stdout.write(f"{portfolio.name}\t{portfolio.reporting_currency}\t{portfolio.is_active}\n")
            elif args.command == "show":
                for account in database.fetch_portfolio_accounts(args.portfolio_name):
                    stdout.write(f"{account.label}\t{account.base_currency}\t{account.display_name or ''}\n")
            elif args.command == "attach-account":
                membership_id = database.attach_portfolio_account(
                    portfolio_name=args.portfolio_name,
                    brokerage_code=args.brokerage_code,
                    account_external_id=args.account_external_id,
                )
                stdout.write(f"Attached account: {membership_id}\n")
            elif args.command == "create-bridge":
                bridge_id = database.create_portfolio_transfer_bridge(
                    portfolio_name=args.portfolio_name,
                    source_brokerage_code=args.source_brokerage_code,
                    source_account_external_id=args.source_account_external_id,
                    destination_brokerage_code=args.destination_brokerage_code,
                    destination_account_external_id=args.destination_account_external_id,
                    departure_date=args.departure_date,
                    arrival_date=args.arrival_date,
                    value=args.value,
                    currency=args.currency,
                    note=args.note,
                )
                stdout.write(f"Created transfer bridge: {bridge_id}\n")
            elif args.command == "list-bridges":
                for bridge in database.fetch_portfolio_transfer_bridges(args.portfolio_name):
                    stdout.write(
                        f"{bridge.source_account.label}->{bridge.destination_account.label}\t"
                        f"{bridge.departure_date}..{bridge.arrival_date}\t"
                        f"{bridge.value} {bridge.currency}\t{bridge.note or ''}\n"
                    )
        return 0
    except Exception as error:
        stderr.write(f"Error: {error}\n")
        return 1


def main(argv: list[str] | None = None) -> int:
    return run(argv)
```

- [ ] **Step 4: Create script wrapper**

Create `scripts/manage_portfolio.py` with this content:

```python
#!/usr/bin/env python3
"""CLI for managing SuperFolio portfolios."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from portfolio_engine.portfolio_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python -m unittest tests.test_portfolio_cli -v
```

Expected: tests pass.

Commit:

```bash
git add portfolio_engine/portfolio_cli.py scripts/manage_portfolio.py tests/test_portfolio_cli.py
git commit -m "feat: add portfolio management CLI" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 8: Add portfolio TWR CLI

**Files:**
- Create: `portfolio_engine/portfolio_db_twr.py`
- Create: `scripts/calculate_portfolio_twr_from_db.py`
- Create: `tests/test_portfolio_db_twr.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_portfolio_db_twr.py` with this content:

```python
from __future__ import annotations

import io
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from portfolio_engine.models import AccountRef, PortfolioDailyInput


class FakePortfolioTwrDatabase:
    def __init__(self) -> None:
        self.accounts = [
            AccountRef("IBKR", "UCA", "USD", "Canada"),
            AccountRef("IBKR", "UUS", "USD", "US"),
        ]
        self.nav_inputs = [
            PortfolioDailyInput(self.accounts[0], date(2026, 1, 1), Decimal("100"), "USD"),
            PortfolioDailyInput(self.accounts[1], date(2026, 1, 1), Decimal("0"), "USD"),
            PortfolioDailyInput(self.accounts[0], date(2026, 1, 2), Decimal("40"), "USD"),
            PortfolioDailyInput(self.accounts[1], date(2026, 1, 2), Decimal("60"), "USD"),
        ]
        self.cash_flows = []
        self.bridges = []
        self.close_count = 0

    def __enter__(self) -> "FakePortfolioTwrDatabase":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self.close_count += 1

    def fetch_portfolio_accounts(self, portfolio_name: str):
        return self.accounts

    def fetch_portfolio_nav_inputs(self, *, portfolio_name: str, start_date: date | None, end_date: date | None):
        return self.nav_inputs

    def fetch_portfolio_cash_flows(self, *, portfolio_name: str, start_date: date | None, end_date: date | None):
        return self.cash_flows

    def fetch_portfolio_transfer_bridges(self, portfolio_name: str):
        return self.bridges


class FakeFactory:
    def __init__(self, database: FakePortfolioTwrDatabase) -> None:
        self.database = database

    def __call__(self, database_url: str | None = None) -> FakePortfolioTwrDatabase:
        return self.database


class PortfolioDbTwrCliTests(unittest.TestCase):
    def test_run_calculates_portfolio_twr_and_prints_summary(self) -> None:
        from portfolio_engine.portfolio_db_twr import run

        database = FakePortfolioTwrDatabase()
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run(
            ["--portfolio-name", "All Accounts", "--reporting-currency", "USD"],
            database_connector=FakeFactory(database),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Portfolio: All Accounts", output)
        self.assertIn("Reporting currency: USD", output)
        self.assertIn("Member accounts: 2", output)
        self.assertIn("NAV rows: 4", output)
        self.assertIn("Return periods: 1", output)
        self.assertIn("TWR: 0.000000%", output)
        self.assertEqual(stderr.getvalue(), "")

    def test_run_writes_optional_daily_csv(self) -> None:
        from portfolio_engine.portfolio_db_twr import run

        database = FakePortfolioTwrDatabase()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "portfolio.csv"
            exit_code = run(
                [
                    "--portfolio-name", "All Accounts",
                    "--reporting-currency", "USD",
                    "--daily-output", str(output_path),
                ],
                database_connector=FakeFactory(database),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.exists())
            self.assertIn("bridge_value_base", output_path.read_text())

    def test_script_wrapper_imports_main(self) -> None:
        import scripts.calculate_portfolio_twr_from_db as script

        self.assertEqual(script.main.__module__, "portfolio_engine.portfolio_db_twr")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m unittest tests.test_portfolio_db_twr -v
```

Expected: imports fail because CLI files do not exist.

- [ ] **Step 3: Create portfolio TWR CLI module**

Create `portfolio_engine/portfolio_db_twr.py` with this content:

```python
"""Database-backed portfolio Time-Weighted Return CLI."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Callable, Protocol, TextIO

from .csv_export import write_portfolio_daily_twr_csv
from .database import connect_database
from .portfolio_twr import calculate_portfolio_twr, missing_nav_counts


class PortfolioTwrDatabase(Protocol):
    def __enter__(self) -> "PortfolioTwrDatabase": ...
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...
    def fetch_portfolio_accounts(self, portfolio_name: str): ...
    def fetch_portfolio_nav_inputs(self, *, portfolio_name: str, start_date: date | None, end_date: date | None): ...
    def fetch_portfolio_cash_flows(self, *, portfolio_name: str, start_date: date | None, end_date: date | None): ...
    def fetch_portfolio_transfer_bridges(self, portfolio_name: str): ...


DatabaseConnector = Callable[[str | None], PortfolioTwrDatabase]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calculate daily linked TWR for a SuperFolio portfolio.")
    parser.add_argument("--portfolio-name", required=True)
    parser.add_argument("--reporting-currency", required=True)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--flow-timing", choices=["end", "start"], default="start")
    parser.add_argument("--start-date", type=date.fromisoformat, default=None)
    parser.add_argument("--end-date", type=date.fromisoformat, default=None)
    parser.add_argument("--daily-output", type=Path, default=None)
    return parser


def run(
    argv: list[str] | None = None,
    *,
    database_connector: DatabaseConnector = connect_database,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.start_date is not None and args.end_date is not None and args.start_date > args.end_date:
            raise RuntimeError("--start-date must be on or before --end-date")

        with database_connector(args.database_url) as database:
            accounts = database.fetch_portfolio_accounts(args.portfolio_name)
            nav_inputs = database.fetch_portfolio_nav_inputs(
                portfolio_name=args.portfolio_name,
                start_date=args.start_date,
                end_date=args.end_date,
            )
            cash_flows = database.fetch_portfolio_cash_flows(
                portfolio_name=args.portfolio_name,
                start_date=args.start_date,
                end_date=args.end_date,
            )
            bridges = database.fetch_portfolio_transfer_bridges(args.portfolio_name)

        rows = calculate_portfolio_twr(
            reporting_currency=args.reporting_currency,
            accounts=accounts,
            nav_inputs=nav_inputs,
            cash_flows=cash_flows,
            transfer_bridges=bridges,
            flow_timing=args.flow_timing,
        )

        if args.daily_output is not None:
            write_portfolio_daily_twr_csv(args.daily_output, rows)

        _print_summary(
            portfolio_name=args.portfolio_name,
            reporting_currency=args.reporting_currency,
            account_count=len(accounts),
            nav_row_count=len(nav_inputs),
            cash_flow_count=len(cash_flows),
            bridge_count=len(bridges),
            rows=rows,
            daily_output=args.daily_output,
            stdout=stdout,
        )
        return 0
    except Exception as error:
        stderr.write(f"Error: {error}\n")
        return 1


def _print_summary(
    *,
    portfolio_name: str,
    reporting_currency: str,
    account_count: int,
    nav_row_count: int,
    cash_flow_count: int,
    bridge_count: int,
    rows: list,
    daily_output: Path | None,
    stdout: TextIO,
) -> None:
    completed_rows = [row for row in rows if row.period_return is not None]
    final_twr = rows[-1].cumulative_twr if rows else Decimal("0")
    stdout.write(f"Portfolio: {portfolio_name}\n")
    stdout.write(f"Reporting currency: {reporting_currency}\n")
    stdout.write(f"Member accounts: {account_count}\n")
    stdout.write(f"NAV rows: {nav_row_count}\n")
    stdout.write(f"Cash-flow records: {cash_flow_count}\n")
    stdout.write(f"Transfer bridges: {bridge_count}\n")
    stdout.write(f"Return periods: {len(completed_rows)}\n")
    stdout.write(f"Date range: {rows[0].report_date} to {rows[-1].report_date}\n")
    counts: Counter[str] = missing_nav_counts(rows)
    if counts:
        stdout.write("Missing NAV warnings:\n")
        for account_label, count in sorted(counts.items()):
            stdout.write(f"  {account_label}: {count}\n")
    stdout.write(f"TWR: {final_twr * Decimal('100'):.6f}%\n")
    if daily_output is not None:
        stdout.write(f"Daily output written to {daily_output}\n")


def main(argv: list[str] | None = None) -> int:
    return run(argv)
```

- [ ] **Step 4: Create script wrapper**

Create `scripts/calculate_portfolio_twr_from_db.py` with this content:

```python
#!/usr/bin/env python3
"""CLI for calculating portfolio TWR from database facts."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from portfolio_engine.portfolio_db_twr import main


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python -m unittest tests.test_portfolio_db_twr -v
```

Expected: tests pass.

Commit:

```bash
git add portfolio_engine/portfolio_db_twr.py scripts/calculate_portfolio_twr_from_db.py tests/test_portfolio_db_twr.py
git commit -m "feat: add portfolio TWR database CLI" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 9: Update documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/database/schema.md`
- Modify: `docs/database/functions.md`

- [ ] **Step 1: Update README**

Add this section after the database-backed TWR CLI section in `README.md`:

````markdown
### Managing consolidated portfolios

Create a logical portfolio and attach existing registered accounts:

```bash
python scripts/manage_portfolio.py create \
  --name "All Accounts" \
  --reporting-currency USD

python scripts/manage_portfolio.py attach-account \
  --portfolio-name "All Accounts" \
  --brokerage-code IBKR \
  --account-external-id U100
```

Transfer bridges can cover assets that are temporarily outside account NAV during an internal transfer:

```bash
python scripts/manage_portfolio.py create-bridge \
  --portfolio-name "All Accounts" \
  --source-brokerage-code IBKR \
  --source-account-external-id U100 \
  --destination-brokerage-code IBKR \
  --destination-account-external-id U200 \
  --departure-date 2026-01-02 \
  --arrival-date 2026-01-04 \
  --value 5000.00 \
  --currency USD
```

### Running portfolio-level database TWR

```bash
python scripts/calculate_portfolio_twr_from_db.py \
  --portfolio-name "All Accounts" \
  --reporting-currency USD \
  --start-date 2026-01-01 \
  --end-date 2026-01-31 \
  --daily-output output/portfolio-twr.csv
```

The command prints a portfolio summary to stdout. The optional daily CSV includes portfolio NAV, net external cash flow, transfer bridge value, missing-NAV diagnostics, period return, and cumulative TWR.
````

- [ ] **Step 2: Update database schema docs**

Add portfolio tables to `docs/database/schema.md` under the Tables section:

```markdown
### `portfolios`

Stores saved portfolio calculation/view definitions. A portfolio has a display name, reporting currency, active flag, and references brokerage accounts through `portfolio_accounts`.

### `portfolio_accounts`

Stores many-to-many membership between portfolios and brokerage accounts. An account can belong to multiple portfolios. Inactive accounts still contribute historical data when they are members.

### `portfolio_transfer_bridges`

Stores explicit in-transit transfer adjustments for a portfolio. Source and destination accounts must both be portfolio members, bridge currency must match the portfolio reporting currency, and overlapping bridge windows for the same source/destination account pair are rejected.
```

- [ ] **Step 3: Update function docs**

Add these rows to `docs/database/functions.md` under Python adapter:

```markdown
| `create_portfolio(...)` | `public.create_portfolio(...)` |
| `attach_portfolio_account(...)` | `public.attach_portfolio_account(...)` |
| `create_portfolio_transfer_bridge(...)` | `public.create_portfolio_transfer_bridge(...)` |
```

Add this section:

```markdown
## Portfolio functions

| Function | Purpose |
| --- | --- |
| `create_portfolio(...)` | Creates or updates a named portfolio with a reporting currency. |
| `attach_portfolio_account(...)` | Attaches an existing registered brokerage account to a portfolio. |
| `create_portfolio_transfer_bridge(...)` | Adds an in-transit transfer bridge after validating portfolio membership, date order, currency, and overlapping bridge windows. |
```

- [ ] **Step 4: Run focused documentation check**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all tests pass.

Commit:

```bash
git add README.md docs/database/schema.md docs/database/functions.md
git commit -m "docs: document portfolio layer workflows" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 10: Final verification

**Files:**
- No new files.

- [ ] **Step 1: Run the full Python test suite**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Inspect git status**

Run:

```bash
git --no-pager status --short --branch
```

Expected: branch is clean except for intentional uncommitted changes if the user asked not to commit during execution.

- [ ] **Step 3: Resolve any remaining uncommitted changes**

If Step 2 shows uncommitted changes, do not make a catch-all commit. Inspect the file list and return to the task whose commit step owns those files:

```bash
git --no-pager diff --name-only
```

Expected: either the branch is clean, or each listed file maps to a prior task with an exact commit command.

## Self-review notes

- Spec coverage: the plan covers portfolio model, multi-portfolio account membership, inactive account history, transfer bridge validation, union-of-NAV-date aggregation, missing NAV warnings, optional CSV, currency validation, CLI management, database function boundaries, docs, and tests.
- Scope: the plan does not add UI/API, automatic FX conversion, position-level valuation, account membership windows, or special zero/undefined TWR handling, matching the spec non-goals.
- Test strategy: each implementation task starts with a failing `unittest` test and uses the existing repository command `python -m unittest discover -s tests -v` for final verification.
