# MVP Sqitch Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a Sqitch migration that deploys, verifies, and reverts the MVP SuperFolio database schema for IBKR daily NAV and cash-flow ingestion.

**Architecture:** Add a second Sqitch change named `create_mvp_schema` after the existing `create_books` example change. The deploy script enables `pgcrypto`, creates the six MVP tables in `public`, uses `VARCHAR + CHECK` for controlled values, stores nullable `source_records.raw_payload JSONB`, and seeds the initial IBKR brokerage row. The verify script proves the extension, tables, key constraints, check constraints, and seed row exist; the revert script drops the MVP schema objects in dependency order.

**Tech Stack:** PostgreSQL, Sqitch, SQL, `pgcrypto` for `gen_random_uuid()`.

---

## File structure

- Modify: `migrations/sqitch.plan`  
  Sqitch plan file. Add the `create_mvp_schema` change after `create_books` by using `sqitch add`.
- Create: `migrations/deploy/create_mvp_schema.sql`  
  Deploy script for enabling `pgcrypto`, creating MVP tables, adding constraints, and seeding IBKR.
- Create: `migrations/revert/create_mvp_schema.sql`  
  Revert script that removes seeded data and drops MVP tables in dependency order.
- Create: `migrations/verify/create_mvp_schema.sql`  
  Verify script that checks the extension, tables, constraints, and seed data.
- Modify: `docs/er-diagram.md`  
  Keep this as the human-readable schema reference. It already contains the intended table names, including `daily_nav_snapshots`.

## Assumptions locked by the design

- Use `VARCHAR + CHECK`, not PostgreSQL enums.
- Enable `pgcrypto` before using `gen_random_uuid()`.
- `updated_at` is app-managed for MVP; no database trigger is needed.
- `source_records.raw_payload` is nullable.
- Seed one brokerage row: `IBKR`, `Interactive Brokers`, `IBKR_FLEX_XML`.
- Keep the current documentation rename to `daily_nav_snapshots`; do not create a table named `daily_snapshots`.

### Task 1: Add the Sqitch change scaffold

**Files:**
- Modify: `migrations/sqitch.plan`
- Create: `migrations/deploy/create_mvp_schema.sql`
- Create: `migrations/revert/create_mvp_schema.sql`
- Create: `migrations/verify/create_mvp_schema.sql`

- [ ] **Step 1: Confirm Sqitch is available**

Run:

```bash
sqitch --version
```

Expected: a Sqitch version string, such as:

```text
sqitch (App::Sqitch) v1.x.x
```

If the command is missing, install the existing project-documented dependencies:

```bash
sudo apt-get update
sudo apt-get install -y sqitch libdbd-pg-perl postgresql-client
sqitch --version
```

Expected after install: a Sqitch version string.

- [ ] **Step 2: Create the Sqitch change**

Run from the repository root:

```bash
sqitch add create_mvp_schema -n 'Create MVP portfolio schema'
```

Expected:

```text
Created deploy/create_mvp_schema.sql
Created revert/create_mvp_schema.sql
Created verify/create_mvp_schema.sql
Added "create_mvp_schema" to sqitch.plan
```

- [ ] **Step 3: Confirm the change was appended after `create_books`**

Run:

```bash
tail -n 5 migrations/sqitch.plan
```

Expected: the final non-empty line starts with `create_mvp_schema` and appears after the existing `create_books` line.

### Task 2: Write the deploy migration

**Files:**
- Modify: `migrations/deploy/create_mvp_schema.sql`

- [ ] **Step 1: Replace the generated deploy file**

Replace the entire contents of `migrations/deploy/create_mvp_schema.sql` with:

```sql
-- Deploy superfolio:create_mvp_schema to pg

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE public.brokerages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(20) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    import_format VARCHAR(50) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT brokerages_code_not_blank_check CHECK (btrim(code) <> ''),
    CONSTRAINT brokerages_name_not_blank_check CHECK (btrim(name) <> ''),
    CONSTRAINT brokerages_import_format_not_blank_check CHECK (btrim(import_format) <> '')
);

CREATE TABLE public.accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brokerage_id UUID NOT NULL REFERENCES public.brokerages(id),
    external_id VARCHAR(50) NOT NULL,
    display_name VARCHAR(100),
    account_type VARCHAR(50) NOT NULL,
    base_currency CHAR(3) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT accounts_brokerage_external_id_key UNIQUE (brokerage_id, external_id),
    CONSTRAINT accounts_external_id_not_blank_check CHECK (btrim(external_id) <> ''),
    CONSTRAINT accounts_account_type_not_blank_check CHECK (btrim(account_type) <> ''),
    CONSTRAINT accounts_base_currency_uppercase_check CHECK (base_currency ~ '^[A-Z]{3}$')
);

CREATE TABLE public.ingestion_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brokerage_id UUID NOT NULL REFERENCES public.brokerages(id),
    source_type VARCHAR(30) NOT NULL,
    status VARCHAR(30) NOT NULL,
    requested_start_date DATE,
    requested_end_date DATE,
    source_filename TEXT,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ingestion_runs_source_type_check CHECK (
        source_type IN ('FLEX_WEB_SERVICE', 'MANUAL_FILE')
    ),
    CONSTRAINT ingestion_runs_status_check CHECK (
        status IN ('pending', 'running', 'succeeded', 'failed')
    ),
    CONSTRAINT ingestion_runs_requested_date_range_check CHECK (
        requested_start_date IS NULL
        OR requested_end_date IS NULL
        OR requested_start_date <= requested_end_date
    ),
    CONSTRAINT ingestion_runs_completed_after_started_check CHECK (
        completed_at IS NULL OR completed_at >= started_at
    )
);

CREATE TABLE public.source_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingestion_run_id UUID NOT NULL REFERENCES public.ingestion_runs(id),
    brokerage_id UUID NOT NULL REFERENCES public.brokerages(id),
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    record_type VARCHAR(50) NOT NULL,
    external_record_id TEXT,
    dedupe_key TEXT NOT NULL,
    source_report_date DATE,
    source_currency CHAR(3),
    raw_payload JSONB,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT source_records_brokerage_dedupe_key UNIQUE (brokerage_id, dedupe_key),
    CONSTRAINT source_records_record_type_check CHECK (
        record_type IN ('CASH_TRANSACTION', 'DAILY_NAV')
    ),
    CONSTRAINT source_records_dedupe_key_not_blank_check CHECK (btrim(dedupe_key) <> ''),
    CONSTRAINT source_records_source_currency_uppercase_check CHECK (
        source_currency IS NULL OR source_currency ~ '^[A-Z]{3}$'
    )
);

CREATE TABLE public.cash_flows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    source_record_id UUID NOT NULL UNIQUE REFERENCES public.source_records(id),
    flow_date DATE NOT NULL,
    cash_flow_type VARCHAR(50) NOT NULL,
    currency CHAR(3) NOT NULL,
    amount NUMERIC(20, 8) NOT NULL,
    amount_base NUMERIC(20, 8) NOT NULL,
    fx_rate_to_base NUMERIC(20, 10),
    description TEXT,
    CONSTRAINT cash_flows_cash_flow_type_not_blank_check CHECK (btrim(cash_flow_type) <> ''),
    CONSTRAINT cash_flows_currency_uppercase_check CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT cash_flows_fx_rate_to_base_positive_check CHECK (
        fx_rate_to_base IS NULL OR fx_rate_to_base > 0
    )
);

CREATE TABLE public.daily_nav_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    source_record_id UUID NOT NULL UNIQUE REFERENCES public.source_records(id),
    snapshot_date DATE NOT NULL,
    base_currency CHAR(3) NOT NULL,
    nav_base NUMERIC(20, 8) NOT NULL,
    CONSTRAINT daily_nav_snapshots_account_snapshot_date_key UNIQUE (account_id, snapshot_date),
    CONSTRAINT daily_nav_snapshots_base_currency_uppercase_check CHECK (base_currency ~ '^[A-Z]{3}$')
);

CREATE INDEX source_records_account_id_idx ON public.source_records (account_id);
CREATE INDEX source_records_ingestion_run_id_idx ON public.source_records (ingestion_run_id);
CREATE INDEX cash_flows_account_flow_date_idx ON public.cash_flows (account_id, flow_date);
CREATE INDEX ingestion_runs_brokerage_started_at_idx
    ON public.ingestion_runs (brokerage_id, started_at);

INSERT INTO public.brokerages (code, name, import_format)
VALUES ('IBKR', 'Interactive Brokers', 'IBKR_FLEX_XML')
ON CONFLICT (code) DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Check SQL syntax with Sqitch deploy dry-run-equivalent planning**

Sqitch does not provide a pure SQL parser dry run for PostgreSQL migrations. Use the verify task later against a real target. For this step, run:

```bash
sed -n '1,240p' migrations/deploy/create_mvp_schema.sql
```

Expected: the file contains exactly one `BEGIN;`, one `COMMIT;`, `CREATE EXTENSION IF NOT EXISTS pgcrypto;`, all six table definitions, four explicit indexes, and the IBKR seed insert. Do not add an explicit `(daily_nav_snapshots.account_id, snapshot_date)` index because the unique constraint already creates one.

### Task 3: Write the revert migration

**Files:**
- Modify: `migrations/revert/create_mvp_schema.sql`

- [ ] **Step 1: Replace the generated revert file**

Replace the entire contents of `migrations/revert/create_mvp_schema.sql` with:

```sql
-- Revert superfolio:create_mvp_schema from pg

