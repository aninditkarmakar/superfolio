# Automated Ingestion Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Subagent-driven execution should use `claude-sonnet-4.6` minimum for implementation subagents.

**Goal:** Build manual-trigger-ready automated ingestion infrastructure with parent automation jobs, account-level child outcomes, a broker-agnostic orchestrator, and a GitHub Actions manual workflow for IBKR Flex Web Service ingestion.

**Architecture:** Add a Sqitch migration for `automation_jobs` and `automation_job_accounts`, expose all automation lifecycle writes through PostgreSQL functions and `SuperFolioDatabase`, then build a small `portfolio_engine.automation` package around typed run requests, integration config, target resolution, adapter dispatch, status aggregation, locking/recovery, and workflow-safe CLI output. The initial IBKR adapter is contract-complete but fetch-internals are intentionally stubbed behind a narrow interface so the later IBKR Web Service design can define authentication/request mechanics.

**Tech Stack:** Python 3.12, `unittest`, PostgreSQL/Sqitch migrations, `psycopg[binary]`, GitHub Actions `workflow_dispatch`, standard-library XML parsing and dataclasses.

---

## Scope and execution notes

- Do not enable a cron schedule.
- Do not build UI/API surfaces.
- Do not implement full IBKR Flex Web Service auth/request internals in this plan. The adapter should expose the required boundary and a deterministic placeholder/fake-friendly implementation path.
- Preserve privacy-safe behavior: no raw XML, credentials, DB URLs, NAV values, cash values, or full broker responses in DB summaries/errors or workflow output.
- Use `python -m unittest discover -s tests -v` for full test verification.
- Commit after each task using the commit messages listed in the task.

## File structure

### Migrations and database docs

- Create `migrations/deploy/create_automation_layer.sql`
  - Tables: `automation_jobs`, `automation_job_accounts`.
  - Functions for job lifecycle, target resolution, stale cleanup, and overlap checks.
- Create `migrations/revert/create_automation_layer.sql`
  - Drops automation functions and tables in dependency order.
- Create `migrations/verify/create_automation_layer.sql`
  - Verifies tables, constraints, functions, dry-run/load behavior, summaries, active-only target resolution, and overlap detection.
- Modify `migrations/sqitch.plan`
  - Add `create_automation_layer` after `create_portfolio_layer`.
- Modify `docs/database/schema.md`
  - Document automation tables and relationships.
- Modify `docs/database/functions.md`
  - Document automation function contracts.

### Python database adapter and models

- Modify `portfolio_engine/models.py`
  - Add automation dataclasses for job/account refs and resolved targets if shared outside database adapter.
- Modify `portfolio_engine/database.py`
  - Add dataclasses for automation lifecycle requests/results.
  - Add `SuperFolioDatabase` methods wrapping PostgreSQL automation functions.
  - Keep direct SQL reads/writes out of orchestrator code.
- Modify `tests/test_database_adapter.py`
  - Cover adapter methods, SQL function calls, JSON parameter handling, commits/rollbacks, and active-only resolution methods.

### Automation package

- Create `portfolio_engine/automation/__init__.py`
  - Package marker and public exports.
- Create `portfolio_engine/automation/config.py`
  - Load `integrations.yaml`, validate required keys, expose typed integration config.
- Create `portfolio_engine/automation/integrations.yaml`
  - Initial `ibkr_flex_ws` mapping to `IBKR`, `FLEX_WEB_SERVICE`, supported modes, required env keys, and default stale-running timeout.
- Create `portfolio_engine/automation/types.py`
  - Run request, target type, mode, status, account target, summaries, adapter protocol.
- Create `portfolio_engine/automation/sanitization.py`
  - Sanitized error categories/messages and summary helpers.
- Create `portfolio_engine/automation/summary.py`
  - Stable child and parent summary builders.
- Create `portfolio_engine/automation/targets.py`
  - Account input parsing, target validation, and resolved-account coordination through database adapter.
- Create `portfolio_engine/automation/adapters.py`
  - Adapter registry and IBKR adapter class boundary.
- Create `portfolio_engine/automation/orchestrator.py`
  - Main orchestration flow, preflight persistence, stale cleanup, account loop, dry-run/load routing, status aggregation.
- Create `portfolio_engine/automation/cli.py`
  - CLI entrypoint for GitHub Actions manual workflow.

### Scripts and workflow

- Create `scripts/run_automated_ingestion.py`
  - Thin wrapper around `portfolio_engine.automation.cli.main`.
- Create `.github/workflows/manual-ingestion.yml`
  - Manual-only `workflow_dispatch` with broad optional inputs and no schedule.

### Tests

- Create `tests/test_automation_config.py`
- Create `tests/test_automation_targets.py`
- Create `tests/test_automation_summary.py`
- Create `tests/test_automation_orchestrator.py`
- Create `tests/test_automation_cli.py`
- Create `tests/test_automation_workflow.py`
- Modify `tests/test_migrations.py`
  - Add migration/revert/verify checks for automation layer files and function signatures.

---

### Task 1: Add automation database migration skeleton and plan entry

**Files:**
- Create: `migrations/deploy/create_automation_layer.sql`
- Create: `migrations/revert/create_automation_layer.sql`
- Create: `migrations/verify/create_automation_layer.sql`
- Modify: `migrations/sqitch.plan`
- Test: `tests/test_migrations.py`

- [ ] **Step 1: Write failing migration-plan tests**

Add these tests to `tests/test_migrations.py`:

```python
    def test_automation_layer_is_registered_after_portfolio_layer(self) -> None:
        plan = Path("migrations/sqitch.plan").read_text(encoding="utf-8")

        portfolio_pos = plan.index("create_portfolio_layer")
        automation_pos = plan.index("create_automation_layer")

        self.assertLess(portfolio_pos, automation_pos)

    def test_automation_layer_migration_files_exist(self) -> None:
        for path in (
            Path("migrations/deploy/create_automation_layer.sql"),
            Path("migrations/revert/create_automation_layer.sql"),
            Path("migrations/verify/create_automation_layer.sql"),
        ):
            self.assertTrue(path.exists(), f"missing {path}")
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
python -m unittest tests.test_migrations -v
```

Expected: failure mentioning missing `create_automation_layer` in `migrations/sqitch.plan` or missing migration files.

- [ ] **Step 3: Add migration files and Sqitch plan entry**

Create `migrations/deploy/create_automation_layer.sql`:

```sql
-- Deploy superfolio:create_automation_layer to pg

BEGIN;

COMMIT;
```

Create `migrations/revert/create_automation_layer.sql`:

```sql
-- Revert superfolio:create_automation_layer from pg

BEGIN;

COMMIT;
```

Create `migrations/verify/create_automation_layer.sql`:

```sql
-- Verify superfolio:create_automation_layer on pg

SELECT 1;
```

Append this line to `migrations/sqitch.plan` after `create_portfolio_layer`:

```text
create_automation_layer 2026-05-14T00:00:00Z node <node@automation-layer> # Create automation ingestion job schema
```

- [ ] **Step 4: Run the migration-plan tests**

Run:

```bash
python -m unittest tests.test_migrations -v
```

Expected: migration-plan tests pass.

- [ ] **Step 5: Commit**

```bash
git add migrations/sqitch.plan migrations/deploy/create_automation_layer.sql migrations/revert/create_automation_layer.sql migrations/verify/create_automation_layer.sql tests/test_migrations.py
git commit -m "test: register automation layer migration"
```

---

### Task 2: Create automation tables and constraints

**Files:**
- Modify: `migrations/deploy/create_automation_layer.sql`
- Modify: `migrations/revert/create_automation_layer.sql`
- Modify: `migrations/verify/create_automation_layer.sql`
- Modify: `tests/test_migrations.py`

- [ ] **Step 1: Write failing tests for table definitions and constraints**

Add to `tests/test_migrations.py`:

```python
    def test_automation_layer_defines_parent_and_child_tables(self) -> None:
        sql = Path("migrations/deploy/create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE public.automation_jobs", sql)
        self.assertIn("CREATE TABLE public.automation_job_accounts", sql)
        self.assertIn("summary JSONB", sql)
        self.assertIn("automation_jobs_target_type_check", sql)
        self.assertIn("automation_jobs_portfolio_target_check", sql)
        self.assertIn("automation_jobs_manual_dates_required_check", sql)
        self.assertIn("automation_job_accounts_unique_account", sql)

    def test_automation_layer_revert_drops_child_before_parent(self) -> None:
        sql = Path("migrations/revert/create_automation_layer.sql").read_text(encoding="utf-8")

        child_pos = sql.index("DROP TABLE IF EXISTS public.automation_job_accounts")
        parent_pos = sql.index("DROP TABLE IF EXISTS public.automation_jobs")

        self.assertLess(child_pos, parent_pos)
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python -m unittest tests.test_migrations -v
```

Expected: failure because table definitions and constraints do not exist yet.

- [ ] **Step 3: Implement deploy table SQL**

Replace `migrations/deploy/create_automation_layer.sql` with:

```sql
-- Deploy superfolio:create_automation_layer to pg

BEGIN;

CREATE TABLE public.automation_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_type VARCHAR(30) NOT NULL,
    target_type VARCHAR(30) NOT NULL,
    portfolio_id UUID REFERENCES public.portfolios(id),
    integration_key VARCHAR(100) NOT NULL,
    mode VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL,
    summary JSONB,
    requested_start_date DATE NOT NULL,
    requested_end_date DATE NOT NULL,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT automation_jobs_trigger_type_check CHECK (
        trigger_type IN ('manual', 'scheduled')
    ),
    CONSTRAINT automation_jobs_target_type_check CHECK (
        target_type IN ('portfolio', 'accounts')
    ),
    CONSTRAINT automation_jobs_portfolio_target_check CHECK (
        (target_type = 'portfolio' AND portfolio_id IS NOT NULL)
        OR (target_type = 'accounts' AND portfolio_id IS NULL)
    ),
    CONSTRAINT automation_jobs_integration_key_not_blank_check CHECK (btrim(integration_key) <> ''),
    CONSTRAINT automation_jobs_mode_check CHECK (mode IN ('dry-run', 'load')),
    CONSTRAINT automation_jobs_status_check CHECK (
        status IN ('pending', 'running', 'succeeded', 'partially_succeeded', 'failed')
    ),
    CONSTRAINT automation_jobs_manual_dates_required_check CHECK (
        trigger_type <> 'manual'
        OR (requested_start_date IS NOT NULL AND requested_end_date IS NOT NULL)
    ),
    CONSTRAINT automation_jobs_requested_date_range_check CHECK (
        requested_start_date <= requested_end_date
    ),
    CONSTRAINT automation_jobs_completed_after_started_check CHECK (
        completed_at IS NULL OR completed_at >= started_at
    )
);

CREATE TABLE public.automation_job_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    automation_job_id UUID NOT NULL REFERENCES public.automation_jobs(id) ON DELETE CASCADE,
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    status VARCHAR(30) NOT NULL,
    ingestion_run_id UUID REFERENCES public.ingestion_runs(id),
    summary JSONB,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT automation_job_accounts_unique_account UNIQUE (automation_job_id, account_id),
    CONSTRAINT automation_job_accounts_status_check CHECK (
        status IN ('pending', 'running', 'succeeded', 'partially_succeeded', 'failed')
    ),
    CONSTRAINT automation_job_accounts_completed_after_started_check CHECK (
        completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at
    )
);

CREATE INDEX automation_jobs_status_started_at_idx
    ON public.automation_jobs (status, started_at);

CREATE INDEX automation_jobs_integration_mode_dates_idx
    ON public.automation_jobs (integration_key, mode, requested_start_date, requested_end_date);

CREATE INDEX automation_job_accounts_account_status_idx
    ON public.automation_job_accounts (account_id, status);

CREATE INDEX automation_job_accounts_ingestion_run_id_idx
    ON public.automation_job_accounts (ingestion_run_id);

COMMIT;
```

