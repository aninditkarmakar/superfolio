# Account Registration CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Python CLI for registering one account at a time through the shared `portfolio_engine.database` adapter.

**Architecture:** Put testable command behavior in `portfolio_engine.account_cli` and keep `scripts/register_account.py` as a thin executable wrapper, matching the existing `scripts/calculate_twr.py` root-path pattern. The command resolves CLI flags, prompts for missing values when stdin is interactive, validates required fields, calls `connect_database(...).register_account(...)`, and prints concise success or error output.

**Tech Stack:** Python 3.12 standard library (`argparse`, `dataclasses`, `io`, `sys`, `typing`, `unittest`) plus the existing `portfolio_engine.database` adapter.

---

## File structure

- Create: `portfolio_engine/account_cli.py`  
  Owns argument parsing, prompting, validation, adapter injection, output formatting, and return-code behavior.
- Create: `scripts/register_account.py`  
  Executable wrapper that adds the repo root to `sys.path` and delegates to `portfolio_engine.account_cli.main`.
- Create: `tests/test_account_cli.py`  
  Unit tests using fake adapters and in-memory streams. These tests must not open a real database connection.
- Modify: `README.md`  
  Documents the new registration CLI and required options.

## Assumptions locked by this block

- The CLI registers exactly one account per invocation.
- Required fields are `brokerage_code`, `external_id`, `account_type`, and `base_currency`.
- Optional `display_name` is prompted in interactive mode; an empty answer means `None`.
- `--database-url` is passed through to `connect_database(...)`; if omitted, the adapter uses `DATABASE_URL`.
- Required values are stripped before validation and before building `AccountRegistration`.
- The CLI does not uppercase or otherwise normalize business values beyond trimming. PostgreSQL remains the normalization authority.
- Non-interactive mode fails before opening a database connection when any required field is missing or blank.
- Database and adapter exceptions are printed as `Error: <message>` to stderr and return exit code `1`.

### Task 1: Add testable argument resolution and prompting

**Files:**
- Create: `portfolio_engine/account_cli.py`
- Create: `tests/test_account_cli.py`

- [ ] **Step 1: Write failing tests for interactive and non-interactive field resolution**

Create `tests/test_account_cli.py`:

```python
from __future__ import annotations

import io
import unittest

from portfolio_engine.account_cli import AccountCliError, resolve_registration


class AccountCliResolutionTests(unittest.TestCase):
    def test_all_parameters_supplied_resolve_without_prompting(self) -> None:
        registration = resolve_registration(
            brokerage_code=" IBKR ",
            external_id=" U100 ",
            account_type=" Individual ",
            base_currency=" USD ",
            display_name=" Main account ",
            stdin=io.StringIO("unused\n"),
            stdout=io.StringIO(),
            interactive=True,
        )

        self.assertEqual(registration.brokerage_code, "IBKR")
        self.assertEqual(registration.external_id, "U100")
        self.assertEqual(registration.account_type, "Individual")
        self.assertEqual(registration.base_currency, "USD")
        self.assertEqual(registration.display_name, "Main account")

    def test_missing_required_parameter_prompts_when_interactive(self) -> None:
        stdout = io.StringIO()

        registration = resolve_registration(
            brokerage_code="IBKR",
            external_id=None,
            account_type="Individual",
            base_currency="USD",
            display_name="Main account",
            stdin=io.StringIO("U100\n"),
            stdout=stdout,
            interactive=True,
        )

        self.assertEqual(registration.external_id, "U100")
        self.assertIn("External ID", stdout.getvalue())

    def test_missing_display_name_prompts_and_empty_answer_becomes_none(self) -> None:
        stdout = io.StringIO()

        registration = resolve_registration(
            brokerage_code="IBKR",
            external_id="U100",
            account_type="Individual",
            base_currency="USD",
            display_name=None,
            stdin=io.StringIO("\n"),
            stdout=stdout,
            interactive=True,
        )

        self.assertIsNone(registration.display_name)
        self.assertIn("Display name", stdout.getvalue())

    def test_blank_required_prompt_response_reprompts_until_non_blank(self) -> None:
        stdout = io.StringIO()

        registration = resolve_registration(
            brokerage_code="IBKR",
            external_id=None,
            account_type="Individual",
            base_currency="USD",
            display_name=None,
            stdin=io.StringIO("   \nU100\n\n"),
            stdout=stdout,
            interactive=True,
        )

        self.assertEqual(registration.external_id, "U100")
        self.assertIn("value is required", stdout.getvalue())

    def test_missing_required_parameters_fail_when_non_interactive(self) -> None:
        with self.assertRaisesRegex(
            AccountCliError,
            "Missing required option\\(s\\): --external-id, --base-currency",
        ):
            resolve_registration(
                brokerage_code="IBKR",
                external_id=None,
                account_type="Individual",
                base_currency=" ",
                display_name=None,
                stdin=io.StringIO(""),
                stdout=io.StringIO(),
                interactive=False,
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m unittest tests.test_account_cli -v
```

