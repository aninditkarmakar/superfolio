# Database Ingestion Functions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add database-only ingestion functions that support explicit account registration, idempotent cash-flow and daily-NAV ingestion, bulk imports, and partial-success ingestion runs.

**Architecture:** Rewrite the existing MVP Sqitch migration in place because the deployed database has no meaningful data yet. Keep account creation separate from ingestion: ingestion functions resolve existing accounts, skip unknown or inactive accounts, and return structured statuses instead of auto-creating accounts. Use single-record functions as the canonical behavior and bulk JSONB wrapper functions to avoid app-side per-row database calls.

**Tech Stack:** PostgreSQL, Sqitch, SQL, PL/pgSQL, JSONB, `pgcrypto` for `gen_random_uuid()`.

---

## File structure

- Modify: `migrations/deploy/create_mvp_schema.sql`  
  Add `partially_succeeded` to the ingestion run status check and define all account/admin, ingestion-run, helper, single-record, and bulk ingestion functions.
- Modify: `migrations/revert/create_mvp_schema.sql`  
  Drop the functions before dropping tables so the revert is dependency-safe.
- Modify: `migrations/verify/create_mvp_schema.sql`  
  Verify the status constraint definition, function existence, and core ingestion behavior inside a transaction that rolls back.
- Create: `docs/database-functions.md`  
  Document function responsibilities, status contracts, JSONB payload shapes, and known MVP limits.

## Assumptions locked by the design

- This is database-only work. Do not modify Python ingestion scripts, Python engine modules, Next.js code, or application code.
- Rewrite `create_mvp_schema` in place rather than adding a new Sqitch change.
- Account records are created separately through database account/admin functions.
- Ingestion functions never create accounts.
- Unknown or inactive accounts are skipped per record.
- Ingestion runs can finish as `succeeded`, `partially_succeeded`, or `failed`.
- `complete_ingestion_run(...)` clears `error_message` on success and allows optional `error_message` for partial or failed runs.
- Single-record ingestion functions are the canonical implementation.
- Bulk ingestion functions call the single-record functions internally for MVP clarity.
- A later optimization may replace PL/pgSQL loops with set-based `jsonb_to_recordset(...)`, but this plan keeps one behavior path.

### Task 1: Update the schema status constraint

**Files:**
- Modify: `migrations/deploy/create_mvp_schema.sql`
- Modify: `migrations/verify/create_mvp_schema.sql`

- [ ] **Step 1: Write the failing verify check for `partially_succeeded`**

In `migrations/verify/create_mvp_schema.sql`, add this check after the existing `ingestion_runs` column check and before the generic constraint-count checks:

```sql
SELECT 1 / count(*)
FROM pg_constraint c
JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'public'
  AND t.relname = 'ingestion_runs'
  AND c.conname = 'ingestion_runs_status_check'
  AND pg_get_constraintdef(c.oid) LIKE '%partially_succeeded%';
```

- [ ] **Step 2: Run Sqitch verify to confirm it fails before implementation**

Run:

```bash
export DATABASE_URL="$(grep -E '^DATABASE_URL=' .env | tail -n 1 | cut -d= -f2-)"
export SQITCH_TARGET="db:pg:${DATABASE_URL#postgresql:}"
sqitch verify "$SQITCH_TARGET"
```

Expected: verification fails because the deployed status constraint does not yet contain `partially_succeeded`.

- [ ] **Step 3: Update the deploy status constraint**

In `migrations/deploy/create_mvp_schema.sql`, replace the current `ingestion_runs_status_check` block:

```sql
    CONSTRAINT ingestion_runs_status_check CHECK (
        status IN ('pending', 'running', 'succeeded', 'failed')
    ),
```

with:

```sql
    CONSTRAINT ingestion_runs_status_check CHECK (
        status IN ('pending', 'running', 'succeeded', 'partially_succeeded', 'failed')
    ),
```

- [ ] **Step 4: Revert and redeploy the rewritten migration**

Run:

```bash
sqitch revert "$SQITCH_TARGET" --to-change create_books -y
sqitch deploy "$SQITCH_TARGET"
sqitch verify "$SQITCH_TARGET"
```

Expected: all three commands complete successfully, and `sqitch verify` passes the new constraint-definition check.

### Task 2: Add account/admin functions

**Files:**
- Modify: `migrations/deploy/create_mvp_schema.sql`
- Modify: `migrations/revert/create_mvp_schema.sql`
- Modify: `migrations/verify/create_mvp_schema.sql`

- [ ] **Step 1: Add failing function-existence checks**

In `migrations/verify/create_mvp_schema.sql`, add this block before `ROLLBACK;`:

```sql
SELECT 1 / (count(*) = 3)::int
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.proname IN (
      'register_account',
      'update_account_metadata',
      'set_account_active'
  );
```

- [ ] **Step 2: Run verify to confirm it fails**

Run:

```bash
sqitch verify "$SQITCH_TARGET"
```

Expected: verification fails because the three account/admin functions do not exist yet.

- [ ] **Step 3: Add `register_account(...)` to the deploy migration**

Append this function after the IBKR seed insert and before `COMMIT;` in `migrations/deploy/create_mvp_schema.sql`:

```sql
CREATE FUNCTION public.register_account(
    p_brokerage_code TEXT,
    p_external_id TEXT,
    p_account_type TEXT,
    p_base_currency TEXT,
    p_display_name TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_brokerage_id UUID;
    v_account_id UUID;
    v_existing_account_type TEXT;
    v_existing_base_currency TEXT;
BEGIN
    SELECT id INTO v_brokerage_id
    FROM public.brokerages
    WHERE code = upper(btrim(p_brokerage_code))
      AND is_active = true;

    IF v_brokerage_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or inactive brokerage code: %', p_brokerage_code;
    END IF;

    SELECT id, account_type, base_currency
      INTO v_account_id, v_existing_account_type, v_existing_base_currency
    FROM public.accounts
    WHERE brokerage_id = v_brokerage_id
      AND external_id = btrim(p_external_id);

    IF v_account_id IS NOT NULL THEN
        IF v_existing_account_type <> btrim(p_account_type)
           OR v_existing_base_currency <> upper(btrim(p_base_currency)) THEN
            RAISE EXCEPTION
                'Account % already exists with account_type %, base_currency %',
                p_external_id,
                v_existing_account_type,
                v_existing_base_currency;
        END IF;

        RETURN v_account_id;
    END IF;

    INSERT INTO public.accounts (
        brokerage_id,
        external_id,
        display_name,
        account_type,
        base_currency
    )
    VALUES (
        v_brokerage_id,
        btrim(p_external_id),
        NULLIF(btrim(p_display_name), ''),
        btrim(p_account_type),
        upper(btrim(p_base_currency))
    )
    RETURNING id INTO v_account_id;

    RETURN v_account_id;
END;
$$;
```

