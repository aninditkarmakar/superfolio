# Account-Scoped Manual Flex Imports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make manual Flex `dry-run` and `load` account-scoped by requiring `--account-external-id`, filtering supported XML records to that account, and recording the selected account on load ingestion runs.

**Architecture:** Extend the database ingestion-run contract first so `load` can persist the user-selected account for auditability. Then add an account-scoped analysis result that keeps full records internal, gives both CLI modes matching filtered records, and reports non-target skip counts without exposing sensitive values.

**Tech Stack:** Python 3.12 standard library (`argparse`, `dataclasses`, `pathlib`, `unittest`, `tempfile`), existing PostgreSQL/Sqitch SQL migrations, and existing `portfolio_engine.database`, `portfolio_engine.ingestion.dry_run`, and `portfolio_engine.ingestion_cli`.

---

## File structure

- Modify: `migrations/deploy/create_mvp_schema.sql`  
  Add `ingestion_runs.account_id`, update `start_ingestion_run(...)` to accept and resolve `p_account_external_id`, and store the resolved active account on the run.
- Modify: `migrations/revert/create_mvp_schema.sql`  
  Update the dropped `start_ingestion_run(...)` signature so revert remains accurate.
- Modify: `migrations/verify/create_mvp_schema.sql`  
  Verify `ingestion_runs.account_id`, the updated function signature, target account persistence, and failure on unknown target accounts.
- Modify: `portfolio_engine/database.py`  
  Add `account_external_id` to `IngestionRunStart` and pass it to `public.start_ingestion_run(...)`.
- Modify: `tests/test_database_adapter.py`  
  Update adapter expectations for the new `start_ingestion_run(...)` signature.
- Modify: `portfolio_engine/ingestion/dry_run.py`  
  Add an account-scoped projection from full `FlexAnalysisResult` records to matching full records, privacy-safe dry-run records, and non-target skipped counts.
- Modify: `tests/test_flex_dry_run.py`  
  Add unit tests for account filtering, non-target skip counts, and dry-run privacy.
- Modify: `portfolio_engine/ingestion_cli.py`  
  Require `--account-external-id` for both commands, use account-scoped analysis for dry-run and load, pass the selected account into `IngestionRunStart`, and print target/skipped counts.
- Modify: `tests/test_ingestion_cli.py`  
  Update existing dry-run tests and add dry-run account-scope coverage.
- Modify: `tests/test_ingestion_load_cli.py`  
  Update existing load tests and add account-scope load coverage.
- Modify: `README.md`  
  Document account-scoped dry-run and load command usage.

## Locked decisions

- Both `dry-run` and `load` require `--account-external-id`.
- `dry-run` does not open a database connection and does not verify that the account exists.
- `load` requires `--brokerage-code` and validates the selected account through `start_ingestion_run(...)`.
- Supported records whose XML `accountId` differs from `--account-external-id` are skipped before bulk DB calls.
- Non-target skips are warnings and do not make the final status `partially_succeeded`.
- XML account IDs are never overwritten.
- Output may include the target account external ID and non-target skipped counts, but never amounts, NAV values, raw payloads, full records, or dedupe key values.
- Do not merge `flex-load-cli` into `main` without explicit user review and approval.

### Task 1: Persist selected account on ingestion runs

**Files:**
- Modify: `migrations/deploy/create_mvp_schema.sql`
- Modify: `migrations/revert/create_mvp_schema.sql`
- Modify: `migrations/verify/create_mvp_schema.sql`
- Modify: `portfolio_engine/database.py`
- Modify: `tests/test_database_adapter.py`

- [ ] **Step 1: Write failing database adapter tests**

Update `tests/test_database_adapter.py` so `IngestionRunStart` requires and sends `account_external_id`.

Change `test_ingestion_run_start_is_immutable` to:

```python
    def test_ingestion_run_start_is_immutable(self) -> None:
        request = IngestionRunStart(
            brokerage_code="IBKR",
            account_external_id="U100",
            source_type="MANUAL_FILE",
            requested_start_date=date(2026, 5, 1),
            requested_end_date=date(2026, 5, 31),
            source_filename="Cash_Flows.xml",
        )

        with self.assertRaises(FrozenInstanceError):
            request.source_filename = "Daily_NAV.xml"
```

Change `test_start_ingestion_run_calls_database_function` expected SQL and params to:

```python
        self.assertEqual(
            connection.cursor_instance.executed,
            [
                (
                    "SELECT public.start_ingestion_run(%s, %s, %s, %s, %s, %s)",
                    (
                        "IBKR",
                        "U100",
                        "MANUAL_FILE",
                        date(2026, 5, 1),
                        date(2026, 5, 31),
                        "Cash_Flows.xml",
                    ),
                )
            ],
        )
```

Change `test_start_ingestion_run_allows_optional_fields` to still require `account_external_id`:

```python
        database.start_ingestion_run(
            IngestionRunStart(
                brokerage_code="IBKR",
                account_external_id="U100",
                source_type="MANUAL_FILE",
            )
        )

        self.assertEqual(
            connection.cursor_instance.executed[0][1],
            ("IBKR", "U100", "MANUAL_FILE", None, None, None),
        )
```

Change `test_start_ingestion_run_rolls_back_and_reraises_on_failure` request to include:

```python
                    account_external_id="U100",
```

- [ ] **Step 2: Run adapter tests to verify failure**

Run:

```bash
python -m unittest tests.test_database_adapter -v
```

Expected: FAIL because `IngestionRunStart` has no `account_external_id` field and the adapter still calls `start_ingestion_run` with 5 arguments.

- [ ] **Step 3: Update Python database adapter**

Modify `portfolio_engine/database.py`:

```python
@dataclass(frozen=True)
class IngestionRunStart:
    brokerage_code: str
    account_external_id: str
    source_type: str
    requested_start_date: date | None = None
    requested_end_date: date | None = None
    source_filename: str | None = None
```

Update `SuperFolioDatabase.start_ingestion_run`:

```python
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
```

- [ ] **Step 4: Update SQL deploy migration**

In `migrations/deploy/create_mvp_schema.sql`, add `account_id` to `public.ingestion_runs` after `brokerage_id`:

```sql
    account_id UUID NOT NULL REFERENCES public.accounts(id),
```

Replace `public.start_ingestion_run(...)` with this account-scoped signature and body:

```sql
CREATE FUNCTION public.start_ingestion_run(
    p_brokerage_code TEXT,
    p_account_external_id TEXT,
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
    v_account_id UUID;
    v_ingestion_run_id UUID;
BEGIN
    IF p_source_type IS NULL OR btrim(p_source_type) = '' THEN
        RAISE EXCEPTION 'source_type must not be NULL or blank';
    END IF;

    IF p_account_external_id IS NULL OR btrim(p_account_external_id) = '' THEN
        RAISE EXCEPTION 'account_external_id must not be NULL or blank';
    END IF;

    SELECT id INTO v_brokerage_id
    FROM public.brokerages
    WHERE code = upper(btrim(p_brokerage_code))
      AND is_active = true;

    IF v_brokerage_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or inactive brokerage code: %', p_brokerage_code;
    END IF;

    SELECT id INTO v_account_id
    FROM public.accounts
    WHERE brokerage_id = v_brokerage_id
      AND external_id = btrim(p_account_external_id)
      AND is_active = true;

    IF v_account_id IS NULL THEN
        RAISE EXCEPTION 'Unknown or inactive account external_id % for brokerage %',
            p_account_external_id,
            p_brokerage_code;
    END IF;

    INSERT INTO public.ingestion_runs (
        brokerage_id,
        account_id,
        source_type,
        status,
        requested_start_date,
        requested_end_date,
        source_filename
    )
    VALUES (
        v_brokerage_id,
        v_account_id,
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

- [ ] **Step 5: Update SQL revert and verify**

In `migrations/revert/create_mvp_schema.sql`, change the dropped function signature to:

```sql
DROP FUNCTION IF EXISTS public.start_ingestion_run(TEXT, TEXT, TEXT, DATE, DATE, TEXT);
```

In `migrations/verify/create_mvp_schema.sql`, update every `public.start_ingestion_run(...)` call to include the account external ID immediately after brokerage code. For example:

```sql
    v_ingestion_run_id := public.start_ingestion_run(
        'IBKR',
        'U100',
        'MANUAL_FILE',
        DATE '2026-01-01',
        DATE '2026-01-31',
        'synthetic-flex.xml'
    );