Expected: FAIL with `ModuleNotFoundError` or import errors because `portfolio_engine.account_cli` does not exist.

- [ ] **Step 3: Implement minimal resolution and prompting logic**

Create `portfolio_engine/account_cli.py`:

```python
"""Command-line helpers for registering brokerage accounts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TextIO

from portfolio_engine.database import AccountRegistration


class AccountCliError(RuntimeError):
    """Raised when account CLI input is missing or invalid."""


@dataclass(frozen=True)
class FieldSpec:
    name: str
    flag: str
    prompt: str
    required: bool


FIELD_SPECS = (
    FieldSpec("brokerage_code", "--brokerage-code", "Brokerage code", True),
    FieldSpec("external_id", "--external-id", "External ID", True),
    FieldSpec("account_type", "--account-type", "Account type", True),
    FieldSpec("base_currency", "--base-currency", "Base currency", True),
    FieldSpec("display_name", "--display-name", "Display name", False),
)


def resolve_registration(
    *,
    brokerage_code: str | None,
    external_id: str | None,
    account_type: str | None,
    base_currency: str | None,
    display_name: str | None,
    stdin: TextIO,
    stdout: TextIO,
    interactive: bool,
) -> AccountRegistration:
    values = {
        "brokerage_code": _clean_required_candidate(brokerage_code),
        "external_id": _clean_required_candidate(external_id),
        "account_type": _clean_required_candidate(account_type),
        "base_currency": _clean_required_candidate(base_currency),
        "display_name": _clean_optional_candidate(display_name),
    }

    missing_required = [
        spec.flag
        for spec in FIELD_SPECS
        if spec.required and values[spec.name] is None
    ]
    if missing_required and not interactive:
        joined = ", ".join(missing_required)
        raise AccountCliError(f"Missing required option(s): {joined}")

    if interactive:
        for spec in FIELD_SPECS:
            if values[spec.name] is not None:
                continue
            if spec.required:
                values[spec.name] = _prompt_required(spec.prompt, stdin, stdout)
            else:
                values[spec.name] = _prompt_optional(spec.prompt, stdin, stdout)

    return AccountRegistration(
        brokerage_code=_required_value(values["brokerage_code"], "--brokerage-code"),
        external_id=_required_value(values["external_id"], "--external-id"),
        account_type=_required_value(values["account_type"], "--account-type"),
        base_currency=_required_value(values["base_currency"], "--base-currency"),
        display_name=values["display_name"],
    )


def _clean_required_candidate(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _clean_optional_candidate(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _prompt_required(prompt: str, stdin: TextIO, stdout: TextIO) -> str:
    while True:
        stdout.write(f"{prompt}: ")
        stdout.flush()
        value = stdin.readline()
        if value == "":
            raise AccountCliError(f"{prompt} is required.")
        stripped = value.strip()
        if stripped:
            return stripped
        stdout.write(f"{prompt} value is required.\n")


def _prompt_optional(prompt: str, stdin: TextIO, stdout: TextIO) -> str | None:
    stdout.write(f"{prompt} (optional): ")
    stdout.flush()
    value = stdin.readline()
    if value == "":
        return None
    stripped = value.strip()
    return stripped or None


def _required_value(value: str | None, flag: str) -> str:
    if value is None:
        raise AccountCliError(f"Missing required option: {flag}")
    return value
```

