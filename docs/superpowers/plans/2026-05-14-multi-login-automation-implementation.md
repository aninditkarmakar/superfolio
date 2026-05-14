# Multi-Login Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor automated ingestion so one portfolio or account-triggered run can process IBKR accounts assigned to multiple IBKR logins/connections.

**Architecture:** Add broker-agnostic integration connections, encrypted credential rows, feeds, and account assignments below the existing automation job layer. The orchestrator resolves accounts with a connection snapshot, groups execution by connection, runs all enabled feeds, and aggregates feed outcomes back to existing account-level child rows. Credentials are encrypted in Python with Fernet before persistence; GitHub Actions supplies only the master encryption key, not per-login IBKR token/query secrets.

**Tech Stack:** Python 3.12, `unittest`, PostgreSQL/Sqitch, `psycopg`, PyYAML, `cryptography.fernet.Fernet`, GitHub Actions.

**Execution constraints:**
- Any subagent-driven execution of this plan must use `claude-sonnet-4.6` or a higher-capability model. Do not use a lesser model for implementers or reviewers.
- Do not merge this branch back onto `dev`, `main`, or any other branch without the repository owner's explicit approval.
- Follow TDD for every code and behavior change: write failing tests first, run them to verify the expected failure, implement, rerun targeted tests, then commit.
- Keep full IBKR Flex Web Service HTTP fetch internals out of scope. The adapter may still raise `NotImplementedError` after validating connection/feed shape.

---

## File structure

### New files

- `portfolio_engine/automation/credentials.py` — Fernet key loading, `SecretValue`, encryption/decryption helpers, credential error types.
- `portfolio_engine/automation/connections.py` — connection/feed/account-assignment dataclasses and helper functions that are not database-specific.
- `portfolio_engine/automation/connection_cli.py` — Python CLI helpers for managing connections, credentials, feeds, and assignments.
- `scripts/manage_integration_connections.py` — user-facing script wrapper for the management CLI.
- `tests/test_automation_credentials.py` — encryption, redaction, key validation, and rotation tests.
- `tests/test_automation_connections_cli.py` — management CLI tests.

### Modified files

- `requirements.txt` — add `cryptography`.
- `migrations/deploy/create_automation_layer.sql` — add connection/feed/credential/assignment tables, child `connection_id`, and new/updated functions.
- `migrations/revert/create_automation_layer.sql` — drop new functions/tables in dependency-safe order.
- `migrations/verify/create_automation_layer.sql` — verify new tables, constraints, columns, and function signatures.
- `portfolio_engine/database.py` — add dataclasses and adapter methods for connection management and connection-aware automation target resolution.
- `portfolio_engine/automation/types.py` — add `SecretValue`, connection/feed contexts, feed result types, and update `BrokerAdapter`.
- `portfolio_engine/automation/adapters.py` — replace env-only preflight/fetch interface with connection/feed-aware methods.
- `portfolio_engine/automation/config.py` and `portfolio_engine/automation/integrations.yaml` — remove IBKR token/query env assumptions from static config.
- `portfolio_engine/automation/orchestrator.py` — group accounts by connection, handle missing assignments/credentials, run feeds, aggregate outcomes.
- `portfolio_engine/automation/summary.py` — add feed-result summaries and multi-feed aggregation support.
- `portfolio_engine/automation/sanitization.py` — redact new credential/query/master-key labels.
- `portfolio_engine/automation/cli.py` — keep trigger shape stable while using new orchestration behavior.
- `.github/workflows/manual-ingestion.yml` — use `SUPERFOLIO_CREDENTIAL_MASTER_KEY`; remove per-login IBKR token/query secrets.
- `tests/test_migrations.py`, `tests/test_database_adapter.py`, `tests/test_automation_config.py`, `tests/test_automation_orchestrator.py`, `tests/test_automation_summary.py`, `tests/test_automation_workflow.py` — update/add coverage.
- `docs/workflows/automated-ingestion.md`, `docs/database/schema.md`, `docs/database/functions.md`, `README.md` — document connection/feed setup and workflow changes.

---

### Task 1: Add cryptography dependency and credential helper

**Files:**
- Modify: `requirements.txt`
- Create: `portfolio_engine/automation/credentials.py`
- Create: `tests/test_automation_credentials.py`

- [ ] **Step 1: Write failing tests for Fernet key validation and redacted secrets**

Create `tests/test_automation_credentials.py`:

```python
from __future__ import annotations

import unittest
from cryptography.fernet import Fernet

from portfolio_engine.automation.credentials import (
    CredentialDecryptionError,
    CredentialMasterKeyError,
    SecretValue,
    decrypt_secret,
    encrypt_secret,
    load_master_key,
)


class SecretValueTests(unittest.TestCase):
    def test_secret_value_redacts_string_forms(self) -> None:
        secret = SecretValue("super-secret")

        self.assertEqual(str(secret), "<redacted>")
        self.assertEqual(repr(secret), "<redacted>")
        self.assertEqual(secret.reveal(), "super-secret")


class CredentialEncryptionTests(unittest.TestCase):
    def test_load_master_key_rejects_missing_value(self) -> None:
        with self.assertRaisesRegex(CredentialMasterKeyError, "missing"):
            load_master_key(None)

    def test_load_master_key_rejects_malformed_value(self) -> None:
        with self.assertRaisesRegex(CredentialMasterKeyError, "invalid"):
            load_master_key("not-a-fernet-key")

    def test_encrypt_decrypt_round_trip(self) -> None:
        key = load_master_key(Fernet.generate_key().decode("ascii"))

        ciphertext = encrypt_secret("ibkr-token", key)
        plaintext = decrypt_secret(ciphertext, key)

        self.assertNotIn(b"ibkr-token", ciphertext)
        self.assertEqual(plaintext.reveal(), "ibkr-token")

    def test_tampered_ciphertext_raises_sanitized_error(self) -> None:
        key = load_master_key(Fernet.generate_key().decode("ascii"))
        ciphertext = bytearray(encrypt_secret("ibkr-token", key))
        ciphertext[-3] = ord("A")

        with self.assertRaisesRegex(CredentialDecryptionError, "credential_decryption_failed"):
            decrypt_secret(bytes(ciphertext), key)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing credential tests**

Run:

```bash
python -m unittest tests.test_automation_credentials -v
```

Expected: import failure because `portfolio_engine.automation.credentials` does not exist.

- [ ] **Step 3: Add the dependency**

Modify `requirements.txt`:

```text
psycopg[binary]>=3.2,<4
PyYAML>=6.0,<7
cryptography>=42,<46
```

- [ ] **Step 4: Implement `credentials.py`**

Create `portfolio_engine/automation/credentials.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken


