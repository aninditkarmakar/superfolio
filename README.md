# Consolidated Portfolio Tracker

A professional-grade, public-facing investment dashboard that tracks portfolio performance across multiple brokerage accounts, international borders, and currencies.

## 🚀 Overview

The tracker solves the "History Gap" problem by stitching together historical data from multiple accounts (e.g., a legacy Canadian IBKR account and a current US IBKR account) into a single, continuous Time-Weighted Return (TWR) curve.

### Key Features
* **Unified Ledger:** Merges disparate brokerage accounts into one logical portfolio view.
* **Multi-Currency Normalization:** Converts CAD transactions and NAV to USD using the `fxRateToBase` field embedded in each Flex record, keeping source currency, base-currency value, and FX rate fully traceable.
* **Daily Valuation TWR:** Uses the Daily Valuation Method to calculate performance, isolating investment returns from the effect of external cash flows (deposits/withdrawals).
* **Privacy-First Public Dashboard:** Exposes percentage growth and top-holding weightings rather than absolute dollar amounts.
* **Automated Ingestion (planned):** Daily syncs via the IBKR Flex Web Service — no local gateway or 2FA required for reporting.

## 🛠 Tech Stack

The architecture follows a **"Python for Data, TypeScript for UI"** philosophy.

| Layer | Technology | Status |
| :--- | :--- | :--- |
| **Data Engine** | Python 3.12 (stdlib only) | ✅ Implemented |
| **Database** | PostgreSQL (Supabase) | 🗓 Planned |
| **API** | Next.js Route Handlers | 🗓 Planned |
| **Frontend** | Next.js + Tremor.so | 🗓 Planned |
| **Automation** | GitHub Actions | 🗓 Planned |
| **Hosting** | Vercel | 🗓 Planned |

## 📂 Project Structure

```
portfolio_engine/        # Python calculation engine (no third-party deps)
  models.py              # CashFlow, NavSnapshot, TwrRow dataclasses
  flex_xml.py            # IBKR Flex XML parsers (CashTransaction, EquitySummaryByReportDateInBase)
  twr.py                 # Daily Valuation TWR math with configurable flow timing
  csv_export.py          # CSV writer for daily TWR output

scripts/
  calculate_twr.py       # End-to-end CLI: Flex XML → TWR → optional CSV export

scratch/                 # Local-only IBKR Flex XML samples (git-ignored, not committed)
```

## ⚙️ Python Engine

### Running the TWR CLI

Place your IBKR Flex XML exports in `scratch/` (git-ignored), then run:

```bash
python scripts/calculate_twr.py \
  --cash-flows scratch/Cash_Flows.xml \
  --daily-nav  scratch/Daily_NAV.xml \
  --start-date 2025-01-01 \
  --daily-output output/twr.csv
```

The script prints a summary to stdout and writes an optional daily CSV:

```
NAV snapshots: 83
Cash-flow records: 4
Return periods: 82
Date range: 2025-01-02 to 2025-04-25
Cash-flow date field: reportDate
Cash-flow timing: start
TWR: 12.345678%
Daily output written to output/twr.csv
```

### CLI Options

| Flag | Default | Description |
| :--- | :--- | :--- |
| `--cash-flows` | `scratch/Cash_Flows.xml` | Path to Flex cash-flow report |
| `--daily-nav` | `scratch/Daily_NAV.xml` | Path to Flex daily NAV report |
| `--flow-date-field` | `reportDate` | Date attribute used to align flows (`reportDate`, `dateTime`, `settleDate`, `availableForTradingDate`) |
| `--flow-timing` | `start` | Return convention: `start` = flow at beginning of period; `end` = flow at end |
| `--cash-flow-type` | `Deposits/Withdrawals` | `CashTransaction` type filter; pass `""` to include all |
| `--start-date` | *(none)* | Filter window start (`YYYY-MM-DD`) |
| `--end-date` | *(none)* | Filter window end (`YYYY-MM-DD`) |
| `--daily-output` | *(none)* | Optional CSV path for daily TWR rows |

### Flex XML Record Types Used

| Element | Purpose |
| :--- | :--- |
| `CashTransaction` | External cash flows (deposits, withdrawals, dividends, fees) |
| `EquitySummaryByReportDateInBase` | Daily total NAV in the base currency |

### Engine Modules

| Module | Responsibility |
| :--- | :--- |
| `portfolio_engine.models` | Immutable dataclasses: `CashFlow`, `NavSnapshot`, `TwrRow` |
| `portfolio_engine.flex_xml` | Structured XML parsing with date filtering and FX normalization |
| `portfolio_engine.twr` | `align_flows_to_nav_dates` + `calculate_twr` with start/end flow-timing modes |
| `portfolio_engine.csv_export` | `write_daily_twr_csv` for downstream analysis |

## 💻 Development Environment

This project uses **VS Code Dev Containers** for a reproducible local setup.

### `.devcontainer/devcontainer.json`
* **Base Image:** `mcr.microsoft.com/devcontainers/typescript-node:4-24-trixie` (Node.js/TypeScript host, extended via `.devcontainer/Dockerfile`)
* **Python Feature:** `ghcr.io/devcontainers/features/python:1` — Python 3.12 with pip and JupyterLab
* **Database Client:** `postgresql-client` — includes `psql` for testing PostgreSQL/Neon connections

No third-party Python packages are required by the current engine — it uses only the standard library (`xml.etree`, `csv`, `dataclasses`, `decimal`, `pathlib`).

## 📊 Planned Database Schema

The intended relational model separates raw broker events from derived portfolio metrics:

* **Accounts** — regional constraints (CAD vs. USD base currency) and status
* **Transactions** — atomic trade executions (BUY/SELL/DIV)
* **Cash Flows** — external deposits, withdrawals, and internal transfers
* **Daily Snapshots** — daily NAV and cash balances for optimized TWR rendering

## 📈 Roadmap

- [ ] **Supabase Schema + Ingestion:** Persist parsed Flex records to PostgreSQL with idempotent upserts.
- [ ] **Next.js Dashboard:** Dense, scan-friendly chart UI displaying TWR curve and holding weightings.
- [ ] **GitHub Actions Automation:** Scheduled daily Flex XML fetch and TWR recalculation.
- [ ] **Alpha Attribution:** Decompose returns by sector and timing.
- [ ] **Public Trade Feed:** Recent executions and per-trade P&L (redacted to percentages).
- [ ] **Multi-Broker Integration:** Expand beyond IBKR using the established schema.

---
*Developed by a software engineer with a 3-year track record of market-beating returns.*