```

Add a verification block after the first run-start verification:

```sql
DO $$
DECLARE
    v_account_id UUID;
    v_ingestion_run_id UUID;
    v_run_account_id UUID;
BEGIN
    SELECT public.register_account(
        'IBKR',
        'UVERIFY',
        'INDIVIDUAL',
        'USD',
        'Verify Account'
    ) INTO v_account_id;

    v_ingestion_run_id := public.start_ingestion_run(
        'IBKR',
        'UVERIFY',
        'MANUAL_FILE',
        DATE '2026-03-01',
        DATE '2026-03-31',
        'account-scoped.xml'
    );

    SELECT account_id INTO v_run_account_id
    FROM public.ingestion_runs
    WHERE id = v_ingestion_run_id;

    IF v_run_account_id IS DISTINCT FROM v_account_id THEN
        RAISE EXCEPTION 'Ingestion run account_id verification failed for %', v_ingestion_run_id;
    END IF;
END;
$$;
```

Add an unknown-account failure check:

```sql
DO $$
BEGIN
    PERFORM public.start_ingestion_run(
        'IBKR',
        'UDOESNOTEXIST',
        'MANUAL_FILE',
        NULL,
        NULL,
        'unknown-account.xml'
    );
    RAISE EXCEPTION 'Expected start_ingestion_run to reject an unknown account';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLERRM = 'Expected start_ingestion_run to reject an unknown account' THEN
            RAISE;
        END IF;
END;
$$;
```

- [ ] **Step 6: Run adapter tests**

Run:

```bash
python -m unittest tests.test_database_adapter -v
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

Run:

```bash
git add migrations/deploy/create_mvp_schema.sql migrations/revert/create_mvp_schema.sql migrations/verify/create_mvp_schema.sql portfolio_engine/database.py tests/test_database_adapter.py
git commit -m "feat: scope ingestion runs to target account" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Add account-scoped analyzer projection

**Files:**
- Modify: `portfolio_engine/ingestion/dry_run.py`
- Modify: `tests/test_flex_dry_run.py`

- [ ] **Step 1: Add failing analyzer tests**

In `tests/test_flex_dry_run.py`, add a mixed-account fixture near the existing XML fixtures:

```python
MIXED_ACCOUNT_XML = """<FlexQueryResponse>
  <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="1000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" />
  <CashTransaction accountId="U200" reportDate="20250102" dateTime="20250102;091501" currency="USD" amount="2000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF2" />
  <EquitySummaryByReportDateInBase accountId="U100" reportDate="20250102" currency="USD" total="10000.00" />
  <EquitySummaryByReportDateInBase accountId="U200" reportDate="20250102" currency="USD" total="20000.00" />
</FlexQueryResponse>"""
```

Add tests inside `FlexDryRunTests`:

```python
    def test_analysis_filters_to_target_account(self) -> None:
        analysis = analyze_flex_xml_text_for_ingestion(MIXED_ACCOUNT_XML)

        scoped = analysis.for_account("U100")

        self.assertEqual(scoped.account_external_id, "U100")
        self.assertEqual(scoped.cash_flow_count, 1)
        self.assertEqual(scoped.daily_nav_count, 1)
        self.assertEqual(scoped.cash_flow_records[0]["account_external_id"], "U100")
        self.assertEqual(scoped.daily_nav_records[0]["account_external_id"], "U100")
        self.assertEqual(scoped.skipped_other_account_cash_flow_count, 1)
        self.assertEqual(scoped.skipped_other_account_daily_nav_count, 1)

    def test_account_scoped_dry_run_summary_is_sanitized(self) -> None:
        summary = analyze_flex_xml_text(
            MIXED_ACCOUNT_XML,
            account_external_id="U100",
        )

        self.assertEqual(summary.account_external_id, "U100")
        self.assertEqual(summary.cash_flow_count, 1)
        self.assertEqual(summary.daily_nav_count, 1)
        self.assertEqual(summary.skipped_other_account_cash_flow_count, 1)
        self.assertEqual(summary.skipped_other_account_daily_nav_count, 1)
        self.assertNotIn("amount", summary.cash_flow_records[0])
        self.assertNotIn("nav_base", summary.daily_nav_records[0])
        self.assertNotIn("2000.00", str(summary.cash_flow_records))
        self.assertNotIn("20000.00", str(summary.daily_nav_records))