class CredentialMasterKeyError(RuntimeError):
    """Raised when the credential master key is missing or malformed."""


class CredentialDecryptionError(RuntimeError):
    """Raised when encrypted credential material cannot be authenticated."""


@dataclass(frozen=True)
class MasterKey:
    key_id: str
    fernet: Fernet


@dataclass(frozen=True)
class SecretValue:
    _value: str

    def reveal(self) -> str:
        return self._value

    def __str__(self) -> str:
        return "<redacted>"

    def __repr__(self) -> str:
        return "<redacted>"


def load_master_key(value: str | None, *, key_id: str = "v1") -> MasterKey:
    if value is None or value.strip() == "":
        raise CredentialMasterKeyError("missing credential master key")
    try:
        return MasterKey(key_id=key_id, fernet=Fernet(value.strip().encode("ascii")))
    except (ValueError, TypeError) as error:
        raise CredentialMasterKeyError("invalid credential master key") from error


def encrypt_secret(plaintext: str, master_key: MasterKey) -> bytes:
    return master_key.fernet.encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes, master_key: MasterKey) -> SecretValue:
    try:
        plaintext = master_key.fernet.decrypt(ciphertext).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as error:
        raise CredentialDecryptionError("credential_decryption_failed") from error
    return SecretValue(plaintext)
```

- [ ] **Step 5: Run credential tests**

Run:

```bash
python -m unittest tests.test_automation_credentials -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt portfolio_engine/automation/credentials.py tests/test_automation_credentials.py
git commit -m "feat: add encrypted automation credential helpers" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Add connection/feed/assignment schema

**Files:**
- Modify: `migrations/deploy/create_automation_layer.sql`
- Modify: `migrations/revert/create_automation_layer.sql`
- Modify: `migrations/verify/create_automation_layer.sql`
- Modify: `tests/test_migrations.py`

- [ ] **Step 1: Write failing migration contract tests**

Add tests to `tests/test_migrations.py`:

```python
class AutomationConnectionMigrationTests(unittest.TestCase):
    def test_automation_layer_creates_connection_tables(self) -> None:
        text = Path("migrations/deploy/create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE public.integration_connections", text)
        self.assertIn("CREATE TABLE public.integration_connection_credentials", text)
        self.assertIn("CREATE TABLE public.integration_feeds", text)
        self.assertIn("CREATE TABLE public.account_integration_assignments", text)
        self.assertIn("connection_id UUID REFERENCES public.integration_connections(id)", text)

    def test_automation_layer_enforces_connection_uniqueness(self) -> None:
        text = Path("migrations/deploy/create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("integration_connections_unique_name", text)
        self.assertIn("integration_connection_credentials_active_unique", text)
        self.assertIn("integration_feeds_unique_key", text)

    def test_revert_drops_connection_tables(self) -> None:
        text = Path("migrations/revert/create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("DROP TABLE public.account_integration_assignments", text)
        self.assertIn("DROP TABLE public.integration_connection_credentials", text)
        self.assertIn("DROP TABLE public.integration_feeds", text)
        self.assertIn("DROP TABLE public.integration_connections", text)

    def test_verify_checks_connection_tables(self) -> None:
        text = Path("migrations/verify/create_automation_layer.sql").read_text(encoding="utf-8")

        self.assertIn("public.integration_connections", text)
        self.assertIn("public.integration_connection_credentials", text)
        self.assertIn("public.integration_feeds", text)
        self.assertIn("public.account_integration_assignments", text)
```

- [ ] **Step 2: Run failing migration tests**

Run:

```bash
python -m unittest tests.test_migrations -v
```

Expected: new tests fail because connection tables are missing.

- [ ] **Step 3: Add deploy schema**

In `migrations/deploy/create_automation_layer.sql`, create tables before `automation_jobs` references them:

```sql
CREATE TABLE public.integration_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_key VARCHAR(100) NOT NULL,
    brokerage_id UUID NOT NULL REFERENCES public.brokerages(id),
    name VARCHAR(120) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT integration_connections_key_not_blank_check CHECK (btrim(integration_key) <> ''),
    CONSTRAINT integration_connections_name_not_blank_check CHECK (btrim(name) <> ''),
    CONSTRAINT integration_connections_unique_name UNIQUE (brokerage_id, integration_key, name)
);

CREATE TABLE public.integration_connection_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL REFERENCES public.integration_connections(id) ON DELETE CASCADE,
    credential_name VARCHAR(200) NOT NULL,
    ciphertext BYTEA NOT NULL,
    encryption_key_id VARCHAR(100) NOT NULL,
    encryption_version INTEGER NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    rotated_at TIMESTAMPTZ,
    CONSTRAINT integration_connection_credentials_name_not_blank_check CHECK (btrim(credential_name) <> ''),
    CONSTRAINT integration_connection_credentials_key_id_not_blank_check CHECK (btrim(encryption_key_id) <> ''),
    CONSTRAINT integration_connection_credentials_version_positive_check CHECK (encryption_version > 0)
);

CREATE UNIQUE INDEX integration_connection_credentials_active_unique
    ON public.integration_connection_credentials (connection_id, credential_name)
    WHERE is_active = true;

CREATE TABLE public.integration_feeds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL REFERENCES public.integration_connections(id) ON DELETE CASCADE,
    feed_key VARCHAR(100) NOT NULL,
    display_name VARCHAR(120),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT integration_feeds_key_not_blank_check CHECK (btrim(feed_key) <> ''),
    CONSTRAINT integration_feeds_key_no_colon_check CHECK (position(':' in feed_key) = 0),
    CONSTRAINT integration_feeds_unique_key UNIQUE (connection_id, feed_key)
);

CREATE TABLE public.account_integration_assignments (
    account_id UUID PRIMARY KEY REFERENCES public.accounts(id) ON DELETE CASCADE,
    connection_id UUID NOT NULL REFERENCES public.integration_connections(id),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Add nullable `connection_id` to `automation_job_accounts`:

```sql
connection_id UUID REFERENCES public.integration_connections(id),
```

- [ ] **Step 4: Update revert and verify**

In revert, drop new tables after automation tables/functions that reference them:

```sql
DROP TABLE public.account_integration_assignments;
DROP TABLE public.integration_connection_credentials;
DROP TABLE public.integration_feeds;
DROP TABLE public.integration_connections;
```

In verify, add error-raising checks:

```sql
SELECT 1 / (count(*) = 4)::int
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
      'integration_connections',
      'integration_connection_credentials',
      'integration_feeds',
      'account_integration_assignments'
  );