- [ ] **Step 4: Add `update_account_metadata(...)` to the deploy migration**

Append this function after `register_account(...)`:

```sql
CREATE FUNCTION public.update_account_metadata(
    p_account_id UUID,
    p_display_name TEXT,
    p_account_type TEXT
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_account_id UUID;
BEGIN
    UPDATE public.accounts
    SET display_name = NULLIF(btrim(p_display_name), ''),
        account_type = btrim(p_account_type),
        updated_at = now()
    WHERE id = p_account_id
    RETURNING id INTO v_account_id;

    IF v_account_id IS NULL THEN
        RAISE EXCEPTION 'Unknown account id: %', p_account_id;
    END IF;

    RETURN v_account_id;
END;
$$;
```

- [ ] **Step 5: Add `set_account_active(...)` to the deploy migration**

Append this function after `update_account_metadata(...)`:

```sql
CREATE FUNCTION public.set_account_active(
    p_account_id UUID,
    p_is_active BOOLEAN
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_account_id UUID;
BEGIN
    UPDATE public.accounts
    SET is_active = p_is_active,
        updated_at = now()
    WHERE id = p_account_id
    RETURNING id INTO v_account_id;

    IF v_account_id IS NULL THEN
        RAISE EXCEPTION 'Unknown account id: %', p_account_id;
    END IF;

    RETURN v_account_id;
END;
$$;
```

- [ ] **Step 6: Add function drops to the revert migration**

In `migrations/revert/create_mvp_schema.sql`, add these lines immediately after `BEGIN;` and before the seed delete/table drops:

```sql
DROP FUNCTION IF EXISTS public.set_account_active(UUID, BOOLEAN);
DROP FUNCTION IF EXISTS public.update_account_metadata(UUID, TEXT, TEXT);
DROP FUNCTION IF EXISTS public.register_account(TEXT, TEXT, TEXT, TEXT, TEXT);
```

- [ ] **Step 7: Redeploy and verify**

Run:

```bash
sqitch revert "$SQITCH_TARGET" --to-change create_books -y
sqitch deploy "$SQITCH_TARGET"
sqitch verify "$SQITCH_TARGET"
```

Expected: deployment succeeds, and the new account/admin function-existence check passes.

### Task 3: Add ingestion-run functions

**Files:**
- Modify: `migrations/deploy/create_mvp_schema.sql`
- Modify: `migrations/revert/create_mvp_schema.sql`
- Modify: `migrations/verify/create_mvp_schema.sql`

- [ ] **Step 1: Add failing function-existence checks**

Update the function-existence check added in Task 2 so it expects five functions:

```sql
SELECT 1 / (count(*) = 5)::int
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.proname IN (
      'register_account',
      'update_account_metadata',
      'set_account_active',
      'start_ingestion_run',
      'complete_ingestion_run'
  );
```

- [ ] **Step 2: Run verify to confirm it fails**

Run:

```bash
sqitch verify "$SQITCH_TARGET"
```

Expected: verification fails because `start_ingestion_run` and `complete_ingestion_run` do not exist yet.

- [ ] **Step 3: Add `start_ingestion_run(...)` to the deploy migration**

Append this function after the account/admin functions:

```sql
CREATE FUNCTION public.start_ingestion_run(
    p_brokerage_code TEXT,
    p_source_type TEXT,
    p_requested_start_date DATE DEFAULT NULL,
    p_requested_end_date DATE DEFAULT NULL,
    p_source_filename TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_brokerage_id UUID;
    v_ingestion_run_id UUID;
BEGIN
    SELECT id INTO v_brokerage_id
    FROM public.brokerages
    WHERE code = upper(btrim(p_brokerage_code))
      AND is_active = true;

    IF v_brokerage_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or inactive brokerage code: %', p_brokerage_code;
    END IF;

    INSERT INTO public.ingestion_runs (
        brokerage_id,
        source_type,
        status,
        requested_start_date,
        requested_end_date,
        source_filename
    )
    VALUES (
        v_brokerage_id,
        upper(btrim(p_source_type)),
        'running',
        p_requested_start_date,
        p_requested_end_date,
        NULLIF(btrim(p_source_filename), '')
    )
    RETURNING id INTO v_ingestion_run_id;

    RETURN v_ingestion_run_id;
END;
$$;
```

- [ ] **Step 4: Add `complete_ingestion_run(...)` to the deploy migration**

Append this function after `start_ingestion_run(...)`:

```sql
CREATE FUNCTION public.complete_ingestion_run(
    p_ingestion_run_id UUID,
    p_status TEXT,
    p_error_message TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_status TEXT := lower(btrim(p_status));
    v_ingestion_run_id UUID;
BEGIN
    IF v_status NOT IN ('succeeded', 'partially_succeeded', 'failed') THEN
        RAISE EXCEPTION 'Invalid final ingestion status: %', p_status;
    END IF;

    UPDATE public.ingestion_runs
    SET status = v_status,
        completed_at = now(),
        error_message = CASE
            WHEN v_status = 'succeeded' THEN NULL
            ELSE NULLIF(btrim(p_error_message), '')
        END
    WHERE id = p_ingestion_run_id
    RETURNING id INTO v_ingestion_run_id;

    IF v_ingestion_run_id IS NULL THEN
        RAISE EXCEPTION 'Unknown ingestion run id: %', p_ingestion_run_id;
    END IF;

    RETURN v_ingestion_run_id;
END;
$$;
```

- [ ] **Step 5: Add function drops to the revert migration**

In `migrations/revert/create_mvp_schema.sql`, add these lines after `BEGIN;` and before the account/admin function drops:

```sql
DROP FUNCTION IF EXISTS public.complete_ingestion_run(UUID, TEXT, TEXT);
DROP FUNCTION IF EXISTS public.start_ingestion_run(TEXT, TEXT, DATE, DATE, TEXT);
```

- [ ] **Step 6: Add behavior checks to verify**

Append this block before `ROLLBACK;` in `migrations/verify/create_mvp_schema.sql`:

```sql
WITH started AS (
    SELECT public.start_ingestion_run(
        'IBKR',
        'MANUAL_FILE',
        DATE '2026-01-01',
        DATE '2026-01-31',
        'synthetic-flex.xml'
    ) AS ingestion_run_id
),
completed AS (
    SELECT public.complete_ingestion_run(
        ingestion_run_id,
        'partially_succeeded',
        'Skipped unknown accounts: U404'
    ) AS ingestion_run_id
    FROM started
)
SELECT 1 / count(*)
FROM public.ingestion_runs ir
JOIN completed c ON c.ingestion_run_id = ir.id
WHERE ir.status = 'partially_succeeded'
  AND ir.error_message = 'Skipped unknown accounts: U404'
  AND ir.completed_at IS NOT NULL;
```

