# Manual Flex File Load CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a privacy-safe `load` subcommand that writes supported Flex XML records into PostgreSQL through the existing database adapter.

**Architecture:** Refactor the existing dry-run analyzer so one XML pass produces full load-ready records for internal database use plus safe summaries for CLI output. Extend `portfolio_engine.ingestion_cli` with a `load` subcommand that starts one ingestion run for the input file, conditionally calls cash-flow and daily-NAV bulk functions, derives a final run status, completes the run, and prints only privacy-safe counts and identifiers.

**Tech Stack:** Python 3.12 standard library (`argparse`, `dataclasses`, `datetime`, `pathlib`, `typing`, `unittest`, `tempfile`) plus existing `portfolio_engine.ingestion.flex_mappers` and `portfolio_engine.database`.

---

## File structure

- Modify: `portfolio_engine/ingestion/dry_run.py`  
  Add a full internal analysis result for load mode while preserving `FlexDryRunSummary`, `analyze_flex_xml_file`, and `analyze_flex_xml_text` for existing dry-run callers.
- Modify: `portfolio_engine/ingestion_cli.py`  
  Add `load` argument parsing, dependency injection for database connector tests, load orchestration, status derivation, failure finalization, and privacy-safe output formatting.
- Create: `tests/test_ingestion_load_cli.py`  
  Isolate load-mode CLI tests and fake database adapter behavior from the existing dry-run tests.
- Modify: `tests/test_flex_dry_run.py`  
  Add analyzer tests proving full records remain available for load while dry-run summaries stay sanitized.
- Modify: `tests/test_ingestion_cli.py`  
  Keep dry-run tests passing; only update imports or expectations if the analyzer refactor changes internal names.
- Modify: `README.md`  
  Document the load command after the dry-run section.

## Locked decisions

- `load` requires `--brokerage-code`; no default brokerage is assumed.
- `--database-url` is optional and overrides `DATABASE_URL` for one run.
- One invocation creates exactly one ingestion run for the whole file.
- `source_type` is the lowercase string `manual_file`.
- `source_filename` is `Path(file).name`, not the full local path.
- Date filters remain ISO strings for mapper filtering, but `IngestionRunStart` receives `datetime.date` values.
- Empty record categories do not call the corresponding bulk function.
- Duplicate-only bulk results complete the run as `succeeded`.
- Unknown accounts, inactive accounts, or conflicts complete the run as `partially_succeeded`.
- Parser, mapper, connection, or database exceptions after run start should attempt `complete_ingestion_run(..., status="failed", error_message=<original error>)`.
- CLI output remains privacy-safe: no amounts, NAV values, raw payloads, full dictionaries, or dedupe key values.

### Task 1: Refactor analyzer to expose full load records safely

**Files:**
- Modify: `portfolio_engine/ingestion/dry_run.py`
- Modify: `tests/test_flex_dry_run.py`

- [ ] **Step 1: Add failing analyzer tests for load-ready records and dry-run sanitization**

Append these tests inside `FlexDryRunTests` in `tests/test_flex_dry_run.py`:

```python
    def test_ingestion_analysis_keeps_full_records_for_load(self) -> None:
        from portfolio_engine.ingestion.dry_run import analyze_flex_xml_text_for_ingestion

        analysis = analyze_flex_xml_text_for_ingestion(MIXED_XML)

        self.assertEqual(analysis.cash_flow_count, 1)
        self.assertEqual(analysis.daily_nav_count, 2)
        self.assertEqual(analysis.cash_flow_records[0]["amount"], "1000.00")
        self.assertEqual(analysis.cash_flow_records[0]["raw_payload"]["amount"], "1000.00")
        self.assertEqual(analysis.daily_nav_records[0]["nav_base"], "10000.00")
        self.assertEqual(analysis.daily_nav_records[0]["raw_payload"]["total"], "10000.00")

    def test_dry_run_summary_stays_sanitized_after_full_analysis_refactor(self) -> None:
        summary = analyze_flex_xml_text(MIXED_XML)

        self.assertNotIn("amount", summary.cash_flow_records[0])
        self.assertNotIn("amount_base", summary.cash_flow_records[0])
        self.assertNotIn("raw_payload", summary.cash_flow_records[0])
        self.assertNotIn("nav_base", summary.daily_nav_records[0])
        self.assertNotIn("raw_payload", summary.daily_nav_records[0])
```