```

- [ ] **Step 5: Run migration tests**

Run:

```bash
python -m unittest tests.test_migrations -v
```

Expected: all migration tests pass.

- [ ] **Step 6: Commit**

```bash
git add migrations/deploy/create_automation_layer.sql migrations/revert/create_automation_layer.sql migrations/verify/create_automation_layer.sql tests/test_migrations.py
git commit -m "feat: add integration connection schema" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Add connection database functions and adapter methods

**Files:**
- Modify: `migrations/deploy/create_automation_layer.sql`
- Modify: `migrations/revert/create_automation_layer.sql`
- Modify: `migrations/verify/create_automation_layer.sql`
- Modify: `portfolio_engine/database.py`
- Modify: `tests/test_database_adapter.py`
- Modify: `tests/test_migrations.py`

- [ ] **Step 1: Write failing adapter tests**

Add tests to `tests/test_database_adapter.py` using the existing fake connection style:

```python
class IntegrationConnectionAdapterTests(unittest.TestCase):
    def test_create_integration_connection_calls_function(self) -> None:
        connection = FakeConnection(rows=[("connection-uuid",)])
        db = SuperFolioDatabase(connection)

        result = db.create_integration_connection(
            IntegrationConnectionCreate(
                integration_key="ibkr_flex_ws",
                brokerage_code="IBKR",
                name="IBKR Personal",
            )
        )

        self.assertEqual(result, "connection-uuid")
        self.assertIn("public.create_integration_connection", connection.statements[0][0])
        self.assertEqual(connection.statements[0][1], ("ibkr_flex_ws", "IBKR", "IBKR Personal"))

    def test_set_integration_credential_passes_ciphertext(self) -> None:
        connection = FakeConnection(rows=[("credential-uuid",)])
        db = SuperFolioDatabase(connection)

        result = db.set_integration_credential(
            IntegrationCredentialSet(
                connection_id="connection-uuid",
                credential_name="flex_token",
                ciphertext=b"ciphertext",
                encryption_key_id="v1",
                encryption_version=1,
            )
        )

        self.assertEqual(result, "credential-uuid")
        self.assertIn("public.set_integration_credential", connection.statements[0][0])
```

- [ ] **Step 2: Run failing adapter tests**

Run:

```bash
python -m unittest tests.test_database_adapter.IntegrationConnectionAdapterTests -v
```

Expected: import/name failures for new dataclasses and methods.

- [ ] **Step 3: Add database dataclasses**

In `portfolio_engine/database.py`, add:

```python
@dataclass(frozen=True)
class IntegrationConnectionCreate:
    integration_key: str
    brokerage_code: str
    name: str


@dataclass(frozen=True)
class IntegrationCredentialSet:
    connection_id: str
    credential_name: str
    ciphertext: bytes
    encryption_key_id: str
    encryption_version: int


@dataclass(frozen=True)
class IntegrationFeedCreate:
    connection_id: str
    feed_key: str
    display_name: str | None = None


@dataclass(frozen=True)
class AccountIntegrationAssignmentSet:
    brokerage_code: str
    account_external_id: str
    connection_id: str
```

- [ ] **Step 4: Add database adapter methods**

In `SuperFolioDatabase`, add:

```python
def create_integration_connection(self, request: IntegrationConnectionCreate) -> str:
    row = self._fetch_one(
        "SELECT public.create_integration_connection(%s, %s, %s)",
        (request.integration_key, request.brokerage_code, request.name),
    )
    return str(row[0])


def set_integration_credential(self, request: IntegrationCredentialSet) -> str:
    row = self._fetch_one(
        "SELECT public.set_integration_credential(%s, %s, %s, %s, %s)",
        (
            request.connection_id,
            request.credential_name,
            request.ciphertext,
            request.encryption_key_id,
            request.encryption_version,
        ),
    )
    return str(row[0])


def create_integration_feed(self, request: IntegrationFeedCreate) -> str:
    row = self._fetch_one(
        "SELECT public.create_integration_feed(%s, %s, %s)",
        (request.connection_id, request.feed_key, request.display_name),
    )
    return str(row[0])


def set_account_integration_assignment(self, request: AccountIntegrationAssignmentSet) -> str:
    row = self._fetch_one(
        "SELECT public.set_account_integration_assignment(%s, %s, %s)",
        (request.brokerage_code, request.account_external_id, request.connection_id),
    )
    return str(row[0])


def validate_account_integration_assignments(
    self,
    *,
    target_type: str,
    portfolio_name: str | None,
    brokerage_code: str,
    account_external_ids: list[str],
) -> list[str]:
    rows = self._fetch_all(
        "SELECT * FROM public.validate_account_integration_assignments(%s, %s, %s, %s)",
        (target_type, portfolio_name, brokerage_code, account_external_ids),
    )
    return [str(row[0]) for row in rows]
```

Add list methods using the same `_fetch_all` pattern:

```python
def list_integration_connections(self) -> list[IntegrationConnectionRecord]:
    rows = self._fetch_all(
        "SELECT * FROM public.list_integration_connections()",
        (),
    )
    return [_integration_connection_record_from_row(row) for row in rows]


def list_integration_feeds(self, connection_id: str) -> list[IntegrationFeedRecord]:
    rows = self._fetch_all(
        "SELECT * FROM public.list_integration_feeds(%s)",
        (connection_id,),
    )
    return [_integration_feed_record_from_row(row) for row in rows]
```

- [ ] **Step 5: Add PostgreSQL functions**

Add functions that:

- create a connection by resolving active brokerage code;
- rotate credentials by deactivating the old active credential in the same transaction;
- create feeds with normalized feed keys;
- assign accounts only when account brokerage matches connection brokerage;
- validate missing assignments for account lists or portfolios.

Use these function signatures:

```sql
CREATE FUNCTION public.create_integration_connection(
    p_integration_key TEXT,
    p_brokerage_code TEXT,
    p_name TEXT
) RETURNS UUID;

CREATE FUNCTION public.set_integration_credential(
    p_connection_id UUID,
    p_credential_name TEXT,
    p_ciphertext BYTEA,
    p_encryption_key_id TEXT,
    p_encryption_version INTEGER
) RETURNS UUID;

CREATE FUNCTION public.create_integration_feed(
    p_connection_id UUID,
    p_feed_key TEXT,
    p_display_name TEXT DEFAULT NULL
) RETURNS UUID;

CREATE FUNCTION public.set_account_integration_assignment(
    p_brokerage_code TEXT,
    p_account_external_id TEXT,
    p_connection_id UUID
) RETURNS UUID;

CREATE FUNCTION public.validate_account_integration_assignments(
    p_target_type TEXT,
    p_portfolio_name TEXT,
    p_brokerage_code TEXT,
    p_account_external_ids TEXT[]
) RETURNS TABLE(account_external_id TEXT);
```