BEGIN;

DELETE FROM public.brokerages
WHERE code = 'IBKR'
  AND name = 'Interactive Brokers'
  AND import_format = 'IBKR_FLEX_XML';

DROP TABLE IF EXISTS public.daily_nav_snapshots;
DROP TABLE IF EXISTS public.cash_flows;
DROP TABLE IF EXISTS public.source_records;
DROP TABLE IF EXISTS public.ingestion_runs;
DROP TABLE IF EXISTS public.accounts;
DROP TABLE IF EXISTS public.brokerages;

COMMIT;
```

- [ ] **Step 2: Confirm dependent tables drop before parents**

Run:

```bash
sed -n '1,80p' migrations/revert/create_mvp_schema.sql
```

Expected: `daily_nav_snapshots` and `cash_flows` are dropped before `source_records`; `source_records` is dropped before `ingestion_runs`, `accounts`, and `brokerages`.

### Task 4: Write the verify migration

**Files:**
- Modify: `migrations/verify/create_mvp_schema.sql`

- [ ] **Step 1: Replace the generated verify file**

Replace the entire contents of `migrations/verify/create_mvp_schema.sql` with:

```sql
-- Verify superfolio:create_mvp_schema on pg

BEGIN;

SELECT 1 / count(*)
FROM pg_extension
WHERE extname = 'pgcrypto';

SELECT 1 / (count(*) = 6)::int
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
      'brokerages',
      'accounts',
      'ingestion_runs',
      'source_records',
      'cash_flows',
      'daily_nav_snapshots'
  );

SELECT 1 / (count(*) = 7)::int
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'brokerages'
  AND column_name IN (
      'id',
      'code',
      'name',
      'import_format',
      'is_active',
      'created_at',
      'updated_at'
  );

SELECT 1 / (count(*) = 9)::int
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'accounts'
  AND column_name IN (
      'id',
      'brokerage_id',
      'external_id',
      'display_name',
      'account_type',
      'base_currency',
      'is_active',
      'created_at',
      'updated_at'
  );

