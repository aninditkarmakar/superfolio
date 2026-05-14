# Consolidated Portfolio Tracker

A portfolio data engine for tracking consolidated investment performance across multiple brokerage accounts and currencies.

## 🚀 Overview

SuperFolio solves the "history gap" problem by stitching together historical data from multiple brokerage accounts into account-level and portfolio-level Time-Weighted Return (TWR) curves.

### Key Features
* **Unified Portfolio View:** Groups registered brokerage accounts into logical portfolios.
* **Manual Flex XML Ingestion:** Previews and loads supported IBKR Flex XML records into PostgreSQL with account scoping and idempotent deduplication.
* **Multi-Currency Normalization:** Preserves source currency, base-currency value, and `fxRateToBase` from each supported Flex record so currency handling remains traceable.
* **Daily Valuation TWR:** Calculates account-level and portfolio-level performance while isolating investment returns from supported external cash flows.
* **Privacy-First Reporting Posture:** Favors percentages, relative performance, and redacted or synthetic examples in public documentation.

Planned features include automated IBKR Flex Web Service ingestion, a Next.js dashboard/API, public hosting, attribution, and trade-feed views.

## 🛠 Tech Stack

The current implementation is Python-first, with the TypeScript UI/API still planned.

| Layer | Technology | Status |
| :--- | :--- | :--- |
| **Data Engine** | Python 3.12 | ✅ Implemented |
| **Database** | PostgreSQL + Sqitch migrations | ✅ Implemented |
| **API** | Next.js Route Handlers | 🗓 Planned |
| **Frontend** | Next.js + Tremor.so | 🗓 Planned |
| **Automation** | GitHub Actions | 🗓 Planned |
| **Hosting** | Vercel | 🗓 Planned |

## 📂 Project Structure

```
portfolio_engine/        # Python parsing, ingestion, database, and TWR engine
  models.py              # CashFlow, NavSnapshot, TwrRow dataclasses
  flex_xml.py            # IBKR Flex XML parsers (CashTransaction, EquitySummaryByReportDateInBase)
  twr.py                 # Daily Valuation TWR math with configurable flow timing
  csv_export.py          # CSV writer for daily TWR output
  database.py            # PostgreSQL function-call adapter
  ingestion/             # Flex XML dry-run and database payload mappers

scripts/
  calculate_twr.py                       # End-to-end CLI: Flex XML -> TWR -> optional CSV export
  calculate_twr_from_db.py               # Database CLI: single-account PostgreSQL facts -> TWR -> optional CSV export
  calculate_portfolio_twr_from_db.py     # Database CLI: portfolio-level TWR across all member accounts
  manage_portfolio.py                    # Portfolio management CLI: create, attach-account, create-bridge
  register_account.py                    # Register a brokerage account before ingestion
  ingest_flex_file.py                    # Dry-run or load supported Flex XML records

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

Place local IBKR Flex XML exports in `scratch/` (git-ignored), then run:

```bash
python scripts/calculate_twr.py \
  --cash-flows scratch/Cash_Flows.xml \
  --daily-nav  scratch/Daily_NAV.xml \
  --start-date 2026-01-01 \
  --daily-output output/twr.csv
```

The script prints a summary to stdout and writes an optional daily CSV:

```
NAV snapshots: 83
Cash-flow records: 4
Return periods: 82
Date range: 2026-01-02 to 2026-04-25
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
| `portfolio_engine.db_twr` | Single-account database-backed TWR calculation |
| `portfolio_engine.portfolio_twr` | Portfolio-level TWR aggregation across multiple accounts with transfer bridge support |
| `portfolio_engine.portfolio_db_twr` | Database-backed portfolio TWR CLI/orchestrator: argument parsing, DB fetch orchestration, optional CSV output, and summary printing |
| `portfolio_engine.portfolio_cli` | CLI helpers for portfolio management commands |
| `portfolio_engine.account_cli` | CLI helpers for account registration workflows |
| `portfolio_engine.ingestion_cli` | CLI helpers for Flex XML dry-run and load workflows |

## 💻 Development Environment

This project uses **VS Code Dev Containers** for a reproducible local setup.

### `.devcontainer/devcontainer.json`
* **Base Image:** `mcr.microsoft.com/devcontainers/typescript-node:4-24-trixie` (Node.js/TypeScript host, extended via `.devcontainer/Dockerfile`)
* **Python Feature:** `ghcr.io/devcontainers/features/python:1` — Python 3.12 with pip and JupyterLab
* **Database Tools:** `postgresql-client`, `sqitch`, and `libdbd-pg-perl` are installed by `.devcontainer/Dockerfile` for PostgreSQL/Sqitch workflows.
* **Python Dependencies:** `.devcontainer/post-create.sh` installs `requirements.txt`, currently `psycopg[binary]` for database-backed CLI workflows.