- [ ] **Step 4: Implement revert table SQL**

Replace `migrations/revert/create_automation_layer.sql` with:

```sql
-- Revert superfolio:create_automation_layer from pg

BEGIN;

DROP TABLE IF EXISTS public.automation_job_accounts;
DROP TABLE IF EXISTS public.automation_jobs;

COMMIT;
```

- [ ] **Step 5: Implement verify table checks**

Replace `migrations/verify/create_automation_layer.sql` with:

```sql
-- Verify superfolio:create_automation_layer on pg

SELECT id, trigger_type, target_type, portfolio_id, integration_key, mode, status,
       summary, requested_start_date, requested_end_date, error_message,
       started_at, completed_at, created_at
FROM public.automation_jobs
WHERE false;

SELECT id, automation_job_id, account_id, status, ingestion_run_id, summary,
       error_message, started_at, completed_at, created_at
FROM public.automation_job_accounts
WHERE false;

SELECT 1
FROM pg_constraint
WHERE conname IN (
    'automation_jobs_target_type_check',
    'automation_jobs_portfolio_target_check',
    'automation_jobs_manual_dates_required_check',
    'automation_job_accounts_unique_account'
)
HAVING count(*) = 4;
```

- [ ] **Step 6: Run tests**

Run:

```bash
python -m unittest tests.test_migrations -v
```

Expected: migration tests pass.

- [ ] **Step 7: Commit**

```bash
git add migrations/deploy/create_automation_layer.sql migrations/revert/create_automation_layer.sql migrations/verify/create_automation_layer.sql tests/test_migrations.py
git commit -m "feat: add automation job tables"
```

---

### Task 3: Add PostgreSQL automation lifecycle functions

**Files:**
- Modify: `migrations/deploy/create_automation_layer.sql`
- Modify: `migrations/revert/create_automation_layer.sql`
- Modify: `migrations/verify/create_automation_layer.sql`
- Modify: `tests/test_migrations.py`

- [ ] **Step 1: Write failing tests for function signatures**

Add to `tests/test_migrations.py`:

```python
    def test_automation_layer_defines_lifecycle_functions(self) -> None:
        sql = Path("migrations/deploy/create_automation_layer.sql").read_text(encoding="utf-8")

        for name in (
            "public.create_automation_job",
            "public.finalize_automation_job",
            "public.add_automation_job_account",
            "public.mark_automation_job_account_running",
            "public.finalize_automation_job_account",
        ):
            self.assertIn(f"CREATE FUNCTION {name}", sql)

    def test_automation_layer_revert_drops_lifecycle_functions(self) -> None:
        sql = Path("migrations/revert/create_automation_layer.sql").read_text(encoding="utf-8")

        for name in (
            "public.finalize_automation_job_account",
            "public.mark_automation_job_account_running",
            "public.add_automation_job_account",
            "public.finalize_automation_job",
            "public.create_automation_job",
        ):
            self.assertIn(f"DROP FUNCTION IF EXISTS {name}", sql)
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python -m unittest tests.test_migrations -v
```

Expected: failure because lifecycle functions do not exist in deploy/revert SQL.

- [ ] **Step 3: Add lifecycle functions to deploy SQL before `COMMIT;`**

Append to `migrations/deploy/create_automation_layer.sql` before `COMMIT;`:

```sql
CREATE FUNCTION public.create_automation_job(
    p_trigger_type TEXT,
    p_target_type TEXT,
    p_portfolio_id UUID,
    p_integration_key TEXT,
    p_mode TEXT,
    p_requested_start_date DATE,
    p_requested_end_date DATE
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_id UUID;
    v_trigger_type TEXT;
    v_target_type TEXT;
    v_integration_key TEXT;
    v_mode TEXT;
BEGIN
    v_trigger_type := lower(btrim(p_trigger_type));
    v_target_type := lower(btrim(p_target_type));
    v_integration_key := lower(btrim(p_integration_key));
    v_mode := lower(btrim(p_mode));

    IF v_trigger_type = '' OR v_target_type = '' OR v_integration_key = '' OR v_mode = '' THEN
        RAISE EXCEPTION 'automation job trigger_type, target_type, integration_key, and mode must not be blank';
    END IF;

    INSERT INTO public.automation_jobs (
        trigger_type,
        target_type,
        portfolio_id,
        integration_key,
        mode,
        status,
        requested_start_date,
        requested_end_date
    )
    VALUES (
        v_trigger_type,
        v_target_type,
        p_portfolio_id,
        v_integration_key,
        v_mode,
        'running',
        p_requested_start_date,
        p_requested_end_date
    )
    RETURNING id INTO v_job_id;

    RETURN v_job_id;
END;
$$;

CREATE FUNCTION public.finalize_automation_job(
    p_automation_job_id UUID,
    p_status TEXT,
    p_summary JSONB DEFAULT NULL,
    p_error_message TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_id UUID;
    v_status TEXT;
BEGIN
    v_status := lower(btrim(p_status));

    UPDATE public.automation_jobs
    SET status = v_status,
        summary = p_summary,
        error_message = NULLIF(btrim(p_error_message), ''),
        completed_at = now()
    WHERE id = p_automation_job_id
      AND status IN ('pending', 'running')
    RETURNING id INTO v_job_id;

    IF v_job_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or already completed automation job id: %', p_automation_job_id;
    END IF;

    RETURN v_job_id;
END;
$$;

CREATE FUNCTION public.add_automation_job_account(
    p_automation_job_id UUID,
    p_account_id UUID
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_account_id UUID;
BEGIN
    INSERT INTO public.automation_job_accounts (
        automation_job_id,
        account_id,
        status
    )
    VALUES (
        p_automation_job_id,
        p_account_id,
        'pending'
    )
    RETURNING id INTO v_job_account_id;

    RETURN v_job_account_id;
END;
$$;

CREATE FUNCTION public.mark_automation_job_account_running(
    p_automation_job_account_id UUID
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_account_id UUID;
BEGIN
    UPDATE public.automation_job_accounts
    SET status = 'running',
        started_at = now()
    WHERE id = p_automation_job_account_id
      AND status = 'pending'
    RETURNING id INTO v_job_account_id;

    IF v_job_account_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or non-pending automation job account id: %', p_automation_job_account_id;
    END IF;

    RETURN v_job_account_id;
END;
$$;

CREATE FUNCTION public.finalize_automation_job_account(
    p_automation_job_account_id UUID,
    p_status TEXT,
    p_ingestion_run_id UUID DEFAULT NULL,
    p_summary JSONB DEFAULT NULL,
    p_error_message TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_account_id UUID;
    v_status TEXT;
BEGIN
    v_status := lower(btrim(p_status));

    UPDATE public.automation_job_accounts
    SET status = v_status,
        ingestion_run_id = p_ingestion_run_id,
        summary = p_summary,
        error_message = NULLIF(btrim(p_error_message), ''),
        completed_at = now()
    WHERE id = p_automation_job_account_id
      AND status IN ('pending', 'running')
    RETURNING id INTO v_job_account_id;

    IF v_job_account_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or already completed automation job account id: %', p_automation_job_account_id;
    END IF;

    RETURN v_job_account_id;
END;
$$;
```

- [ ] **Step 4: Add lifecycle drops to revert SQL before table drops**

Insert before `DROP TABLE IF EXISTS public.automation_job_accounts;`:

```sql
DROP FUNCTION IF EXISTS public.finalize_automation_job_account(UUID, TEXT, UUID, JSONB, TEXT);
DROP FUNCTION IF EXISTS public.mark_automation_job_account_running(UUID);
DROP FUNCTION IF EXISTS public.add_automation_job_account(UUID, UUID);
DROP FUNCTION IF EXISTS public.finalize_automation_job(UUID, TEXT, JSONB, TEXT);
DROP FUNCTION IF EXISTS public.create_automation_job(TEXT, TEXT, UUID, TEXT, TEXT, DATE, DATE);
```

- [ ] **Step 5: Add function existence checks to verify SQL**

Append to `migrations/verify/create_automation_layer.sql`:

```sql
SELECT 1
WHERE to_regprocedure('public.create_automation_job(text,text,uuid,text,text,date,date)') IS NOT NULL
  AND to_regprocedure('public.finalize_automation_job(uuid,text,jsonb,text)') IS NOT NULL
  AND to_regprocedure('public.add_automation_job_account(uuid,uuid)') IS NOT NULL
  AND to_regprocedure('public.mark_automation_job_account_running(uuid)') IS NOT NULL
  AND to_regprocedure('public.finalize_automation_job_account(uuid,text,uuid,jsonb,text)') IS NOT NULL;
```

- [ ] **Step 6: Run tests**

Run:

```bash
python -m unittest tests.test_migrations -v
```

Expected: migration tests pass.

- [ ] **Step 7: Commit**

```bash
git add migrations/deploy/create_automation_layer.sql migrations/revert/create_automation_layer.sql migrations/verify/create_automation_layer.sql tests/test_migrations.py
git commit -m "feat: add automation lifecycle functions"
```

---

### Task 4: Add target-resolution and stale-cleanup PostgreSQL functions

**Files:**
- Modify: `migrations/deploy/create_automation_layer.sql`
- Modify: `migrations/revert/create_automation_layer.sql`
- Modify: `migrations/verify/create_automation_layer.sql`
- Modify: `tests/test_migrations.py`

- [ ] **Step 1: Write failing tests for target and cleanup functions**

Add to `tests/test_migrations.py`:

```python
    def test_automation_layer_defines_target_and_cleanup_functions(self) -> None:
        sql = Path("migrations/deploy/create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE FUNCTION public.resolve_automation_portfolio_accounts", sql)
        self.assertIn("CREATE FUNCTION public.resolve_automation_account_targets", sql)
        self.assertIn("CREATE FUNCTION public.fail_stale_automation_runs", sql)
        self.assertIn("a.is_active = true", sql)
        self.assertIn("b.is_active = true", sql)
        self.assertIn("p.is_active = true", sql)
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python -m unittest tests.test_migrations -v
```

Expected: failure because target and cleanup functions do not exist yet.

- [ ] **Step 3: Add target-resolution and stale-cleanup functions**

Append to deploy SQL before `COMMIT;`:

```sql
CREATE FUNCTION public.resolve_automation_portfolio_accounts(
    p_portfolio_name TEXT,
    p_brokerage_code TEXT
)
RETURNS TABLE (
    account_id UUID,
    brokerage_code TEXT,
    account_external_id TEXT,
    base_currency TEXT,
    display_name TEXT
)
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_portfolio_name IS NULL OR btrim(p_portfolio_name) = '' THEN
        RAISE EXCEPTION 'target_type=portfolio requires portfolio_name';
    END IF;

    RETURN QUERY
    SELECT a.id, b.code::TEXT, a.external_id::TEXT, a.base_currency::TEXT, a.display_name::TEXT
    FROM public.portfolio_accounts pa
    JOIN public.portfolios p ON p.id = pa.portfolio_id
    JOIN public.accounts a ON a.id = pa.account_id
    JOIN public.brokerages b ON b.id = a.brokerage_id
    WHERE p.name = btrim(p_portfolio_name)
      AND p.is_active = true
      AND a.is_active = true
      AND b.is_active = true
      AND b.code = upper(btrim(p_brokerage_code))
    ORDER BY b.code, a.external_id;
END;
$$;

CREATE FUNCTION public.resolve_automation_account_targets(
    p_brokerage_code TEXT,
    p_account_external_ids TEXT[]
)
RETURNS TABLE (
    account_id UUID,
    brokerage_code TEXT,
    account_external_id TEXT,
    base_currency TEXT,
    display_name TEXT
)
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_account_external_ids IS NULL OR array_length(p_account_external_ids, 1) IS NULL THEN
        RAISE EXCEPTION 'target_type=accounts requires account_external_ids';
    END IF;

    RETURN QUERY
    SELECT a.id, b.code::TEXT, a.external_id::TEXT, a.base_currency::TEXT, a.display_name::TEXT
    FROM public.accounts a
    JOIN public.brokerages b ON b.id = a.brokerage_id
    WHERE b.code = upper(btrim(p_brokerage_code))
      AND b.is_active = true
      AND a.is_active = true
      AND a.external_id = ANY(p_account_external_ids)
    ORDER BY b.code, a.external_id;
END;
$$;

CREATE FUNCTION public.fail_stale_automation_runs(
    p_stale_before TIMESTAMPTZ,
    p_error_message TEXT
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_child_count INTEGER;
    v_parent_count INTEGER;
BEGIN
    UPDATE public.automation_job_accounts
    SET status = 'failed',
        error_message = NULLIF(btrim(p_error_message), ''),
        completed_at = now()
    WHERE status = 'running'
      AND started_at < p_stale_before;
    GET DIAGNOSTICS v_child_count = ROW_COUNT;

    UPDATE public.automation_jobs
    SET status = 'failed',
        error_message = NULLIF(btrim(p_error_message), ''),
        completed_at = now()
    WHERE status = 'running'
      AND started_at < p_stale_before;
    GET DIAGNOSTICS v_parent_count = ROW_COUNT;

    RETURN v_child_count + v_parent_count;
END;
$$;
```

- [ ] **Step 4: Add drops and verify checks**

Add to revert SQL before lifecycle drops:

```sql
DROP FUNCTION IF EXISTS public.fail_stale_automation_runs(TIMESTAMPTZ, TEXT);
DROP FUNCTION IF EXISTS public.resolve_automation_account_targets(TEXT, TEXT[]);
DROP FUNCTION IF EXISTS public.resolve_automation_portfolio_accounts(TEXT, TEXT);
```

Append to verify SQL:

```sql
SELECT 1
WHERE to_regprocedure('public.resolve_automation_portfolio_accounts(text,text)') IS NOT NULL
  AND to_regprocedure('public.resolve_automation_account_targets(text,text[])') IS NOT NULL
  AND to_regprocedure('public.fail_stale_automation_runs(timestamptz,text)') IS NOT NULL;
```

- [ ] **Step 5: Run tests**

Run:

```bash
python -m unittest tests.test_migrations -v
```

Expected: migration tests pass.

- [ ] **Step 6: Commit**

```bash
git add migrations/deploy/create_automation_layer.sql migrations/revert/create_automation_layer.sql migrations/verify/create_automation_layer.sql tests/test_migrations.py
git commit -m "feat: add automation target resolution functions"
```

---

### Task 5: Add automation dataclasses and database adapter methods

**Files:**
- Modify: `portfolio_engine/database.py`
- Modify: `tests/test_database_adapter.py`

- [ ] **Step 1: Write failing database adapter tests**

Add imports to `tests/test_database_adapter.py`:

```python
from portfolio_engine.database import (
    AccountRegistration,
    AutomationAccountTarget,
    AutomationJobStart,
    AutomationJobAccountAdd,
    AutomationJobAccountFinalize,
    AutomationJobFinalize,
    BulkIngestionSummary,
    DatabaseConfigurationError,
    IngestionRunStart,
    SuperFolioDatabase,
    connect_database,
)
```

Add tests:

```python
    def test_create_automation_job_calls_database_function(self) -> None:
        connection = FakeConnection(("job-uuid",))
        database = SuperFolioDatabase(connection)

        job_id = database.create_automation_job(
            AutomationJobStart(
                trigger_type="manual",
                target_type="accounts",
                portfolio_id=None,
                integration_key="ibkr_flex_ws",
                mode="dry-run",
                requested_start_date=date(2026, 5, 1),
                requested_end_date=date(2026, 5, 14),
            )
        )

        self.assertEqual(job_id, "job-uuid")
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(
            connection.cursor_instance.executed[0],
            (
                "SELECT public.create_automation_job(%s, %s, %s, %s, %s, %s, %s)",
                ("manual", "accounts", None, "ibkr_flex_ws", "dry-run", date(2026, 5, 1), date(2026, 5, 14)),
            ),
        )

    def test_finalize_automation_job_passes_summary_json(self) -> None:
        connection = FakeConnection(("job-uuid",))
        database = SuperFolioDatabase(connection)

        result = database.finalize_automation_job(
            AutomationJobFinalize(
                automation_job_id="job-uuid",
                status="succeeded",
                summary={"account_counts": {"total": 1, "succeeded": 1, "partially_succeeded": 0, "failed": 0}},
                error_message=None,
            )
        )

        self.assertEqual(result, "job-uuid")
        sql, params = connection.cursor_instance.executed[0]
        self.assertEqual(sql, "SELECT public.finalize_automation_job(%s, %s, %s, %s)")
        self.assertEqual(params[0], "job-uuid")
        self.assertEqual(params[1], "succeeded")
        self.assertEqual(params[3], None)

    def test_resolve_automation_account_targets_maps_rows(self) -> None:
        connection = FakeConnection(
            rows=[("account-uuid", "IBKR", "U100", "USD", "Main")]
        )
        database = SuperFolioDatabase(connection)

        accounts = database.resolve_automation_account_targets(
            brokerage_code="IBKR",
            account_external_ids=["U100"],
        )

        self.assertEqual(
            accounts,
            [AutomationAccountTarget("account-uuid", "IBKR", "U100", "USD", "Main")],
        )
```

- [ ] **Step 2: Run failing database adapter tests**

Run:

```bash
python -m unittest tests.test_database_adapter -v
```

Expected: import errors for missing automation dataclasses/methods.

- [ ] **Step 3: Add dataclasses to `portfolio_engine/database.py`**

Add below `BulkIngestionSummary`:

```python
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
```

- [ ] **Step 4: Add methods to `SuperFolioDatabase`**

Add methods after `complete_ingestion_run`:

```python
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
            "SELECT public.add_automation_job_account(%s, %s)",
            (request.automation_job_id, request.account_id),
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

    def fail_stale_automation_runs(self, *, stale_before: date, error_message: str) -> int:
        row = self._fetch_one(
            "SELECT public.fail_stale_automation_runs(%s, %s)",
            (stale_before, error_message),
        )
        return int(row[0])
```

Add helper above `connect_database`:

```python
def _automation_account_target_from_row(row: tuple[Any, ...]) -> AutomationAccountTarget:
    return AutomationAccountTarget(
        account_id=str(row[0]),
        brokerage_code=str(row[1]),
        account_external_id=str(row[2]),
        base_currency=str(row[3]),
        display_name=None if row[4] is None else str(row[4]),
    )
```

- [ ] **Step 5: Run database adapter tests**

Run:

```bash
python -m unittest tests.test_database_adapter -v
```

Expected: database adapter tests pass.

- [ ] **Step 6: Commit**

```bash
git add portfolio_engine/database.py tests/test_database_adapter.py
git commit -m "feat: add automation database adapter methods"
```

---

### Task 6: Add automation types, config loader, and integration config

**Files:**
- Create: `portfolio_engine/automation/__init__.py`
- Create: `portfolio_engine/automation/types.py`
- Create: `portfolio_engine/automation/config.py`
- Create: `portfolio_engine/automation/integrations.yaml`
- Create: `tests/test_automation_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/test_automation_config.py`:

```python
from __future__ import annotations

import unittest

from portfolio_engine.automation.config import load_integration_config


class AutomationConfigTests(unittest.TestCase):
    def test_load_ibkr_flex_ws_config(self) -> None:
        config = load_integration_config("ibkr_flex_ws")

        self.assertEqual(config.integration_key, "ibkr_flex_ws")
        self.assertEqual(config.brokerage_code, "IBKR")
        self.assertEqual(config.source_type, "FLEX_WEB_SERVICE")
        self.assertIn("dry-run", config.supported_modes)
        self.assertIn("load", config.supported_modes)
        self.assertGreater(config.stale_running_timeout_minutes, 0)

    def test_unknown_integration_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown integration"):
            load_integration_config("missing")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing config tests**

Run:

```bash
python -m unittest tests.test_automation_config -v
```

Expected: import failure because automation package does not exist.

- [ ] **Step 3: Create automation package and types**

Create `portfolio_engine/automation/__init__.py`:

```python
"""Automation infrastructure for broker ingestion jobs."""
```

Create `portfolio_engine/automation/types.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from portfolio_engine.database import AutomationAccountTarget, BulkIngestionSummary


VALID_TARGET_TYPES = frozenset({"portfolio", "accounts"})
VALID_MODES = frozenset({"dry-run", "load"})
VALID_STATUSES = frozenset({"pending", "running", "succeeded", "partially_succeeded", "failed"})


@dataclass(frozen=True)
class IntegrationConfig:
    integration_key: str
    brokerage_code: str
    source_type: str
    adapter_key: str
    supported_modes: tuple[str, ...]
    required_env_keys: tuple[str, ...]
    stale_running_timeout_minutes: int


@dataclass(frozen=True)
class AutomationRunRequest:
    target_type: str
    integration_key: str
    mode: str
    requested_start_date: date
    requested_end_date: date
    portfolio_name: str | None = None
    account_external_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class BrokerPayload:
    xml_text: str
    source_name: str | None = None


class BrokerAdapter(Protocol):
    def preflight_validate_config(self, config: IntegrationConfig) -> None: ...
    def fetch_payload(
        self,
        account: AutomationAccountTarget,
        request: AutomationRunRequest,
        config: IntegrationConfig,
    ) -> BrokerPayload: ...


@dataclass(frozen=True)
class AccountRunResult:
    status: str
    ingestion_run_id: str | None
    summary: dict[str, object]
    error_message: str | None = None
```

- [ ] **Step 4: Create `integrations.yaml`**

Create `portfolio_engine/automation/integrations.yaml`:

```yaml
integrations:
  ibkr_flex_ws:
    brokerage_code: IBKR
    source_type: FLEX_WEB_SERVICE
    adapter_key: ibkr_flex_ws
    supported_modes:
      - dry-run
      - load
    required_env_keys:
      - DATABASE_URL
      - IBKR_FLEX_TOKEN
      - IBKR_FLEX_QUERY_ID
    stale_running_timeout_minutes: 120
```

- [ ] **Step 5: Implement config loader**

Create `portfolio_engine/automation/config.py`:

```python
from __future__ import annotations