SELECT 1 / (count(*) = 11)::int
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'ingestion_runs'
  AND column_name IN (
      'id',
      'brokerage_id',
      'source_type',
      'status',
      'requested_start_date',
      'requested_end_date',
      'source_filename',
      'error_message',
      'started_at',
      'completed_at',
      'created_at'
  );

SELECT 1 / (count(*) = 11)::int
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'source_records'
  AND column_name IN (
      'id',
      'ingestion_run_id',
      'brokerage_id',
      'account_id',
      'record_type',
      'external_record_id',
      'dedupe_key',
      'source_report_date',
      'source_currency',
      'raw_payload',
      'first_seen_at'
  );

SELECT 1 / (count(*) = 10)::int
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'cash_flows'
  AND column_name IN (
      'id',
      'account_id',
      'source_record_id',
      'flow_date',
      'cash_flow_type',
      'currency',
      'amount',
      'amount_base',
      'fx_rate_to_base',
      'description'
  );

SELECT 1 / (count(*) = 6)::int
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'daily_nav_snapshots'
  AND column_name IN (
      'id',
      'account_id',
      'source_record_id',
      'snapshot_date',
      'base_currency',
      'nav_base'
  );

SELECT 1 / (count(*) = 16)::int
FROM information_schema.table_constraints
WHERE table_schema = 'public'
  AND constraint_name IN (
      'brokerages_code_key',
      'brokerages_code_not_blank_check',
      'brokerages_name_not_blank_check',
      'brokerages_import_format_not_blank_check',
      'accounts_brokerage_external_id_key',
      'accounts_external_id_not_blank_check',
      'accounts_account_type_not_blank_check',
      'accounts_base_currency_uppercase_check',
      'ingestion_runs_source_type_check',
      'ingestion_runs_status_check',
      'ingestion_runs_requested_date_range_check',
      'ingestion_runs_completed_after_started_check',
      'source_records_brokerage_dedupe_key',
      'source_records_record_type_check',
      'source_records_dedupe_key_not_blank_check',
      'source_records_source_currency_uppercase_check'
  );

SELECT 1 / (count(*) = 7)::int
FROM information_schema.table_constraints
WHERE table_schema = 'public'
  AND constraint_name IN (
      'cash_flows_source_record_id_key',
      'cash_flows_cash_flow_type_not_blank_check',
      'cash_flows_currency_uppercase_check',
      'cash_flows_fx_rate_to_base_positive_check',
      'daily_nav_snapshots_source_record_id_key',
      'daily_nav_snapshots_account_snapshot_date_key',
      'daily_nav_snapshots_base_currency_uppercase_check'
  );

SELECT 1 / count(*)
FROM public.brokerages
WHERE code = 'IBKR'
  AND name = 'Interactive Brokers'
  AND import_format = 'IBKR_FLEX_XML'
  AND is_active = true;

ROLLBACK;
```

- [ ] **Step 2: Check verify file for table-name consistency**

Run:

```bash
grep -n "daily_snapshots\|daily_nav_snapshots" migrations/verify/create_mvp_schema.sql
```

Expected: every match uses `daily_nav_snapshots`; there are no matches for `daily_snapshots`.

### Task 5: Deploy and verify against a PostgreSQL target

**Files:**
- Read: `.env`
- Run against: PostgreSQL target referenced by `DATABASE_URL`

- [ ] **Step 1: Load database connection settings without printing secrets**

Run from the repository root:

```bash
export DATABASE_URL="$(grep -E '^DATABASE_URL=' .env | tail -n 1 | cut -d= -f2-)"
export SQITCH_TARGET="db:pg:${DATABASE_URL#postgresql:}"
test -n "$DATABASE_URL"
```

Expected: no output and exit code `0`.

- [ ] **Step 2: Check Sqitch status before deployment**

Run:

```bash
sqitch status "$SQITCH_TARGET"
```

Expected before implementation deployment: `create_mvp_schema` is listed as undeployed, or the target reports that changes are available to deploy.

- [ ] **Step 3: Deploy the migration**

Run:

```bash
sqitch deploy "$SQITCH_TARGET"
```

Expected: Sqitch deploys `create_mvp_schema` successfully. If `create_books` is not already deployed, Sqitch may deploy it first because it appears earlier in `migrations/sqitch.plan`.

- [ ] **Step 4: Run Sqitch verification**

Run:

```bash
sqitch verify "$SQITCH_TARGET"
```

Expected: verification succeeds for `create_mvp_schema` with no division-by-zero errors.

- [ ] **Step 5: Confirm the seeded IBKR brokerage row**

Run:

```bash
psql "$DATABASE_URL" -c "SELECT code, name, import_format, is_active FROM public.brokerages WHERE code = 'IBKR';"
```

Expected:

```text
 code |        name         | import_format | is_active
