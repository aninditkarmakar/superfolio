# Manual Flex File Dry-Run CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a database-free dry-run CLI that accepts one Flex XML file, auto-detects supported record types, maps them to bulk-ready payloads, and prints a privacy-safe summary.

**Architecture:** Add a focused dry-run analyzer in `portfolio_engine.ingestion.dry_run` that scans XML once and reuses the existing Flex mapper functions. Add a separate CLI module in `portfolio_engine.ingestion_cli` for argument parsing, date validation, error formatting, and human-readable output. Keep `scripts/ingest_flex_file.py` as a thin executable wrapper so future load mode can reuse the same command surface.

**Tech Stack:** Python 3.12 standard library (`argparse`, `dataclasses`, `datetime`, `pathlib`, `sys`, `xml.etree.ElementTree`, `unittest`, `tempfile`) plus existing `portfolio_engine.ingestion.flex_mappers`.

---

## File structure

- Create: `portfolio_engine/ingestion/dry_run.py`  
  Owns dry-run analysis dataclasses and XML record scanning. It must not call the database.
- Create: `portfolio_engine/ingestion_cli.py`  
  Owns `ingest_flex_file.py` command parsing, `dry-run` subcommand execution, output formatting, and CLI return codes.
- Create: `scripts/ingest_flex_file.py`  
  Executable wrapper following the existing script pattern.
- Create: `tests/test_flex_dry_run.py`  
  Synthetic XML tests for mixed-file analysis, unsupported cash types, date filters, duplicate dedupe keys, malformed XML, and missing required supported attributes.
- Create: `tests/test_ingestion_cli.py`  
  CLI tests using temporary synthetic files and in-memory output streams.
- Modify: `README.md`  
  Document dry-run usage and note that only `Deposits/Withdrawals` cash transactions are supported for now.

## Assumptions locked by this plan

- The dry run processes exactly one XML file per invocation.
- The input file can contain `CashTransaction`, `EquitySummaryByReportDateInBase`, both, or neither.
- Supported cash transactions are limited to `type="Deposits/Withdrawals"`.
- Unsupported `CashTransaction` types are counted and skipped. They do not fail the command.
- Unsupported cash-transaction counting is independent of date filters because these records are intentionally not mapped in this block.
- Date filters apply to supported/mapped records using `reportDate`.
- Missing required attributes in supported records fail the dry run.
- Unsupported cash transactions with missing mapper-required attributes do not fail because they are not mapped.
- Output may include account identifiers, currencies, dates, counts, and dedupe keys. It must not print raw XML payloads, amounts, NAV values, or full `raw_payload` dictionaries.
- The dry run performs no database reads or writes.

### Task 1: Add the dry-run analyzer

**Files:**
- Create: `portfolio_engine/ingestion/dry_run.py`
- Create: `tests/test_flex_dry_run.py`

- [ ] **Step 1: Write failing dry-run analyzer tests**

Create `tests/test_flex_dry_run.py`:

```python
from __future__ import annotations

import unittest
from xml.etree import ElementTree

from portfolio_engine.ingestion.dry_run import analyze_flex_xml_text


MIXED_XML = """<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement>
      <CashTransactions>
        <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="1000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" description="Synthetic deposit" />
        <CashTransaction accountId="U100" reportDate="20250103" dateTime="20250103;101500" currency="USD" amount="5.00" fxRateToBase="1" type="Broker Interest Paid" transactionID="INT1" description="Unsupported interest" />
      </CashTransactions>
      <EquitySummaryInBase>
        <EquitySummaryByReportDateInBase accountId="U100" reportDate="20250102" currency="USD" total="10000.00" />
        <EquitySummaryByReportDateInBase accountId="U200" reportDate="20250103" currency="CAD" total="20000.00" />
      </EquitySummaryInBase>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""


class FlexDryRunTests(unittest.TestCase):
    def test_mixed_xml_maps_supported_cash_and_nav_records(self) -> None:
        summary = analyze_flex_xml_text(MIXED_XML)

        self.assertEqual(summary.cash_flow_count, 1)
        self.assertEqual(summary.daily_nav_count, 2)
        self.assertEqual(summary.unsupported_cash_transaction_count, 1)
        self.assertEqual(summary.accounts_seen, ("U100", "U200"))
        self.assertEqual(summary.currencies_seen, ("CAD", "USD"))
        self.assertEqual(summary.cash_flow_date_range, ("2025-01-02", "2025-01-02"))
        self.assertEqual(summary.daily_nav_date_range, ("2025-01-02", "2025-01-03"))
        self.assertEqual(summary.duplicate_dedupe_keys, ())

    def test_date_filter_applies_to_supported_record_types(self) -> None:
        summary = analyze_flex_xml_text(
            MIXED_XML,
            start_date="2025-01-03",
            end_date="2025-01-03",
        )

        self.assertEqual(summary.cash_flow_count, 0)
        self.assertEqual(summary.daily_nav_count, 1)
        self.assertEqual(summary.accounts_seen, ("U200",))
        self.assertIsNone(summary.cash_flow_date_range)
        self.assertEqual(summary.daily_nav_date_range, ("2025-01-03", "2025-01-03"))

    def test_duplicate_dedupe_keys_within_file_are_detected(self) -> None:
        xml = """<FlexQueryResponse>
          <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="1000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" />
          <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="1000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" />
        </FlexQueryResponse>"""

        summary = analyze_flex_xml_text(xml)

        self.assertEqual(summary.cash_flow_count, 2)
        self.assertEqual(
            summary.duplicate_dedupe_keys,
            ("IBKR:U100:CASH_TRANSACTION:CF1",),
        )

    def test_malformed_xml_raises_parse_error(self) -> None:
        with self.assertRaises(ElementTree.ParseError):
            analyze_flex_xml_text("<FlexQueryResponse>")

    def test_missing_required_attribute_in_supported_record_raises_value_error(self) -> None:
        xml = """<FlexQueryResponse>
          <CashTransaction accountId="U100" reportDate="20250102" currency="USD" amount="1000.00" type="Deposits/Withdrawals" />
        </FlexQueryResponse>"""

        with self.assertRaisesRegex(ValueError, "missing required Flex attribute: dateTime"):
            analyze_flex_xml_text(xml)

    def test_missing_attributes_in_unsupported_cash_transaction_do_not_fail(self) -> None:
        xml = """<FlexQueryResponse>
          <CashTransaction type="Dividend" />
        </FlexQueryResponse>"""

        summary = analyze_flex_xml_text(xml)

        self.assertEqual(summary.cash_flow_count, 0)
        self.assertEqual(summary.unsupported_cash_transaction_count, 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run analyzer tests to verify they fail**

Run:

```bash
python -m unittest tests.test_flex_dry_run -v
```

Expected: FAIL with `ModuleNotFoundError` or import errors because `portfolio_engine.ingestion.dry_run` does not exist.

- [ ] **Step 3: Implement the dry-run analyzer**

Create `portfolio_engine/ingestion/dry_run.py`:

```python
"""Dry-run analysis for manual Flex XML ingestion files."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable
from typing import Any
from xml.etree import ElementTree

from portfolio_engine.ingestion.flex_mappers import (
    DEFAULT_CASH_FLOW_TYPE,
    flex_date_to_payload,
    in_date_range,
    map_cash_transaction_attributes,
    map_daily_nav_attributes,
    require_attribute,
)


DateRange = tuple[str, str]


@dataclass(frozen=True)
class FlexDryRunSummary:
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


def analyze_flex_xml_file(
    path: Path,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> FlexDryRunSummary:
    return analyze_flex_xml_text(
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
    root = ElementTree.fromstring(xml_text)
    cash_flow_records: list[dict[str, Any]] = []
    daily_nav_records: list[dict[str, Any]] = []
    unsupported_cash_transaction_count = 0

    for element in root.iter("CashTransaction"):
        raw = dict(element.attrib)
        if raw.get("type") != DEFAULT_CASH_FLOW_TYPE:
            unsupported_cash_transaction_count += 1
            continue

        source_report_date = flex_date_to_payload(require_attribute(raw, "reportDate"))
        if not in_date_range(source_report_date, start_date, end_date):
            continue

        cash_flow_records.append(map_cash_transaction_attributes(raw).to_bulk_record())

    for element in root.iter("EquitySummaryByReportDateInBase"):
        raw = dict(element.attrib)
        source_report_date = flex_date_to_payload(require_attribute(raw, "reportDate"))
        if not in_date_range(source_report_date, start_date, end_date):
            continue

        daily_nav_records.append(map_daily_nav_attributes(raw).to_bulk_record())

    all_records = cash_flow_records + daily_nav_records
    return FlexDryRunSummary(
        cash_flow_records=tuple(cash_flow_records),
        daily_nav_records=tuple(daily_nav_records),
        unsupported_cash_transaction_count=unsupported_cash_transaction_count,
        accounts_seen=_sorted_unique(record["account_external_id"] for record in all_records),
        currencies_seen=_sorted_unique(record["source_currency"] for record in all_records),
        cash_flow_date_range=_record_date_range(cash_flow_records, "flow_date"),
        daily_nav_date_range=_record_date_range(daily_nav_records, "snapshot_date"),
        duplicate_dedupe_keys=_duplicate_dedupe_keys(all_records),
    )


def _sorted_unique(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values}))


def _record_date_range(records: list[dict[str, Any]], field_name: str) -> DateRange | None:
    if not records:
        return None
    dates = sorted(str(record[field_name]) for record in records)
    return dates[0], dates[-1]


def _duplicate_dedupe_keys(records: list[dict[str, Any]]) -> tuple[str, ...]:
    counts = Counter(str(record["dedupe_key"]) for record in records)
    return tuple(sorted(key for key, count in counts.items() if count > 1))
```

- [ ] **Step 4: Run analyzer tests**

Run:

```bash
python -m unittest tests.test_flex_dry_run -v
```

Expected: PASS for all dry-run analyzer tests.

- [ ] **Step 5: Run existing mapper tests**

Run:

```bash
python -m unittest tests.test_flex_ingestion_mappers -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

Run:

```bash
git add portfolio_engine/ingestion/dry_run.py tests/test_flex_dry_run.py
git commit -m "feat: add Flex dry-run analyzer" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Add dry-run CLI runner

**Files:**
- Create: `portfolio_engine/ingestion_cli.py`
- Create: `tests/test_ingestion_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_ingestion_cli.py`:

```python
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from portfolio_engine.ingestion_cli import run


MIXED_XML = """<FlexQueryResponse>
  <CashTransaction accountId="U100" reportDate="20250102" dateTime="20250102;091500" currency="USD" amount="1000.00" fxRateToBase="1" type="Deposits/Withdrawals" transactionID="CF1" />
  <CashTransaction accountId="U100" reportDate="20250103" dateTime="20250103;101500" currency="USD" amount="5.00" fxRateToBase="1" type="Dividend" transactionID="DIV1" />
  <EquitySummaryByReportDateInBase accountId="U100" reportDate="20250102" currency="USD" total="10000.00" />