from pathlib import Path

from portfolio_engine.automation.types import IntegrationConfig


CONFIG_PATH = Path(__file__).with_name("integrations.yaml")


def load_integration_config(integration_key: str, path: Path = CONFIG_PATH) -> IntegrationConfig:
    key = integration_key.strip().lower()
    data = _load_simple_yaml(path)
    integrations = data.get("integrations", {})
    raw = integrations.get(key)
    if raw is None:
        raise ValueError(f"unknown integration: {integration_key}")

    return IntegrationConfig(
        integration_key=key,
        brokerage_code=str(raw["brokerage_code"]),
        source_type=str(raw["source_type"]),
        adapter_key=str(raw["adapter_key"]),
        supported_modes=tuple(str(mode) for mode in raw["supported_modes"]),
        required_env_keys=tuple(str(name) for name in raw["required_env_keys"]),
        stale_running_timeout_minutes=int(raw["stale_running_timeout_minutes"]),
    )


def _load_simple_yaml(path: Path) -> dict[str, object]:
    try:
        import yaml
    except ImportError as error:
        raise RuntimeError("PyYAML is required to read automation integration config") from error

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"invalid integration config file: {path}")
    return loaded
```

- [ ] **Step 6: Add PyYAML dependency**

Modify `requirements.txt` to include:

```text
PyYAML
```

Then run:

```bash
python -m pip install -r requirements.txt
```

Expected: dependencies install successfully.

- [ ] **Step 7: Run config tests**

Run:

```bash
python -m unittest tests.test_automation_config -v
```

Expected: tests pass.

- [ ] **Step 8: Commit**

```bash
git add portfolio_engine/automation/__init__.py portfolio_engine/automation/types.py portfolio_engine/automation/config.py portfolio_engine/automation/integrations.yaml tests/test_automation_config.py requirements.txt
git commit -m "feat: add automation integration config"
```

---

### Task 7: Add sanitized summaries and error helpers

**Files:**
- Create: `portfolio_engine/automation/sanitization.py`
- Create: `portfolio_engine/automation/summary.py`
- Create: `tests/test_automation_summary.py`

- [ ] **Step 1: Write failing summary tests**

Create `tests/test_automation_summary.py`:

```python
from __future__ import annotations

import unittest

from portfolio_engine.automation.sanitization import sanitize_error_message
from portfolio_engine.automation.summary import (
    empty_record_counts,
    build_child_summary,
    build_parent_summary,
)


class AutomationSummaryTests(unittest.TestCase):
    def test_empty_record_counts_shape(self) -> None:
        counts = empty_record_counts()

        self.assertEqual(counts["cash_flows"]["supported"], 0)
        self.assertEqual(counts["cash_flows"]["skipped_other_account"], 0)
        self.assertEqual(counts["daily_nav_snapshots"]["conflicts"], 0)

    def test_child_summary_excludes_values(self) -> None:
        summary = build_child_summary(
            cash_supported=2,
            nav_supported=1,
            cash_inserted=1,
            nav_inserted=0,
            cash_duplicates=1,
            nav_duplicates=1,
            cash_skipped_other_account=3,
            nav_skipped_other_account=4,
        )

        self.assertEqual(summary["record_counts"]["cash_flows"]["supported"], 2)
        self.assertEqual(summary["record_counts"]["cash_flows"]["duplicates"], 1)
        self.assertNotIn("amount", str(summary).lower())
        self.assertNotIn("nav_base", str(summary).lower())

    def test_parent_summary_aggregates_child_summaries(self) -> None:
        child = build_child_summary(cash_supported=1, nav_supported=2)

        parent = build_parent_summary(
            child_statuses=["succeeded", "failed"],
            child_summaries=[child, empty_record_counts()],
        )

        self.assertEqual(parent["account_counts"]["total"], 2)
        self.assertEqual(parent["account_counts"]["succeeded"], 1)
        self.assertEqual(parent["account_counts"]["failed"], 1)
        self.assertEqual(parent["record_counts"]["daily_nav_snapshots"]["supported"], 2)

    def test_sanitize_error_message_redacts_sensitive_text(self) -> None:
        message = sanitize_error_message(
            "DATABASE_URL=postgresql://secret token=abc amount=123.45 nav=999"
        )

        self.assertNotIn("postgresql://secret", message)
        self.assertNotIn("abc", message)
        self.assertIn("[redacted]", message)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing summary tests**

Run:

```bash
python -m unittest tests.test_automation_summary -v
```

Expected: import failure because summary modules do not exist.

- [ ] **Step 3: Implement sanitization helper**

Create `portfolio_engine/automation/sanitization.py`:

```python
from __future__ import annotations

import re


_SENSITIVE_PATTERNS = (
    re.compile(r"postgres(?:ql)?://\S+", re.IGNORECASE),
    re.compile(r"(token|password|secret|key)=\S+", re.IGNORECASE),
    re.compile(r"(amount|nav)=\S+", re.IGNORECASE),
)


def sanitize_error_message(message: str | None) -> str | None:
    if message is None:
        return None
    sanitized = message
    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[redacted]", sanitized)
    return sanitized[:500]
```

- [ ] **Step 4: Implement summary builders**

Create `portfolio_engine/automation/summary.py`:

```python
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any


RECORD_TYPES = ("cash_flows", "daily_nav_snapshots")
COUNT_KEYS = (
    "supported",
    "inserted",
    "duplicates",
    "skipped_unknown_account",
    "skipped_inactive_account",
    "skipped_other_account",
    "conflicts",
)


def empty_record_counts() -> dict[str, dict[str, int]]:
    return {record_type: {key: 0 for key in COUNT_KEYS} for record_type in RECORD_TYPES}


def build_child_summary(
    *,
    cash_supported: int = 0,
    nav_supported: int = 0,
    cash_inserted: int = 0,
    nav_inserted: int = 0,
    cash_duplicates: int = 0,
    nav_duplicates: int = 0,
    cash_skipped_unknown_account: int = 0,
    nav_skipped_unknown_account: int = 0,
    cash_skipped_inactive_account: int = 0,
    nav_skipped_inactive_account: int = 0,
    cash_skipped_other_account: int = 0,
    nav_skipped_other_account: int = 0,
    cash_conflicts: int = 0,
    nav_conflicts: int = 0,
    error_category: str | None = None,
) -> dict[str, Any]:
    counts = empty_record_counts()
    counts["cash_flows"].update(
        {
            "supported": cash_supported,
            "inserted": cash_inserted,
            "duplicates": cash_duplicates,
            "skipped_unknown_account": cash_skipped_unknown_account,
            "skipped_inactive_account": cash_skipped_inactive_account,
            "skipped_other_account": cash_skipped_other_account,
            "conflicts": cash_conflicts,
        }
    )
    counts["daily_nav_snapshots"].update(
        {
            "supported": nav_supported,
            "inserted": nav_inserted,
            "duplicates": nav_duplicates,
            "skipped_unknown_account": nav_skipped_unknown_account,
            "skipped_inactive_account": nav_skipped_inactive_account,
            "skipped_other_account": nav_skipped_other_account,
            "conflicts": nav_conflicts,
        }
    )
    summary: dict[str, Any] = {"record_counts": counts}
    if error_category is not None:
        summary["error_category"] = error_category
    return summary


def build_parent_summary(
    *,
    child_statuses: list[str],
    child_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    status_counts = Counter(child_statuses)
    aggregate = empty_record_counts()
    for summary in child_summaries:
        record_counts = summary.get("record_counts", summary)
        for record_type in RECORD_TYPES:
            for key in COUNT_KEYS:
                aggregate[record_type][key] += int(record_counts.get(record_type, {}).get(key, 0))

    return {
        "account_counts": {
            "total": len(child_statuses),
            "succeeded": status_counts["succeeded"],
            "partially_succeeded": status_counts["partially_succeeded"],
            "failed": status_counts["failed"],
        },
        "record_counts": deepcopy(aggregate),
    }
```

- [ ] **Step 5: Run summary tests**

Run:

```bash
python -m unittest tests.test_automation_summary -v
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add portfolio_engine/automation/sanitization.py portfolio_engine/automation/summary.py tests/test_automation_summary.py
git commit -m "feat: add automation summary helpers"
```

---

### Task 8: Add target parsing and validation

**Files:**
- Create: `portfolio_engine/automation/targets.py`
- Create: `tests/test_automation_targets.py`

- [ ] **Step 1: Write failing target tests**

Create `tests/test_automation_targets.py`:

```python
from __future__ import annotations

import unittest

from portfolio_engine.automation.targets import (
    AutomationValidationError,
    parse_account_external_ids,
    validate_target_inputs,
)


class AutomationTargetTests(unittest.TestCase):
    def test_parse_account_external_ids_trims_ignores_empty_and_deduplicates(self) -> None:
        self.assertEqual(
            parse_account_external_ids(" U100, ,U200,U100,, "),
            ("U100", "U200"),
        )

    def test_portfolio_target_requires_portfolio_name_and_rejects_accounts(self) -> None:
        with self.assertRaisesRegex(
            AutomationValidationError,
            "target_type=portfolio requires portfolio_name and rejects account_external_ids",
        ):
            validate_target_inputs(
                target_type="portfolio",
                portfolio_name=None,
                account_external_ids=("U100",),
            )

    def test_accounts_target_requires_accounts_and_rejects_portfolio_name(self) -> None:
        with self.assertRaisesRegex(
            AutomationValidationError,
            "target_type=accounts requires account_external_ids and rejects portfolio_name",
        ):
            validate_target_inputs(
                target_type="accounts",
                portfolio_name="All Accounts",
                account_external_ids=(),
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing target tests**

Run:

```bash
python -m unittest tests.test_automation_targets -v
```

Expected: import failure because target module does not exist.

- [ ] **Step 3: Implement target parsing and validation**

Create `portfolio_engine/automation/targets.py`:

```python
from __future__ import annotations


class AutomationValidationError(ValueError):
    """Raised when automation run inputs are invalid."""


def parse_account_external_ids(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    seen: set[str] = set()
    parsed: list[str] = []
    for token in value.split(","):
        account_id = token.strip()
        if not account_id:
            continue
        if account_id not in seen:
            seen.add(account_id)
            parsed.append(account_id)
    return tuple(parsed)


def validate_target_inputs(
    *,
    target_type: str,
    portfolio_name: str | None,
    account_external_ids: tuple[str, ...],
) -> None:
    normalized = target_type.strip().lower()
    has_portfolio = portfolio_name is not None and portfolio_name.strip() != ""
    has_accounts = bool(account_external_ids)

    if normalized == "portfolio":
        if not has_portfolio or has_accounts:
            raise AutomationValidationError(
                "target_type=portfolio requires portfolio_name and rejects account_external_ids"
            )
        return

    if normalized == "accounts":
        if not has_accounts or has_portfolio:
            raise AutomationValidationError(
                "target_type=accounts requires account_external_ids and rejects portfolio_name"
            )
        return

    raise AutomationValidationError("target_type must be portfolio or accounts")
```

- [ ] **Step 4: Run target tests**

Run:

```bash
python -m unittest tests.test_automation_targets -v
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add portfolio_engine/automation/targets.py tests/test_automation_targets.py
git commit -m "feat: add automation target validation"
```

---

### Task 9: Add adapter registry and IBKR adapter boundary

**Files:**
- Create: `portfolio_engine/automation/adapters.py`
- Create: `tests/test_automation_orchestrator.py`

- [ ] **Step 1: Write failing adapter registry tests**

Create `tests/test_automation_orchestrator.py` with the first test class:

```python
from __future__ import annotations

import os
import unittest
from datetime import date
from unittest.mock import patch

from portfolio_engine.database import AutomationAccountTarget
from portfolio_engine.automation.adapters import get_adapter
from portfolio_engine.automation.config import load_integration_config
from portfolio_engine.automation.types import AutomationRunRequest


class AutomationAdapterTests(unittest.TestCase):
    def test_get_ibkr_adapter(self) -> None:
        adapter = get_adapter("ibkr_flex_ws")

        self.assertEqual(adapter.__class__.__name__, "IbkrFlexWebServiceAdapter")

    def test_ibkr_adapter_preflight_requires_env_keys(self) -> None:
        adapter = get_adapter("ibkr_flex_ws")
        config = load_integration_config("ibkr_flex_ws")

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "missing required environment variables"):
                adapter.preflight_validate_config(config)