- [ ] **Step 6: Run targeted tests**

Run:

```bash
python -m unittest tests.test_database_adapter tests.test_migrations -v
```

Expected: all targeted tests pass.

- [ ] **Step 7: Commit**

```bash
git add migrations/deploy/create_automation_layer.sql migrations/revert/create_automation_layer.sql migrations/verify/create_automation_layer.sql portfolio_engine/database.py tests/test_database_adapter.py tests/test_migrations.py
git commit -m "feat: add integration connection database functions" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Add connection management CLI

**Files:**
- Create: `portfolio_engine/automation/connection_cli.py`
- Create: `scripts/manage_integration_connections.py`
- Create: `tests/test_automation_connections_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_automation_connections_cli.py`:

```python
from __future__ import annotations

import unittest
from io import StringIO
from cryptography.fernet import Fernet

from portfolio_engine.automation.connection_cli import run


class ConnectionCliTests(unittest.TestCase):
    def test_create_connection_calls_database(self) -> None:
        calls = []

        class FakeDatabase:
            def create_integration_connection(self, request):
                calls.append(request)
                return "connection-uuid"

        stdout = StringIO()
        code = run(
            ["create", "--integration", "ibkr_flex_ws", "--brokerage-code", "IBKR", "--name", "IBKR Personal"],
            stdout=stdout,
            database_connector=lambda: FakeDatabase(),
            environ={"SUPERFOLIO_CREDENTIAL_MASTER_KEY": Fernet.generate_key().decode("ascii")},
        )

        self.assertEqual(code, 0)
        self.assertEqual(calls[0].name, "IBKR Personal")
        self.assertIn("connection-uuid", stdout.getvalue())

    def test_set_credential_encrypts_plaintext(self) -> None:
        captured = []

        class FakeDatabase:
            def set_integration_credential(self, request):
                captured.append(request)
                return "credential-uuid"

        code = run(
            [
                "set-credential",
                "--connection-id", "connection-uuid",
                "--credential-name", "flex_token",
                "--value", "plain-token",
            ],
            stdout=StringIO(),
            database_connector=lambda: FakeDatabase(),
            environ={"SUPERFOLIO_CREDENTIAL_MASTER_KEY": Fernet.generate_key().decode("ascii")},
        )

        self.assertEqual(code, 0)
        self.assertNotEqual(captured[0].ciphertext, b"plain-token")
        self.assertNotIn(b"plain-token", captured[0].ciphertext)
```

- [ ] **Step 2: Run failing CLI tests**

Run:

```bash
python -m unittest tests.test_automation_connections_cli -v
```

Expected: import failure because `connection_cli.py` does not exist.

- [ ] **Step 3: Implement CLI commands**

Implement commands:

```text
create
set-credential
add-feed
assign-account
assign-accounts
assign-portfolio
validate-assignments
list-connections
list-feeds
```

Each command returns `0` on success, writes non-secret identifiers/status to stdout, writes sanitized errors to stderr, and returns `1` on failure.

- [ ] **Step 4: Add script wrapper**

Create `scripts/manage_integration_connections.py`:

```python
#!/usr/bin/env python
from __future__ import annotations

import sys

from portfolio_engine.automation.connection_cli import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 5: Run CLI tests**

Run:

```bash
python -m unittest tests.test_automation_connections_cli -v
```

Expected: all CLI tests pass.

- [ ] **Step 6: Commit**

```bash
git add portfolio_engine/automation/connection_cli.py scripts/manage_integration_connections.py tests/test_automation_connections_cli.py
git commit -m "feat: add integration connection management CLI" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Update automation types and adapter protocol

**Files:**
- Modify: `portfolio_engine/automation/types.py`
- Modify: `portfolio_engine/automation/adapters.py`
- Modify: `tests/test_automation_orchestrator.py`

- [ ] **Step 1: Write failing protocol tests**

Add tests:

```python
class AdapterContextTests(unittest.TestCase):
    def test_secret_value_is_redacted_in_adapter_context(self) -> None:
        secret = SecretValue("plain")
        context = IntegrationConnectionContext(
            connection_id="connection-uuid",
            integration_key="ibkr_flex_ws",
            brokerage_code="IBKR",
            name="IBKR Personal",
            credentials={"flex_token": secret},
        )

        self.assertEqual(str(context.credentials["flex_token"]), "<redacted>")
        self.assertEqual(context.credentials["flex_token"].reveal(), "plain")

    def test_ibkr_adapter_preflight_requires_token_and_feed_query_ids(self) -> None:
        adapter = IbkrFlexWebServiceAdapter()
        connection = IntegrationConnectionContext(
            connection_id="connection-uuid",
            integration_key="ibkr_flex_ws",
            brokerage_code="IBKR",
            name="IBKR Personal",
            credentials={},
        )
        feed = IntegrationFeedContext(
            feed_id="feed-uuid",
            feed_key="daily",
            display_name="Daily",
            secrets={},
        )

        with self.assertRaisesRegex(RuntimeError, "missing_connection_credential"):
            adapter.preflight_connection(connection, (feed,))
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.AdapterContextTests -v
```

Expected: import/name failures for new context types.

- [ ] **Step 3: Update `types.py`**

Move or re-export `SecretValue` from `credentials.py` and add:

```python
@dataclass(frozen=True)
class IntegrationConnectionContext:
    connection_id: str
    integration_key: str
    brokerage_code: str
    name: str
    credentials: dict[str, SecretValue]


@dataclass(frozen=True)
class IntegrationFeedContext:
    feed_id: str
    feed_key: str
    display_name: str | None
    secrets: dict[str, SecretValue]


class BrokerAdapter(Protocol):
    def preflight_connection(
        self,
        connection: IntegrationConnectionContext,
        feeds: tuple[IntegrationFeedContext, ...],
    ) -> None:
        """Validate decrypted connection and feed credential shape before fetch."""

    def fetch_feed_payload(
        self,
        connection: IntegrationConnectionContext,
        feed: IntegrationFeedContext,
        request: AutomationRunRequest,
    ) -> BrokerPayload:
        """Fetch one broker payload for one connection feed."""
```

- [ ] **Step 4: Update IBKR adapter**

`IbkrFlexWebServiceAdapter.preflight_connection` requires `flex_token` in connection credentials and `query_id` in each feed's secrets. `fetch_feed_payload` continues to raise `NotImplementedError`.

- [ ] **Step 5: Run adapter tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.AdapterContextTests -v
```

Expected: all adapter context tests pass.

- [ ] **Step 6: Commit**

