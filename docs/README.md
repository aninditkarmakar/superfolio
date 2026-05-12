# SuperFolio Documentation

This directory contains project documentation for the implemented SuperFolio data engine, manual ingestion workflows, and PostgreSQL database boundary.

## Start here

| Topic | File | Use when |
| --- | --- | --- |
| Architecture | [architecture.md](architecture.md) | You need the current system map and implemented/planned boundaries. |
| Manual Flex ingestion | [workflows/manual-flex-ingestion.md](workflows/manual-flex-ingestion.md) | You are registering accounts, previewing Flex XML, or loading supported records into PostgreSQL. |
| TWR calculation | [workflows/twr-calculation.md](workflows/twr-calculation.md) | You are calculating daily linked TWR from local Flex XML exports. |
| Database schema | [database/schema.md](database/schema.md) | You need table relationships, constraints, or the ingestion data model. |
| Database functions | [database/functions.md](database/functions.md) | You need PostgreSQL function contracts or bulk ingestion JSON shapes. |

## Source of truth

- `README.md` at the repository root describes the product goal, setup, and roadmap.
- `portfolio_engine/` contains the implemented Python parsing, ingestion, database adapter, and TWR code.
- `scripts/` contains the user-facing CLIs.
- `migrations/` contains the Sqitch-managed PostgreSQL schema and function contracts.
- `tests/` contains executable examples for the current behavior.

## Privacy notes

Do not commit raw IBKR Flex XML, account values, connection strings, or local files from `scratch/`. Documentation examples should use synthetic account IDs, synthetic dates, and placeholder values.