</FlexQueryResponse>"""


class IngestionCliTests(unittest.TestCase):
    def test_dry_run_prints_privacy_safe_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Flex.xml"
            path.write_text(MIXED_XML, encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()

            exit_code = run(["dry-run", str(path)], stdout=stdout, stderr=stderr)

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Dry run:", output)
        self.assertIn("Cash-flow records mapped: 1", output)
        self.assertIn("Daily NAV snapshots mapped: 1", output)
        self.assertIn("Unsupported CashTransaction records skipped: 1", output)
        self.assertIn("Accounts seen: U100", output)
        self.assertIn("Currencies seen: USD", output)
        self.assertIn("Duplicate dedupe keys: 0", output)
        self.assertIn("No database writes performed.", output)
        self.assertNotIn("1000.00", output)
        self.assertEqual(stderr.getvalue(), "")

    def test_dry_run_date_filter_limits_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Flex.xml"
            path.write_text(MIXED_XML, encoding="utf-8")
            stdout = io.StringIO()

            exit_code = run(
                ["dry-run", str(path), "--start-date", "2025-01-03", "--end-date", "2025-01-03"],
                stdout=stdout,
                stderr=io.StringIO(),
            )

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Cash-flow records mapped: 0", output)
        self.assertIn("Daily NAV snapshots mapped: 0", output)

    def test_dry_run_rejects_start_date_after_end_date(self) -> None:
        stderr = io.StringIO()

        exit_code = run(
            ["dry-run", "missing.xml", "--start-date", "2025-01-04", "--end-date", "2025-01-03"],
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: --start-date must be on or before --end-date", stderr.getvalue())

    def test_dry_run_invalid_date_returns_error(self) -> None:
        stderr = io.StringIO()

        exit_code = run(
            ["dry-run", "missing.xml", "--start-date", "20250103"],
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: invalid date '20250103'; expected YYYY-MM-DD", stderr.getvalue())

    def test_dry_run_missing_file_returns_error(self) -> None:
        stderr = io.StringIO()

        exit_code = run(["dry-run", "missing.xml"], stdout=io.StringIO(), stderr=stderr)

        self.assertEqual(exit_code, 1)
        self.assertIn("Error:", stderr.getvalue())
        self.assertIn("missing.xml", stderr.getvalue())

    def test_dry_run_malformed_xml_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.xml"
            path.write_text("<FlexQueryResponse>", encoding="utf-8")
            stderr = io.StringIO()

            exit_code = run(["dry-run", str(path)], stdout=io.StringIO(), stderr=stderr)

        self.assertEqual(exit_code, 1)
        self.assertIn("Error:", stderr.getvalue())
```

- [ ] **Step 2: Run CLI tests to verify they fail**

Run:

```bash
python -m unittest tests.test_ingestion_cli -v
```

Expected: FAIL with `ModuleNotFoundError` or import errors because `portfolio_engine.ingestion_cli` does not exist.

- [ ] **Step 3: Implement CLI runner**

Create `portfolio_engine/ingestion_cli.py`:

```python
"""CLI helpers for manual Flex XML ingestion workflows."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import TextIO