- [ ] **Step 2: Run analyzer tests to verify they fail**

Run:

```bash
python -m unittest tests.test_flex_dry_run -v
```

Expected: FAIL with `ImportError` or `AttributeError` because `analyze_flex_xml_text_for_ingestion` does not exist yet.

- [ ] **Step 3: Implement the full analysis result while preserving dry-run APIs**

Update `portfolio_engine/ingestion/dry_run.py` with these concrete changes:

1. Add `FlexAnalysisResult` after `FlexDryRunSummary`:

```python
@dataclass(frozen=True)
class FlexAnalysisResult:
    cash_flow_records: tuple[dict[str, Any], ...]
    daily_nav_records: tuple[dict[str, Any], ...]
    unsupported_cash_transaction_count: int
    accounts_seen: tuple[str, ...]
    currencies_seen: tuple[str, ...]
    cash_flow_date_range: DateRange | None
    daily_nav_date_range: DateRange | None
    duplicate_dedupe_keys: tuple[str, ...]

    @property
    def cash_flow_count(self) -> int:
        return len(self.cash_flow_records)

    @property
    def daily_nav_count(self) -> int:
        return len(self.daily_nav_records)

    def to_dry_run_summary(self) -> FlexDryRunSummary:
        safe_cash_records = tuple(
            _safe_cash_flow_record(record) for record in self.cash_flow_records
        )
        safe_nav_records = tuple(
            _safe_daily_nav_record(record) for record in self.daily_nav_records
        )
        return FlexDryRunSummary(
            cash_flow_records=safe_cash_records,
            daily_nav_records=safe_nav_records,
            unsupported_cash_transaction_count=self.unsupported_cash_transaction_count,
            accounts_seen=self.accounts_seen,
            currencies_seen=self.currencies_seen,
            cash_flow_date_range=self.cash_flow_date_range,
            daily_nav_date_range=self.daily_nav_date_range,
            duplicate_dedupe_keys=self.duplicate_dedupe_keys,
        )
```

2. Change existing public dry-run functions to delegate through the new full analysis functions:

```python
def analyze_flex_xml_file(
    path: Path,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> FlexDryRunSummary:
    return analyze_flex_xml_file_for_ingestion(
        path,
        start_date=start_date,
        end_date=end_date,
    ).to_dry_run_summary()


def analyze_flex_xml_file_for_ingestion(
    path: Path,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> FlexAnalysisResult:
    return analyze_flex_xml_text_for_ingestion(
        path.read_text(encoding="utf-8"),
        start_date=start_date,
        end_date=end_date,
    )


def analyze_flex_xml_text(
    xml_text: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> FlexDryRunSummary:
    return analyze_flex_xml_text_for_ingestion(
        xml_text,
        start_date=start_date,
        end_date=end_date,
    ).to_dry_run_summary()
```

3. Rename the existing XML traversal implementation to `analyze_flex_xml_text_for_ingestion(...) -> FlexAnalysisResult`, and make it append full bulk records, not safe projections:

```python
def analyze_flex_xml_text_for_ingestion(
    xml_text: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> FlexAnalysisResult:
    root = ElementTree.fromstring(xml_text)
    cash_flow_records: list[dict[str, Any]] = []
    daily_nav_records: list[dict[str, Any]] = []
    unsupported_cash_transaction_count = 0

    for element in root.iter():
        if element.tag == "CashTransaction":
            raw = dict(element.attrib)
            if raw.get("type") != DEFAULT_CASH_FLOW_TYPE:
                unsupported_cash_transaction_count += 1
                continue

            source_report_date = flex_date_to_payload(
                require_attribute(raw, "reportDate")
            )
            if not in_date_range(source_report_date, start_date, end_date):
                continue

            cash_flow_records.append(map_cash_transaction_attributes(raw).to_bulk_record())

        elif element.tag == "EquitySummaryByReportDateInBase":
            raw = dict(element.attrib)
            source_report_date = flex_date_to_payload(
                require_attribute(raw, "reportDate")
            )
            if not in_date_range(source_report_date, start_date, end_date):
                continue

            daily_nav_records.append(map_daily_nav_attributes(raw).to_bulk_record())

    all_records = cash_flow_records + daily_nav_records
    return FlexAnalysisResult(
        cash_flow_records=tuple(cash_flow_records),
        daily_nav_records=tuple(daily_nav_records),
        unsupported_cash_transaction_count=unsupported_cash_transaction_count,
        accounts_seen=_sorted_unique(record["account_external_id"] for record in all_records),
        currencies_seen=_sorted_unique(record["source_currency"] for record in all_records),
        cash_flow_date_range=_record_date_range(cash_flow_records, "flow_date"),
        daily_nav_date_range=_record_date_range(daily_nav_records, "snapshot_date"),
        duplicate_dedupe_keys=_duplicate_dedupe_keys(all_records),
    )
```

- [ ] **Step 4: Run analyzer and dry-run CLI tests**

Run:

```bash
python -m unittest tests.test_flex_dry_run tests.test_ingestion_cli -v
```

Expected: PASS. Existing dry-run output remains privacy-safe.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add portfolio_engine/ingestion/dry_run.py tests/test_flex_dry_run.py
git commit -m "feat: expose load-ready Flex analysis records" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Add load command parsing and successful load path

**Files:**
- Modify: `portfolio_engine/ingestion_cli.py`
- Create: `tests/test_ingestion_load_cli.py`

- [ ] **Step 1: Write failing load CLI tests for required brokerage, connector override, and mixed-file success**

Create `tests/test_ingestion_load_cli.py`:

```python
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from typing import Any

from portfolio_engine.database import BulkIngestionSummary, IngestionRunStart
from portfolio_engine.ingestion_cli import run


MIXED_XML = """<FlexQueryResponse>
  <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="1000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" />
  <CashTransaction accountId="U100" reportDate="20250103" dateTime="20250103;101500" currency="USD" amount="5.00" fxRateToBase="1" type="Dividend" transactionID="DIV1" />
  <EquitySummaryByReportDateInBase accountId="U100" reportDate="20250102" currency="USD" total="10000.00" />
</FlexQueryResponse>"""


def summary(
    *,
    inserted: int = 0,
    duplicate: int = 0,
    unknown: int = 0,
    inactive: int = 0,
    conflicts: int = 0,
    skipped_accounts: list[str] | None = None,
) -> BulkIngestionSummary:
    return BulkIngestionSummary(
        inserted_count=inserted,
        duplicate_count=duplicate,
        skipped_unknown_account_count=unknown,
        skipped_inactive_account_count=inactive,
        conflict_count=conflicts,
        skipped_accounts=skipped_accounts or [],
        record_results=[],
    )


class FakeDatabase:
    def __init__(self) -> None:
        self.started: list[IngestionRunStart] = []
        self.completed: list[tuple[str, str, str | None]] = []
        self.cash_records: list[list[dict[str, Any]]] = []
        self.nav_records: list[list[dict[str, Any]]] = []
        self.cash_summary = summary(inserted=1)
        self.nav_summary = summary(inserted=1)
        self.closed = False

    def __enter__(self) -> "FakeDatabase":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.closed = True

    def start_ingestion_run(self, request: IngestionRunStart) -> str:
        self.started.append(request)
        return "run-123"

    def bulk_ingest_cash_flows(
        self, ingestion_run_id: str, records: list[dict[str, Any]]
    ) -> BulkIngestionSummary:
        self.cash_records.append(records)
        return self.cash_summary

    def bulk_ingest_daily_nav_snapshots(
        self, ingestion_run_id: str, records: list[dict[str, Any]]
    ) -> BulkIngestionSummary:
        self.nav_records.append(records)
        return self.nav_summary

    def complete_ingestion_run(
        self, *, ingestion_run_id: str, status: str, error_message: str | None = None
    ) -> str:
        self.completed.append((ingestion_run_id, status, error_message))
        return ingestion_run_id


class Connector:
    def __init__(self, database: FakeDatabase | None = None) -> None:
        self.database = database or FakeDatabase()
        self.urls: list[str | None] = []

    def __call__(self, database_url: str | None = None) -> FakeDatabase:
        self.urls.append(database_url)
        return self.database


class IngestionLoadCliTests(unittest.TestCase):
    def write_xml(self, xml_text: str = MIXED_XML) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "Flex.xml"
        path.write_text(xml_text, encoding="utf-8")
        return directory, path

    def test_load_requires_brokerage_code(self) -> None:
        stderr = io.StringIO()

        exit_code = run(["load", "Flex.xml"], stdout=io.StringIO(), stderr=stderr)

        self.assertEqual(exit_code, 1)
        self.assertIn("Error:", stderr.getvalue())
        self.assertIn("brokerage-code", stderr.getvalue())

    def test_load_passes_database_url_override_to_connector(self) -> None:
        connector = Connector()
        directory, path = self.write_xml()
        self.addCleanup(directory.cleanup)

        exit_code = run(
            [
                "load",
                str(path),
                "--brokerage-code",
                "IBKR",
                "--database-url",
                "postgresql://example",
            ],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            database_connector=connector,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(connector.urls, ["postgresql://example"])

    def test_load_mixed_file_starts_one_run_and_bulk_loads_both_types(self) -> None:
        database = FakeDatabase()
        connector = Connector(database)
        directory, path = self.write_xml()
        self.addCleanup(directory.cleanup)
        stdout = io.StringIO()

        exit_code = run(
            [
                "load",
                str(path),
                "--brokerage-code",
                "IBKR",
                "--start-date",
                "2025-01-01",
                "--end-date",
                "2025-01-31",
            ],
            stdout=stdout,
            stderr=io.StringIO(),
            database_connector=connector,
        )

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(database.started), 1)
        self.assertEqual(database.started[0].brokerage_code, "IBKR")
        self.assertEqual(database.started[0].source_type, "manual_file")
        self.assertEqual(database.started[0].source_filename, "Flex.xml")
        self.assertEqual(database.started[0].requested_start_date.isoformat(), "2025-01-01")
        self.assertEqual(database.started[0].requested_end_date.isoformat(), "2025-01-31")
        self.assertEqual(len(database.cash_records), 1)
        self.assertEqual(len(database.nav_records), 1)
        self.assertEqual(database.cash_records[0][0]["amount"], "1000.00")
        self.assertEqual(database.nav_records[0][0]["nav_base"], "10000.00")
        self.assertEqual(database.completed, [("run-123", "succeeded", None)])
        self.assertIn("Load:", output)
        self.assertIn("Ingestion run: run-123", output)
        self.assertIn("Cash-flow results: inserted=1 duplicate=0 skipped_unknown=0 skipped_inactive=0 conflicts=0", output)
        self.assertIn("Daily NAV results: inserted=1 duplicate=0 skipped_unknown=0 skipped_inactive=0 conflicts=0", output)
        self.assertIn("Final status: succeeded", output)
        self.assertNotIn("1000.00", output)
        self.assertNotIn("10000.00", output)
```

- [ ] **Step 2: Run load CLI tests to verify they fail**

Run:

```bash
python -m unittest tests.test_ingestion_load_cli -v
```

Expected: FAIL because `load` is not registered and `run()` does not accept `database_connector`.

- [ ] **Step 3: Implement load parser, dependency injection, and success path**

Modify imports in `portfolio_engine/ingestion_cli.py`:

```python
from collections.abc import Callable
from datetime import date, datetime
from typing import Protocol

from portfolio_engine.database import (
    BulkIngestionSummary,
    IngestionRunStart,
    SuperFolioDatabase,
    connect_database,
)
from portfolio_engine.ingestion.dry_run import (
    FlexAnalysisResult,
    FlexDryRunSummary,
    analyze_flex_xml_file,
    analyze_flex_xml_file_for_ingestion,
)
```

Add constants and connector type after `IngestionCliError`:

```python
SOURCE_TYPE_MANUAL_FILE = "manual_file"


DatabaseConnector = Callable[[str | None], SuperFolioDatabase]
```

Extend `build_parser()` after the dry-run parser:

```python
    load = subparsers.add_parser("load", help="Load supported Flex records into the database.")
    load.add_argument("file", type=Path, help="Flex XML file to load.")
    load.add_argument("--brokerage-code", required=True, help="Brokerage code for this file, e.g. IBKR.")
    load.add_argument("--database-url", help="Database URL override for this run.")
    load.add_argument("--start-date", type=_parse_iso_date, help="Inclusive reportDate filter start.")
    load.add_argument("--end-date", type=_parse_iso_date, help="Inclusive reportDate filter end.")
```

Change `run()` signature and dispatch:

```python
def run(
    argv: list[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    database_connector: DatabaseConnector = connect_database,
) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "dry-run":
            _validate_date_range(args.start_date, args.end_date)
            summary = analyze_flex_xml_file(
                args.file,
                start_date=args.start_date,
                end_date=args.end_date,
            )
            _print_dry_run_summary(args.file, summary, stdout)
            return 0
        if args.command == "load":
            _validate_date_range(args.start_date, args.end_date)
            _load_flex_file(args, stdout, database_connector)
            return 0
    except Exception as error:
        stderr.write(f"Error: {error}\n")
        return 1
    raise AssertionError(f"unhandled command: {args.command!r}")
```

Add load helpers:

```python
def _load_flex_file(
    args: argparse.Namespace,
    stdout: TextIO,
    database_connector: DatabaseConnector,
) -> None:
    analysis = analyze_flex_xml_file_for_ingestion(
        args.file,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    with database_connector(args.database_url) as database:
        ingestion_run_id = database.start_ingestion_run(
            IngestionRunStart(
                brokerage_code=args.brokerage_code,
                source_type=SOURCE_TYPE_MANUAL_FILE,
                requested_start_date=_date_or_none(args.start_date),
                requested_end_date=_date_or_none(args.end_date),
                source_filename=args.file.name,
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
        final_status, message = _derive_final_status(cash_summary, nav_summary)
        database.complete_ingestion_run(
            ingestion_run_id=ingestion_run_id,
            status=final_status,
            error_message=message,
        )
        _print_load_summary(
            args.file,
            ingestion_run_id,
            analysis,
            cash_summary,
            nav_summary,
            final_status,
            message,
            stdout,
        )


def _date_or_none(value: str | None) -> date | None:
    return date.fromisoformat(value) if value is not None else None


def _empty_bulk_summary() -> BulkIngestionSummary:
    return BulkIngestionSummary(
        inserted_count=0,
        duplicate_count=0,
        skipped_unknown_account_count=0,
        skipped_inactive_account_count=0,
        conflict_count=0,
        skipped_accounts=[],
        record_results=[],
    )
```

Add initial status and output helpers:

```python
def _derive_final_status(
    cash_summary: BulkIngestionSummary,
    nav_summary: BulkIngestionSummary,
) -> tuple[str, str | None]:
    if _has_partial_conditions(cash_summary) or _has_partial_conditions(nav_summary):
        return "partially_succeeded", "skipped accounts or conflicts require review"
    return "succeeded", None


def _has_partial_conditions(summary: BulkIngestionSummary) -> bool:
    return (
        summary.skipped_unknown_account_count > 0
        or summary.skipped_inactive_account_count > 0
        or summary.conflict_count > 0
    )


def _print_load_summary(
    path: Path,
    ingestion_run_id: str,
    analysis: FlexAnalysisResult,
    cash_summary: BulkIngestionSummary,
    nav_summary: BulkIngestionSummary,
    final_status: str,
    message: str | None,
    stdout: TextIO,
) -> None:
    stdout.write(f"Load: {path}\n")
    stdout.write(f"Ingestion run: {ingestion_run_id}\n")
    stdout.write(f"Cash-flow records mapped: {analysis.cash_flow_count}\n")
    stdout.write(f"Daily NAV snapshots mapped: {analysis.daily_nav_count}\n")
    stdout.write(
        f"Unsupported CashTransaction records skipped: {analysis.unsupported_cash_transaction_count}\n"
    )
    stdout.write(f"Cash-flow results: {_format_bulk_summary(cash_summary)}\n")
    stdout.write(f"Daily NAV results: {_format_bulk_summary(nav_summary)}\n")
    stdout.write(f"Accounts seen: {_format_tuple(analysis.accounts_seen)}\n")
    stdout.write(f"Currencies seen: {_format_tuple(analysis.currencies_seen)}\n")
    skipped_accounts = _combined_skipped_accounts(cash_summary, nav_summary)
    if skipped_accounts:
        stdout.write(f"Skipped accounts: {_format_tuple(skipped_accounts)}\n")
    stdout.write(f"Final status: {final_status}\n")
    if message is not None:
        stdout.write(f"Message: {message}\n")


def _format_bulk_summary(summary: BulkIngestionSummary) -> str:
    return (
        f"inserted={summary.inserted_count} "
        f"duplicate={summary.duplicate_count} "
        f"skipped_unknown={summary.skipped_unknown_account_count} "
        f"skipped_inactive={summary.skipped_inactive_account_count} "
        f"conflicts={summary.conflict_count}"
    )


def _combined_skipped_accounts(
    cash_summary: BulkIngestionSummary,
    nav_summary: BulkIngestionSummary,
) -> tuple[str, ...]:
    return tuple(sorted(set(cash_summary.skipped_accounts + nav_summary.skipped_accounts)))
```

- [ ] **Step 4: Run successful load tests**

Run:

```bash
python -m unittest tests.test_ingestion_load_cli -v
```

Expected: PASS for the new Task 2 tests.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add portfolio_engine/ingestion_cli.py tests/test_ingestion_load_cli.py
git commit -m "feat: add Flex load CLI success path" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Add partial-status, failure-finalization, empty-category, and privacy coverage

**Files:**
- Modify: `portfolio_engine/ingestion_cli.py`
- Modify: `tests/test_ingestion_load_cli.py`

- [ ] **Step 1: Add failing tests for partial status, empty categories, failures, and fallback dedupe privacy**

Append these tests inside `IngestionLoadCliTests` in `tests/test_ingestion_load_cli.py`:

```python
    def test_load_skips_empty_categories_without_bulk_calls(self) -> None:
        nav_only_xml = """<FlexQueryResponse>
  <EquitySummaryByReportDateInBase accountId="U100" reportDate="20250102" currency="USD" total="10000.00" />
</FlexQueryResponse>"""
        database = FakeDatabase()
        connector = Connector(database)
        directory, path = self.write_xml(nav_only_xml)
        self.addCleanup(directory.cleanup)

        exit_code = run(
            ["load", str(path), "--brokerage-code", "IBKR"],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            database_connector=connector,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(database.cash_records, [])
        self.assertEqual(len(database.nav_records), 1)

    def test_load_marks_unknown_inactive_or_conflict_results_partially_succeeded(self) -> None:
        database = FakeDatabase()
        database.cash_summary = summary(unknown=1, skipped_accounts=["U404"])
        database.nav_summary = summary(conflicts=1)
        connector = Connector(database)
        directory, path = self.write_xml()
        self.addCleanup(directory.cleanup)
        stdout = io.StringIO()

        exit_code = run(
            ["load", str(path), "--brokerage-code", "IBKR"],
            stdout=stdout,
            stderr=io.StringIO(),
            database_connector=connector,
        )

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            database.completed,
            [("run-123", "partially_succeeded", "skipped accounts or conflicts require review")],
        )
        self.assertIn("Skipped accounts: U404", output)
        self.assertIn("Final status: partially_succeeded", output)
        self.assertIn("Message: skipped accounts or conflicts require review", output)

    def test_load_duplicate_only_results_are_succeeded(self) -> None:
        database = FakeDatabase()
        database.cash_summary = summary(duplicate=1)
        database.nav_summary = summary(duplicate=1)
        connector = Connector(database)
        directory, path = self.write_xml()
        self.addCleanup(directory.cleanup)

        exit_code = run(
            ["load", str(path), "--brokerage-code", "IBKR"],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            database_connector=connector,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(database.completed, [("run-123", "succeeded", None)])

    def test_load_failure_after_run_start_marks_run_failed(self) -> None:
        class FailingBulkDatabase(FakeDatabase):
            def bulk_ingest_cash_flows(
                self, ingestion_run_id: str, records: list[dict[str, Any]]
            ) -> BulkIngestionSummary:
                raise RuntimeError("bulk cash failed")

        database = FailingBulkDatabase()
        connector = Connector(database)
        directory, path = self.write_xml()
        self.addCleanup(directory.cleanup)
        stderr = io.StringIO()

        exit_code = run(
            ["load", str(path), "--brokerage-code", "IBKR"],
            stdout=io.StringIO(),
            stderr=stderr,
            database_connector=connector,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: bulk cash failed", stderr.getvalue())
        self.assertEqual(database.completed, [("run-123", "failed", "bulk cash failed")])

    def test_load_reports_failed_finalization_error_too(self) -> None:
        class FailingFinalizeDatabase(FakeDatabase):
            def bulk_ingest_cash_flows(
                self, ingestion_run_id: str, records: list[dict[str, Any]]
            ) -> BulkIngestionSummary:
                raise RuntimeError("bulk cash failed")

            def complete_ingestion_run(
                self,
                *,
                ingestion_run_id: str,
                status: str,
                error_message: str | None = None,
            ) -> str:
                raise RuntimeError("completion failed")

        database = FailingFinalizeDatabase()
        connector = Connector(database)
        directory, path = self.write_xml()
        self.addCleanup(directory.cleanup)
        stderr = io.StringIO()

        exit_code = run(
            ["load", str(path), "--brokerage-code", "IBKR"],
            stdout=io.StringIO(),
            stderr=stderr,
            database_connector=connector,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("bulk cash failed", stderr.getvalue())
        self.assertIn("failed to mark ingestion run failed: completion failed", stderr.getvalue())

    def test_load_output_never_prints_fallback_dedupe_key_amount_or_raw_payload(self) -> None:
        xml = """<FlexQueryResponse>
  <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="99999.99" fxRateToBase="1" type="Deposits/Withdrawals" />
  <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="99999.99" fxRateToBase="1" type="Deposits/Withdrawals" />
  <EquitySummaryByReportDateInBase accountId="U100" reportDate="20250102" currency="USD" total="88888.88" />
</FlexQueryResponse>"""
        database = FakeDatabase()
        connector = Connector(database)
        directory, path = self.write_xml(xml)
        self.addCleanup(directory.cleanup)
        stdout = io.StringIO()

        exit_code = run(
            ["load", str(path), "--brokerage-code", "IBKR"],
            stdout=stdout,
            stderr=io.StringIO(),
            database_connector=connector,
        )

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertNotIn("99999.99", output)
        self.assertNotIn("88888.88", output)
        self.assertNotIn("raw_payload", output)
        self.assertNotIn("dedupe_key", output)
```

- [ ] **Step 2: Run the new tests to verify failures**

Run:

```bash
python -m unittest tests.test_ingestion_load_cli -v
```

Expected: at least the failure-finalization tests fail because `_load_flex_file` does not yet catch post-start failures.

- [ ] **Step 3: Implement failure finalization and verify privacy-safe output**

Replace `_load_flex_file(...)` in `portfolio_engine/ingestion_cli.py` with this version:

```python
def _load_flex_file(
    args: argparse.Namespace,
    stdout: TextIO,
    database_connector: DatabaseConnector,
) -> None:
    analysis = analyze_flex_xml_file_for_ingestion(
        args.file,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    with database_connector(args.database_url) as database:
        ingestion_run_id: str | None = None
        try:
            ingestion_run_id = database.start_ingestion_run(
                IngestionRunStart(
                    brokerage_code=args.brokerage_code,
                    source_type=SOURCE_TYPE_MANUAL_FILE,
                    requested_start_date=_date_or_none(args.start_date),
                    requested_end_date=_date_or_none(args.end_date),
                    source_filename=args.file.name,
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
            final_status, message = _derive_final_status(cash_summary, nav_summary)
            database.complete_ingestion_run(
                ingestion_run_id=ingestion_run_id,
                status=final_status,
                error_message=message,
            )
        except Exception as error:
            if ingestion_run_id is not None:
                _mark_run_failed(database, ingestion_run_id, error)
            raise

        _print_load_summary(
            args.file,
            ingestion_run_id,
            analysis,
            cash_summary,
            nav_summary,
            final_status,
            message,
            stdout,
        )
```

Add `_mark_run_failed(...)`:

```python
def _mark_run_failed(
    database: SuperFolioDatabase,
    ingestion_run_id: str,
    error: Exception,
) -> None:
    try:
        database.complete_ingestion_run(
            ingestion_run_id=ingestion_run_id,
            status="failed",
            error_message=str(error),
        )
    except Exception as finalization_error:
        raise IngestionCliError(
            f"{error}; additionally failed to mark ingestion run failed: {finalization_error}"
        ) from finalization_error
```

Do not add any output lines that include raw records, raw payloads, dedupe keys, amounts, or NAV values.

- [ ] **Step 4: Run load CLI tests**

Run:

```bash
python -m unittest tests.test_ingestion_load_cli -v
```

Expected: PASS.

- [ ] **Step 5: Run dry-run regression tests**

Run:

```bash
python -m unittest tests.test_ingestion_cli tests.test_flex_dry_run -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add portfolio_engine/ingestion_cli.py tests/test_ingestion_load_cli.py
git commit -m "feat: finalize Flex load runs with safe status reporting" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Document load mode and run final verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add README documentation**

Add this section after the existing `### Dry-running a Flex XML file` section in `README.md`:

```markdown
### Loading a Flex XML file

After reviewing a dry run and registering the accounts found in the file, load supported records into PostgreSQL:

```bash
python scripts/ingest_flex_file.py load scratch/Flex.xml \
  --brokerage-code IBKR \
  --start-date 2025-01-01 \
  --end-date 2025-04-30
```

The load command uses `DATABASE_URL` by default. Pass `--database-url` to override it for one run. One load command creates one ingestion run for the whole file, bulk-loads supported cash-flow and daily NAV records, and prints privacy-safe inserted/duplicate/skipped/conflict counts. Duplicate records are treated as idempotent re-ingestion; unknown accounts, inactive accounts, and conflicts mark the ingestion run `partially_succeeded`.
```

- [ ] **Step 2: Run the full test suite**

Run:

```bash
python -m unittest tests.test_ingestion_load_cli tests.test_ingestion_cli tests.test_flex_dry_run tests.test_flex_ingestion_mappers tests.test_account_cli tests.test_database_adapter -v
```

Expected: all tests pass.

- [ ] **Step 3: Run compile and whitespace checks**

Run:

```bash
python -m compileall portfolio_engine scripts tests
git diff --check
```

Expected: `compileall` succeeds and `git diff --check` is clean.

- [ ] **Step 4: Commit Task 4**

Run:

```bash
git add README.md
git commit -m "docs: document Flex load CLI" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Self-review notes

- Spec coverage: This plan covers the approved `load` subcommand, required brokerage code, optional database URL override, one ingestion run per file, database adapter reuse, cash/NAV bulk loading, final status rules, failure finalization, privacy-safe output, and synthetic fake-database tests.
- Out-of-scope check: The plan does not add account readiness preflight, automatic account registration, new cash transaction types, JSON output, direct SQL, real DB integration tests, or TWR calculation.
- Placeholder scan: The plan contains concrete file paths, commands, expected outcomes, and code snippets for each implementation step.
- Type consistency: The plan consistently uses `FlexAnalysisResult`, `FlexDryRunSummary`, `analyze_flex_xml_file_for_ingestion`, `analyze_flex_xml_text_for_ingestion`, `BulkIngestionSummary`, `IngestionRunStart`, `SOURCE_TYPE_MANUAL_FILE`, and `DatabaseConnector`.