- [ ] **Step 7: Redeploy and verify**

Run:

```bash
sqitch revert "$SQITCH_TARGET" --to-change create_books -y
sqitch deploy "$SQITCH_TARGET"
sqitch verify "$SQITCH_TARGET"
```

Expected: deployment succeeds, and verify proves a run can complete as `partially_succeeded` with an optional error summary.

### Task 4: Add internal helper functions

**Files:**
- Modify: `migrations/deploy/create_mvp_schema.sql`
- Modify: `migrations/revert/create_mvp_schema.sql`
- Modify: `migrations/verify/create_mvp_schema.sql`

- [ ] **Step 1: Add failing helper-existence checks**

Add this block before `ROLLBACK;` in `migrations/verify/create_mvp_schema.sql`:

```sql
SELECT 1 / (count(*) = 2)::int
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.proname IN (
      '_resolve_ingestion_account',
      '_insert_source_record'
  );
```

- [ ] **Step 2: Run verify to confirm it fails**

Run:

```bash
sqitch verify "$SQITCH_TARGET"
```

Expected: verification fails because the helper functions do not exist yet.

- [ ] **Step 3: Add `_resolve_ingestion_account(...)` to the deploy migration**

Append this function after the ingestion-run functions:

```sql
CREATE FUNCTION public._resolve_ingestion_account(
    p_brokerage_id UUID,
    p_account_external_id TEXT
)
RETURNS TABLE (
    account_id UUID,
    account_status TEXT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT a.id,
           CASE WHEN a.is_active THEN 'active' ELSE 'inactive' END
    FROM public.accounts a
    WHERE a.brokerage_id = p_brokerage_id
      AND a.external_id = btrim(p_account_external_id);

    IF NOT FOUND THEN
        RETURN QUERY SELECT NULL::UUID, 'unknown'::TEXT;
    END IF;
END;
$$;
```

- [ ] **Step 4: Add `_insert_source_record(...)` to the deploy migration**

Append this function after `_resolve_ingestion_account(...)`:

```sql
CREATE FUNCTION public._insert_source_record(
    p_ingestion_run_id UUID,
    p_brokerage_id UUID,
    p_account_id UUID,
    p_record_type TEXT,
    p_external_record_id TEXT,
    p_dedupe_key TEXT,
    p_source_report_date DATE,
    p_source_currency TEXT,
    p_raw_payload JSONB
)
RETURNS TABLE (
    source_record_id UUID,
    was_inserted BOOLEAN
)
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO public.source_records (
        ingestion_run_id,
        brokerage_id,
        account_id,
        record_type,
        external_record_id,
        dedupe_key,
        source_report_date,
        source_currency,
        raw_payload
    )
    VALUES (
        p_ingestion_run_id,
        p_brokerage_id,
        p_account_id,
        upper(btrim(p_record_type)),
        NULLIF(btrim(p_external_record_id), ''),
        btrim(p_dedupe_key),
        p_source_report_date,
        NULLIF(upper(btrim(p_source_currency)), ''),
        p_raw_payload
    )
    ON CONFLICT (brokerage_id, dedupe_key) DO NOTHING
    RETURNING id, true
    INTO source_record_id, was_inserted;

    IF source_record_id IS NOT NULL THEN
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT sr.id, false
      INTO source_record_id, was_inserted
    FROM public.source_records sr
    WHERE sr.brokerage_id = p_brokerage_id
      AND sr.dedupe_key = btrim(p_dedupe_key);

    RETURN NEXT;
END;
$$;
```

- [ ] **Step 5: Add helper drops to the revert migration**

In `migrations/revert/create_mvp_schema.sql`, add these lines after `BEGIN;` and before public ingestion function drops:

```sql
DROP FUNCTION IF EXISTS public._insert_source_record(UUID, UUID, UUID, TEXT, TEXT, TEXT, DATE, TEXT, JSONB);
DROP FUNCTION IF EXISTS public._resolve_ingestion_account(UUID, TEXT);
```

- [ ] **Step 6: Redeploy and verify**

Run:

```bash
sqitch revert "$SQITCH_TARGET" --to-change create_books -y
sqitch deploy "$SQITCH_TARGET"
sqitch verify "$SQITCH_TARGET"
```

Expected: deployment succeeds, and verify proves both helper functions exist.

### Task 5: Add single-record cash-flow ingestion

**Files:**
- Modify: `migrations/deploy/create_mvp_schema.sql`
- Modify: `migrations/revert/create_mvp_schema.sql`
- Modify: `migrations/verify/create_mvp_schema.sql`

- [ ] **Step 1: Add a failing function-existence check**

Update the main public function-existence check so it expects six functions and includes `ingest_cash_flow`:

```sql
SELECT 1 / (count(*) = 6)::int
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.proname IN (
      'register_account',
      'update_account_metadata',
      'set_account_active',
      'start_ingestion_run',
      'complete_ingestion_run',
      'ingest_cash_flow'
  );
```

- [ ] **Step 2: Run verify to confirm it fails**

Run:

```bash
sqitch verify "$SQITCH_TARGET"
```

Expected: verification fails because `ingest_cash_flow` does not exist yet.

- [ ] **Step 3: Add `ingest_cash_flow(...)` to the deploy migration**

Append this function after the helper functions:

```sql
CREATE FUNCTION public.ingest_cash_flow(
    p_ingestion_run_id UUID,
    p_account_external_id TEXT,
    p_external_record_id TEXT,
    p_dedupe_key TEXT,
    p_source_report_date DATE,
    p_source_currency TEXT,
    p_raw_payload JSONB,
    p_flow_date DATE,
    p_cash_flow_type TEXT,
    p_currency TEXT,
    p_amount NUMERIC,
    p_amount_base NUMERIC,
    p_fx_rate_to_base NUMERIC DEFAULT NULL,
    p_description TEXT DEFAULT NULL
)
RETURNS TABLE (
    cash_flow_id UUID,
    source_record_id UUID,
    account_id UUID,
    record_status TEXT
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_brokerage_id UUID;
    v_account_status TEXT;
    v_was_inserted BOOLEAN;
BEGIN
    SELECT ir.brokerage_id INTO v_brokerage_id
    FROM public.ingestion_runs ir
    WHERE ir.id = p_ingestion_run_id
      AND ir.status = 'running';

    IF v_brokerage_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or non-running ingestion run id: %', p_ingestion_run_id;
    END IF;

    SELECT resolved.account_id, resolved.account_status
      INTO account_id, v_account_status
    FROM public._resolve_ingestion_account(v_brokerage_id, p_account_external_id) AS resolved;

    IF v_account_status = 'unknown' THEN
        cash_flow_id := NULL;
        source_record_id := NULL;
        record_status := 'skipped_unknown_account';
        RETURN NEXT;
        RETURN;
    END IF;

    IF v_account_status = 'inactive' THEN
        cash_flow_id := NULL;
        source_record_id := NULL;
        record_status := 'skipped_inactive_account';
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT inserted.source_record_id, inserted.was_inserted
      INTO source_record_id, v_was_inserted
    FROM public._insert_source_record(
        p_ingestion_run_id,
        v_brokerage_id,
        account_id,
        'CASH_TRANSACTION',
        p_external_record_id,
        p_dedupe_key,
        p_source_report_date,
        p_source_currency,
        p_raw_payload
    ) AS inserted;

    IF NOT v_was_inserted THEN
        SELECT cf.id INTO cash_flow_id
        FROM public.cash_flows cf
        WHERE cf.source_record_id = source_record_id;

        record_status := 'skipped_duplicate';
        RETURN NEXT;
        RETURN;
    END IF;

    INSERT INTO public.cash_flows (
        account_id,
        source_record_id,
        flow_date,
        cash_flow_type,
        currency,
        amount,
        amount_base,
        fx_rate_to_base,
        description
    )
    VALUES (
        account_id,
        source_record_id,
        p_flow_date,
        btrim(p_cash_flow_type),
        upper(btrim(p_currency)),
        p_amount,
        p_amount_base,
        p_fx_rate_to_base,
        NULLIF(btrim(p_description), '')
    )
    RETURNING id INTO cash_flow_id;

    record_status := 'inserted';
    RETURN NEXT;
END;
$$;
```

- [ ] **Step 4: Add the function drop to the revert migration**

In `migrations/revert/create_mvp_schema.sql`, add this line after `BEGIN;` and before helper drops:

```sql
DROP FUNCTION IF EXISTS public.ingest_cash_flow(UUID, TEXT, TEXT, TEXT, DATE, TEXT, JSONB, DATE, TEXT, TEXT, NUMERIC, NUMERIC, NUMERIC, TEXT);
```

- [ ] **Step 5: Add verify behavior checks for cash-flow insert, duplicate, and unknown account**

Append this block before `ROLLBACK;` in `migrations/verify/create_mvp_schema.sql`:

```sql
WITH account_created AS (
    SELECT public.register_account(
        'IBKR',
        'U100',
        'INDIVIDUAL',
        'USD',
        'Synthetic Account'
    ) AS account_id
),
run_started AS (
    SELECT public.start_ingestion_run(
        'IBKR',
        'MANUAL_FILE',
        DATE '2026-02-01',
        DATE '2026-02-28',
        'cash-flow-synthetic.xml'
    ) AS ingestion_run_id
),
first_insert AS (
    SELECT result.record_status, result.cash_flow_id
    FROM run_started r,
         public.ingest_cash_flow(
             r.ingestion_run_id,
             'U100',
             'CF-1',
             'IBKR:U100:CASH:2026-02-03:CF-1',
             DATE '2026-02-03',
             'USD',
             '{"accountId":"U100","amount":"1000.00"}'::jsonb,
             DATE '2026-02-03',
             'Deposits/Withdrawals',
             'USD',
             1000.00,
             1000.00,
             1.0,
             'Synthetic deposit'
         ) AS result
),
duplicate_insert AS (
    SELECT result.record_status
    FROM run_started r,
         public.ingest_cash_flow(
             r.ingestion_run_id,
             'U100',
             'CF-1',
             'IBKR:U100:CASH:2026-02-03:CF-1',
             DATE '2026-02-03',
             'USD',
             '{"accountId":"U100","amount":"1000.00"}'::jsonb,
             DATE '2026-02-03',
             'Deposits/Withdrawals',
             'USD',
             1000.00,
             1000.00,
             1.0,
             'Synthetic deposit'
         ) AS result
),
unknown_insert AS (
    SELECT result.record_status
    FROM run_started r,
         public.ingest_cash_flow(
             r.ingestion_run_id,
             'U404',
             'CF-404',
             'IBKR:U404:CASH:2026-02-04:CF-404',
             DATE '2026-02-04',
             'USD',
             '{"accountId":"U404","amount":"500.00"}'::jsonb,
             DATE '2026-02-04',
             'Deposits/Withdrawals',
             'USD',
             500.00,
             500.00,
             1.0,
             'Synthetic skipped deposit'
         ) AS result
)
SELECT 1 / count(*)
FROM first_insert fi
CROSS JOIN duplicate_insert di
CROSS JOIN unknown_insert ui
WHERE fi.record_status = 'inserted'
  AND fi.cash_flow_id IS NOT NULL
  AND di.record_status = 'skipped_duplicate'
  AND ui.record_status = 'skipped_unknown_account';
```

- [ ] **Step 6: Redeploy and verify**

Run:

```bash
sqitch revert "$SQITCH_TARGET" --to-change create_books -y
sqitch deploy "$SQITCH_TARGET"
sqitch verify "$SQITCH_TARGET"
```

Expected: verification proves cash-flow insert, duplicate skip, and unknown-account skip behavior.

### Task 6: Add single-record daily-NAV ingestion

**Files:**
- Modify: `migrations/deploy/create_mvp_schema.sql`
- Modify: `migrations/revert/create_mvp_schema.sql`
- Modify: `migrations/verify/create_mvp_schema.sql`

- [ ] **Step 1: Add a failing function-existence check**

Update the main public function-existence check so it expects seven functions and includes `ingest_daily_nav_snapshot`:

```sql
SELECT 1 / (count(*) = 7)::int
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.proname IN (
      'register_account',
      'update_account_metadata',
      'set_account_active',
      'start_ingestion_run',
      'complete_ingestion_run',
      'ingest_cash_flow',
      'ingest_daily_nav_snapshot'
  );
```

- [ ] **Step 2: Run verify to confirm it fails**

Run:

```bash
sqitch verify "$SQITCH_TARGET"
```

Expected: verification fails because `ingest_daily_nav_snapshot` does not exist yet.

- [ ] **Step 3: Add `ingest_daily_nav_snapshot(...)` to the deploy migration**

Append this function after `ingest_cash_flow(...)`:

```sql
CREATE FUNCTION public.ingest_daily_nav_snapshot(
    p_ingestion_run_id UUID,
    p_account_external_id TEXT,
    p_external_record_id TEXT,
    p_dedupe_key TEXT,
    p_source_report_date DATE,
    p_source_currency TEXT,
    p_raw_payload JSONB,
    p_snapshot_date DATE,
    p_base_currency TEXT,
    p_nav_base NUMERIC
)
RETURNS TABLE (
    daily_nav_snapshot_id UUID,
    source_record_id UUID,
    account_id UUID,
    record_status TEXT
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_brokerage_id UUID;
    v_account_status TEXT;
    v_was_inserted BOOLEAN;
BEGIN
    SELECT ir.brokerage_id INTO v_brokerage_id
    FROM public.ingestion_runs ir
    WHERE ir.id = p_ingestion_run_id
      AND ir.status = 'running';

    IF v_brokerage_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or non-running ingestion run id: %', p_ingestion_run_id;
    END IF;

    SELECT resolved.account_id, resolved.account_status
      INTO account_id, v_account_status
    FROM public._resolve_ingestion_account(v_brokerage_id, p_account_external_id) AS resolved;

    IF v_account_status = 'unknown' THEN
        daily_nav_snapshot_id := NULL;
        source_record_id := NULL;
        record_status := 'skipped_unknown_account';
        RETURN NEXT;
        RETURN;
    END IF;

    IF v_account_status = 'inactive' THEN
        daily_nav_snapshot_id := NULL;
        source_record_id := NULL;
        record_status := 'skipped_inactive_account';
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT sr.id INTO source_record_id
    FROM public.source_records sr
    WHERE sr.brokerage_id = v_brokerage_id
      AND sr.dedupe_key = btrim(p_dedupe_key);

    IF source_record_id IS NOT NULL THEN
        SELECT dns.id INTO daily_nav_snapshot_id
        FROM public.daily_nav_snapshots dns
        WHERE dns.source_record_id = source_record_id;

        record_status := 'skipped_duplicate';
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT dns.id INTO daily_nav_snapshot_id
    FROM public.daily_nav_snapshots dns
    WHERE dns.account_id = account_id
      AND dns.snapshot_date = p_snapshot_date;

    IF daily_nav_snapshot_id IS NOT NULL THEN
        source_record_id := NULL;
        record_status := 'conflict_existing_snapshot';
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT inserted.source_record_id, inserted.was_inserted
      INTO source_record_id, v_was_inserted
    FROM public._insert_source_record(
        p_ingestion_run_id,
        v_brokerage_id,
        account_id,
        'DAILY_NAV',
        p_external_record_id,
        p_dedupe_key,
        p_source_report_date,
        p_source_currency,
        p_raw_payload
    ) AS inserted;

    INSERT INTO public.daily_nav_snapshots (
        account_id,
        source_record_id,
        snapshot_date,
        base_currency,
        nav_base
    )
    VALUES (
        account_id,
        source_record_id,
        p_snapshot_date,
        upper(btrim(p_base_currency)),
        p_nav_base
    )
    RETURNING id INTO daily_nav_snapshot_id;

    record_status := 'inserted';
    RETURN NEXT;
END;
$$;
```

- [ ] **Step 4: Add the function drop to the revert migration**

In `migrations/revert/create_mvp_schema.sql`, add this line after `BEGIN;` and before `ingest_cash_flow` drop:

```sql
DROP FUNCTION IF EXISTS public.ingest_daily_nav_snapshot(UUID, TEXT, TEXT, TEXT, DATE, TEXT, JSONB, DATE, TEXT, NUMERIC);
```

- [ ] **Step 5: Add verify behavior checks for daily-NAV insert, duplicate, unknown account, and account/date conflict**

Append this block before `ROLLBACK;` in `migrations/verify/create_mvp_schema.sql`:

```sql
WITH account_created AS (
    SELECT public.register_account(
        'IBKR',
        'U200',
        'INDIVIDUAL',
        'USD',
        'Synthetic NAV Account'
    ) AS account_id
),
run_started AS (
    SELECT public.start_ingestion_run(
        'IBKR',
        'MANUAL_FILE',
        DATE '2026-03-01',
        DATE '2026-03-31',
        'daily-nav-synthetic.xml'
    ) AS ingestion_run_id
),
first_insert AS (
    SELECT result.record_status, result.daily_nav_snapshot_id
    FROM run_started r,
         public.ingest_daily_nav_snapshot(
             r.ingestion_run_id,
             'U200',
             'NAV-1',
             'IBKR:U200:NAV:2026-03-03:NAV-1',
             DATE '2026-03-03',
             'USD',
             '{"accountId":"U200","nav":"12345.67"}'::jsonb,
             DATE '2026-03-03',
             'USD',
             12345.67
         ) AS result
),
duplicate_insert AS (
    SELECT result.record_status
    FROM run_started r,
         public.ingest_daily_nav_snapshot(
             r.ingestion_run_id,
             'U200',
             'NAV-1',
             'IBKR:U200:NAV:2026-03-03:NAV-1',
             DATE '2026-03-03',
             'USD',
             '{"accountId":"U200","nav":"12345.67"}'::jsonb,
             DATE '2026-03-03',
             'USD',
             12345.67
         ) AS result
),
unknown_insert AS (
    SELECT result.record_status
    FROM run_started r,
         public.ingest_daily_nav_snapshot(
             r.ingestion_run_id,
             'U404',
             'NAV-404',
             'IBKR:U404:NAV:2026-03-04:NAV-404',
             DATE '2026-03-04',
             'USD',
             '{"accountId":"U404","nav":"999.99"}'::jsonb,
             DATE '2026-03-04',
             'USD',
             999.99
         ) AS result
),
conflict_insert AS (
    SELECT result.record_status
    FROM run_started r,
         public.ingest_daily_nav_snapshot(
             r.ingestion_run_id,
             'U200',
             'NAV-2',
             'IBKR:U200:NAV:2026-03-03:NAV-2',
             DATE '2026-03-03',
             'USD',
             '{"accountId":"U200","nav":"12345.67","revision":"second-source"}'::jsonb,
             DATE '2026-03-03',
             'USD',
             12345.67
         ) AS result
)
SELECT 1 / count(*)
FROM first_insert fi
CROSS JOIN duplicate_insert di
CROSS JOIN unknown_insert ui
CROSS JOIN conflict_insert ci
WHERE fi.record_status = 'inserted'
  AND fi.daily_nav_snapshot_id IS NOT NULL
  AND di.record_status = 'skipped_duplicate'
  AND ui.record_status = 'skipped_unknown_account'
  AND ci.record_status = 'conflict_existing_snapshot';
```

- [ ] **Step 6: Redeploy and verify**

Run:

```bash
sqitch revert "$SQITCH_TARGET" --to-change create_books -y
sqitch deploy "$SQITCH_TARGET"
sqitch verify "$SQITCH_TARGET"
```

Expected: verification proves daily-NAV insert, duplicate skip, unknown-account skip, and account/date conflict behavior.

### Task 7: Add bulk ingestion functions

**Files:**
- Modify: `migrations/deploy/create_mvp_schema.sql`
- Modify: `migrations/revert/create_mvp_schema.sql`
- Modify: `migrations/verify/create_mvp_schema.sql`