```bash
git add portfolio_engine/automation/types.py portfolio_engine/automation/adapters.py tests/test_automation_orchestrator.py
git commit -m "feat: introduce connection-aware adapter protocol" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Update static config and workflow secrets

**Files:**
- Modify: `portfolio_engine/automation/integrations.yaml`
- Modify: `portfolio_engine/automation/config.py`
- Modify: `.github/workflows/manual-ingestion.yml`
- Modify: `tests/test_automation_config.py`
- Modify: `tests/test_automation_workflow.py`

- [ ] **Step 1: Write failing config/workflow tests**

Add assertions:

```python
def test_ibkr_config_no_longer_requires_per_login_secrets(self) -> None:
    config = load_integration_config("ibkr_flex_ws")

    self.assertIn("SUPERFOLIO_CREDENTIAL_MASTER_KEY", config.required_env_keys)
    self.assertNotIn("IBKR_FLEX_TOKEN", config.required_env_keys)
    self.assertNotIn("IBKR_FLEX_QUERY_ID", config.required_env_keys)
```

Add workflow assertions:

```python
def test_workflow_uses_master_key_not_per_login_secrets(self) -> None:
    text = Path(".github/workflows/manual-ingestion.yml").read_text(encoding="utf-8")

    self.assertIn("SUPERFOLIO_CREDENTIAL_MASTER_KEY: ${{ secrets.SUPERFOLIO_CREDENTIAL_MASTER_KEY }}", text)
    self.assertNotIn("IBKR_FLEX_TOKEN:", text)
    self.assertNotIn("IBKR_FLEX_QUERY_ID:", text)
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python -m unittest tests.test_automation_config tests.test_automation_workflow -v
```

Expected: failures because the old env keys are still present.

- [ ] **Step 3: Update config and workflow**

In `integrations.yaml`, use:

```yaml
required_env_keys:
  - DATABASE_URL
  - SUPERFOLIO_CREDENTIAL_MASTER_KEY
```

In workflow `env`, use:

```yaml
DATABASE_URL: ${{ secrets.DATABASE_URL }}
SUPERFOLIO_CREDENTIAL_MASTER_KEY: ${{ secrets.SUPERFOLIO_CREDENTIAL_MASTER_KEY }}
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
python -m unittest tests.test_automation_config tests.test_automation_workflow -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add portfolio_engine/automation/integrations.yaml portfolio_engine/automation/config.py .github/workflows/manual-ingestion.yml tests/test_automation_config.py tests/test_automation_workflow.py
git commit -m "feat: use stored credentials for automation workflow" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 7: Add connection-aware target resolution

**Files:**
- Modify: `migrations/deploy/create_automation_layer.sql`
- Modify: `migrations/revert/create_automation_layer.sql`
- Modify: `migrations/verify/create_automation_layer.sql`
- Modify: `portfolio_engine/database.py`
- Modify: `tests/test_database_adapter.py`
- Modify: `tests/test_migrations.py`

- [ ] **Step 1: Write failing database adapter tests**

Add tests:

```python
class AutomationConnectionTargetResolutionTests(unittest.TestCase):
    def test_resolve_automation_targets_with_connections_maps_nullable_connection(self) -> None:
        connection = FakeConnection(rows=[
            ("account-1", "IBKR", "U100", "USD", "Taxable", "connection-1", "IBKR Personal"),
            ("account-2", "IBKR", "U200", "USD", "IRA", None, None),
        ])
        db = SuperFolioDatabase(connection)

        results = db.resolve_automation_targets_with_connections(
            target_type="accounts",
            portfolio_name=None,
            brokerage_code="IBKR",
            account_external_ids=["U100", "U200"],
        )

        self.assertEqual(results[0].connection_id, "connection-1")
        self.assertIsNone(results[1].connection_id)
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python -m unittest tests.test_database_adapter.AutomationConnectionTargetResolutionTests -v
```

Expected: missing method/dataclass failures.

- [ ] **Step 3: Add dataclass and adapter method**

In `database.py`:

```python
@dataclass(frozen=True)
class AutomationConnectionTarget:
    account_id: str
    brokerage_code: str
    account_external_id: str
    base_currency: str
    display_name: str | None
    connection_id: str | None
    connection_name: str | None
```

Add:

```python
def resolve_automation_targets_with_connections(
    self,
    *,
    target_type: str,
    portfolio_name: str | None,
    brokerage_code: str,
    account_external_ids: list[str],
) -> list[AutomationConnectionTarget]:
    rows = self._fetch_all(
        "SELECT * FROM public.resolve_automation_targets_with_connections(%s, %s, %s, %s)",
        (target_type, portfolio_name, brokerage_code, account_external_ids),
    )
    return [_automation_connection_target_from_row(row) for row in rows]
```

- [ ] **Step 4: Add SQL resolver**

Add this resolver:

```sql
CREATE FUNCTION public.resolve_automation_targets_with_connections(
    p_target_type TEXT,
    p_portfolio_name TEXT,
    p_brokerage_code TEXT,
    p_account_external_ids TEXT[]
)
RETURNS TABLE (
    account_id UUID,
    brokerage_code TEXT,
    account_external_id TEXT,
    base_currency TEXT,
    display_name TEXT,
    connection_id UUID,
    connection_name TEXT
);
```

The function rejects invalid target type, preserves current target validation behavior, returns active target accounts, and left joins only active same-brokerage assignments/connections.

- [ ] **Step 5: Run targeted tests**

Run:

```bash
python -m unittest tests.test_database_adapter tests.test_migrations -v
```

Expected: all targeted tests pass.

- [ ] **Step 6: Commit**

```bash
git add migrations/deploy/create_automation_layer.sql migrations/revert/create_automation_layer.sql migrations/verify/create_automation_layer.sql portfolio_engine/database.py tests/test_database_adapter.py tests/test_migrations.py
git commit -m "feat: resolve automation targets with connection assignments" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 8: Snapshot connection IDs on automation child rows

**Files:**
- Modify: `migrations/deploy/create_automation_layer.sql`
- Modify: `migrations/revert/create_automation_layer.sql`
- Modify: `migrations/verify/create_automation_layer.sql`
- Modify: `portfolio_engine/database.py`
- Modify: `tests/test_database_adapter.py`
- Modify: `tests/test_migrations.py`
- Modify: `tests/test_automation_orchestrator.py`

- [ ] **Step 1: Write failing child snapshot tests**

Add tests:

```python
def test_add_automation_job_account_accepts_connection_snapshot(self) -> None:
    connection = FakeConnection(rows=[("child-uuid",)])
    db = SuperFolioDatabase(connection)

    db.add_automation_job_account(
        AutomationJobAccountAdd(
            automation_job_id="job-uuid",
            account_id="account-uuid",
            connection_id="connection-uuid",
        )
    )

    self.assertEqual(connection.statements[0][1], ("job-uuid", "account-uuid", "connection-uuid"))
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python -m unittest tests.test_database_adapter -v
```

Expected: dataclass does not accept `connection_id`.

- [ ] **Step 3: Update dataclass and SQL function**

Change `AutomationJobAccountAdd`:

```python
@dataclass(frozen=True)
class AutomationJobAccountAdd:
    automation_job_id: str
    account_id: str
    connection_id: str | None = None