```

- [ ] **Step 2: Run analyzer tests to verify failure**

Run:

```bash
python -m unittest tests.test_flex_dry_run -v
```

Expected: FAIL because `FlexAnalysisResult.for_account(...)`, `account_external_id`, and non-target skipped count fields do not exist.

- [ ] **Step 3: Implement account-scoped dataclasses**

In `portfolio_engine/ingestion/dry_run.py`, add account-scope metadata fields to both `FlexDryRunSummary` and `FlexAnalysisResult`. This preserves the existing field-sync guard test while allowing all-account analyses to keep default account-scope metadata:

```python
    account_external_id: str | None = None
    skipped_other_account_cash_flow_count: int = 0
    skipped_other_account_daily_nav_count: int = 0
```

Update `FlexAnalysisResult.to_dry_run_summary()` to pass these fields through:

```python
            account_external_id=self.account_external_id,
            skipped_other_account_cash_flow_count=self.skipped_other_account_cash_flow_count,
            skipped_other_account_daily_nav_count=self.skipped_other_account_daily_nav_count,
```

Add a new dataclass after `FlexAnalysisResult`:

```python
@dataclass(frozen=True)
class AccountScopedFlexAnalysisResult:
    account_external_id: str
    cash_flow_records: tuple[dict[str, Any], ...]
    daily_nav_records: tuple[dict[str, Any], ...]
    unsupported_cash_transaction_count: int
    accounts_seen: tuple[str, ...]
    currencies_seen: tuple[str, ...]
    cash_flow_date_range: DateRange | None
    daily_nav_date_range: DateRange | None
    duplicate_dedupe_keys: tuple[str, ...]
    skipped_other_account_cash_flow_count: int
    skipped_other_account_daily_nav_count: int

    @property
    def cash_flow_count(self) -> int:
        return len(self.cash_flow_records)

    @property
    def daily_nav_count(self) -> int:
        return len(self.daily_nav_records)

    def to_dry_run_summary(self) -> FlexDryRunSummary:
        return FlexDryRunSummary(
            cash_flow_records=tuple(_safe_cash_flow_record(record) for record in self.cash_flow_records),
            daily_nav_records=tuple(_safe_daily_nav_record(record) for record in self.daily_nav_records),
            unsupported_cash_transaction_count=self.unsupported_cash_transaction_count,
            accounts_seen=self.accounts_seen,
            currencies_seen=self.currencies_seen,
            cash_flow_date_range=self.cash_flow_date_range,
            daily_nav_date_range=self.daily_nav_date_range,
            duplicate_dedupe_keys=self.duplicate_dedupe_keys,
            account_external_id=self.account_external_id,
            skipped_other_account_cash_flow_count=self.skipped_other_account_cash_flow_count,
            skipped_other_account_daily_nav_count=self.skipped_other_account_daily_nav_count,
        )
