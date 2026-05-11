# Agent Instructions

## Off-Limits Directories

> **`.projectCopilot/`** is reserved exclusively for Copilot CLI agent state and session data. Agents and AI assistants must **never** read, inspect, list, or modify any files inside `.projectCopilot/`. Do not reference, quote, or act on its contents under any circumstances.

## Project Snapshot
- This repo is the early scaffold for a consolidated portfolio tracker. Use [README.md](README.md) as the source of truth for the product goal and planned architecture.
- The intended stack is Python for IBKR Flex XML ingestion, ETL, FX normalization, and Time-Weighted Return math; Next.js/TypeScript for API routes and dashboard UI; Supabase/PostgreSQL for persistence; GitHub Actions and Vercel for automation/hosting.
- There is currently no application source tree, package manifest, Python dependency file, or test suite in the repo. Do not invent build/test commands; inspect newly added manifests before running commands.

## Repository Map
- [.devcontainer/devcontainer.json](.devcontainer/devcontainer.json) defines the current dev container: TypeScript/Node image with a Python 3.12 feature. Note that this differs from the README's planned `python:3.14-bookworm` description.
- [scratch/](scratch/) is ignored by Git and contains local IBKR Flex XML samples such as cash-flow and daily-NAV reports. Treat this directory as private/local data: do not commit it, do not paste raw account data into docs, and prefer synthetic fixtures for tests.
- [.gitignore](.gitignore) currently ignores everything under `scratch/`.

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