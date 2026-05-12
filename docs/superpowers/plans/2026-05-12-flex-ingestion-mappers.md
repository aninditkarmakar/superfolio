# Flex Ingestion Mappers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first ingestion block: pure Python mappers that convert IBKR Flex XML cash-flow and daily-NAV records into the JSON-compatible payloads expected by the existing database bulk ingestion functions.

**Architecture:** Keep TWR calculation models separate from ingestion payload models. Reuse the existing Flex XML parsing helpers for dates and decimals, but add an ingestion-focused module that preserves source fields, builds deterministic dedupe keys, uses `reportDate` as the canonical cash-flow date, and returns dictionaries shaped for `bulk_ingest_cash_flows(...)` and `bulk_ingest_daily_nav_snapshots(...)`. This block does not connect to PostgreSQL and does not add a CLI.

**Tech Stack:** Python 3.12, standard library `xml.etree.ElementTree`, `dataclasses`, `datetime`, `decimal`, and `unittest`.

---

## File structure

- Create: `portfolio_engine/ingestion/__init__.py`  
  Marks ingestion code as its own package and exports the mapper API.
- Create: `portfolio_engine/ingestion/flex_mappers.py`  
  Contains ingestion dataclasses, dedupe-key helpers, XML traversal, and conversion to DB bulk payload dictionaries.
- Create: `tests/__init__.py`  
  Makes tests importable by `python -m unittest`.
- Create: `tests/test_flex_ingestion_mappers.py`  
  Contains synthetic XML tests for cash-flow payload mapping, NAV payload mapping, date filtering, amount-base conversion, dedupe stability, and required-field failures.

## Assumptions locked by this block

- `reportDate` is the canonical cash-flow date and maps to DB field `flow_date`.
- Cash-flow records default to `cash_flow_type="Deposits/Withdrawals"` to match the current TWR CLI behavior.
- Source Flex attributes are stored in `raw_payload` as a plain dictionary of string attributes.
- Cash-flow `external_record_id` uses IBKR `transactionID` when present.
- Daily-NAV `external_record_id` uses `NAV:<accountId>:<reportDate>` because daily NAV records do not have a transaction id.
- Dedupe keys are deterministic strings:
  - Cash flow: `IBKR:<accountId>:CASH_TRANSACTION:<transactionID>` when `transactionID` is present.
  - Cash flow fallback: `IBKR:<accountId>:CASH_TRANSACTION:<reportDate>:<currency>:<amount>:<description>` when `transactionID` is absent.
  - Daily NAV: `IBKR:<accountId>:DAILY_NAV:<reportDate>`.
- JSON-compatible payload values for dates and decimals are strings, because PostgreSQL bulk functions cast JSON text to `DATE` and `NUMERIC`.
- This block intentionally does not register accounts, start ingestion runs, call DB functions, or calculate TWR.

### Task 1: Add ingestion mapper dataclasses and helpers

**Files:**
- Create: `portfolio_engine/ingestion/__init__.py`
- Create: `portfolio_engine/ingestion/flex_mappers.py`
- Create: `tests/__init__.py`
- Test: `tests/test_flex_ingestion_mappers.py`

- [ ] **Step 1: Create the package files**

Create `portfolio_engine/ingestion/__init__.py`:

```python
"""Ingestion adapters for broker source data."""
```

Create `tests/__init__.py`:

```python
"""Test package for SuperFolio."""
```

- [ ] **Step 2: Write the failing tests for helper behavior**

Create `tests/test_flex_ingestion_mappers.py` with these imports and tests:

```python
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from portfolio_engine.ingestion.flex_mappers import (
    FlexCashTransactionPayload,
    FlexDailyNavPayload,
    build_cash_transaction_dedupe_key,
    build_daily_nav_dedupe_key,
    decimal_to_payload,
    flex_date_to_payload,
)


class FlexIngestionMapperTests(unittest.TestCase):
    def test_flex_date_to_payload_formats_iso_date(self) -> None:
        self.assertEqual(flex_date_to_payload("20260512"), "2026-05-12")

    def test_decimal_to_payload_preserves_decimal_string(self) -> None:
        self.assertEqual(decimal_to_payload(Decimal("123.4500")), "123.4500")

    def test_cash_dedupe_key_prefers_transaction_id(self) -> None:
        raw = {
            "accountId": "U100",
            "transactionID": "987654",
            "reportDate": "20260512",
            "currency": "USD",
            "amount": "10.00",
            "description": "Deposit",
        }

        self.assertEqual(
            build_cash_transaction_dedupe_key(raw),
            "IBKR:U100:CASH_TRANSACTION:987654",
        )

    def test_cash_dedupe_key_has_stable_fallback_without_transaction_id(self) -> None:
        raw = {
            "accountId": "U100",
            "reportDate": "20260512",
            "currency": "USD",
            "amount": "10.00",
            "description": "Deposit",
        }

        self.assertEqual(
            build_cash_transaction_dedupe_key(raw),
            "IBKR:U100:CASH_TRANSACTION:20260512:USD:10.00:Deposit",
        )

    def test_daily_nav_dedupe_key_uses_account_and_report_date(self) -> None:
        raw = {"accountId": "U100", "reportDate": "20260512"}

        self.assertEqual(
            build_daily_nav_dedupe_key(raw),
            "IBKR:U100:DAILY_NAV:20260512",
        )

    def test_payload_dataclasses_are_available_for_type_boundaries(self) -> None:
        cash_payload = FlexCashTransactionPayload(
            account_external_id="U100",
            external_record_id="987654",
            dedupe_key="IBKR:U100:CASH_TRANSACTION:987654",
            source_report_date="2026-05-12",
            source_currency="USD",
            raw_payload={"accountId": "U100"},
            flow_date="2026-05-12",
            cash_flow_type="Deposits/Withdrawals",
            currency="USD",
            amount="10.00",
            amount_base="13.5000",
            fx_rate_to_base="1.3500",
            description="Deposit",
        )
        nav_payload = FlexDailyNavPayload(
            account_external_id="U100",
            external_record_id="NAV:U100:20260512",
            dedupe_key="IBKR:U100:DAILY_NAV:20260512",
            source_report_date="2026-05-12",
            source_currency="USD",
            raw_payload={"accountId": "U100"},
            snapshot_date="2026-05-12",
            base_currency="USD",
            nav_base="1000.00",
        )

        self.assertEqual(cash_payload.flow_date, "2026-05-12")
        self.assertEqual(nav_payload.nav_base, "1000.00")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the helper tests to verify they fail**

Run:

```bash
python -m unittest tests.test_flex_ingestion_mappers -v
```

Expected: FAIL with `ModuleNotFoundError` or import errors because `portfolio_engine.ingestion.flex_mappers` does not exist yet.

- [ ] **Step 4: Implement the helper module**

Create `portfolio_engine/ingestion/flex_mappers.py`:

```python
"""Map IBKR Flex XML records to database ingestion payloads."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from portfolio_engine.flex_xml import parse_flex_date

BROKERAGE_CODE = "IBKR"
DEFAULT_CASH_FLOW_TYPE = "Deposits/Withdrawals"


@dataclass(frozen=True)
class FlexCashTransactionPayload:
    account_external_id: str
    external_record_id: str | None
    dedupe_key: str
    source_report_date: str
    source_currency: str
    raw_payload: dict[str, str]
    flow_date: str
    cash_flow_type: str
    currency: str
    amount: str
    amount_base: str
    fx_rate_to_base: str | None
    description: str | None

    def to_bulk_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FlexDailyNavPayload:
    account_external_id: str
    external_record_id: str
    dedupe_key: str
    source_report_date: str
    source_currency: str
    raw_payload: dict[str, str]
    snapshot_date: str
    base_currency: str
    nav_base: str

    def to_bulk_record(self) -> dict[str, Any]:
        return asdict(self)


def flex_date_to_payload(value: str | None) -> str:
    return parse_flex_date(value).isoformat()


def decimal_to_payload(value: Decimal) -> str:
    return str(value)


def require_attribute(raw: dict[str, str], name: str) -> str:
    value = raw.get(name)
    if value is None or value == "":
        raise ValueError(f"missing required Flex attribute: {name}")
    return value


def optional_blank_to_none(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return value


def in_date_range(record_date: date, start_date: date | None, end_date: date | None) -> bool:
    if start_date is not None and record_date < start_date:
        return False
    if end_date is not None and record_date > end_date:
        return False
    return True


def build_cash_transaction_dedupe_key(raw: dict[str, str]) -> str:
    account_id = require_attribute(raw, "accountId")
    transaction_id = raw.get("transactionID")
    if transaction_id:
        return f"{BROKERAGE_CODE}:{account_id}:CASH_TRANSACTION:{transaction_id}"

    report_date = require_attribute(raw, "reportDate")
    currency = require_attribute(raw, "currency")
    amount = require_attribute(raw, "amount")
    description = raw.get("description", "")
    return (
        f"{BROKERAGE_CODE}:{account_id}:CASH_TRANSACTION:"
        f"{report_date}:{currency}:{amount}:{description}"
    )


def build_daily_nav_dedupe_key(raw: dict[str, str]) -> str:
    account_id = require_attribute(raw, "accountId")
    report_date = require_attribute(raw, "reportDate")
    return f"{BROKERAGE_CODE}:{account_id}:DAILY_NAV:{report_date}"
```

- [ ] **Step 5: Run the helper tests to verify they pass**

Run:

```bash
python -m unittest tests.test_flex_ingestion_mappers -v
```

Expected: PASS for the helper tests.

- [ ] **Step 6: Commit Task 1**

Run:

```bash
git add portfolio_engine/ingestion/__init__.py portfolio_engine/ingestion/flex_mappers.py tests/__init__.py tests/test_flex_ingestion_mappers.py
git commit -m "feat: add Flex ingestion mapper helpers" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Map CashTransaction XML records to DB bulk payloads

**Files:**
- Modify: `portfolio_engine/ingestion/flex_mappers.py`
- Test: `tests/test_flex_ingestion_mappers.py`

- [ ] **Step 1: Add failing cash-flow mapping tests**

Append these tests inside `FlexIngestionMapperTests` in `tests/test_flex_ingestion_mappers.py`:

```python
    def test_map_cash_transactions_uses_report_date_as_flow_date(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U100" fromDate="20260501" toDate="20260531">
      <CashTransactions>
        <CashTransaction accountId="U100" transactionID="987654" reportDate="20260512"
          dateTime="20260510;120000" settleDate="20260513" availableForTradingDate="20260514"
          type="Deposits/Withdrawals" currency="CAD" amount="100.00" fxRateToBase="0.730000"
          description="Synthetic deposit" />
      </CashTransactions>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

        from portfolio_engine.ingestion.flex_mappers import map_cash_transactions_from_flex_xml_text

        records = map_cash_transactions_from_flex_xml_text(xml)

        self.assertEqual(
            records,
            [
                {
                    "account_external_id": "U100",
                    "external_record_id": "987654",
                    "dedupe_key": "IBKR:U100:CASH_TRANSACTION:987654",
                    "source_report_date": "2026-05-12",
                    "source_currency": "CAD",
                    "raw_payload": {
                        "accountId": "U100",
                        "transactionID": "987654",
                        "reportDate": "20260512",
                        "dateTime": "20260510;120000",
                        "settleDate": "20260513",
                        "availableForTradingDate": "20260514",
                        "type": "Deposits/Withdrawals",
                        "currency": "CAD",
                        "amount": "100.00",
                        "fxRateToBase": "0.730000",
                        "description": "Synthetic deposit",
                    },
                    "flow_date": "2026-05-12",
                    "cash_flow_type": "Deposits/Withdrawals",
                    "currency": "CAD",
                    "amount": "100.00",
                    "amount_base": "73.00000000",
                    "fx_rate_to_base": "0.730000",
                    "description": "Synthetic deposit",
                }
            ],
        )

    def test_map_cash_transactions_filters_to_deposits_withdrawals_by_default(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <CashTransactions>
    <CashTransaction accountId="U100" transactionID="1" reportDate="20260512"
      type="Deposits/Withdrawals" currency="USD" amount="100.00" fxRateToBase="1"
      description="Synthetic deposit" />
    <CashTransaction accountId="U100" transactionID="2" reportDate="20260512"
      type="Dividends" currency="USD" amount="5.00" fxRateToBase="1"
      description="Synthetic dividend" />
  </CashTransactions>
</FlexQueryResponse>
"""

        from portfolio_engine.ingestion.flex_mappers import map_cash_transactions_from_flex_xml_text

        records = map_cash_transactions_from_flex_xml_text(xml)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["external_record_id"], "1")

    def test_map_cash_transactions_allows_date_range_filter(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <CashTransactions>
    <CashTransaction accountId="U100" transactionID="1" reportDate="20260501"
      type="Deposits/Withdrawals" currency="USD" amount="100.00" fxRateToBase="1"
      description="Before range" />
    <CashTransaction accountId="U100" transactionID="2" reportDate="20260512"
      type="Deposits/Withdrawals" currency="USD" amount="200.00" fxRateToBase="1"
      description="Inside range" />
  </CashTransactions>
</FlexQueryResponse>
"""

        from portfolio_engine.ingestion.flex_mappers import map_cash_transactions_from_flex_xml_text

        records = map_cash_transactions_from_flex_xml_text(
            xml,
            start_date=date(2026, 5, 10),
            end_date=date(2026, 5, 20),
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["external_record_id"], "2")

    def test_map_cash_transactions_raises_for_missing_report_date(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <CashTransactions>
    <CashTransaction accountId="U100" transactionID="1"
      type="Deposits/Withdrawals" currency="USD" amount="100.00" fxRateToBase="1"
      description="Missing date" />
  </CashTransactions>
</FlexQueryResponse>
"""

        from portfolio_engine.ingestion.flex_mappers import map_cash_transactions_from_flex_xml_text

        with self.assertRaisesRegex(ValueError, "missing required Flex attribute: reportDate"):
            map_cash_transactions_from_flex_xml_text(xml)
```

- [ ] **Step 2: Run the cash-flow mapping tests to verify they fail**

Run:

```bash
python -m unittest tests.test_flex_ingestion_mappers.FlexIngestionMapperTests.test_map_cash_transactions_uses_report_date_as_flow_date tests.test_flex_ingestion_mappers.FlexIngestionMapperTests.test_map_cash_transactions_filters_to_deposits_withdrawals_by_default tests.test_flex_ingestion_mappers.FlexIngestionMapperTests.test_map_cash_transactions_allows_date_range_filter tests.test_flex_ingestion_mappers.FlexIngestionMapperTests.test_map_cash_transactions_raises_for_missing_report_date -v
```

Expected: FAIL with import errors because `map_cash_transactions_from_flex_xml_text` does not exist.

- [ ] **Step 3: Implement cash-flow XML mapping**

Append this code to `portfolio_engine/ingestion/flex_mappers.py`:

```python
from pathlib import Path
from xml.etree import ElementTree

from portfolio_engine.flex_xml import parse_decimal


def map_cash_transaction_attributes(raw: dict[str, str]) -> FlexCashTransactionPayload:
    account_id = require_attribute(raw, "accountId")
    report_date_raw = require_attribute(raw, "reportDate")
    currency = require_attribute(raw, "currency").upper()
    amount = parse_decimal(require_attribute(raw, "amount"), field_name="amount")
    fx_rate_raw = raw.get("fxRateToBase")
    fx_rate = parse_decimal(fx_rate_raw, field_name="fxRateToBase") if fx_rate_raw not in (None, "") else Decimal("1")
    amount_base = amount * fx_rate
    transaction_type = require_attribute(raw, "type")

    return FlexCashTransactionPayload(
        account_external_id=account_id,
        external_record_id=optional_blank_to_none(raw.get("transactionID")),
        dedupe_key=build_cash_transaction_dedupe_key(raw),
        source_report_date=flex_date_to_payload(report_date_raw),
        source_currency=currency,
        raw_payload=dict(raw),
        flow_date=flex_date_to_payload(report_date_raw),
        cash_flow_type=transaction_type,
        currency=currency,
        amount=decimal_to_payload(amount),
        amount_base=decimal_to_payload(amount_base),
        fx_rate_to_base=decimal_to_payload(fx_rate) if fx_rate_raw not in (None, "") else None,
        description=optional_blank_to_none(raw.get("description")),
    )


def map_cash_transactions_from_flex_xml_text(
    xml_text: str,
    *,
    cash_flow_type: str = DEFAULT_CASH_FLOW_TYPE,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text)
    records: list[dict[str, Any]] = []

    for element in root.iter("CashTransaction"):
        raw = dict(element.attrib)
        transaction_type = raw.get("type", "")
        if cash_flow_type and transaction_type != cash_flow_type:
            continue

        report_date = parse_flex_date(require_attribute(raw, "reportDate"))
        if not in_date_range(report_date, start_date, end_date):
            continue

        records.append(map_cash_transaction_attributes(raw).to_bulk_record())

    return records


def map_cash_transactions_from_flex_xml_file(
    path: Path,
    *,
    cash_flow_type: str = DEFAULT_CASH_FLOW_TYPE,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    return map_cash_transactions_from_flex_xml_text(
        path.read_text(encoding="utf-8"),
        cash_flow_type=cash_flow_type,
        start_date=start_date,
        end_date=end_date,
    )
```

Then move the appended imports to the top of the file so the import section is:

```python
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from portfolio_engine.flex_xml import parse_decimal, parse_flex_date
```

- [ ] **Step 4: Run the cash-flow mapping tests to verify they pass**

Run:

```bash
python -m unittest tests.test_flex_ingestion_mappers -v
```

Expected: PASS for all current tests.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add portfolio_engine/ingestion/flex_mappers.py tests/test_flex_ingestion_mappers.py
git commit -m "feat: map Flex cash transactions for ingestion" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Map daily NAV XML records to DB bulk payloads

**Files:**
- Modify: `portfolio_engine/ingestion/flex_mappers.py`
- Modify: `portfolio_engine/ingestion/__init__.py`
- Test: `tests/test_flex_ingestion_mappers.py`

- [ ] **Step 1: Add failing daily NAV mapping tests**

Append these tests inside `FlexIngestionMapperTests` in `tests/test_flex_ingestion_mappers.py`:

```python
    def test_map_daily_nav_snapshots_maps_total_to_nav_base(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U100" fromDate="20260501" toDate="20260531">
      <EquitySummaryInBase>
        <EquitySummaryByReportDateInBase accountId="U100" reportDate="20260512"
          currency="USD" total="12345.6700" cash="100.00" stock="12245.67" />
      </EquitySummaryInBase>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

        from portfolio_engine.ingestion.flex_mappers import map_daily_nav_snapshots_from_flex_xml_text

        records = map_daily_nav_snapshots_from_flex_xml_text(xml)

        self.assertEqual(
            records,
            [
                {
                    "account_external_id": "U100",
                    "external_record_id": "NAV:U100:20260512",
                    "dedupe_key": "IBKR:U100:DAILY_NAV:20260512",
                    "source_report_date": "2026-05-12",
                    "source_currency": "USD",
                    "raw_payload": {
                        "accountId": "U100",
                        "reportDate": "20260512",
                        "currency": "USD",
                        "total": "12345.6700",
                        "cash": "100.00",
                        "stock": "12245.67",
                    },
                    "snapshot_date": "2026-05-12",
                    "base_currency": "USD",
                    "nav_base": "12345.6700",
                }
            ],
        )

    def test_map_daily_nav_snapshots_allows_date_range_filter(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <EquitySummaryInBase>
    <EquitySummaryByReportDateInBase accountId="U100" reportDate="20260501"
      currency="USD" total="100.00" />
    <EquitySummaryByReportDateInBase accountId="U100" reportDate="20260512"
      currency="USD" total="200.00" />
  </EquitySummaryInBase>
</FlexQueryResponse>
"""

        from portfolio_engine.ingestion.flex_mappers import map_daily_nav_snapshots_from_flex_xml_text

        records = map_daily_nav_snapshots_from_flex_xml_text(
            xml,
            start_date=date(2026, 5, 10),
            end_date=date(2026, 5, 20),
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["snapshot_date"], "2026-05-12")

    def test_map_daily_nav_snapshots_raises_for_missing_total(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <EquitySummaryInBase>
    <EquitySummaryByReportDateInBase accountId="U100" reportDate="20260512"
      currency="USD" />
  </EquitySummaryInBase>
</FlexQueryResponse>
"""

        from portfolio_engine.ingestion.flex_mappers import map_daily_nav_snapshots_from_flex_xml_text

        with self.assertRaisesRegex(ValueError, "missing required Flex attribute: total"):
            map_daily_nav_snapshots_from_flex_xml_text(xml)
```

- [ ] **Step 2: Run the daily NAV tests to verify they fail**

Run:

```bash
python -m unittest tests.test_flex_ingestion_mappers.FlexIngestionMapperTests.test_map_daily_nav_snapshots_maps_total_to_nav_base tests.test_flex_ingestion_mappers.FlexIngestionMapperTests.test_map_daily_nav_snapshots_allows_date_range_filter tests.test_flex_ingestion_mappers.FlexIngestionMapperTests.test_map_daily_nav_snapshots_raises_for_missing_total -v
```

Expected: FAIL with import errors because `map_daily_nav_snapshots_from_flex_xml_text` does not exist.

- [ ] **Step 3: Implement daily NAV XML mapping**

Append this code to `portfolio_engine/ingestion/flex_mappers.py`:

```python
def map_daily_nav_attributes(raw: dict[str, str]) -> FlexDailyNavPayload:
    account_id = require_attribute(raw, "accountId")
    report_date_raw = require_attribute(raw, "reportDate")
    currency = require_attribute(raw, "currency").upper()
    total = parse_decimal(require_attribute(raw, "total"), field_name="total")

    return FlexDailyNavPayload(
        account_external_id=account_id,
        external_record_id=f"NAV:{account_id}:{report_date_raw}",
        dedupe_key=build_daily_nav_dedupe_key(raw),
        source_report_date=flex_date_to_payload(report_date_raw),
        source_currency=currency,
        raw_payload=dict(raw),
        snapshot_date=flex_date_to_payload(report_date_raw),
        base_currency=currency,
        nav_base=decimal_to_payload(total),
    )


def map_daily_nav_snapshots_from_flex_xml_text(
    xml_text: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text)
    records: list[dict[str, Any]] = []

    for element in root.iter("EquitySummaryByReportDateInBase"):
        raw = dict(element.attrib)
        report_date = parse_flex_date(require_attribute(raw, "reportDate"))
        if not in_date_range(report_date, start_date, end_date):
            continue

        records.append(map_daily_nav_attributes(raw).to_bulk_record())

    return records


def map_daily_nav_snapshots_from_flex_xml_file(
    path: Path,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    return map_daily_nav_snapshots_from_flex_xml_text(
        path.read_text(encoding="utf-8"),
        start_date=start_date,
        end_date=end_date,
    )
```

- [ ] **Step 4: Export the public mapper API**

Replace `portfolio_engine/ingestion/__init__.py` with:

```python
"""Ingestion adapters for broker source data."""

from .flex_mappers import (
    FlexCashTransactionPayload,
    FlexDailyNavPayload,
    map_cash_transactions_from_flex_xml_file,
    map_cash_transactions_from_flex_xml_text,
    map_daily_nav_snapshots_from_flex_xml_file,
    map_daily_nav_snapshots_from_flex_xml_text,
)

__all__ = [
    "FlexCashTransactionPayload",
    "FlexDailyNavPayload",
    "map_cash_transactions_from_flex_xml_file",
    "map_cash_transactions_from_flex_xml_text",
    "map_daily_nav_snapshots_from_flex_xml_file",
    "map_daily_nav_snapshots_from_flex_xml_text",
]
```

- [ ] **Step 5: Run the full mapper test file**

Run:

```bash
python -m unittest tests.test_flex_ingestion_mappers -v
```

Expected: PASS for all mapper tests.

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add portfolio_engine/ingestion/__init__.py portfolio_engine/ingestion/flex_mappers.py tests/test_flex_ingestion_mappers.py
git commit -m "feat: map Flex daily NAV snapshots for ingestion" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Verify Block 1 against real sample shape without exposing private data

**Files:**
- Modify: `tests/test_flex_ingestion_mappers.py`
- No production file changes expected

- [ ] **Step 1: Add privacy-safe sample-shape smoke tests**

Append these tests inside `FlexIngestionMapperTests` in `tests/test_flex_ingestion_mappers.py`:

```python
    def test_scratch_cash_flow_file_shape_when_available(self) -> None:
        from pathlib import Path

        from portfolio_engine.ingestion.flex_mappers import map_cash_transactions_from_flex_xml_file

        sample_path = Path("scratch/Cash_Flows.xml")
        if not sample_path.exists():
            self.skipTest("scratch/Cash_Flows.xml is not available")

        records = map_cash_transactions_from_flex_xml_file(sample_path)

        self.assertGreater(len(records), 0)
        first = records[0]
        self.assertIn("account_external_id", first)
        self.assertIn("dedupe_key", first)
        self.assertIn("flow_date", first)
        self.assertIn("amount_base", first)
        self.assertIn("raw_payload", first)

    def test_scratch_daily_nav_file_shape_when_available(self) -> None:
        from pathlib import Path

        from portfolio_engine.ingestion.flex_mappers import map_daily_nav_snapshots_from_flex_xml_file

        sample_path = Path("scratch/Daily_NAV.xml")
        if not sample_path.exists():
            self.skipTest("scratch/Daily_NAV.xml is not available")

        records = map_daily_nav_snapshots_from_flex_xml_file(sample_path)

        self.assertGreater(len(records), 0)
        first = records[0]
        self.assertIn("account_external_id", first)
        self.assertIn("dedupe_key", first)
        self.assertIn("snapshot_date", first)
        self.assertIn("nav_base", first)
        self.assertIn("raw_payload", first)
```

- [ ] **Step 2: Run the full mapper test file**

Run:

```bash
python -m unittest tests.test_flex_ingestion_mappers -v
```

Expected: PASS. If `scratch/` files are unavailable, the two smoke tests SKIP and all synthetic tests PASS. Do not print raw scratch records or values.

- [ ] **Step 3: Run a syntax check for the touched Python package**

Run:

```bash
python -m compileall portfolio_engine tests
```

Expected: command completes successfully.

- [ ] **Step 4: Commit Task 4**

Run:

```bash
git add tests/test_flex_ingestion_mappers.py
git commit -m "test: verify Flex mapper sample shapes" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Self-review notes

- Spec coverage: The plan covers Block 1 only: transform Flex XML records into DB bulk-function payload dictionaries. It does not include a DB client, CLI, account registration, or TWR DB reader; those belong to later blocks.
- Placeholder scan: The plan contains no deferred implementation steps. Each task has concrete file paths, test code, implementation code, commands, and expected outcomes.
- Type consistency: Mapper function names, dataclass names, payload fields, and DB JSON keys match the existing `docs/database-functions.md` contract and are reused consistently across tasks.