```

Add this method to `FlexAnalysisResult`:

```python
    def for_account(self, account_external_id: str) -> AccountScopedFlexAnalysisResult:
        target = account_external_id.strip()
        cash_flow_records = tuple(
            record for record in self.cash_flow_records
            if str(record["account_external_id"]) == target
        )
        daily_nav_records = tuple(
            record for record in self.daily_nav_records
            if str(record["account_external_id"]) == target
        )
        all_records = list(cash_flow_records + daily_nav_records)
        return AccountScopedFlexAnalysisResult(
            account_external_id=target,
            cash_flow_records=cash_flow_records,
            daily_nav_records=daily_nav_records,
            unsupported_cash_transaction_count=self.unsupported_cash_transaction_count,
            accounts_seen=(target,) if target else (),
            currencies_seen=_sorted_unique(record["source_currency"] for record in all_records),
            cash_flow_date_range=_record_date_range(list(cash_flow_records), "flow_date"),
            daily_nav_date_range=_record_date_range(list(daily_nav_records), "snapshot_date"),
            duplicate_dedupe_keys=_duplicate_dedupe_keys(all_records),
            skipped_other_account_cash_flow_count=len(self.cash_flow_records) - len(cash_flow_records),
            skipped_other_account_daily_nav_count=len(self.daily_nav_records) - len(daily_nav_records),
        )
```

Change `analyze_flex_xml_text` and `analyze_flex_xml_file` signatures to accept:

```python
    account_external_id: str | None = None,
```

If `account_external_id` is provided, return:

```python
analysis.for_account(account_external_id).to_dry_run_summary()
```

Otherwise keep the existing all-account behavior for internal tests and compatibility:

```python
analysis.to_dry_run_summary()
```

- [ ] **Step 4: Run analyzer tests**

Run:

```bash
python -m unittest tests.test_flex_dry_run -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add portfolio_engine/ingestion/dry_run.py tests/test_flex_dry_run.py
git commit -m "feat: add account-scoped Flex analysis" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Require account-scoped dry-run CLI

**Files:**
- Modify: `portfolio_engine/ingestion_cli.py`
- Modify: `tests/test_ingestion_cli.py`

- [ ] **Step 1: Add failing dry-run CLI tests**

Update every existing dry-run `run([...])` call in `tests/test_ingestion_cli.py` that should parse successfully to include:

```python
"--account-external-id",
"U100",
```

Add this test:

```python
    def test_dry_run_requires_account_external_id(self) -> None:
        stderr = io.StringIO()

        exit_code = run(["dry-run", "Flex.xml"], stdout=io.StringIO(), stderr=stderr)

        self.assertEqual(exit_code, 1)
        self.assertIn("Error:", stderr.getvalue())
        self.assertIn("account-external-id", stderr.getvalue())
```

Add mixed-account filtering test:

```python
    def test_dry_run_filters_to_target_account_and_reports_skips(self) -> None:
        mixed_account_xml = """<FlexQueryResponse>
  <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="1000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" />
  <CashTransaction accountId="U200" reportDate="20250102" dateTime="20250102;091501" currency="USD" amount="2000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF2" />
  <EquitySummaryByReportDateInBase accountId="U100" reportDate="20250102" currency="USD" total="10000.00" />
  <EquitySummaryByReportDateInBase accountId="U200" reportDate="20250102" currency="USD" total="20000.00" />
</FlexQueryResponse>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Flex.xml"
            path.write_text(mixed_account_xml, encoding="utf-8")
            stdout = io.StringIO()

            exit_code = run(
                ["dry-run", str(path), "--account-external-id", "U100"],
                stdout=stdout,
                stderr=io.StringIO(),
            )

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Target account: U100", output)
        self.assertIn("Cash-flow records mapped: 1", output)
        self.assertIn("Daily NAV snapshots mapped: 1", output)
        self.assertIn("Cash-flow records skipped for other accounts: 1", output)
        self.assertIn("Daily NAV snapshots skipped for other accounts: 1", output)
        self.assertNotIn("2000.00", output)
        self.assertNotIn("20000.00", output)
```

- [ ] **Step 2: Run dry-run CLI tests to verify failure**

Run:

```bash
python -m unittest tests.test_ingestion_cli -v
```

