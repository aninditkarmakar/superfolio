# Devcontainer Required Tools Setup Design

## Problem

The repository now contains Python database code, a `requirements.txt` file, and Sqitch-managed PostgreSQL migrations, but the devcontainer setup does not fully install the tools needed for those workflows after a fresh rebuild.

## Goals

- Make database-backed Python code usable in the devcontainer by installing committed Python dependencies.
- Make Sqitch migration commands available without requiring manual package installation.
- Keep the change limited to repo-required setup. Do not add optional test tooling such as `pytest` because the current tests use `unittest`.
- Keep documentation aligned with the actual devcontainer behavior.

## Design

Install OS-level migration tooling at image build time in `.devcontainer/Dockerfile`:

- `postgresql-client`, already present, for `psql`.
- `sqitch`, required by `sqitch.conf` and `migrations/`.
- `libdbd-pg-perl`, required for Sqitch to talk to PostgreSQL.

Install Python dependencies at container post-create time in `.devcontainer/post-create.sh` with:

```bash
python -m pip install -r requirements.txt
```

This keeps Python dependencies tied to the committed manifest while avoiding a Docker image rebuild for ordinary Python dependency changes.

Update README/dev guidance that currently describes Sqitch and Python dependencies as manual or absent so future users and agents know the devcontainer provisions them.

## Validation

- Confirm configured tools are available: `sqitch --version`, `psql --version`, and importing `psycopg`.
- Run the standard-library test suite with `python -m unittest discover -s tests -v`.

## Out of Scope

- Adding pytest or other optional developer tools.
- Adding frontend/npm setup, because no frontend package manifest exists.
- Running live database migrations, because that requires user-provided `DATABASE_URL`.