```

Change SQL:

```sql
CREATE FUNCTION public.add_automation_job_account(
    p_automation_job_id UUID,
    p_account_id UUID,
    p_connection_id UUID DEFAULT NULL
)
```

Insert `connection_id` into `automation_job_accounts`.

- [ ] **Step 4: Run targeted tests**

Run:

```bash
python -m unittest tests.test_database_adapter tests.test_migrations tests.test_automation_orchestrator -v
```

Expected: all targeted tests pass after updating existing fakes to accept connection IDs.

- [ ] **Step 5: Commit**

```bash
git add migrations/deploy/create_automation_layer.sql migrations/revert/create_automation_layer.sql migrations/verify/create_automation_layer.sql portfolio_engine/database.py tests/test_database_adapter.py tests/test_migrations.py tests/test_automation_orchestrator.py
git commit -m "feat: snapshot connection on automation job accounts" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 9: Update sanitization and summaries for feed diagnostics

**Files:**
- Modify: `portfolio_engine/automation/sanitization.py`
- Modify: `portfolio_engine/automation/summary.py`
- Modify: `tests/test_automation_summary.py`

- [ ] **Step 1: Write failing sanitizer tests**

Add:

```python
def test_sanitizer_redacts_query_and_credential_labels(self) -> None:
    message = "query_id=123 credential=abc ciphertext=deadbeef master_key=secret"

    sanitized = sanitize_error_message(message)

    self.assertNotIn("123", sanitized)
    self.assertNotIn("abc", sanitized)
    self.assertNotIn("deadbeef", sanitized)
    self.assertNotIn("secret", sanitized)
```

- [ ] **Step 2: Write failing feed summary tests**

Add:

```python
def test_child_summary_includes_feed_results_without_secrets(self) -> None:
    summary = build_child_summary(
        error_category="feed_fetch_failed",
        feed_results=[
            {
                "feed_key": "daily",
                "display_name": "Daily",
                "status": "failed",
                "error_category": "feed_fetch_failed",
                "record_counts": empty_record_counts(),
            }
        ],
    )

    self.assertEqual(summary["feed_results"][0]["feed_key"], "daily")
    self.assertNotIn("query_id", str(summary))
```

- [ ] **Step 3: Run failing tests**

Run:

```bash
python -m unittest tests.test_automation_summary -v
```

Expected: failures for sanitizer and unsupported `feed_results` argument.

- [ ] **Step 4: Update sanitizer and summary helper**

Extend `_SECRET_ASSIGNMENT_RE` labels:

```python
r"\b(?:token|password|secret|api_key|key|query_id|flex_query_id|credential|ciphertext|master_key)\b\s*=\s*\S+"
```

Add optional `feed_results` to `build_child_summary`, copying only non-secret fields and nested record counts.

- [ ] **Step 5: Run summary tests**

Run:

```bash
python -m unittest tests.test_automation_summary -v
```

Expected: all summary tests pass.

- [ ] **Step 6: Commit**

```bash
git add portfolio_engine/automation/sanitization.py portfolio_engine/automation/summary.py tests/test_automation_summary.py
git commit -m "feat: add feed diagnostics to automation summaries" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 10: Refactor orchestrator for connection grouping and missing assignments

**Files:**
- Modify: `portfolio_engine/automation/orchestrator.py`
- Modify: `tests/test_automation_orchestrator.py`

- [ ] **Step 1: Write failing missing-assignment tests**

Add:

```python
class ConnectionAssignmentOrchestratorTests(unittest.TestCase):
    def test_missing_connection_assignment_fails_child_and_continues(self) -> None:
        db = FakeAutomationDatabase()
        db.portfolio_id_by_name["All Accounts"] = "portfolio-uuid"
        db.connection_targets = [
            target("account-1", "U100", connection_id="connection-1"),
            target("account-2", "U200", connection_id=None),
        ]
        adapter = FakeConnectionAdapter(payload_by_feed={"daily": SAMPLE_XML})

        result = run_automation(
            portfolio_request(),
            database=db,
            adapter=adapter,
        )

        self.assertEqual(result.status, "partially_succeeded")
        self.assertEqual(db.finalized_children["child-account-2"].summary["error_category"], "missing_integration_connection")
        self.assertIn("account-1", adapter.fetched_account_ids)
```

- [ ] **Step 2: Run failing test**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.ConnectionAssignmentOrchestratorTests -v
```

Expected: orchestrator still uses old account target resolver and cannot group by connection.

- [ ] **Step 3: Refactor target resolution and child creation**

Update `_resolve_accounts` to call `resolve_automation_targets_with_connections`. Insert child rows with `connection_id`. Immediately finalize missing/inactive connection children as failed, append failed status/summary, and group remaining children by `connection_id`.

- [ ] **Step 4: Run targeted tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator.ConnectionAssignmentOrchestratorTests -v
```

Expected: missing assignment test passes.

- [ ] **Step 5: Commit**

```bash
git add portfolio_engine/automation/orchestrator.py tests/test_automation_orchestrator.py
git commit -m "feat: group automation accounts by integration connection" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 11: Add credential loading for connection groups

**Files:**
- Modify: `portfolio_engine/database.py`
- Modify: `portfolio_engine/automation/orchestrator.py`
- Modify: `tests/test_database_adapter.py`
- Modify: `tests/test_automation_orchestrator.py`

- [ ] **Step 1: Write failing credential-loading tests**

Add tests proving:

- connection credentials decrypt into `SecretValue`;
- missing `flex_token` fails only that connection's children with `missing_connection_credential`;
- missing feed query ID fails only that connection's children with `missing_feed_secret`;
- tampered ciphertext fails only that connection's children with `credential_decryption_failed`.

Example:

```python
def test_missing_connection_credential_fails_only_that_connection(self) -> None:
    db = FakeAutomationDatabase()
    db.connection_targets = [
        target("account-1", "U100", connection_id="connection-1"),
        target("account-2", "U200", connection_id="connection-2"),
    ]
    db.connection_credentials["connection-2"] = {"flex_token": encrypted("token")}
    db.connection_feeds["connection-2"] = [feed("daily", encrypted("query"))]

    result = run_automation(accounts_request("U100,U200"), database=db, adapter=FakeConnectionAdapter())

    self.assertEqual(result.status, "partially_succeeded")
    self.assertEqual(db.finalized_children["child-account-1"].summary["error_category"], "missing_connection_credential")
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator -v
```