Expected: FAIL because the parser does not require `--account-external-id` and output does not include target/skipped lines.

- [ ] **Step 3: Implement dry-run CLI account scope**

In `portfolio_engine/ingestion_cli.py`, add to the dry-run parser:

```python
    dry_run.add_argument("--account-external-id", required=True, help="Brokerage account external ID to preview.")
```

Change the dry-run analyzer call in `run()`:

```python
            summary = analyze_flex_xml_file(
                args.file,
                start_date=args.start_date,
                end_date=args.end_date,
                account_external_id=args.account_external_id,
            )
```

Update `_print_dry_run_summary(...)` to print account scope:

```python
    if summary.account_external_id is not None:
        stdout.write(f"Target account: {summary.account_external_id}\n")
```

Replace the `Accounts seen:` line with target account output for scoped dry-run. Keep `Currencies seen:`. Add:

```python
    stdout.write(
        f"Cash-flow records skipped for other accounts: {summary.skipped_other_account_cash_flow_count}\n"
    )
    stdout.write(
        f"Daily NAV snapshots skipped for other accounts: {summary.skipped_other_account_daily_nav_count}\n"
    )
```

- [ ] **Step 4: Run dry-run CLI tests**

Run:

```bash
python -m unittest tests.test_ingestion_cli tests.test_flex_dry_run -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add portfolio_engine/ingestion_cli.py tests/test_ingestion_cli.py
git commit -m "feat: require account-scoped Flex dry-run" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Require account-scoped load CLI

**Files:**
- Modify: `portfolio_engine/ingestion_cli.py`
- Modify: `tests/test_ingestion_load_cli.py`

- [ ] **Step 1: Add failing load account tests**

Update every successful `load` invocation in `tests/test_ingestion_load_cli.py` to include:

```python
"--account-external-id",
"U100",
```

Update `test_load_mixed_file_starts_one_run_and_bulk_loads_both_types` to assert:

```python
        self.assertEqual(database.started[0].account_external_id, "U100")
        self.assertIn("Target account: U100", output)
```

Add:

```python
    def test_load_requires_account_external_id(self) -> None:
        stderr = io.StringIO()

        exit_code = run(
            ["load", "Flex.xml", "--brokerage-code", "IBKR"],
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error:", stderr.getvalue())
        self.assertIn("account-external-id", stderr.getvalue())
```

Add mixed-account skip test:

```python
    def test_load_filters_to_target_account_and_reports_other_account_skips(self) -> None:
        xml = """<FlexQueryResponse>
  <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="1000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" />
  <CashTransaction accountId="U200" reportDate="20250102" dateTime="20250102;091501" currency="USD" amount="2000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF2" />
  <EquitySummaryByReportDateInBase accountId="U100" reportDate="20250102" currency="USD" total="10000.00" />
  <EquitySummaryByReportDateInBase accountId="U200" reportDate="20250102" currency="USD" total="20000.00" />
</FlexQueryResponse>"""
        database = FakeDatabase()
        connector = Connector(database)
        directory, path = self.write_xml(xml)
        self.addCleanup(directory.cleanup)
        stdout = io.StringIO()

        exit_code = run(
            ["load", str(path), "--brokerage-code", "IBKR", "--account-external-id", "U100"],
            stdout=stdout,
            stderr=io.StringIO(),
            database_connector=connector,
        )

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(database.cash_records[0]), 1)
        self.assertEqual(database.cash_records[0][0]["account_external_id"], "U100")
        self.assertEqual(len(database.nav_records[0]), 1)
        self.assertEqual(database.nav_records[0][0]["account_external_id"], "U100")
        self.assertEqual(database.completed, [("run-123", "succeeded", None)])
        self.assertIn("Cash-flow records skipped for other accounts: 1", output)
        self.assertIn("Daily NAV snapshots skipped for other accounts: 1", output)
        self.assertNotIn("2000.00", output)
        self.assertNotIn("20000.00", output)
