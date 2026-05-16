# User Guides

These guides cover the user-facing SuperFolio capabilities that are implemented today. They focus on command-line workflows, database setup, and the manual GitHub Actions ingestion workflow.

## Setup

| Guide | Use when |
| --- | --- |
| [Environment and database setup](environment-and-database-setup.md) | You are preparing Python dependencies, local environment variables, PostgreSQL, or Sqitch migrations. |

## Accounts and manual ingestion

| Guide | Use when |
| --- | --- |
| [Register a brokerage account](register-brokerage-account.md) | You need to register an account before loading Flex XML or assigning automation connections. |
| [Dry-run a Flex XML file](manual-flex-xml-dry-run.md) | You want to inspect supported records in a local Flex XML file without database writes. |
| [Load a Flex XML file](manual-flex-xml-load.md) | You want to persist supported Flex XML records into PostgreSQL. |

## TWR reporting

| Guide | Use when |
| --- | --- |
| [Calculate TWR from local XML](standalone-twr-from-local-xml.md) | You want a one-account TWR result from local Flex XML without querying PostgreSQL. |
| [Calculate account TWR from the database](account-twr-from-database.md) | You want one registered account's TWR from normalized database facts. |
| [Manage portfolios](portfolio-management.md) | You want to create portfolios, list them, show members, or attach accounts. |
| [Manage transfer bridges](transfer-bridges.md) | You need to model money temporarily outside account NAV during an internal transfer. |
| [Calculate portfolio TWR from the database](portfolio-twr-from-database.md) | You want consolidated portfolio TWR across member accounts. |

## Automated ingestion

| Guide | Use when |
| --- | --- |
| [Set up integration connections](integration-connection-setup.md) | You need encrypted IBKR Flex Web Service credentials, feeds, and account assignments. |
| [Run automated ingestion](automated-ingestion-runs.md) | You want to run the local automation CLI or the manual GitHub Actions workflow. |
| [Debug automated ingestion locally](local-automation-debugging.md) | You need to save fetched Flex XML locally for troubleshooting. |

## Privacy notes

Raw Flex XML, generated CSVs containing NAV values, account identifiers, connection strings, and credential values are private. Keep local broker files under `scratch/` or another ignored directory, and use synthetic examples in documentation and issue discussions.