- [ ] **Step 1: Add failing function-existence checks**

Update the main public function-existence check so it expects nine functions and includes both bulk functions:

```sql
SELECT 1 / (count(*) = 9)::int
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.proname IN (
      'register_account',
      'update_account_metadata',
      'set_account_active',
      'start_ingestion_run',
      'complete_ingestion_run',
      'ingest_cash_flow',
      'ingest_daily_nav_snapshot',
      'bulk_ingest_cash_flows',
      'bulk_ingest_daily_nav_snapshots'
  );
```

- [ ] **Step 2: Run verify to confirm it fails**

Run:

```bash
sqitch verify "$SQITCH_TARGET"
```

Expected: verification fails because the bulk functions do not exist yet.

- [ ] **Step 3: Add `bulk_ingest_cash_flows(...)` to the deploy migration**

Append this function after `ingest_daily_nav_snapshot(...)`:

```sql
CREATE FUNCTION public.bulk_ingest_cash_flows(
    p_ingestion_run_id UUID,
    p_records JSONB
)
RETURNS TABLE (
    inserted_count INTEGER,
    duplicate_count INTEGER,
    skipped_unknown_account_count INTEGER,
    skipped_inactive_account_count INTEGER,
    conflict_count INTEGER,
    skipped_accounts TEXT[],
    record_results JSONB
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_record JSONB;
    v_result RECORD;
    v_results JSONB := '[]'::jsonb;
    v_skipped_accounts TEXT[] := ARRAY[]::TEXT[];
BEGIN
    inserted_count := 0;
    duplicate_count := 0;
    skipped_unknown_account_count := 0;
    skipped_inactive_account_count := 0;
    conflict_count := 0;

    IF jsonb_typeof(p_records) <> 'array' THEN
        RAISE EXCEPTION 'bulk_ingest_cash_flows expects a JSONB array';
    END IF;

    FOR v_record IN SELECT value FROM jsonb_array_elements(p_records)
    LOOP
        SELECT *
          INTO v_result
        FROM public.ingest_cash_flow(
            p_ingestion_run_id,
            v_record->>'account_external_id',
            v_record->>'external_record_id',
            v_record->>'dedupe_key',
            (v_record->>'source_report_date')::DATE,
            v_record->>'source_currency',
            v_record->'raw_payload',
            (v_record->>'flow_date')::DATE,
            v_record->>'cash_flow_type',
            v_record->>'currency',
            (v_record->>'amount')::NUMERIC,
            (v_record->>'amount_base')::NUMERIC,
            NULLIF(v_record->>'fx_rate_to_base', '')::NUMERIC,
            v_record->>'description'
        );

        inserted_count := inserted_count + CASE WHEN v_result.record_status = 'inserted' THEN 1 ELSE 0 END;
        duplicate_count := duplicate_count + CASE WHEN v_result.record_status = 'skipped_duplicate' THEN 1 ELSE 0 END;
        skipped_unknown_account_count := skipped_unknown_account_count + CASE WHEN v_result.record_status = 'skipped_unknown_account' THEN 1 ELSE 0 END;
        skipped_inactive_account_count := skipped_inactive_account_count + CASE WHEN v_result.record_status = 'skipped_inactive_account' THEN 1 ELSE 0 END;
        conflict_count := conflict_count + CASE WHEN v_result.record_status LIKE 'conflict_%' THEN 1 ELSE 0 END;

        IF v_result.record_status IN ('skipped_unknown_account', 'skipped_inactive_account') THEN
            v_skipped_accounts := array_append(v_skipped_accounts, v_record->>'account_external_id');
        END IF;

        v_results := v_results || jsonb_build_array(jsonb_build_object(
            'account_external_id', v_record->>'account_external_id',
            'dedupe_key', v_record->>'dedupe_key',
            'record_status', v_result.record_status,
            'cash_flow_id', v_result.cash_flow_id,
            'source_record_id', v_result.source_record_id,
            'account_id', v_result.account_id
        ));
    END LOOP;

    SELECT ARRAY(
        SELECT DISTINCT skipped_account
        FROM unnest(v_skipped_accounts) AS skipped_account
        WHERE skipped_account IS NOT NULL
        ORDER BY skipped_account
    ) INTO skipped_accounts;

    record_results := v_results;
    RETURN NEXT;
END;
$$;
```

- [ ] **Step 4: Add `bulk_ingest_daily_nav_snapshots(...)` to the deploy migration**

Append this function after `bulk_ingest_cash_flows(...)`:

```sql
CREATE FUNCTION public.bulk_ingest_daily_nav_snapshots(
    p_ingestion_run_id UUID,
    p_records JSONB
)
RETURNS TABLE (
    inserted_count INTEGER,
    duplicate_count INTEGER,
    skipped_unknown_account_count INTEGER,
    skipped_inactive_account_count INTEGER,
    conflict_count INTEGER,
    skipped_accounts TEXT[],
    record_results JSONB
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_record JSONB;
    v_result RECORD;
    v_results JSONB := '[]'::jsonb;
    v_skipped_accounts TEXT[] := ARRAY[]::TEXT[];
BEGIN
    inserted_count := 0;
    duplicate_count := 0;
    skipped_unknown_account_count := 0;
    skipped_inactive_account_count := 0;
    conflict_count := 0;

    IF jsonb_typeof(p_records) <> 'array' THEN
        RAISE EXCEPTION 'bulk_ingest_daily_nav_snapshots expects a JSONB array';
    END IF;

    FOR v_record IN SELECT value FROM jsonb_array_elements(p_records)
    LOOP
        SELECT *
          INTO v_result
        FROM public.ingest_daily_nav_snapshot(
            p_ingestion_run_id,
            v_record->>'account_external_id',
            v_record->>'external_record_id',
            v_record->>'dedupe_key',
            (v_record->>'source_report_date')::DATE,
            v_record->>'source_currency',
            v_record->'raw_payload',
            (v_record->>'snapshot_date')::DATE,
            v_record->>'base_currency',
            (v_record->>'nav_base')::NUMERIC
        );

        inserted_count := inserted_count + CASE WHEN v_result.record_status = 'inserted' THEN 1 ELSE 0 END;
        duplicate_count := duplicate_count + CASE WHEN v_result.record_status = 'skipped_duplicate' THEN 1 ELSE 0 END;
        skipped_unknown_account_count := skipped_unknown_account_count + CASE WHEN v_result.record_status = 'skipped_unknown_account' THEN 1 ELSE 0 END;
        skipped_inactive_account_count := skipped_inactive_account_count + CASE WHEN v_result.record_status = 'skipped_inactive_account' THEN 1 ELSE 0 END;
        conflict_count := conflict_count + CASE WHEN v_result.record_status LIKE 'conflict_%' THEN 1 ELSE 0 END;

        IF v_result.record_status IN ('skipped_unknown_account', 'skipped_inactive_account') THEN
            v_skipped_accounts := array_append(v_skipped_accounts, v_record->>'account_external_id');
        END IF;

        v_results := v_results || jsonb_build_array(jsonb_build_object(
            'account_external_id', v_record->>'account_external_id',
            'dedupe_key', v_record->>'dedupe_key',
            'record_status', v_result.record_status,
            'daily_nav_snapshot_id', v_result.daily_nav_snapshot_id,
            'source_record_id', v_result.source_record_id,
            'account_id', v_result.account_id
        ));
    END LOOP;

    SELECT ARRAY(
        SELECT DISTINCT skipped_account
        FROM unnest(v_skipped_accounts) AS skipped_account
        WHERE skipped_account IS NOT NULL
        ORDER BY skipped_account
    ) INTO skipped_accounts;

    record_results := v_results;
    RETURN NEXT;
END;
$$;
```