- [ ] **Step 4: Run resolution tests**

Run:

```bash
python -m unittest tests.test_account_cli -v
```

Expected: PASS for the `AccountCliResolutionTests` tests.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add portfolio_engine/account_cli.py tests/test_account_cli.py
git commit -m "feat: add account CLI input resolution" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Add command execution over the database adapter

**Files:**
- Modify: `portfolio_engine/account_cli.py`
- Modify: `tests/test_account_cli.py`

- [ ] **Step 1: Write failing command execution tests**

Append to `tests/test_account_cli.py` before the `if __name__ == "__main__"` block:

```python
from portfolio_engine.database import AccountRegistration


class FakeDatabase:
    def __init__(self, account_id: str = "account-uuid", error: Exception | None = None) -> None:
        self.account_id = account_id
        self.error = error
        self.registrations: list[AccountRegistration] = []
        self.close_count = 0

    def __enter__(self) -> "FakeDatabase":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self.close_count += 1

    def register_account(self, registration: AccountRegistration) -> str:
        if self.error is not None:
            raise self.error
        self.registrations.append(registration)
        return self.account_id


class FakeDatabaseFactory:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database
        self.database_urls: list[str | None] = []

    def __call__(self, database_url: str | None = None) -> FakeDatabase:
        self.database_urls.append(database_url)
        return self.database


class AccountCliRunTests(unittest.TestCase):
    def test_run_registers_account_and_prints_success(self) -> None:
        database = FakeDatabase()
        factory = FakeDatabaseFactory(database)
        stdout = io.StringIO()
        stderr = io.StringIO()

        from portfolio_engine.account_cli import run

        exit_code = run(
            [
                "--brokerage-code",
                "IBKR",
                "--external-id",
                "U100",
                "--account-type",
                "Individual",
                "--base-currency",
                "USD",
                "--display-name",
                "Main account",
                "--database-url",
                "postgresql://example",
            ],
            adapter_factory=factory,
            stdin=io.StringIO(""),
            stdout=stdout,
            stderr=stderr,
            interactive=False,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(factory.database_urls, ["postgresql://example"])
        self.assertEqual(
            database.registrations,
            [
                AccountRegistration(
                    brokerage_code="IBKR",
                    external_id="U100",
                    account_type="Individual",
                    base_currency="USD",
                    display_name="Main account",
                )
            ],
        )
        self.assertEqual(database.close_count, 1)
        self.assertIn("Registered account: account-uuid", stdout.getvalue())
        self.assertIn("External ID: U100", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_run_fails_before_database_call_when_required_flags_missing(self) -> None:
        database = FakeDatabase()
        factory = FakeDatabaseFactory(database)
        stderr = io.StringIO()

        from portfolio_engine.account_cli import run

        exit_code = run(
            ["--brokerage-code", "IBKR", "--account-type", "Individual"],
            adapter_factory=factory,
            stdin=io.StringIO(""),
            stdout=io.StringIO(),
            stderr=stderr,
            interactive=False,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(factory.database_urls, [])
        self.assertIn("Error: Missing required option(s): --external-id, --base-currency", stderr.getvalue())

    def test_run_prints_database_error_and_returns_nonzero(self) -> None:
        database = FakeDatabase(error=RuntimeError("unknown brokerage code"))
        factory = FakeDatabaseFactory(database)
        stderr = io.StringIO()

        from portfolio_engine.account_cli import run

        exit_code = run(
            [
                "--brokerage-code",
                "UNKNOWN",
                "--external-id",
                "U100",
                "--account-type",
                "Individual",
                "--base-currency",
                "USD",
            ],
            adapter_factory=factory,
            stdin=io.StringIO(""),
            stdout=io.StringIO(),
            stderr=stderr,
            interactive=False,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: unknown brokerage code", stderr.getvalue())
```

- [ ] **Step 2: Run command execution tests to verify they fail**

Run:

```bash
python -m unittest tests.test_account_cli.AccountCliRunTests -v
```

Expected: FAIL with import or attribute errors because `run` does not exist.

- [ ] **Step 3: Implement argument parsing and `run(...)`**

Replace `portfolio_engine/account_cli.py` with this complete implementation:

```python
"""Command-line helpers for registering brokerage accounts."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Callable, Protocol, TextIO

from portfolio_engine.database import AccountRegistration, SuperFolioDatabase, connect_database


class AccountCliError(RuntimeError):
    """Raised when account CLI input is missing or invalid."""


class AccountDatabase(Protocol):
    def __enter__(self) -> "AccountDatabase": ...
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...
    def register_account(self, registration: AccountRegistration) -> str: ...


AdapterFactory = Callable[[str | None], AccountDatabase]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    flag: str
    prompt: str
    required: bool


FIELD_SPECS = (
    FieldSpec("brokerage_code", "--brokerage-code", "Brokerage code", True),
    FieldSpec("external_id", "--external-id", "External ID", True),
    FieldSpec("account_type", "--account-type", "Account type", True),
    FieldSpec("base_currency", "--base-currency", "Base currency", True),
    FieldSpec("display_name", "--display-name", "Display name", False),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register a brokerage account for ingestion.")
    parser.add_argument("--brokerage-code", help="Brokerage code, for example IBKR.")
    parser.add_argument("--external-id", help="Brokerage account identifier, for example U100.")
    parser.add_argument("--account-type", help="Account type label, for example Individual.")
    parser.add_argument("--base-currency", help="Account base currency, for example USD.")
    parser.add_argument("--display-name", help="Optional friendly account display name.")
    parser.add_argument(
        "--database-url",
        help="Optional PostgreSQL connection URL. Defaults to DATABASE_URL via the DB adapter.",
    )
    return parser


def run(
    argv: list[str] | None = None,
    *,
    adapter_factory: AdapterFactory = connect_database,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    interactive: bool | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    is_interactive = stdin.isatty() if interactive is None else interactive

    try:
        registration = resolve_registration(
            brokerage_code=args.brokerage_code,
            external_id=args.external_id,
            account_type=args.account_type,
            base_currency=args.base_currency,
            display_name=args.display_name,
            stdin=stdin,
            stdout=stdout,
            interactive=is_interactive,
        )
        with adapter_factory(args.database_url) as database:
            account_id = database.register_account(registration)
    except Exception as error:
        stderr.write(f"Error: {error}\n")
        return 1

    _print_success(account_id, registration, stdout)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(argv)


def resolve_registration(
    *,
    brokerage_code: str | None,
    external_id: str | None,
    account_type: str | None,
    base_currency: str | None,
    display_name: str | None,
    stdin: TextIO,
    stdout: TextIO,
    interactive: bool,
) -> AccountRegistration:
    values = {
        "brokerage_code": _clean_required_candidate(brokerage_code),
        "external_id": _clean_required_candidate(external_id),
        "account_type": _clean_required_candidate(account_type),
        "base_currency": _clean_required_candidate(base_currency),
        "display_name": _clean_optional_candidate(display_name),
    }

    missing_required = [
        spec.flag
        for spec in FIELD_SPECS
        if spec.required and values[spec.name] is None
    ]
    if missing_required and not interactive:
        joined = ", ".join(missing_required)
        raise AccountCliError(f"Missing required option(s): {joined}")

    if interactive:
        for spec in FIELD_SPECS:
            if values[spec.name] is not None:
                continue
            if spec.required:
                values[spec.name] = _prompt_required(spec.prompt, stdin, stdout)
            else:
                values[spec.name] = _prompt_optional(spec.prompt, stdin, stdout)

    return AccountRegistration(
        brokerage_code=_required_value(values["brokerage_code"], "--brokerage-code"),
        external_id=_required_value(values["external_id"], "--external-id"),
        account_type=_required_value(values["account_type"], "--account-type"),
        base_currency=_required_value(values["base_currency"], "--base-currency"),
        display_name=values["display_name"],
    )


def _clean_required_candidate(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _clean_optional_candidate(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _prompt_required(prompt: str, stdin: TextIO, stdout: TextIO) -> str:
    while True:
        stdout.write(f"{prompt}: ")
        stdout.flush()
        value = stdin.readline()
        if value == "":
            raise AccountCliError(f"{prompt} is required.")
        stripped = value.strip()
        if stripped:
            return stripped
        stdout.write(f"{prompt} value is required.\n")


def _prompt_optional(prompt: str, stdin: TextIO, stdout: TextIO) -> str | None:
    stdout.write(f"{prompt} (optional): ")
    stdout.flush()
    value = stdin.readline()
    if value == "":
        return None
    stripped = value.strip()
    return stripped or None


def _required_value(value: str | None, flag: str) -> str:
    if value is None:
        raise AccountCliError(f"Missing required option: {flag}")
    return value


def _print_success(account_id: str, registration: AccountRegistration, stdout: TextIO) -> None:
    stdout.write(f"Registered account: {account_id}\n")
    stdout.write(f"Brokerage: {registration.brokerage_code}\n")
    stdout.write(f"External ID: {registration.external_id}\n")
    stdout.write(f"Account type: {registration.account_type}\n")
    stdout.write(f"Base currency: {registration.base_currency}\n")
    stdout.write(f"Display name: {registration.display_name or '(none)'}\n")
```