```

- [ ] **Step 2: Run failing adapter tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.AutomationAdapterTests -v
```

Expected: import failure because adapters module does not exist.

- [ ] **Step 3: Implement adapter registry and IBKR boundary**

Create `portfolio_engine/automation/adapters.py`:

```python
from __future__ import annotations

import os

from portfolio_engine.database import AutomationAccountTarget
from portfolio_engine.automation.types import AutomationRunRequest, BrokerPayload, IntegrationConfig


class IbkrFlexWebServiceAdapter:
    def preflight_validate_config(self, config: IntegrationConfig) -> None:
        missing = [
            key for key in config.required_env_keys
            if key != "DATABASE_URL" and not os.environ.get(key, "").strip()
        ]
        if missing:
            raise RuntimeError(
                "missing required environment variables: " + ", ".join(sorted(missing))
            )

    def fetch_payload(
        self,
        account: AutomationAccountTarget,
        request: AutomationRunRequest,
        config: IntegrationConfig,
    ) -> BrokerPayload:
        raise NotImplementedError(
            "IBKR Flex Web Service fetch internals require the follow-up IBKR fetch design"
        )


def get_adapter(adapter_key: str):
    normalized = adapter_key.strip().lower()
    if normalized == "ibkr_flex_ws":
        return IbkrFlexWebServiceAdapter()
    raise ValueError(f"unknown adapter: {adapter_key}")
```

- [ ] **Step 4: Run adapter tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.AutomationAdapterTests -v
```

Expected: adapter registry tests pass.

- [ ] **Step 5: Commit**

```bash
git add portfolio_engine/automation/adapters.py tests/test_automation_orchestrator.py
git commit -m "feat: add automation adapter registry"
```

---

### Task 10: Add orchestrator request validation, stale cleanup, and preflight failure persistence

**Files:**
- Create: `portfolio_engine/automation/orchestrator.py`
- Modify: `tests/test_automation_orchestrator.py`

- [ ] **Step 1: Add failing orchestrator tests**

Append to `tests/test_automation_orchestrator.py`:

```python
from portfolio_engine.automation.orchestrator import run_automation
from portfolio_engine.automation.types import AccountRunResult


class FakeAutomationDatabase:
    def __init__(self) -> None:
        self.created_jobs = []
        self.finalized_jobs = []
        self.fail_stale_calls = []
        self.portfolio_accounts = []
        self.account_targets = []

    def fail_stale_automation_runs(self, *, stale_before, error_message):
        self.fail_stale_calls.append((stale_before, error_message))
        return 0

    def create_automation_job(self, request):
        self.created_jobs.append(request)
        return "job-uuid"

    def finalize_automation_job(self, request):
        self.finalized_jobs.append(request)
        return request.automation_job_id

    def resolve_automation_portfolio_accounts(self, *, portfolio_name, brokerage_code):
        return self.portfolio_accounts

    def resolve_automation_account_targets(self, *, brokerage_code, account_external_ids):
        return self.account_targets


class AutomationOrchestratorValidationTests(unittest.TestCase):
    def test_preflight_failure_persists_failed_parent_job(self) -> None:
        database = FakeAutomationDatabase()
        request = AutomationRunRequest(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2026, 5, 1),
            requested_end_date=date(2026, 5, 14),
            account_external_ids=(),
        )

        result = run_automation(request, database=database)

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(database.created_jobs), 1)
        self.assertEqual(database.finalized_jobs[0].status, "failed")

    def test_stale_cleanup_runs_before_job_creation(self) -> None:
        database = FakeAutomationDatabase()
        request = AutomationRunRequest(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2026, 5, 1),
            requested_end_date=date(2026, 5, 14),
            account_external_ids=("U100",),
        )

        run_automation(request, database=database)

        self.assertEqual(len(database.fail_stale_calls), 1)
        self.assertEqual(len(database.created_jobs), 1)
```

- [ ] **Step 2: Run failing orchestrator validation tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.AutomationOrchestratorValidationTests -v
```

Expected: import failure because orchestrator module does not exist.

- [ ] **Step 3: Implement minimal orchestrator validation flow**

Create `portfolio_engine/automation/orchestrator.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from portfolio_engine.database import AutomationJobFinalize, AutomationJobStart
from portfolio_engine.automation.config import load_integration_config
from portfolio_engine.automation.sanitization import sanitize_error_message
from portfolio_engine.automation.summary import build_parent_summary
from portfolio_engine.automation.targets import AutomationValidationError, validate_target_inputs
from portfolio_engine.automation.types import AutomationRunRequest, VALID_MODES, VALID_TARGET_TYPES


@dataclass(frozen=True)
class AutomationRunResult:
    automation_job_id: str | None
    status: str
    summary: dict[str, Any]
    error_message: str | None = None


def run_automation(request: AutomationRunRequest, *, database) -> AutomationRunResult:
    config = load_integration_config(request.integration_key)
    stale_before = datetime.now(timezone.utc) - timedelta(minutes=config.stale_running_timeout_minutes)
    database.fail_stale_automation_runs(
        stale_before=stale_before,
        error_message="stale_run_timeout",
    )

    job_id = database.create_automation_job(
        AutomationJobStart(
            trigger_type="manual",
            target_type=request.target_type,
            portfolio_id=None,
            integration_key=request.integration_key,
            mode=request.mode,
            requested_start_date=request.requested_start_date,
            requested_end_date=request.requested_end_date,
        )
    )

    try:
        _validate_request(request)
    except Exception as error:
        message = sanitize_error_message(str(error))
        summary = build_parent_summary(child_statuses=[], child_summaries=[])
        database.finalize_automation_job(
            AutomationJobFinalize(
                automation_job_id=job_id,
                status="failed",
                summary=summary,
                error_message=message,
            )
        )
        return AutomationRunResult(job_id, "failed", summary, message)

    return AutomationRunResult(
        job_id,
        "failed",
        build_parent_summary(child_statuses=[], child_summaries=[]),
        "target execution not implemented yet",
    )


def _validate_request(request: AutomationRunRequest) -> None:
    if request.target_type not in VALID_TARGET_TYPES:
        raise AutomationValidationError("target_type must be portfolio or accounts")
    if request.mode not in VALID_MODES:
        raise AutomationValidationError("mode must be dry-run or load")
    if request.requested_start_date > request.requested_end_date:
        raise AutomationValidationError("requested_start_date must be on or before requested_end_date")
    validate_target_inputs(
        target_type=request.target_type,
        portfolio_name=request.portfolio_name,
        account_external_ids=request.account_external_ids,
    )
```

- [ ] **Step 4: Run orchestrator validation tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.AutomationOrchestratorValidationTests -v
```

Expected: validation tests pass.

- [ ] **Step 5: Commit**

```bash
git add portfolio_engine/automation/orchestrator.py tests/test_automation_orchestrator.py
git commit -m "feat: add automation orchestrator preflight"
```

---

### Task 11: Implement target resolution and child snapshot creation

**Files:**
- Modify: `portfolio_engine/automation/orchestrator.py`
- Modify: `tests/test_automation_orchestrator.py`

- [ ] **Step 1: Add failing target-resolution tests**

Append methods to `FakeAutomationDatabase` in `tests/test_automation_orchestrator.py`:

```python
        self.added_accounts = []

    def add_automation_job_account(self, request):
        child_id = f"child-{len(self.added_accounts) + 1}"
        self.added_accounts.append((child_id, request))
        return child_id
```

Add test:

```python
    def test_account_target_resolution_creates_child_rows(self) -> None:
        database = FakeAutomationDatabase()
        database.account_targets = [
            AutomationAccountTarget("account-uuid", "IBKR", "U100", "USD", "Main")
        ]
        request = AutomationRunRequest(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2026, 5, 1),
            requested_end_date=date(2026, 5, 14),
            account_external_ids=("U100",),
        )

        run_automation(request, database=database)

        self.assertEqual(len(database.added_accounts), 1)
        self.assertEqual(database.added_accounts[0][1].account_id, "account-uuid")
```

- [ ] **Step 2: Run failing target-resolution tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.AutomationOrchestratorValidationTests -v
```

Expected: failure because orchestrator does not resolve targets/add children yet.

- [ ] **Step 3: Implement target resolution and child rows**

Modify `portfolio_engine/automation/orchestrator.py` imports:

```python
from portfolio_engine.database import (
    AutomationJobAccountAdd,
    AutomationJobFinalize,
    AutomationJobStart,
)
```

Add inside `run_automation` after `_validate_request(request)`:

```python
        accounts = _resolve_accounts(request, config, database)
        if not accounts:
            raise AutomationValidationError("empty resolved account set")
        children = [
            (
                database.add_automation_job_account(
                    AutomationJobAccountAdd(
                        automation_job_id=job_id,
                        account_id=account.account_id,
                    )
                ),
                account,
            )
            for account in accounts
        ]
```

Replace the temporary return with:

```python
    return AutomationRunResult(
        job_id,
        "failed",
        build_parent_summary(child_statuses=[], child_summaries=[]),
        "account execution not implemented yet",
    )
```

Add helper:

```python
def _resolve_accounts(request: AutomationRunRequest, config, database):
    if request.target_type == "portfolio":
        return database.resolve_automation_portfolio_accounts(
            portfolio_name=request.portfolio_name or "",
            brokerage_code=config.brokerage_code,
        )
    return database.resolve_automation_account_targets(
        brokerage_code=config.brokerage_code,
        account_external_ids=list(request.account_external_ids),
    )
```

- [ ] **Step 4: Run tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.AutomationOrchestratorValidationTests -v
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add portfolio_engine/automation/orchestrator.py tests/test_automation_orchestrator.py
git commit -m "feat: resolve automation target accounts"
```

---

### Task 12: Implement per-account dry-run execution

**Files:**
- Modify: `portfolio_engine/automation/orchestrator.py`
- Modify: `tests/test_automation_orchestrator.py`

- [ ] **Step 1: Add failing dry-run account-loop test**

Extend `FakeAutomationDatabase`:

```python
        self.running_children = []
        self.finalized_children = []

    def mark_automation_job_account_running(self, automation_job_account_id):
        self.running_children.append(automation_job_account_id)
        return automation_job_account_id

    def finalize_automation_job_account(self, request):
        self.finalized_children.append(request)
        return request.automation_job_account_id