from portfolio_engine.ingestion.dry_run import FlexDryRunSummary, analyze_flex_xml_file


class IngestionCliError(RuntimeError):
    """Raised when ingestion CLI input is invalid."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise IngestionCliError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(description="Manual Flex XML ingestion utilities.")
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=_ArgumentParser)

    dry_run = subparsers.add_parser("dry-run", help="Preview supported Flex records without database writes.")
    dry_run.add_argument("file", type=Path, help="Flex XML file to inspect.")
    dry_run.add_argument("--start-date", type=_parse_iso_date, help="Inclusive reportDate filter start.")
    dry_run.add_argument("--end-date", type=_parse_iso_date, help="Inclusive reportDate filter end.")
    return parser


def run(
    argv: list[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
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
    except Exception as error:
        stderr.write(f"Error: {error}\n")
        return 1

    stderr.write("Error: unsupported command\n")
    return 1


def main(argv: list[str] | None = None) -> int:
    return run(argv)


def _parse_iso_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as error:
        raise IngestionCliError(f"invalid date {value!r}; expected YYYY-MM-DD") from error


def _validate_date_range(start_date: str | None, end_date: str | None) -> None:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise IngestionCliError("--start-date must be on or before --end-date")


def _print_dry_run_summary(path: Path, summary: FlexDryRunSummary, stdout: TextIO) -> None:
    stdout.write(f"Dry run: {path}\n")
    stdout.write(f"Cash-flow records mapped: {summary.cash_flow_count}\n")
    stdout.write(f"Daily NAV snapshots mapped: {summary.daily_nav_count}\n")
    stdout.write(
        f"Unsupported CashTransaction records skipped: {summary.unsupported_cash_transaction_count}\n"
    )
    stdout.write(f"Accounts seen: {_format_tuple(summary.accounts_seen)}\n")
    stdout.write(f"Currencies seen: {_format_tuple(summary.currencies_seen)}\n")
    stdout.write(f"Cash-flow date range: {_format_range(summary.cash_flow_date_range)}\n")
    stdout.write(f"Daily NAV date range: {_format_range(summary.daily_nav_date_range)}\n")
    stdout.write(f"Duplicate dedupe keys: {len(summary.duplicate_dedupe_keys)}\n")
    for dedupe_key in summary.duplicate_dedupe_keys[:5]:
        stdout.write(f"  - {dedupe_key}\n")
    stdout.write("No database writes performed.\n")


def _format_tuple(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "(none)"


def _format_range(value: tuple[str, str] | None) -> str:
    if value is None:
        return "(none)"
    return f"{value[0]} to {value[1]}"
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
python -m unittest tests.test_ingestion_cli -v
```

Expected: PASS.

- [ ] **Step 5: Run dry-run analyzer and mapper tests**

Run:

```bash
python -m unittest tests.test_flex_dry_run tests.test_flex_ingestion_mappers -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

Run:

```bash
git add portfolio_engine/ingestion_cli.py tests/test_ingestion_cli.py
git commit -m "feat: add Flex dry-run CLI runner" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Add executable script, docs, and final verification

**Files:**
- Create: `scripts/ingest_flex_file.py`
- Modify: `README.md`
- Modify: `tests/test_ingestion_cli.py`

- [ ] **Step 1: Write failing script wrapper smoke test**

Append inside `IngestionCliTests` in `tests/test_ingestion_cli.py`:

```python
    def test_script_wrapper_imports_main(self) -> None:
        import scripts.ingest_flex_file as ingest_flex_file_script

        self.assertEqual(ingest_flex_file_script.main.__module__, "portfolio_engine.ingestion_cli")
```

- [ ] **Step 2: Run wrapper test to verify it fails**

Run:

```bash
python -m unittest tests.test_ingestion_cli.IngestionCliTests.test_script_wrapper_imports_main -v
```

Expected: FAIL with `ModuleNotFoundError` because `scripts/ingest_flex_file.py` does not exist.

- [ ] **Step 3: Create executable wrapper**

Create `scripts/ingest_flex_file.py`:

```python
#!/usr/bin/env python3
"""CLI for manual Flex XML ingestion workflows."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from portfolio_engine.ingestion_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
```

Then make it executable:

```bash
git update-index --chmod=+x scripts/ingest_flex_file.py
```

- [ ] **Step 4: Add README documentation**

Add this section near the existing Python CLI documentation in `README.md`:

```markdown
### Dry-running a Flex XML file