```

- [ ] **Step 2: Run load tests to verify failure**

Run:

```bash
python -m unittest tests.test_ingestion_load_cli -v
```

Expected: FAIL because `load` does not require `--account-external-id`, `IngestionRunStart` calls do not include it, and load does not filter records.

- [ ] **Step 3: Implement load account scope**

In `portfolio_engine/ingestion_cli.py`, add to the load parser:

```python
    load.add_argument("--account-external-id", required=True, help="Brokerage account external ID to load.")
```

In `_load_flex_file(...)`, after `analysis = analyze_flex_xml_file_for_ingestion(...)`, add:

```python
    scoped = analysis.for_account(args.account_external_id)
```

Pass `scoped` records to bulk calls:

```python
            if scoped.cash_flow_records:
                cash_summary = database.bulk_ingest_cash_flows(
                    ingestion_run_id,
                    list(scoped.cash_flow_records),
                )
            if scoped.daily_nav_records:
                nav_summary = database.bulk_ingest_daily_nav_snapshots(
                    ingestion_run_id,
                    list(scoped.daily_nav_records),
                )
```

Add `account_external_id` to `IngestionRunStart`:

```python
                    account_external_id=args.account_external_id,
```

Pass `scoped` to `_print_load_summary(...)` instead of `analysis`.

Update `_print_load_summary(...)` type from `FlexAnalysisResult` to `AccountScopedFlexAnalysisResult` and print:

```python
    stdout.write(f"Target account: {analysis.account_external_id}\n")
```

Add skipped count lines:

```python
    stdout.write(
        f"Cash-flow records skipped for other accounts: {analysis.skipped_other_account_cash_flow_count}\n"
    )
    stdout.write(
        f"Daily NAV snapshots skipped for other accounts: {analysis.skipped_other_account_daily_nav_count}\n"
    )
```

Remove any `Accounts seen:` output from load mode because the target account line replaces it.

- [ ] **Step 4: Run load and adapter tests**

Run:

```bash
python -m unittest tests.test_ingestion_load_cli tests.test_database_adapter -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

Run:

```bash
git add portfolio_engine/ingestion_cli.py tests/test_ingestion_load_cli.py
git commit -m "feat: require account-scoped Flex load" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 5: Update docs and run final verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README commands**

In `README.md`, update the dry-run command example to include:

```bash
python scripts/ingest_flex_file.py dry-run scratch/Flex.xml \
  --account-external-id U17072019 \
  --start-date 2025-01-01 \
  --end-date 2025-04-30
```

Update the load command example to include:

```bash
python scripts/ingest_flex_file.py load scratch/Flex.xml \
  --brokerage-code IBKR \
  --account-external-id U17072019 \
  --start-date 2025-01-01 \
  --end-date 2025-04-30
```

Add this explanatory paragraph to the load section:

```markdown
Both dry-run and load are account-scoped. The command only maps supported records whose Flex `accountId` matches `--account-external-id`; supported records for other accounts are counted as skipped warnings and are not written. Load mode also records the selected account on the ingestion run for auditability.
```

- [ ] **Step 2: Run full tests**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 3: Run compile and diff checks**

Run:

```bash
python -m compileall portfolio_engine scripts tests
git diff --check
```

Expected: compile succeeds and diff check is clean.

- [ ] **Step 4: Commit Task 5**

Run:

```bash
git add README.md
git commit -m "docs: document account-scoped Flex imports" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Self-review notes

- Spec coverage: This plan covers required `--account-external-id` on both commands, no-DB dry-run filtering, DB-audited load account scoping, non-target skip counts, final status behavior, migration deploy/revert/verify coverage, adapter changes, privacy-safe output, and README updates.
- Placeholder scan: The plan contains no placeholders or deferred requirements.
- Type consistency: The plan consistently uses `account_external_id`, `AccountScopedFlexAnalysisResult`, `skipped_other_account_cash_flow_count`, and `skipped_other_account_daily_nav_count`.
- Scope check: The work is focused on account-scoped manual Flex imports and does not add auto-registration, JSON output, new transaction types, real DB integration tests, or TWR calculation.
