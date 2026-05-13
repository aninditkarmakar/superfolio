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
| **Database** | PostgreSQL + Sqitch migrations | 🚧 Scaffolded |
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
  calculate_twr.py          # End-to-end CLI: Flex XML -> TWR -> optional CSV export
  calculate_twr_from_db.py  # Database CLI: PostgreSQL facts -> TWR -> optional CSV export

migrations/
  deploy/                # Sqitch deploy scripts
  revert/                # Sqitch revert scripts
  verify/                # Sqitch verification scripts
  sqitch.plan            # Ordered migration plan

sqitch.conf              # Sqitch project configuration

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

The command uses `DATABASE_URL` by default. Pass `--database-url` to override it for one run. It calculates one selected brokerage account at a time, reads daily NAV snapshots and Deposits/Withdrawals cash flows from the database, and writes the same optional daily CSV schema as `scripts/calculate_twr.py`.

### Database-backed CLI Options

| Flag | Default | Description |
| :--- | :--- | :--- |
| `--brokerage-code` | required | Brokerage code for the selected account, for example `IBKR`. |
| `--account-external-id` | required | Brokerage account id to calculate. |
| `--database-url` | `DATABASE_URL` | Optional database URL override. |
| `--flow-timing` | `start` | Return convention: `start` = flow at beginning of period; `end` = flow at end. |
| `--start-date` | none | Filter window start (`YYYY-MM-DD`). |
| `--end-date` | none | Filter window end (`YYYY-MM-DD`). |
| `--daily-output` | none | Optional CSV path for daily TWR rows. |

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
* **Database Tools:** `postgresql-client`, `sqitch`, and `libdbd-pg-perl` are installed by `.devcontainer/Dockerfile` for PostgreSQL/Sqitch workflows.
* **Python Dependencies:** `.devcontainer/post-create.sh` installs `requirements.txt`, currently `psycopg[binary]` for database-backed CLI workflows.

The core TWR engine uses only the Python standard library. Database-backed commands additionally require the committed `requirements.txt` dependencies.

### `.env` — local configuration

Create a `.env` file at the repository root (it is git-ignored). The dev container's `post-create.sh` reads this file on every container rebuild, so set it up once and it is applied automatically.

```dotenv
# Git identity — used by .devcontainer/post-create.sh to run
# `git config --global user.name` and `git config --global user.email`
GITHUB_NAME=Your Name
GITHUB_EMAIL=your-id+handle@users.noreply.github.com

# Database — Neon/PostgreSQL connection string (see Database Migrations section)
DATABASE_URL=postgresql://USER:PASSWORD@HOST/neondb?sslmode=require&channel_binding=require
```

| Key | Required by | Purpose |
| :--- | :--- | :--- |
| `GITHUB_NAME` | dev container (`post-create.sh`) | Sets `git config --global user.name` inside the container |
| `GITHUB_EMAIL` | dev container (`post-create.sh`) | Sets `git config --global user.email` inside the container |
| `DATABASE_URL` | Sqitch migrations and database CLI scripts | PostgreSQL connection string for `sqitch deploy/verify` and database-backed CLI workflows |

### Registering an account

Before loading Flex XML records into the database, register each brokerage account once:

```bash
python scripts/register_account.py \
  --brokerage-code IBKR \
  --external-id U100 \
  --account-type Individual \
  --base-currency USD \
  --display-name "Main account"
```

The command uses `DATABASE_URL` by default. Pass `--database-url` to override it for one run. If a required option is omitted in an interactive terminal, the command prompts for it; in non-interactive use, missing required options fail before any database call.

### Dry-running a Flex XML file

Before loading manual Flex XML into the database, inspect a file locally:

```bash
python scripts/ingest_flex_file.py dry-run scratch/Flex.xml \
  --account-external-id U17072019 \
  --start-date 2025-01-01 \
  --end-date 2025-04-30
```

The dry run scans one Flex XML file for supported records and performs no database writes. A file can contain cash transactions, daily NAV snapshots, or both. Current cash-transaction support is limited to `Deposits/Withdrawals`; other `CashTransaction` types are counted as unsupported and skipped for now.

### Loading a Flex XML file

After reviewing a dry run and registering the accounts found in the file, load supported records into PostgreSQL:

```bash
python scripts/ingest_flex_file.py load scratch/Flex.xml \
  --brokerage-code IBKR \
  --account-external-id U17072019 \
  --start-date 2025-01-01 \
  --end-date 2025-04-30
```

The load command uses `DATABASE_URL` by default. Pass `--database-url` to override it for one run. One load command creates one ingestion run for the whole file, bulk-loads supported cash-flow and daily NAV records, and prints privacy-safe inserted/duplicate/skipped/conflict counts. Duplicate records are treated as idempotent re-ingestion; unknown accounts, inactive accounts, and conflicts mark the ingestion run `partially_succeeded`.

Both dry-run and load are account-scoped. The command only maps supported records whose Flex `accountId` matches `--account-external-id`; supported records for other accounts are counted and reported in the output summary but are not written. Load mode also records the selected account on the ingestion run for auditability.

## 📊 Database Migrations

Database changes are managed with [Sqitch](https://sqitch.org/) against PostgreSQL. Migration scripts live under `migrations/`, with project configuration in [`sqitch.conf`](sqitch.conf).

The current example migration creates a simple `example.books` table, keeping example/demo objects out of the default `public` schema:

```text
migrations/
  deploy/create_books.sql
  revert/create_books.sql
  verify/create_books.sql
  sqitch.plan
```

### Sqitch availability

The devcontainer installs Sqitch and its PostgreSQL driver automatically. In a non-devcontainer environment, install the same packages before running migrations:

```bash
sudo apt-get update
sudo apt-get install -y sqitch libdbd-pg-perl postgresql-client
sqitch --version
```

### Configure the database URL

Keep connection strings out of Git. Add your Neon connection string to the ignored local `.env` file (see the [`.env` reference](#env--local-configuration) in the Development Environment section for the full template).

Load it from the repository root without printing the secret, then convert the PostgreSQL URL to Sqitch's `db:pg:` target URI:

```bash
export DATABASE_URL="$(grep -E '^DATABASE_URL=' .env | tail -n 1 | cut -d= -f2-)"
export SQITCH_TARGET="db:pg:${DATABASE_URL#postgresql:}"
```

### Run migrations

Check the current database state, deploy pending changes, and run Sqitch verification:

```bash
sqitch status "$SQITCH_TARGET"
sqitch deploy "$SQITCH_TARGET"
sqitch verify "$SQITCH_TARGET"
```

Confirm the example table exists:

```bash
psql "$DATABASE_URL" -c "\d example.books"
```

### Roll back while developing

Sqitch reverts back to a target change, not a Git-style `HEAD` reference. For the current single example migration, revert back to the empty baseline:

```bash
sqitch revert "$SQITCH_TARGET" --to-change @ROOT
```

When the plan has multiple migrations, revert only the latest migration by targeting the previous deployed change:

```bash
sqitch revert "$SQITCH_TARGET" --to-change previous_change_name
```

Then deploy again when ready:

```bash
sqitch deploy "$SQITCH_TARGET"
sqitch verify "$SQITCH_TARGET"
```

### Add future migrations

Create a new change with:

```bash
sqitch add change_name -n 'Describe the database change'
```

Sqitch creates matching files under `migrations/deploy/`, `migrations/revert/`, and `migrations/verify/`. Fill in all three files so every migration can be deployed, rolled back, and verified.

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