```

Add a fake adapter:

```python
class FakeAdapter:
    def preflight_validate_config(self, config):
        return None

    def fetch_payload(self, account, request, config):
        return type("Payload", (), {"xml_text": "<FlexQueryResponse></FlexQueryResponse>", "source_name": "fake.xml"})()
```

Add test:

```python
    def test_dry_run_finalizes_child_without_ingestion_run(self) -> None:
        database = FakeAutomationDatabase()
        database.account_targets = [
            AutomationAccountTarget("account-uuid", "IBKR", "U100", "USD", "Main")
        ]
        request = AutomationRunRequest(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2026, 5, 1),
            requested_end_date=date(2026, 5, 14),
            account_external_ids=("U100",),
        )

        result = run_automation(request, database=database, adapter=FakeAdapter())

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(database.finalized_children[0].status, "succeeded")
        self.assertIsNone(database.finalized_children[0].ingestion_run_id)
```

- [ ] **Step 2: Run failing dry-run test**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.AutomationOrchestratorValidationTests.test_dry_run_finalizes_child_without_ingestion_run -v
```

Expected: failure because `run_automation` does not accept adapter or execute children.

- [ ] **Step 3: Implement dry-run account execution**

Modify `run_automation` signature:

```python
def run_automation(request: AutomationRunRequest, *, database, adapter=None) -> AutomationRunResult:
```

Resolve adapter after config:

```python
    if adapter is None:
        from portfolio_engine.automation.adapters import get_adapter
        adapter = get_adapter(config.adapter_key)
```

Call adapter preflight before account loop:

```python
        adapter.preflight_validate_config(config)
```

Add imports:

```python
from portfolio_engine.database import AutomationJobAccountFinalize
from portfolio_engine.automation.ingestion import dry_run_payload
```

Create `portfolio_engine/automation/ingestion.py`:

```python
from __future__ import annotations

from portfolio_engine.automation.summary import build_child_summary
from portfolio_engine.ingestion.dry_run import analyze_flex_xml_text_for_ingestion


def dry_run_payload(xml_text: str, *, account_external_id: str, start_date: str, end_date: str) -> dict[str, object]:
    analysis = analyze_flex_xml_text_for_ingestion(
        xml_text,
        start_date=start_date,
        end_date=end_date,
    ).for_account(account_external_id)
    return build_child_summary(
        cash_supported=analysis.cash_flow_count,
        nav_supported=analysis.daily_nav_count,
        cash_skipped_other_account=analysis.skipped_other_account_cash_flow_count,
        nav_skipped_other_account=analysis.skipped_other_account_daily_nav_count,
    )
```

Replace temporary account execution return with child loop:

```python
        child_statuses: list[str] = []
        child_summaries: list[dict[str, Any]] = []
        for child_id, account in children:
            database.mark_automation_job_account_running(child_id)
            payload = adapter.fetch_payload(account, request, config)
            summary = dry_run_payload(
                payload.xml_text,
                account_external_id=account.account_external_id,
                start_date=request.requested_start_date.isoformat(),
                end_date=request.requested_end_date.isoformat(),
            )
            status = "succeeded"
            database.finalize_automation_job_account(
                AutomationJobAccountFinalize(
                    automation_job_account_id=child_id,
                    status=status,
                    ingestion_run_id=None,
                    summary=summary,
                    error_message=None,
                )
            )
            child_statuses.append(status)
            child_summaries.append(summary)

        parent_status = _derive_parent_status(child_statuses)
        parent_summary = build_parent_summary(
            child_statuses=child_statuses,
            child_summaries=child_summaries,
        )
        database.finalize_automation_job(
            AutomationJobFinalize(
                automation_job_id=job_id,
                status=parent_status,
                summary=parent_summary,
                error_message=None,
            )
        )
        return AutomationRunResult(job_id, parent_status, parent_summary)
```

Add helper:

```python
def _derive_parent_status(child_statuses: list[str]) -> str:
    if not child_statuses:
        return "failed"
    if all(status == "succeeded" for status in child_statuses):
        return "succeeded"
    if any(status in {"succeeded", "partially_succeeded"} for status in child_statuses):
        return "partially_succeeded"
    return "failed"
```

- [ ] **Step 4: Run dry-run tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.AutomationOrchestratorValidationTests.test_dry_run_finalizes_child_without_ingestion_run -v
```

Expected: test passes.

- [ ] **Step 5: Run all automation tests so far**

Run:

```bash
python -m unittest tests.test_automation_config tests.test_automation_summary tests.test_automation_targets tests.test_automation_orchestrator -v
```

Expected: automation tests pass.

- [ ] **Step 6: Commit**

```bash
git add portfolio_engine/automation/orchestrator.py portfolio_engine/automation/ingestion.py tests/test_automation_orchestrator.py
git commit -m "feat: add automation dry-run execution"
```

---

### Task 13: Implement per-account load execution

**Files:**
- Modify: `portfolio_engine/automation/ingestion.py`
- Modify: `portfolio_engine/automation/orchestrator.py`
- Modify: `tests/test_automation_orchestrator.py`

- [ ] **Step 1: Add failing load test**

Extend `FakeAutomationDatabase`:

```python
        self.started_ingestion_runs = []
        self.completed_ingestion_runs = []
        self.cash_bulk_calls = []
        self.nav_bulk_calls = []

    def start_ingestion_run(self, request):
        self.started_ingestion_runs.append(request)
        return "ingestion-run-uuid"

    def complete_ingestion_run(self, *, ingestion_run_id, status, error_message=None):
        self.completed_ingestion_runs.append((ingestion_run_id, status, error_message))
        return ingestion_run_id

    def bulk_ingest_cash_flows(self, ingestion_run_id, records):
        self.cash_bulk_calls.append((ingestion_run_id, records))
        return BulkIngestionSummary(0, 0, 0, 0, 0, [], [])

    def bulk_ingest_daily_nav_snapshots(self, ingestion_run_id, records):
        self.nav_bulk_calls.append((ingestion_run_id, records))
        return BulkIngestionSummary(0, 0, 0, 0, 0, [], [])
```

Add import:

```python
from portfolio_engine.database import BulkIngestionSummary
```

Add test:

```python
    def test_load_finalizes_child_with_ingestion_run(self) -> None:
        database = FakeAutomationDatabase()
        database.account_targets = [
            AutomationAccountTarget("account-uuid", "IBKR", "U100", "USD", "Main")
        ]
        request = AutomationRunRequest(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode="load",
            requested_start_date=date(2026, 5, 1),
            requested_end_date=date(2026, 5, 14),
            account_external_ids=("U100",),
        )

        result = run_automation(request, database=database, adapter=FakeAdapter())

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(database.finalized_children[0].ingestion_run_id, "ingestion-run-uuid")
        self.assertEqual(database.completed_ingestion_runs[0][1], "succeeded")
```

- [ ] **Step 2: Run failing load test**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.AutomationOrchestratorValidationTests.test_load_finalizes_child_with_ingestion_run -v
```

Expected: failure because load mode does not create ingestion runs yet.

- [ ] **Step 3: Implement load payload helper**

Add to `portfolio_engine/automation/ingestion.py`:

```python
from portfolio_engine.database import BulkIngestionSummary, IngestionRunStart, SuperFolioDatabase


def load_payload(
    xml_text: str,
    *,
    database: SuperFolioDatabase,
    brokerage_code: str,
    account_external_id: str,
    source_type: str,
    source_name: str | None,
    start_date: str,
    end_date: str,
) -> tuple[str, str, dict[str, object], str | None]:
    analysis = analyze_flex_xml_text_for_ingestion(
        xml_text,
        start_date=start_date,
        end_date=end_date,
    ).for_account(account_external_id)
    ingestion_run_id = database.start_ingestion_run(
        IngestionRunStart(
            brokerage_code=brokerage_code,
            account_external_id=account_external_id,
            source_type=source_type,
            requested_start_date=date.fromisoformat(start_date),
            requested_end_date=date.fromisoformat(end_date),
            source_filename=source_name,
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
    status = _derive_ingestion_status(cash_summary, nav_summary)
    message = "skipped accounts or conflicts require review" if status == "partially_succeeded" else None
    database.complete_ingestion_run(
        ingestion_run_id=ingestion_run_id,
        status=status,
        error_message=message,
    )
    summary = build_child_summary(
        cash_supported=analysis.cash_flow_count,
        nav_supported=analysis.daily_nav_count,
        cash_inserted=cash_summary.inserted_count,
        nav_inserted=nav_summary.inserted_count,
        cash_duplicates=cash_summary.duplicate_count,
        nav_duplicates=nav_summary.duplicate_count,
        cash_skipped_unknown_account=cash_summary.skipped_unknown_account_count,
        nav_skipped_unknown_account=nav_summary.skipped_unknown_account_count,
        cash_skipped_inactive_account=cash_summary.skipped_inactive_account_count,
        nav_skipped_inactive_account=nav_summary.skipped_inactive_account_count,
        cash_skipped_other_account=analysis.skipped_other_account_cash_flow_count,
        nav_skipped_other_account=analysis.skipped_other_account_daily_nav_count,
        cash_conflicts=cash_summary.conflict_count,
        nav_conflicts=nav_summary.conflict_count,
    )
    return ingestion_run_id, status, summary, message


def _empty_bulk_summary() -> BulkIngestionSummary:
    return BulkIngestionSummary(0, 0, 0, 0, 0, [], [])


def _derive_ingestion_status(
    cash_summary: BulkIngestionSummary,
    nav_summary: BulkIngestionSummary,
) -> str:
    if any(
        (
            cash_summary.skipped_unknown_account_count,
            cash_summary.skipped_inactive_account_count,
            cash_summary.conflict_count,
            nav_summary.skipped_unknown_account_count,
            nav_summary.skipped_inactive_account_count,
            nav_summary.conflict_count,
        )
    ):
        return "partially_succeeded"
    return "succeeded"
```

Also add `from datetime import date` at top of `ingestion.py`.

- [ ] **Step 4: Route load mode in orchestrator**

In `orchestrator.py`, import `load_payload`:

```python
from portfolio_engine.automation.ingestion import dry_run_payload, load_payload
```

Replace per-account summary logic with:

```python
            if request.mode == "dry-run":
                summary = dry_run_payload(
                    payload.xml_text,
                    account_external_id=account.account_external_id,
                    start_date=request.requested_start_date.isoformat(),
                    end_date=request.requested_end_date.isoformat(),
                )
                status = "succeeded"
                ingestion_run_id = None
                message = None
            else:
                ingestion_run_id, status, summary, message = load_payload(
                    payload.xml_text,
                    database=database,
                    brokerage_code=config.brokerage_code,
                    account_external_id=account.account_external_id,
                    source_type=config.source_type,
                    source_name=payload.source_name,
                    start_date=request.requested_start_date.isoformat(),
                    end_date=request.requested_end_date.isoformat(),
                )
```

Use `ingestion_run_id` and `message` in `AutomationJobAccountFinalize`.