The core TWR engine uses only the Python standard library. Database-backed commands additionally require the committed `requirements.txt` dependencies.

### `.env` — local configuration

Copy the checked-in `.env.example` template to `.env` at the repository root, then fill in local values. The `.env` file is git-ignored. The dev container's `post-create.sh` reads it on every container rebuild, so set it up once and it is applied automatically.

```bash
cp .env.example .env
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
  --account-external-id U100 \
  --start-date 2026-01-01 \
  --end-date 2026-04-30
```

The dry run scans one Flex XML file for supported records and performs no database writes. A file can contain cash transactions, daily NAV snapshots, or both. Current cash-transaction support is limited to `Deposits/Withdrawals`; other `CashTransaction` types are counted as unsupported and skipped for now.

### Loading a Flex XML file

After reviewing a dry run and registering the accounts found in the file, load supported records into PostgreSQL:

```bash
python scripts/ingest_flex_file.py load scratch/Flex.xml \
  --brokerage-code IBKR \
  --account-external-id U100 \
  --start-date 2026-01-01 \
  --end-date 2026-04-30
```

The load command uses `DATABASE_URL` by default. Pass `--database-url` to override it for one run. One load command creates one ingestion run for the whole file, bulk-loads supported cash-flow and daily NAV records, and prints privacy-safe inserted/duplicate/skipped/conflict counts. Duplicate records are treated as idempotent re-ingestion; unknown accounts, inactive accounts, and conflicts mark the ingestion run `partially_succeeded`.

Both dry-run and load are account-scoped. The command only maps supported records whose Flex `accountId` matches `--account-external-id`; supported records for other accounts are counted and reported in the output summary but are not written. Load mode also records the selected account on the ingestion run for auditability.

## 📊 Database Migrations

Database changes are managed with [Sqitch](https://sqitch.org/) against PostgreSQL. Migration scripts live under `migrations/`, with project configuration in [`sqitch.conf`](sqitch.conf).

The current migration plan includes an initial example migration plus the implemented portfolio schema:

```text
migrations/
  deploy/create_books.sql
  deploy/create_mvp_schema.sql
  deploy/create_portfolio_layer.sql
  revert/create_books.sql
  revert/create_mvp_schema.sql
  revert/create_portfolio_layer.sql
  verify/create_books.sql
  verify/create_mvp_schema.sql
  verify/create_portfolio_layer.sql
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

Keep connection strings out of Git. Add a local PostgreSQL connection string to the ignored `.env` file copied from `.env.example` (see the [`.env` reference](#env--local-configuration) in the Development Environment section for the full template).

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

Review the deployed objects with `psql` when needed:

```bash
psql "$DATABASE_URL" -c "\dt public.*"
```

### Roll back while developing

Sqitch reverts back to a target change, not a Git-style `HEAD` reference. To revert back to the empty baseline:

```bash
sqitch revert "$SQITCH_TARGET" --to-change @ROOT
```

To revert only the latest migration, target the previous deployed change:

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

## 📊 Implemented Database Model

The relational model separates raw broker-origin records from normalized portfolio facts:

* **Brokerages and accounts** — supported integrations, account metadata, base currency, and activity status.
* **Ingestion runs and source records** — audit each manual file load and deduplicate broker-origin records.
* **Cash flows and daily NAV snapshots** — normalized account-scoped facts used by TWR calculations.
* **Portfolios, portfolio accounts, and transfer bridges** — logical multi-account groupings and in-transit transfer adjustments.

See [`docs/database/schema.md`](docs/database/schema.md) and [`docs/database/functions.md`](docs/database/functions.md) for table relationships, constraints, and PostgreSQL function contracts.

## 📈 Roadmap

- [x] **PostgreSQL Schema + Manual Ingestion:** Persist supported Flex records to PostgreSQL with idempotent upserts.
- [x] **Portfolio Layer:** Group registered accounts and calculate portfolio-level TWR with transfer bridge support.
- [ ] **Next.js Dashboard:** Dense, scan-friendly chart UI displaying TWR curve and holding weightings.
- [ ] **GitHub Actions Automation:** Scheduled daily Flex XML fetch and TWR recalculation.
- [ ] **Alpha Attribution:** Decompose returns by sector and timing.
- [ ] **Public Trade Feed:** Recent executions and per-trade P&L (redacted to percentages).
- [ ] **Multi-Broker Integration:** Expand beyond IBKR using the established schema.