- [ ] **Step 5: Add bulk function drops to the revert migration**

In `migrations/revert/create_mvp_schema.sql`, add these lines after `BEGIN;` and before single-record function drops:

```sql
DROP FUNCTION IF EXISTS public.bulk_ingest_daily_nav_snapshots(UUID, JSONB);
DROP FUNCTION IF EXISTS public.bulk_ingest_cash_flows(UUID, JSONB);
```

- [ ] **Step 6: Add verify behavior checks for bulk cash-flow summary**

Append this block before `ROLLBACK;` in `migrations/verify/create_mvp_schema.sql`:

```sql
WITH account_created AS (
    SELECT public.register_account(
        'IBKR',
        'U300',
        'INDIVIDUAL',
        'USD',
        'Bulk Cash Account'
    ) AS account_id
),
run_started AS (
    SELECT public.start_ingestion_run(
        'IBKR',
        'MANUAL_FILE',
        DATE '2026-04-01',
        DATE '2026-04-30',
        'bulk-cash-synthetic.xml'
    ) AS ingestion_run_id
),
bulk_result AS (
    SELECT result.*
    FROM run_started r,
         public.bulk_ingest_cash_flows(
             r.ingestion_run_id,
             jsonb_build_array(
                 jsonb_build_object(
                     'account_external_id', 'U300',
                     'external_record_id', 'BCF-1',
                     'dedupe_key', 'IBKR:U300:CASH:2026-04-03:BCF-1',
                     'source_report_date', '2026-04-03',
                     'source_currency', 'USD',
                     'raw_payload', jsonb_build_object('accountId', 'U300', 'amount', '100.00'),
                     'flow_date', '2026-04-03',
                     'cash_flow_type', 'Deposits/Withdrawals',
                     'currency', 'USD',
                     'amount', '100.00',
                     'amount_base', '100.00',
                     'fx_rate_to_base', '1.0',
                     'description', 'Bulk synthetic deposit'
                 ),
                 jsonb_build_object(
                     'account_external_id', 'U404',
                     'external_record_id', 'BCF-404',
                     'dedupe_key', 'IBKR:U404:CASH:2026-04-03:BCF-404',
                     'source_report_date', '2026-04-03',
                     'source_currency', 'USD',
                     'raw_payload', jsonb_build_object('accountId', 'U404', 'amount', '25.00'),
                     'flow_date', '2026-04-03',
                     'cash_flow_type', 'Deposits/Withdrawals',
                     'currency', 'USD',
                     'amount', '25.00',
                     'amount_base', '25.00',
                     'fx_rate_to_base', '1.0',
                     'description', 'Bulk skipped deposit'
                 )
             )
         ) AS result
)
SELECT 1 / count(*)
FROM bulk_result
WHERE inserted_count = 1
  AND duplicate_count = 0
  AND skipped_unknown_account_count = 1
  AND skipped_inactive_account_count = 0
  AND conflict_count = 0
  AND skipped_accounts = ARRAY['U404']::TEXT[];
```

- [ ] **Step 7: Add verify behavior checks for bulk daily-NAV summary**

Append this block before `ROLLBACK;` in `migrations/verify/create_mvp_schema.sql`:

```sql
WITH account_created AS (
    SELECT public.register_account(
        'IBKR',
        'U400',
        'INDIVIDUAL',
        'USD',
        'Bulk NAV Account'
    ) AS account_id
),
run_started AS (
    SELECT public.start_ingestion_run(
        'IBKR',
        'MANUAL_FILE',
        DATE '2026-05-01',
        DATE '2026-05-31',
        'bulk-nav-synthetic.xml'
    ) AS ingestion_run_id
),
bulk_result AS (
    SELECT result.*
    FROM run_started r,
         public.bulk_ingest_daily_nav_snapshots(
             r.ingestion_run_id,
             jsonb_build_array(
                 jsonb_build_object(
                     'account_external_id', 'U400',
                     'external_record_id', 'BNAV-1',
                     'dedupe_key', 'IBKR:U400:NAV:2026-05-03:BNAV-1',
                     'source_report_date', '2026-05-03',
                     'source_currency', 'USD',
                     'raw_payload', jsonb_build_object('accountId', 'U400', 'nav', '10000.00'),
                     'snapshot_date', '2026-05-03',
                     'base_currency', 'USD',
                     'nav_base', '10000.00'
                 ),
                 jsonb_build_object(
                     'account_external_id', 'U404',
                     'external_record_id', 'BNAV-404',
                     'dedupe_key', 'IBKR:U404:NAV:2026-05-03:BNAV-404',
                     'source_report_date', '2026-05-03',
                     'source_currency', 'USD',
                     'raw_payload', jsonb_build_object('accountId', 'U404', 'nav', '500.00'),
                     'snapshot_date', '2026-05-03',
                     'base_currency', 'USD',
                     'nav_base', '500.00'
                 )
             )
         ) AS result
)
SELECT 1 / count(*)
FROM bulk_result
WHERE inserted_count = 1
  AND duplicate_count = 0
  AND skipped_unknown_account_count = 1
  AND skipped_inactive_account_count = 0
  AND conflict_count = 0
  AND skipped_accounts = ARRAY['U404']::TEXT[];
```

- [ ] **Step 8: Redeploy and verify**

Run:

```bash
sqitch revert "$SQITCH_TARGET" --to-change create_books -y
sqitch deploy "$SQITCH_TARGET"
sqitch verify "$SQITCH_TARGET"
```

Expected: verification proves bulk wrappers summarize inserted and skipped records correctly.

### Task 8: Document database function contracts

**Files:**
- Create: `docs/database-functions.md`

- [ ] **Step 1: Create the database functions documentation**

Create `docs/database-functions.md` with:

```markdown
# Database Function Contracts

SuperFolio uses PostgreSQL functions as the database mutation boundary for ingestion and account administration. Application and ingestion clients should call these functions instead of writing directly to normalized ingestion tables.

## Account functions

| Function | Purpose |
| --- | --- |
| `register_account(...)` | Explicitly registers an account before ingestion. It returns the existing account id only when the existing account has the same account type and base currency. It raises on unknown brokerage or conflicting account metadata. |
| `update_account_metadata(...)` | Updates user/admin-controlled account label and account type. It does not change broker identity or base currency. |
| `set_account_active(...)` | Activates or deactivates an account. Ingestion skips inactive accounts. |

## Ingestion run functions

| Function | Purpose |
| --- | --- |
| `start_ingestion_run(...)` | Creates a `running` ingestion run for a brokerage, source type, optional date range, and optional source filename. |
| `complete_ingestion_run(...)` | Finalizes a run as `succeeded`, `partially_succeeded`, or `failed`. It clears `error_message` for success and allows an optional message for partial or failed runs. |

## Single-record ingestion functions

| Function | Purpose |
| --- | --- |
| `ingest_cash_flow(...)` | Resolves an existing active account, inserts a source record idempotently, then inserts one normalized cash-flow row. |
| `ingest_daily_nav_snapshot(...)` | Resolves an existing active account, checks source-record and account/date conflicts, inserts a source record idempotently, then inserts one normalized daily NAV row. |

Single-record functions return a `record_status`:

| Status | Meaning |
| --- | --- |
| `inserted` | A new source record and normalized row were inserted. |
| `skipped_duplicate` | The source dedupe key already exists. No new normalized row was inserted. |
| `skipped_unknown_account` | The source account id was not registered for the brokerage. |
| `skipped_inactive_account` | The source account exists but is inactive. |
| `conflict_existing_snapshot` | A daily NAV row already exists for the account/date with a different source dedupe key. |

## Bulk ingestion functions

| Function | Purpose |
| --- | --- |
| `bulk_ingest_cash_flows(p_ingestion_run_id uuid, p_records jsonb)` | Processes a JSONB array of cash-flow records using `ingest_cash_flow(...)`. |
| `bulk_ingest_daily_nav_snapshots(p_ingestion_run_id uuid, p_records jsonb)` | Processes a JSONB array of NAV records using `ingest_daily_nav_snapshot(...)`. |

Bulk functions return summary counts:

| Field | Meaning |
| --- | --- |
| `inserted_count` | Records inserted as new normalized rows. |
| `duplicate_count` | Records skipped because the source dedupe key already exists. |
| `skipped_unknown_account_count` | Records skipped because account configuration is missing. |
| `skipped_inactive_account_count` | Records skipped because account configuration is inactive. |
| `conflict_count` | Records skipped because of a canonical-data conflict. |
| `skipped_accounts` | Distinct external account ids skipped for unknown or inactive account status. |
| `record_results` | Per-record result details for diagnostics. |

## Cash-flow bulk JSON shape

```json
[
  {
    "account_external_id": "U100",
    "external_record_id": "CF-1",
    "dedupe_key": "IBKR:U100:CASH:2026-02-03:CF-1",
    "source_report_date": "2026-02-03",
    "source_currency": "USD",
    "raw_payload": {"accountId": "U100", "amount": "1000.00"},
    "flow_date": "2026-02-03",
    "cash_flow_type": "Deposits/Withdrawals",
    "currency": "USD",
    "amount": "1000.00",
    "amount_base": "1000.00",
    "fx_rate_to_base": "1.0",
    "description": "Synthetic deposit"
  }
]
```

## Daily NAV bulk JSON shape

```json
[
  {
    "account_external_id": "U200",
    "external_record_id": "NAV-1",
    "dedupe_key": "IBKR:U200:NAV:2026-03-03:NAV-1",
    "source_report_date": "2026-03-03",
    "source_currency": "USD",
    "raw_payload": {"accountId": "U200", "nav": "12345.67"},
    "snapshot_date": "2026-03-03",
    "base_currency": "USD",
    "nav_base": "12345.67"
  }
]
```

## MVP limits

- The bulk functions process records in a PL/pgSQL loop to keep one canonical behavior path. This avoids app-side per-record network calls while keeping the implementation simple.
- Unexpected malformed JSON or type-cast errors abort the bulk function. Account-level misses are handled as skipped records.
- Skipped-account summaries live in the function return value and can be copied by callers into `ingestion_runs.error_message` when completing a run as `partially_succeeded`.
```

- [ ] **Step 2: Check documentation for Python scope creep**

Run:

```bash
rg "Python|calculate_twr|portfolio_engine|scripts/calculate_twr" docs/database-functions.md
```

Expected: no matches. This phase is database-only.

### Task 9: Final validation

**Files:**
- Modify: `migrations/deploy/create_mvp_schema.sql`
- Modify: `migrations/revert/create_mvp_schema.sql`
- Modify: `migrations/verify/create_mvp_schema.sql`
- Create: `docs/database-functions.md`

- [ ] **Step 1: Revert, redeploy, and verify from a clean MVP migration state**

Run:

```bash
sqitch revert "$SQITCH_TARGET" --to-change create_books -y
sqitch deploy "$SQITCH_TARGET"
sqitch verify "$SQITCH_TARGET"
```

Expected: all commands complete successfully.

- [ ] **Step 2: Confirm no Python files changed**

Run:

```bash
git --no-pager diff --name-only | rg "^(portfolio_engine/|scripts/|.*\.py$)" || true
```

Expected: no output.

- [ ] **Step 3: Review the database-only diff**

Run:

```bash
git --no-pager diff -- migrations/deploy/create_mvp_schema.sql migrations/revert/create_mvp_schema.sql migrations/verify/create_mvp_schema.sql docs/database-functions.md
```

Expected: diff contains only database migration/function changes and database function documentation.

- [ ] **Step 4: Commit when the user approves**

Run only after the user confirms commits are allowed:

```bash
git add migrations/deploy/create_mvp_schema.sql \
  migrations/revert/create_mvp_schema.sql \
  migrations/verify/create_mvp_schema.sql \
  docs/database-functions.md
git commit -m "Add database ingestion functions" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: one commit containing the database-only ingestion function work.

## Self-review

- Spec coverage: the plan covers partial ingestion status, explicit account registration, account metadata updates, account activation, ingestion run start/complete, internal helper functions, single-record cash-flow and NAV ingestion, bulk JSONB ingestion, skip statuses, conflict status, verification, documentation, and the database-only scope restriction.
- Placeholder scan: no task uses placeholder language; each implementation step includes exact file paths, SQL blocks, commands, and expected outcomes.
- Type consistency: function names, parameter names, status strings, table names, and return columns are consistent across deploy, revert, verify, and documentation tasks.