- [ ] **Step 5: Run load test**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.AutomationOrchestratorValidationTests.test_load_finalizes_child_with_ingestion_run -v
```

Expected: load test passes.

- [ ] **Step 6: Run automation tests**

Run:

```bash
python -m unittest tests.test_automation_config tests.test_automation_summary tests.test_automation_targets tests.test_automation_orchestrator -v
```

Expected: automation tests pass.

- [ ] **Step 7: Commit**

```bash
git add portfolio_engine/automation/ingestion.py portfolio_engine/automation/orchestrator.py tests/test_automation_orchestrator.py
git commit -m "feat: add automation load execution"
```

---

### Task 14: Add per-account error isolation and parent aggregation

**Files:**
- Modify: `portfolio_engine/automation/orchestrator.py`
- Modify: `tests/test_automation_orchestrator.py`

- [ ] **Step 1: Add failing continue-on-error test**

Add fake adapter:

```python
class FailingOneAccountAdapter(FakeAdapter):
    def fetch_payload(self, account, request, config):
        if account.account_external_id == "U200":
            raise RuntimeError("token=secret failed")
        return super().fetch_payload(account, request, config)
```

Add test:

```python
    def test_account_failure_does_not_stop_other_accounts(self) -> None:
        database = FakeAutomationDatabase()
        database.account_targets = [
            AutomationAccountTarget("account-1", "IBKR", "U100", "USD", "Main"),
            AutomationAccountTarget("account-2", "IBKR", "U200", "USD", "Other"),
        ]
        request = AutomationRunRequest(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode="dry-run",
            requested_start_date=date(2026, 5, 1),
            requested_end_date=date(2026, 5, 14),
            account_external_ids=("U100", "U200"),
        )

        result = run_automation(request, database=database, adapter=FailingOneAccountAdapter())

        self.assertEqual(result.status, "partially_succeeded")
        self.assertEqual(len(database.finalized_children), 2)
        self.assertEqual(database.finalized_children[1].status, "failed")
        self.assertNotIn("secret", database.finalized_children[1].error_message)
```

- [ ] **Step 2: Run failing continue-on-error test**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.AutomationOrchestratorValidationTests.test_account_failure_does_not_stop_other_accounts -v
```

Expected: failure because account exceptions are not isolated.

- [ ] **Step 3: Catch per-account exceptions in orchestrator**

Wrap the body of the child loop in `orchestrator.py`:

```python
        for child_id, account in children:
            database.mark_automation_job_account_running(child_id)
            try:
                payload = adapter.fetch_payload(account, request, config)
                if request.mode == "dry-run":
                    summary = dry_run_payload(
                        payload.xml_text,
                        account_external_id=account.account_external_id,
                        start_date=request.requested_start_date.isoformat(),
                        end_date=request.requested_end_date.isoformat(),
                    )
                    status = "succeeded"
                    ingestion_run_id = None
                    message = None
                else:
                    ingestion_run_id, status, summary, message = load_payload(
                        payload.xml_text,
                        database=database,
                        brokerage_code=config.brokerage_code,
                        account_external_id=account.account_external_id,
                        source_type=config.source_type,
                        source_name=payload.source_name,
                        start_date=request.requested_start_date.isoformat(),
                        end_date=request.requested_end_date.isoformat(),
                    )
            except Exception as error:
                status = "failed"
                ingestion_run_id = None
                message = sanitize_error_message(str(error))
                from portfolio_engine.automation.summary import build_child_summary
                summary = build_child_summary(error_category="account_error")

            database.finalize_automation_job_account(
                AutomationJobAccountFinalize(
                    automation_job_account_id=child_id,
                    status=status,
                    ingestion_run_id=ingestion_run_id,
                    summary=summary,
                    error_message=message,
                )
            )
            child_statuses.append(status)
            child_summaries.append(summary)
```

- [ ] **Step 4: Run continue-on-error test**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.AutomationOrchestratorValidationTests.test_account_failure_does_not_stop_other_accounts -v
```

Expected: test passes.

- [ ] **Step 5: Run all automation tests**

Run:

```bash
python -m unittest tests.test_automation_config tests.test_automation_summary tests.test_automation_targets tests.test_automation_orchestrator -v
```

Expected: automation tests pass.

- [ ] **Step 6: Commit**

```bash
git add portfolio_engine/automation/orchestrator.py tests/test_automation_orchestrator.py
git commit -m "feat: isolate automation account failures"
```

---

### Task 15: Add overlap detection and load blocking

**Files:**
- Modify: `migrations/deploy/create_automation_layer.sql`
- Modify: `migrations/revert/create_automation_layer.sql`
- Modify: `migrations/verify/create_automation_layer.sql`
- Modify: `portfolio_engine/database.py`
- Modify: `portfolio_engine/automation/orchestrator.py`
- Modify: `tests/test_database_adapter.py`
- Modify: `tests/test_automation_orchestrator.py`

- [ ] **Step 1: Add failing migration and adapter tests**

Add migration test:

```python
    def test_automation_layer_defines_overlapping_load_function(self) -> None:
        sql = Path("migrations/deploy/create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE FUNCTION public.has_overlapping_automation_load", sql)
        self.assertIn("daterange", sql)
```

Add database adapter test:

```python
    def test_has_overlapping_automation_load_calls_database_function(self) -> None:
        connection = FakeConnection((True,))
        database = SuperFolioDatabase(connection)

        result = database.has_overlapping_automation_load(
            integration_key="ibkr_flex_ws",
            account_id="account-uuid",
            requested_start_date=date(2026, 5, 1),
            requested_end_date=date(2026, 5, 14),
        )

        self.assertTrue(result)
        self.assertEqual(
            connection.cursor_instance.executed[0],
            (
                "SELECT public.has_overlapping_automation_load(%s, %s, %s, %s)",
                ("ibkr_flex_ws", "account-uuid", date(2026, 5, 1), date(2026, 5, 14)),
            ),
        )
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python -m unittest tests.test_migrations tests.test_database_adapter -v
```

Expected: failures for missing overlap function and adapter method.

- [ ] **Step 3: Add overlap function**

Append to deploy SQL:

```sql
CREATE FUNCTION public.has_overlapping_automation_load(
    p_integration_key TEXT,
    p_account_id UUID,
    p_requested_start_date DATE,
    p_requested_end_date DATE
)
RETURNS BOOLEAN
LANGUAGE sql
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.automation_jobs j
        JOIN public.automation_job_accounts ja ON ja.automation_job_id = j.id
        WHERE j.integration_key = lower(btrim(p_integration_key))
          AND j.mode = 'load'
          AND j.status IN ('pending', 'running')
          AND ja.account_id = p_account_id
          AND ja.status IN ('pending', 'running')
          AND daterange(j.requested_start_date, j.requested_end_date, '[]')
              && daterange(p_requested_start_date, p_requested_end_date, '[]')
    );
$$;
```

Add to revert:

```sql
DROP FUNCTION IF EXISTS public.has_overlapping_automation_load(TEXT, UUID, DATE, DATE);
```

Add to verify:

```sql
SELECT 1
WHERE to_regprocedure('public.has_overlapping_automation_load(text,uuid,date,date)') IS NOT NULL;
```

- [ ] **Step 4: Add database adapter method**

Add to `SuperFolioDatabase`:

```python
    def has_overlapping_automation_load(
        self,
        *,
        integration_key: str,
        account_id: str,
        requested_start_date: date,
        requested_end_date: date,
    ) -> bool:
        row = self._fetch_one(
            "SELECT public.has_overlapping_automation_load(%s, %s, %s, %s)",
            (integration_key, account_id, requested_start_date, requested_end_date),
        )
        return bool(row[0])
```

- [ ] **Step 5: Add failing orchestrator overlap test**

Extend fake database:

```python
        self.overlapping_load = False

    def has_overlapping_automation_load(self, *, integration_key, account_id, requested_start_date, requested_end_date):
        return self.overlapping_load
```

Add test:

```python
    def test_overlapping_load_marks_child_failed(self) -> None:
        database = FakeAutomationDatabase()
        database.overlapping_load = True
        database.account_targets = [
            AutomationAccountTarget("account-uuid", "IBKR", "U100", "USD", "Main")
        ]
        request = AutomationRunRequest(
            target_type="accounts",
            integration_key="ibkr_flex_ws",
            mode="load",
            requested_start_date=date(2026, 5, 1),
            requested_end_date=date(2026, 5, 14),
            account_external_ids=("U100",),
        )

        result = run_automation(request, database=database, adapter=FakeAdapter())

        self.assertEqual(result.status, "failed")
        self.assertEqual(database.finalized_children[0].status, "failed")
```

- [ ] **Step 6: Implement orchestrator overlap check**

Inside child loop before fetching payload:

```python
                if request.mode == "load" and database.has_overlapping_automation_load(
                    integration_key=request.integration_key,
                    account_id=account.account_id,
                    requested_start_date=request.requested_start_date,
                    requested_end_date=request.requested_end_date,
                ):
                    raise RuntimeError("overlapping_load_job")
```

- [ ] **Step 7: Run overlap tests**

Run:

```bash
python -m unittest tests.test_migrations tests.test_database_adapter tests.test_automation_orchestrator -v
```

Expected: relevant tests pass.

- [ ] **Step 8: Commit**

```bash
git add migrations/deploy/create_automation_layer.sql migrations/revert/create_automation_layer.sql migrations/verify/create_automation_layer.sql portfolio_engine/database.py portfolio_engine/automation/orchestrator.py tests/test_migrations.py tests/test_database_adapter.py tests/test_automation_orchestrator.py
git commit -m "feat: block overlapping automation loads"
```

---

### Task 16: Add CLI entrypoint and script wrapper

**Files:**
- Create: `portfolio_engine/automation/cli.py`
- Create: `scripts/run_automated_ingestion.py`
- Create: `tests/test_automation_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_automation_cli.py`:

```python
from __future__ import annotations

import unittest
from io import StringIO

from portfolio_engine.automation.cli import run