- [ ] **Step 4: Run account CLI tests**

Run:

```bash
python -m unittest tests.test_account_cli -v
```

Expected: PASS for resolution and run tests.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add portfolio_engine/account_cli.py tests/test_account_cli.py
git commit -m "feat: add account registration command runner" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Add executable script wrapper

**Files:**
- Create: `scripts/register_account.py`
- Modify: `tests/test_account_cli.py`

- [ ] **Step 1: Write failing wrapper smoke test**

Append inside `AccountCliRunTests` in `tests/test_account_cli.py`:

```python
    def test_script_wrapper_imports_main(self) -> None:
        import scripts.register_account as register_account_script

        self.assertIs(register_account_script.main.__module__, "portfolio_engine.account_cli")
```

- [ ] **Step 2: Run wrapper smoke test to verify it fails**

Run:

```bash
python -m unittest tests.test_account_cli.AccountCliRunTests.test_script_wrapper_imports_main -v
```

Expected: FAIL with `ModuleNotFoundError` because `scripts/register_account.py` does not exist.

- [ ] **Step 3: Implement executable wrapper**

Create `scripts/register_account.py`:

```python
#!/usr/bin/env python3
"""CLI for registering a brokerage account before ingestion."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from portfolio_engine.account_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run account CLI tests**

Run:

```bash
python -m unittest tests.test_account_cli -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add scripts/register_account.py tests/test_account_cli.py
git commit -m "feat: add account registration script" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Document usage and run final verification

**Files:**
- Modify: `README.md`
- Test: `tests/test_account_cli.py`

- [ ] **Step 1: Add README documentation**

In `README.md`, add this section after the `.env — local configuration` section:

```markdown
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
```

- [ ] **Step 2: Run final verification**

Run:

```bash
python -m unittest tests.test_account_cli tests.test_database_adapter tests.test_flex_ingestion_mappers -v
python -m compileall portfolio_engine scripts tests
```

Expected: all tests pass and compileall succeeds.

- [ ] **Step 3: Commit Task 4**

Run:

```bash
git add README.md
git commit -m "docs: document account registration CLI" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Self-review notes

- Spec coverage: The plan covers every in-scope spec item: all `register_account(...)` inputs, interactive prompts, non-interactive missing-field failures, adapter reuse, success output, error output, and fake-adapter tests.
- Out-of-scope check: The plan does not add bulk account import, update/deactivate commands, direct `psql`, Flex XML ingestion, dry-run/load mode, or TWR behavior.
- Placeholder scan: The plan contains no deferred implementation placeholders.
- Type consistency: `AccountCliError`, `resolve_registration`, `run`, `main`, `AccountRegistration`, and fake adapter method names are consistent across tests and implementation steps.
