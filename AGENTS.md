# Agent Instructions

## Off-Limits Directories

> **`.projectCopilot/`** is reserved exclusively for Copilot CLI agent state and session data. Agents and AI assistants must **never** read, inspect, list, or modify any files inside `.projectCopilot/`. Do not reference, quote, or act on its contents under any circumstances.

## Project Snapshot
- This repo is a consolidated portfolio tracker. Use [README.md](README.md) as the source of truth for the product goal, supported workflows, and planned roadmap.
- Current implementation is Python-first: IBKR Flex XML parsing, manual ingestion CLIs, PostgreSQL/Sqitch database boundaries, CSV export, and Time-Weighted Return math.
- Planned UI/API work is still future-facing: Next.js/TypeScript dashboard/API routes, GitHub Actions automation, and Vercel hosting are described in the roadmap but are not present as application code.

## Repository Map
- [portfolio_engine/](portfolio_engine/) contains the Python engine, Flex XML parsing, ingestion mappers, database adapter, and CLI support code.
- [scripts/](scripts/) contains user-facing CLIs for TWR calculation, account registration, and manual Flex XML dry-run/load workflows.
- [tests/](tests/) contains the current Python test suite.
- [migrations/](migrations/) and [sqitch.conf](sqitch.conf) define PostgreSQL schema changes managed by Sqitch. See [docs/er-diagram.md](docs/er-diagram.md) and [docs/database-functions.md](docs/database-functions.md) for database design and function contracts.
- [requirements.txt](requirements.txt) currently declares the PostgreSQL adapter dependency (`psycopg[binary]`).
- [.devcontainer/devcontainer.json](.devcontainer/devcontainer.json) defines the current dev container: TypeScript/Node base image extended by [.devcontainer/Dockerfile](.devcontainer/Dockerfile), with a Python 3.12 feature and `postgresql-client`.
- [scratch/](scratch/) is ignored by Git and contains local IBKR Flex XML samples such as cash-flow and daily-NAV reports. Treat this directory as private/local data: do not commit it, do not paste raw account data into docs, and prefer synthetic fixtures for tests.
- [.gitignore](.gitignore) currently ignores everything under `scratch/`.

## Commands And Tooling
- There is no `package.json` or frontend app yet; do not invent npm build, lint, or dev commands.
- Install Python database dependencies with `python -m pip install -r requirements.txt` when database-backed code needs to run.
- Run Python tests with `python -m pytest` when `pytest` is available in the environment. There is no committed Python dev-dependency manifest yet, so do not assume a fresh environment already has pytest.
- For database migrations, use Sqitch only after it is installed and `DATABASE_URL`/`SQITCH_TARGET` are configured as described in [README.md](README.md). Do not print database connection strings.

## Data And Finance Conventions
- Parse Flex XML with a structured XML parser, not ad hoc string splitting. Preserve IBKR identifiers and report dates during ingestion so repeated imports can be idempotent.
- Distinguish external cash flows from valuation changes. Cash deposits, withdrawals, cancellations, transfers, dividends, fees, and internal movement can affect TWR differently; add focused tests around each case.
- Normalize currencies explicitly. Flex records may include CAD and USD amounts plus `fxRateToBase`; keep the source currency, base-currency value, and FX rate traceable.
- For public dashboard work, preserve the privacy-first posture from the README: expose percentages, relative performance, and weightings rather than absolute account values unless the user explicitly asks otherwise.

## Development Guidance
- Keep the Python data engine separate from the TypeScript UI/API code when source directories are introduced.
- For database work, model accounts, transactions, cash flows, and daily snapshots as separate concepts; avoid collapsing raw broker events and derived portfolio metrics into one table.
- For UI work, build the usable dashboard view first rather than a marketing landing page. Financial dashboards should be dense, quiet, and scan-friendly.
- When adding tests, include small synthetic XML fixtures that cover the current sample shapes: `CashTransaction` records and `EquitySummaryByReportDateInBase` daily snapshots.

## Git And Branching
- Never automatically merge feature branches onto `main`. Always ask for the user's explicit approval before merging, even when work is complete and checks pass.