Expected: failures because credential loading is absent.

- [ ] **Step 3: Add database methods**

Add methods:

```python
def list_active_connection_credentials(self, connection_id: str) -> dict[str, bytes]:
    rows = self._fetch_all(
        "SELECT credential_name, ciphertext FROM public.list_active_connection_credentials(%s)",
        (connection_id,),
    )
    return {str(row[0]): bytes(row[1]) for row in rows}


def list_active_integration_feeds(self, connection_id: str) -> list[IntegrationFeedRecord]:
    rows = self._fetch_all(
        "SELECT * FROM public.list_active_integration_feeds(%s)",
        (connection_id,),
    )
    return [_integration_feed_record_from_row(row) for row in rows]
```

Use these in orchestrator to build `IntegrationConnectionContext` and `IntegrationFeedContext`.

- [ ] **Step 4: Implement connection credential error handling**

In the per-connection group, catch missing/tampered credential errors and finalize all children in that connection group with the matching category.

- [ ] **Step 5: Run targeted tests**

Run:

```bash
python -m unittest tests.test_database_adapter tests.test_automation_orchestrator -v
```

Expected: all targeted tests pass.

- [ ] **Step 6: Commit**

```bash
git add portfolio_engine/database.py portfolio_engine/automation/orchestrator.py tests/test_database_adapter.py tests/test_automation_orchestrator.py
git commit -m "feat: load encrypted credentials for automation connections" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 12: Execute all enabled feeds and aggregate dry-run outcomes

**Files:**
- Modify: `portfolio_engine/automation/orchestrator.py`
- Modify: `portfolio_engine/automation/summary.py`
- Modify: `tests/test_automation_orchestrator.py`
- Modify: `tests/test_automation_summary.py`

- [ ] **Step 1: Write failing dry-run multi-feed tests**

Add tests:

```python
def test_dry_run_fetches_all_enabled_feeds_for_connection(self) -> None:
    db = configured_db_with_connection_feeds(["cash", "nav"])
    adapter = FakeConnectionAdapter(payload_by_feed={"cash": CASH_XML, "nav": NAV_XML})

    result = run_automation(accounts_request("U100"), database=db, adapter=adapter)

    self.assertEqual(result.status, "succeeded")
    self.assertEqual(adapter.fetched_feed_keys, ["cash", "nav"])
    self.assertEqual(db.finalized_children["child-account-1"].summary["feed_results"][0]["feed_key"], "cash")

def test_dry_run_partial_when_one_feed_fails(self) -> None:
    db = configured_db_with_connection_feeds(["cash", "nav"])
    adapter = FakeConnectionAdapter(payload_by_feed={"cash": CASH_XML}, failing_feed_keys={"nav"})

    result = run_automation(accounts_request("U100"), database=db, adapter=adapter)

    self.assertEqual(result.status, "partially_succeeded")
    self.assertEqual(db.finalized_children["child-account-1"].status, "partially_succeeded")
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator -v
```

Expected: dry-run only handles one payload per account.

- [ ] **Step 3: Implement dry-run feed loop**

For each connection group in dry-run:

- call `adapter.preflight_connection(connection_context, feeds)`;
- fetch each feed in stable `feed_key` order;
- run `dry_run_payload` per successful feed and account;
- aggregate counts per account;
- create `feed_results` entries;
- derive child status from feed outcomes.

- [ ] **Step 4: Run targeted tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator tests.test_automation_summary -v
```

Expected: all targeted tests pass.

- [ ] **Step 5: Commit**

```bash
git add portfolio_engine/automation/orchestrator.py portfolio_engine/automation/summary.py tests/test_automation_orchestrator.py tests/test_automation_summary.py
git commit -m "feat: aggregate dry-run results across connection feeds" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 13: Execute all enabled feeds and aggregate load outcomes

**Files:**
- Modify: `portfolio_engine/automation/orchestrator.py`
- Modify: `portfolio_engine/automation/ingestion.py`
- Modify: `tests/test_automation_orchestrator.py`

- [ ] **Step 1: Write failing load multi-feed tests**

Add tests:

```python
def test_load_fetches_all_feeds_and_sums_insert_counts(self) -> None:
    db = configured_db_with_connection_feeds(["cash", "nav"])
    adapter = FakeConnectionAdapter(payload_by_feed={"cash": CASH_XML, "nav": NAV_XML})

    result = run_automation(load_accounts_request("U100"), database=db, adapter=adapter)

    self.assertEqual(result.status, "succeeded")
    summary = db.finalized_children["child-account-1"].summary
    self.assertGreaterEqual(summary["record_counts"]["cash_flows"]["supported"], 1)
    self.assertGreaterEqual(summary["record_counts"]["daily_nav_snapshots"]["supported"], 1)

def test_load_partial_when_one_feed_fails_after_another_succeeds(self) -> None:
    db = configured_db_with_connection_feeds(["cash", "nav"])
    adapter = FakeConnectionAdapter(payload_by_feed={"cash": CASH_XML}, failing_feed_keys={"nav"})

    result = run_automation(load_accounts_request("U100"), database=db, adapter=adapter)

    self.assertEqual(result.status, "partially_succeeded")
    self.assertEqual(db.finalized_children["child-account-1"].status, "partially_succeeded")
```

- [ ] **Step 2: Run failing load tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator -v
```

Expected: load only handles one payload per account.

- [ ] **Step 3: Implement load feed loop**

For each account in a connection group:

- run account/date overlap check once before any feed load;
- for each feed in stable feed order, fetch payload and call the existing load ingestion path;
- sum record counts across feed loads;
- preserve ingestion-run cleanup semantics from existing `load_payload`;
- aggregate child status according to the spec.

- [ ] **Step 4: Run targeted tests**

Run:

```bash
python -m unittest tests.test_automation_orchestrator -v
```

Expected: all orchestrator tests pass.

- [ ] **Step 5: Commit**

```bash
git add portfolio_engine/automation/orchestrator.py portfolio_engine/automation/ingestion.py tests/test_automation_orchestrator.py
git commit -m "feat: aggregate load results across connection feeds" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 14: Preserve account/date-scoped overlap blocking

**Files:**
- Modify: `migrations/deploy/create_automation_layer.sql`
- Modify: `portfolio_engine/database.py`
- Modify: `tests/test_migrations.py`
- Modify: `tests/test_database_adapter.py`
- Modify: `tests/test_automation_orchestrator.py`

- [ ] **Step 1: Write failing overlap tests**

Add tests asserting no connection parameter is required:

```python
def test_overlap_check_remains_account_scoped(self) -> None:
    text = Path("migrations/deploy/create_automation_layer.sql").read_text(encoding="utf-8")

    self.assertIn("p_account_id UUID", text)
    self.assertNotIn("p_connection_id UUID", text)

