# Environment and Database Setup

Use this guide before running database-backed workflows: account registration, manual file loading, portfolio management, database TWR, and automated ingestion.

## Prerequisites

The dev container installs the expected toolchain:

| Tool | Source |
| --- | --- |
| Python 3.12 | `.devcontainer/devcontainer.json` Python feature |
| Python packages | `.devcontainer/post-create.sh` runs `python -m pip install -r requirements.txt` |
| `sqitch` | `.devcontainer/Dockerfile` |
| `libdbd-pg-perl` | `.devcontainer/Dockerfile`, required for Sqitch PostgreSQL connections |
| `postgresql-client` | `.devcontainer/Dockerfile`, provides `psql` |

Outside the dev container, install the same pieces manually:

```bash
sudo apt-get update
sudo apt-get install -y sqitch libdbd-pg-perl postgresql-client
python -m pip install -r requirements.txt
```

`requirements.txt` includes the PostgreSQL adapter, YAML support, Fernet encryption, and HTTP client dependencies used by database-backed and automation workflows. The standalone local XML TWR engine uses only the Python standard library.

## Configure local environment variables

Copy the checked-in template and fill in local values:

```bash
cp .env.example .env
```

| Variable | Required by | Purpose |
| --- | --- | --- |
| `GITHUB_NAME` | Dev container post-create script | Configures `git config --global user.name`. |
| `GITHUB_EMAIL` | Dev container post-create script | Configures `git config --global user.email`. |
| `DATABASE_URL` | Sqitch and database-backed CLIs | PostgreSQL connection string. |
| `SUPERFOLIO_CREDENTIAL_MASTER_KEY` | Automated ingestion | Fernet key used to encrypt and decrypt stored broker credentials. |

The `.env` file is ignored by Git. Do not commit it, print it in shared logs, or paste connection strings into docs.

Generate the automation master key when you need automated ingestion:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store that value locally as `SUPERFOLIO_CREDENTIAL_MASTER_KEY` and as a GitHub Actions repository secret if you will run the workflow.

## Deploy database migrations

Load `DATABASE_URL` from `.env` without printing it, then create the Sqitch target URI:

```bash
export DATABASE_URL="$(grep -E '^DATABASE_URL=' .env | tail -n 1 | cut -d= -f2-)"
export SQITCH_TARGET="db:pg:${DATABASE_URL#postgresql:}"
```

Deploy and verify all pending migrations:

```bash
sqitch status "$SQITCH_TARGET"
sqitch deploy "$SQITCH_TARGET"
sqitch verify "$SQITCH_TARGET"
```

Inspect deployed tables when needed:

```bash
psql "$DATABASE_URL" -c "\dt public.*"
```

## Migration order

The current Sqitch plan includes:

| Change | Purpose |
| --- | --- |
| `create_books` | Example placeholder migration. |
| `create_mvp_schema` | Brokerages, accounts, ingestion runs, source records, cash flows, and daily NAV snapshots. |
| `create_portfolio_layer` | Portfolios, portfolio memberships, and transfer bridges. |
| `create_automation_layer` | Automation jobs, connection credentials, feeds, and account assignments. |

## Rollback while developing

Revert all migrations:

```bash
sqitch revert "$SQITCH_TARGET" --to-change @ROOT
```

Revert to a specific prior change, then redeploy:

```bash
sqitch revert "$SQITCH_TARGET" --to-change create_portfolio_layer
sqitch deploy "$SQITCH_TARGET"
sqitch verify "$SQITCH_TARGET"
```

## First-run order

1. Copy `.env.example` to `.env` and set `DATABASE_URL`.
2. Install dependencies, or rebuild/open the dev container.
3. Export `DATABASE_URL` and `SQITCH_TARGET`.
4. Run `sqitch deploy` and `sqitch verify`.
5. Register each brokerage account.
6. Dry-run local Flex XML files.
7. Load reviewed Flex XML files.
8. Calculate account or portfolio TWR.

## Common gotchas

- `SQITCH_TARGET` is not stored in `sqitch.conf`; derive it from `DATABASE_URL` each session.
- `libdbd-pg-perl` is required for Sqitch even when `psql` works.
- The dev container post-create script reads `.env` during container creation or rebuild.
- Portfolio accounts must use the same base currency as the portfolio reporting currency.
- The standalone XML TWR CLI does not query PostgreSQL.