------+---------------------+---------------+-----------
 IBKR | Interactive Brokers | IBKR_FLEX_XML | t
```

### Task 6: Test rollback and redeploy

**Files:**
- Run against: PostgreSQL target referenced by `DATABASE_URL`

- [ ] **Step 1: Revert only the MVP schema change**

Run:

```bash
sqitch revert "$SQITCH_TARGET" --to-change create_books -y
```

Expected: Sqitch reverts `create_mvp_schema` and leaves `create_books` deployed.

- [ ] **Step 2: Confirm MVP tables are gone**

Run:

```bash
psql "$DATABASE_URL" -c "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('brokerages', 'accounts', 'ingestion_runs', 'source_records', 'cash_flows', 'daily_nav_snapshots') ORDER BY table_name;"
```

Expected:

```text
 table_name
------------
(0 rows)
```

- [ ] **Step 3: Redeploy and verify again**

Run:

```bash
sqitch deploy "$SQITCH_TARGET"
sqitch verify "$SQITCH_TARGET"
```

Expected: both commands complete successfully.

### Task 7: Final review and commit

**Files:**
- Modify: `migrations/sqitch.plan`
- Create: `migrations/deploy/create_mvp_schema.sql`
- Create: `migrations/revert/create_mvp_schema.sql`
- Create: `migrations/verify/create_mvp_schema.sql`
- Modify: `docs/er-diagram.md`

- [ ] **Step 1: Search for stale table names**

Run:

```bash
rg "daily_snapshots" migrations docs/er-diagram.md
```

Expected: no matches.

- [ ] **Step 2: Review the final diff**

Run:

```bash
git --no-pager diff -- migrations docs/er-diagram.md
```

Expected: diff contains the new Sqitch change, the `daily_nav_snapshots` naming in docs, and no unrelated changes.

- [ ] **Step 3: Commit the migration and ERD rename when the user is ready**

Run only after the user confirms commits are allowed:

```bash
git add migrations/sqitch.plan \
  migrations/deploy/create_mvp_schema.sql \
  migrations/revert/create_mvp_schema.sql \
  migrations/verify/create_mvp_schema.sql \
  docs/er-diagram.md
git commit -m "Add MVP portfolio schema migration" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: one commit containing the schema migration and the `daily_nav_snapshots` ERD rename.

## Self-review

- Spec coverage: the plan covers `pgcrypto`, all six finalized tables, `VARCHAR + CHECK`, nullable `raw_payload`, app-managed `updated_at`, IBKR seed data, deploy/revert/verify scripts, and the `daily_nav_snapshots` rename.
- Placeholder scan: no placeholder tasks are left; each implementation step includes exact file paths, SQL, commands, and expected outcomes.
- Type consistency: table and column names match `docs/er-diagram.md`; the plan consistently uses `daily_nav_snapshots`, `source_records.raw_payload JSONB`, and `gen_random_uuid()`.