class AutomationCliTests(unittest.TestCase):
    def test_accounts_target_parses_and_runs(self) -> None:
        calls = []

        def fake_runner(request, database):
            calls.append(request)
            return type("Result", (), {"status": "succeeded", "summary": {}, "error_message": None})()

        stdout = StringIO()
        exit_code = run(
            [
                "--target-type", "accounts",
                "--integration", "ibkr_flex_ws",
                "--mode", "dry-run",
                "--start-date", "2026-05-01",
                "--end-date", "2026-05-14",
                "--account-external-ids", "U100,,U200",
            ],
            stdout=stdout,
            runner=fake_runner,
            database_connector=lambda: object(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls[0].account_external_ids, ("U100", "U200"))
        self.assertIn("Automation status: succeeded", stdout.getvalue())

    def test_partial_status_exits_zero_with_warning(self) -> None:
        def fake_runner(request, database):
            return type("Result", (), {"status": "partially_succeeded", "summary": {}, "error_message": None})()

        stdout = StringIO()
        exit_code = run(
            [
                "--target-type", "accounts",
                "--integration", "ibkr_flex_ws",
                "--mode", "dry-run",
                "--start-date", "2026-05-01",
                "--end-date", "2026-05-14",
                "--account-external-ids", "U100",
            ],
            stdout=stdout,
            runner=fake_runner,
            database_connector=lambda: object(),
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("WARNING", stdout.getvalue())

    def test_failed_status_exits_one(self) -> None:
        def fake_runner(request, database):
            return type("Result", (), {"status": "failed", "summary": {}, "error_message": "bad"})()

        stdout = StringIO()
        exit_code = run(
            [
                "--target-type", "accounts",
                "--integration", "ibkr_flex_ws",
                "--mode", "dry-run",
                "--start-date", "2026-05-01",
                "--end-date", "2026-05-14",
                "--account-external-ids", "U100",
            ],
            stdout=stdout,
            runner=fake_runner,
            database_connector=lambda: object(),
        )

        self.assertEqual(exit_code, 1)
```

- [ ] **Step 2: Run failing CLI tests**

Run:

```bash
python -m unittest tests.test_automation_cli -v
```

Expected: import failure because CLI module does not exist.

- [ ] **Step 3: Implement CLI**

Create `portfolio_engine/automation/cli.py`:

```python
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from typing import Callable, TextIO

from portfolio_engine.database import connect_database
from portfolio_engine.automation.orchestrator import run_automation
from portfolio_engine.automation.targets import parse_account_external_ids
from portfolio_engine.automation.types import AutomationRunRequest


def run(
    argv: list[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    runner=run_automation,
    database_connector: Callable[[], object] = connect_database,
) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        request = AutomationRunRequest(
            target_type=args.target_type,
            integration_key=args.integration,
            mode=args.mode,
            requested_start_date=_parse_date(args.start_date),
            requested_end_date=_parse_date(args.end_date),
            portfolio_name=args.portfolio_name,
            account_external_ids=parse_account_external_ids(args.account_external_ids),
        )
        with database_connector() as database:
            result = runner(request, database=database)
        stdout.write(f"Automation status: {result.status}\n")
        if result.status == "partially_succeeded":
            stdout.write("WARNING: automation job partially succeeded; review account summaries.\n")
        if result.error_message:
            stdout.write(f"Message: {result.error_message}\n")
        return 1 if result.status == "failed" else 0
    except Exception as error:
        stderr.write(f"Error: {error}\n")
        return 1


def main(argv: list[str] | None = None) -> int:
    return run(argv)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run automated broker ingestion.")
    parser.add_argument("--target-type", required=True, choices=("portfolio", "accounts"))
    parser.add_argument("--integration", default="ibkr_flex_ws")
    parser.add_argument("--mode", required=True, choices=("dry-run", "load"))
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--portfolio-name")
    parser.add_argument("--account-external-ids")
    return parser


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()
```

Create `scripts/run_automated_ingestion.py`:

```python
#!/usr/bin/env python
"""Run automated broker ingestion."""

from __future__ import annotations

import sys

from portfolio_engine.automation.cli import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
python -m unittest tests.test_automation_cli -v
```

Expected: CLI tests pass.

- [ ] **Step 5: Commit**

```bash
git add portfolio_engine/automation/cli.py scripts/run_automated_ingestion.py tests/test_automation_cli.py
git commit -m "feat: add automation ingestion CLI"
```

---

### Task 17: Add manual GitHub Actions workflow

**Files:**
- Create: `.github/workflows/manual-ingestion.yml`
- Create: `tests/test_automation_workflow.py`

- [ ] **Step 1: Write failing workflow tests**

Create `tests/test_automation_workflow.py`:

```python
from __future__ import annotations

from pathlib import Path
import unittest


class AutomationWorkflowTests(unittest.TestCase):
    def test_manual_workflow_exists_without_schedule(self) -> None:
        workflow = Path(".github/workflows/manual-ingestion.yml")
        self.assertTrue(workflow.exists())

        text = workflow.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("schedule:", text)

    def test_manual_workflow_calls_python_entrypoint(self) -> None:
        text = Path(".github/workflows/manual-ingestion.yml").read_text(encoding="utf-8")

        self.assertIn("python scripts/run_automated_ingestion.py", text)
        self.assertIn("DATABASE_URL: ${{ secrets.DATABASE_URL }}", text)
        self.assertIn("IBKR_FLEX_TOKEN: ${{ secrets.IBKR_FLEX_TOKEN }}", text)
        self.assertIn("IBKR_FLEX_QUERY_ID: ${{ secrets.IBKR_FLEX_QUERY_ID }}", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing workflow tests**

Run:

```bash
python -m unittest tests.test_automation_workflow -v
```

Expected: failure because workflow file does not exist.

- [ ] **Step 3: Create workflow**

Create `.github/workflows/manual-ingestion.yml`:

```yaml
name: Manual Ingestion

on:
  workflow_dispatch:
    inputs:
      target_type:
        description: "Target type: portfolio or accounts"
        required: true
        type: choice
        options:
          - portfolio
          - accounts
      integration:
        description: "Integration key"
        required: true
        default: "ibkr_flex_ws"
      mode:
        description: "Run mode"
        required: true
        type: choice
        options:
          - dry-run
          - load
      start_date:
        description: "Requested start date (YYYY-MM-DD)"
        required: true
      end_date:
        description: "Requested end date (YYYY-MM-DD)"
        required: true
      portfolio_name:
        description: "Portfolio name for portfolio target"
        required: false
      account_external_ids:
        description: "Comma-separated account external IDs for accounts target"
        required: false

jobs:
  ingest:
    runs-on: ubuntu-latest
    env:
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
      IBKR_FLEX_TOKEN: ${{ secrets.IBKR_FLEX_TOKEN }}
      IBKR_FLEX_QUERY_ID: ${{ secrets.IBKR_FLEX_QUERY_ID }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: python -m pip install -r requirements.txt

      - name: Run automated ingestion
        run: |
          python scripts/run_automated_ingestion.py \
            --target-type "${{ inputs.target_type }}" \
            --integration "${{ inputs.integration }}" \
            --mode "${{ inputs.mode }}" \
            --start-date "${{ inputs.start_date }}" \
            --end-date "${{ inputs.end_date }}" \
            --portfolio-name "${{ inputs.portfolio_name }}" \
            --account-external-ids "${{ inputs.account_external_ids }}"
```

- [ ] **Step 4: Run workflow tests**

Run:

```bash
python -m unittest tests.test_automation_workflow -v
```

Expected: workflow tests pass.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/manual-ingestion.yml tests/test_automation_workflow.py
git commit -m "feat: add manual ingestion workflow"
```

---

### Task 18: Update database and workflow documentation

**Files:**
- Modify: `docs/database/schema.md`
- Modify: `docs/database/functions.md`
- Create: `docs/workflows/automated-ingestion.md`
- Modify: `README.md`

- [ ] **Step 1: Update `docs/database/schema.md`**

Add `AUTOMATION_JOBS` and `AUTOMATION_JOB_ACCOUNTS` to the relationship overview and add table sections:

```markdown
### `automation_jobs`

Stores one user-triggered or future scheduled automation operation. Manual jobs require a requested start and end date, record the target type (`portfolio` or `accounts`), selected integration, mode (`dry-run` or `load`), status, sanitized parent summary, and sanitized error message.

### `automation_job_accounts`

Stores the resolved account snapshot for one automation job. Each row tracks account-level status, optional linked `ingestion_runs.id` for load mode, sanitized child summary counts, and sanitized error message. Dry-run rows leave `ingestion_run_id` null.
```

- [ ] **Step 2: Update `docs/database/functions.md`**

Add automation function mappings:

```markdown
| `create_automation_job(...)` | `public.create_automation_job(...)` |
| `finalize_automation_job(...)` | `public.finalize_automation_job(...)` |
| `add_automation_job_account(...)` | `public.add_automation_job_account(...)` |
| `mark_automation_job_account_running(...)` | `public.mark_automation_job_account_running(...)` |
| `finalize_automation_job_account(...)` | `public.finalize_automation_job_account(...)` |
| `resolve_automation_portfolio_accounts(...)` | `public.resolve_automation_portfolio_accounts(...)` |
| `resolve_automation_account_targets(...)` | `public.resolve_automation_account_targets(...)` |
| `fail_stale_automation_runs(...)` | `public.fail_stale_automation_runs(...)` |
| `has_overlapping_automation_load(...)` | `public.has_overlapping_automation_load(...)` |
```

- [ ] **Step 3: Create automated ingestion workflow docs**

Create `docs/workflows/automated-ingestion.md`:

```markdown
# Automated Ingestion

Automated ingestion runs through the manual GitHub Actions workflow `.github/workflows/manual-ingestion.yml`. No cron schedule is enabled yet.

## Inputs

- `target_type`: `portfolio` or `accounts`
- `integration`: defaults to `ibkr_flex_ws`
- `mode`: `dry-run` or `load`
- `start_date`: required `YYYY-MM-DD`
- `end_date`: required `YYYY-MM-DD`
- `portfolio_name`: required when `target_type=portfolio`
- `account_external_ids`: comma-separated account external ids when `target_type=accounts`

## Behavior

Dry-run records automation job metadata and account outcomes but does not create account-scoped ingestion runs or normalized facts. Load mode creates account-scoped ingestion runs and writes supported normalized records through the existing ingestion functions.

`failed` jobs fail the workflow. `partially_succeeded` jobs exit successfully with a prominent warning summary for review.

Database summaries and workflow output are privacy-safe: they contain counts, statuses, and sanitized error categories only.
```

- [ ] **Step 4: Update README roadmap/status**

In `README.md`, update the automation roadmap entry from planned-only wording to mention manual automation infrastructure when implemented:

```markdown
- [x] **Manual Automation Infrastructure:** Parent automation jobs, account-level outcomes, and manual GitHub Actions trigger for broker ingestion testing.
- [ ] **Scheduled GitHub Actions Automation:** Scheduled daily Flex XML fetch and TWR recalculation.
```

- [ ] **Step 5: Commit**

```bash
git add README.md docs/database/schema.md docs/database/functions.md docs/workflows/automated-ingestion.md
git commit -m "docs: document automated ingestion workflow"
```

---

### Task 19: Full verification

**Files:**
- No source edits expected during the first verification pass.

- [ ] **Step 1: Run full Python test suite**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Inspect git status**

Run:

```bash
git --no-pager status --short
```

Expected: no uncommitted changes.

- [ ] **Step 3: Handle test failures with TDD**

For each failing test:

1. Read the failure.
2. Identify the smallest code or test-plan mismatch.
3. Apply a focused fix.
4. Re-run the specific failing test.
5. Re-run full suite.
6. Commit the fix with a focused message.

- [ ] **Step 4: Final handoff**

Report:

- final commit SHA.
- test command and result.
- any known limitations, especially that full IBKR Web Service fetch internals remain out of scope pending follow-up design.

---

## Self-review against spec

- Parent job and child account schema: covered by Tasks 1-4.
- PostgreSQL function boundary and `SuperFolioDatabase` adapter: covered by Tasks 3-5.
- Portfolio/account target resolution and validation: covered by Tasks 4, 8, 10, 11.
- Active-only ingestion targets with inactive historical reporting preserved: covered by Task 4 and docs in Task 18.
- Dry-run metadata-only behavior: covered by Tasks 12 and 16.
- Load mode and existing ingestion boundaries: covered by Task 13.
- Continue-on-error per account and parent aggregation: covered by Task 14.
- Sanitized summaries and diagnostics: covered by Task 7 and docs in Task 18.
- `skipped_other_account` counts and other-account-only success: covered by Tasks 7, 12, 13, 14.
- Concurrency blocking by intersecting load windows: covered by Task 15.
- Stale-running cleanup with configurable timeout: covered by Tasks 4, 6, 10.
- GitHub Actions manual trigger with no cron schedule: covered by Task 17.
- Documentation updates: covered by Task 18.
- Full verification: covered by Task 19.

No implementation should start until the repository owner explicitly approves execution.