def test_reassigned_connection_does_not_bypass_overlap(self) -> None:
    db = configured_db_with_connection_feeds(["daily"])
    db.overlapping_account_ids.add("account-1")

    result = run_automation(load_accounts_request("U100"), database=db, adapter=FakeConnectionAdapter())

    self.assertEqual(result.status, "failed")
    self.assertEqual(db.finalized_children["child-account-1"].summary["error_category"], "overlapping_load_job")
```

- [ ] **Step 2: Run targeted tests**

Run:

```bash
python -m unittest tests.test_migrations tests.test_database_adapter tests.test_automation_orchestrator -v
```

Expected: tests pass if prior tasks did not add connection-scoped overlap; failures identify refactor drift to fix.

- [ ] **Step 3: Fix overlap drift if present**

Ensure `has_overlapping_automation_load` still filters by account ID, date range, load mode, active parent/child statuses, and excludes current automation job ID. Do not add `connection_id` as a match condition.

- [ ] **Step 4: Commit**

```bash
git add migrations/deploy/create_automation_layer.sql portfolio_engine/database.py tests/test_migrations.py tests/test_database_adapter.py tests/test_automation_orchestrator.py
git commit -m "test: preserve account-scoped automation overlap blocking" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 15: Update automated ingestion CLI behavior and workflow tests

**Files:**
- Modify: `portfolio_engine/automation/cli.py`
- Modify: `.github/workflows/manual-ingestion.yml`
- Modify: `tests/test_automation_cli.py`
- Modify: `tests/test_automation_workflow.py`

- [ ] **Step 1: Write failing workflow/CLI tests**

Add tests proving trigger inputs remain stable and workflow secrets changed:

```python
def test_automation_cli_does_not_require_connection_input(self) -> None:
    stdout = StringIO()

    exit_code = run(
        [
            "--target-type", "accounts",
            "--integration", "ibkr_flex_ws",
            "--mode", "dry-run",
            "--start-date", "2026-05-01",
            "--end-date", "2026-05-14",
            "--account-external-ids", "U100",
        ],
        stdout=stdout,
        runner=lambda request, database: result("succeeded"),
        database_connector=lambda: object(),
    )

    self.assertEqual(exit_code, 0)

def test_workflow_requires_master_key_secret(self) -> None:
    text = Path(".github/workflows/manual-ingestion.yml").read_text(encoding="utf-8")

    self.assertIn("SUPERFOLIO_CREDENTIAL_MASTER_KEY", text)
    self.assertNotIn("IBKR_FLEX_TOKEN:", text)
```

- [ ] **Step 2: Run targeted tests**

Run:

```bash
python -m unittest tests.test_automation_cli tests.test_automation_workflow -v
```

Expected: workflow tests fail until secrets are updated.

- [ ] **Step 3: Keep CLI trigger shape unchanged**

Keep `portfolio_engine/automation/cli.py` accepting only these run-trigger flags:

```text
--target-type
--integration
--mode
--start-date
--end-date
--portfolio-name
--account-external-ids
```

Do not add normal run flags for connection selection. The regular automation trigger remains account/portfolio scoped, and connection choice comes from account assignments.

- [ ] **Step 4: Run targeted tests**

Run:

```bash
python -m unittest tests.test_automation_cli tests.test_automation_workflow -v
```

Expected: all targeted tests pass.

- [ ] **Step 5: Commit**

```bash
git add portfolio_engine/automation/cli.py .github/workflows/manual-ingestion.yml tests/test_automation_cli.py tests/test_automation_workflow.py
git commit -m "feat: keep automation triggers connection-assignment driven" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 16: Update documentation

**Files:**
- Modify: `docs/workflows/automated-ingestion.md`
- Modify: `docs/database/schema.md`
- Modify: `docs/database/functions.md`
- Modify: `README.md`

- [ ] **Step 1: Update workflow docs**

Document:

- `SUPERFOLIO_CREDENTIAL_MASTER_KEY`;
- no per-login IBKR token/query GitHub secrets;
- connection/feed/assignment setup commands;
- cutover checklist;
- fetch internals still out of scope.

- [ ] **Step 2: Update database docs**

Document:

- `integration_connections`;
- `integration_connection_credentials`;
- `integration_feeds`;
- `account_integration_assignments`;
- `automation_job_accounts.connection_id`.

- [ ] **Step 3: Update function docs**

Document new PostgreSQL functions and `SuperFolioDatabase` methods for connection management, credentials, feeds, assignments, and connection-aware target resolution.

- [ ] **Step 4: Update README**

Add `scripts/manage_integration_connections.py` and describe multi-login automation setup at a high level.

- [ ] **Step 5: Commit docs**

```bash
git add docs/workflows/automated-ingestion.md docs/database/schema.md docs/database/functions.md README.md
git commit -m "docs: document multi-login automation setup" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 17: Final verification

**Files:**
- No source edits expected unless verification finds a bug.

- [ ] **Step 1: Run full Python test suite**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Inspect git status**

Run:

```bash
git --no-pager status --short
```

Expected: no uncommitted changes.

- [ ] **Step 3: If failures occur, use TDD fixes**

For each failure:

1. Write or keep the failing test that demonstrates the issue.
2. Implement the smallest fix.
3. Run the targeted failing test.
4. Run the full suite.
5. Commit the focused fix with the required co-author trailer.

- [ ] **Step 4: Final handoff**

Report:

- final commit SHA;
- full test command and result;
- that the branch was not merged;
- that full IBKR Flex Web Service HTTP fetch internals remain out of scope.

---

## Self-review against spec

- Persistent connection metadata: Tasks 2, 3, 4, 16.
- Encrypted credential storage with Fernet: Tasks 1, 3, 4, 11.
- Integration feeds and feed query-id credentials: Tasks 2, 3, 4, 11, 12, 13.
- Explicit account assignments: Tasks 2, 3, 4, 7, 10.
- Connection grouping and failure isolation: Tasks 10, 11, 12, 13.
- Adapter context boundary: Task 5.
- Management CLI and cutover validation: Task 4 and Task 16.
- Workflow master key and removal of per-login secrets: Task 6 and Task 15.
- Account/date-scoped overlap: Task 14.
- Multi-feed aggregation and feed summaries: Tasks 9, 12, 13.
- Sanitizer updates: Task 9.
- Documentation: Task 16.
- Full verification: Task 17.