Before loading manual Flex XML into the database, inspect a file locally:

```bash
python scripts/ingest_flex_file.py dry-run scratch/Flex.xml \
  --start-date 2025-01-01 \
  --end-date 2025-04-30
```

The dry run scans one Flex XML file for supported records and performs no database writes. A file can contain cash transactions, daily NAV snapshots, or both. Current cash-transaction support is limited to `Deposits/Withdrawals`; other `CashTransaction` types are counted as unsupported and skipped for now.
```

- [ ] **Step 5: Run final verification**

Run:

```bash
python -m unittest tests.test_ingestion_cli tests.test_flex_dry_run tests.test_flex_ingestion_mappers tests.test_account_cli tests.test_database_adapter -v
python -m compileall portfolio_engine scripts tests
git diff --check
```

Expected: all tests pass, compileall succeeds, and `git diff --check` is clean.

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add README.md scripts/ingest_flex_file.py tests/test_ingestion_cli.py
git commit -m "docs: document Flex dry-run CLI" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Self-review notes

- Spec coverage: The plan implements the approved mapper-only dry run, mixed-file auto-detection, `Deposits/Withdrawals` cash-transaction support, daily NAV support, optional `reportDate` filtering, duplicate dedupe-key detection, privacy-safe output, and database-free behavior.
- Out-of-scope check: The plan does not add DB reads/writes, account readiness, ingestion run lifecycle calls, load mode, TWR, non-`Deposits/Withdrawals` cash transaction support, or JSON output.
- Placeholder scan: The plan contains no deferred implementation placeholders.
- Type consistency: `FlexDryRunSummary`, `analyze_flex_xml_text`, `analyze_flex_xml_file`, `IngestionCliError`, `run`, and `main` are named consistently across tasks and tests.
