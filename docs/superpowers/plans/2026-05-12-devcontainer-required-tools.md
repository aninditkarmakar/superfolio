# Devcontainer Required Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a fresh devcontainer include the repository-required Sqitch migration tooling and committed Python database dependency setup.

**Architecture:** Install OS packages that belong to the container image in `.devcontainer/Dockerfile`, and install Python dependencies from the committed manifest in `.devcontainer/post-create.sh`. Update README and agent guidance so documented setup matches what the devcontainer now provisions.

**Tech Stack:** VS Code Dev Containers, Debian `apt`, Python 3.12, pip, Psycopg 3, Sqitch, PostgreSQL client tooling, Markdown.

---

## File Structure

- Modify `.devcontainer/Dockerfile` to install `sqitch`, `libdbd-pg-perl`, and `postgresql-client` during image build.
- Modify `.devcontainer/post-create.sh` to run `python -m pip install -r requirements.txt` during post-create setup.
- Modify `README.md` to replace stale manual-install language with the new automatic devcontainer setup and keep the manual command only for non-devcontainer environments.
- Modify `AGENTS.md` to tell future agents that devcontainer rebuilds install Python dependencies and Sqitch, while still avoiding invented frontend commands.

### Task 1: Install Sqitch packages in the devcontainer image

**Files:**
- Modify: `.devcontainer/Dockerfile`

- [ ] **Step 1: Update the apt package list in Dockerfile**

Change `.devcontainer/Dockerfile` to:

```dockerfile
FROM mcr.microsoft.com/devcontainers/typescript-node:4-24-trixie

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libdbd-pg-perl \
        postgresql-client \
        sqitch \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 2: Verify the Dockerfile text includes all required packages**

Run:

```bash
grep -nE 'libdbd-pg-perl|postgresql-client|sqitch' .devcontainer/Dockerfile
```

Expected: output includes one line each for `libdbd-pg-perl`, `postgresql-client`, and `sqitch`.

- [ ] **Step 3: Commit the Dockerfile change**

Run:

```bash
git add .devcontainer/Dockerfile
git commit -m "chore: install sqitch in devcontainer" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: commit succeeds.

### Task 2: Install Python requirements during post-create setup

**Files:**
- Modify: `.devcontainer/post-create.sh`

- [ ] **Step 1: Add Python dependency installation**

Insert this command after the Copilot plugin install block and before the `.env` Git identity block:

```bash
python -m pip install -r requirements.txt
```

The resulting middle of `.devcontainer/post-create.sh` should be:

```bash
# Re-register marketplace and reinstall plugins so the container state
# stays in sync with what settings.json records after a rebuild.
copilot plugin marketplace remove superpowers-marketplace --force 2>/dev/null || true
copilot plugin marketplace add obra/superpowers-marketplace
copilot plugin install superpowers@superpowers-marketplace

python -m pip install -r requirements.txt

# Configure git identity from .env if present
if [ -f .env ]; then
  GITHUB_NAME=$(grep -E '^GITHUB_NAME=' .env | cut -d '=' -f2- | tr -d '"' | tr -d "'")
```

- [ ] **Step 2: Run the Python dependency install command**

Run:

```bash
python -m pip install -r requirements.txt
```

Expected: pip completes successfully and `psycopg[binary]>=3.2,<4` is installed or already satisfied.

- [ ] **Step 3: Verify Psycopg can be imported**

Run:

```bash
python - <<'PY'
import psycopg
print(psycopg.__version__)
PY
```

Expected: command prints a Psycopg 3 version.

- [ ] **Step 4: Commit the post-create change**

Run:

```bash
git add .devcontainer/post-create.sh
git commit -m "chore: install python requirements in devcontainer" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: commit succeeds.

### Task 3: Update setup documentation

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Update README devcontainer package bullets**

In `README.md`, replace the development environment bullets around lines 112-117 with:

```markdown
### `.devcontainer/devcontainer.json`
* **Base Image:** `mcr.microsoft.com/devcontainers/typescript-node:4-24-trixie` (Node.js/TypeScript host, extended via `.devcontainer/Dockerfile`)
* **Python Feature:** `ghcr.io/devcontainers/features/python:1` — Python 3.12 with pip and JupyterLab
* **Database Tools:** `postgresql-client`, `sqitch`, and `libdbd-pg-perl` are installed by `.devcontainer/Dockerfile` for PostgreSQL/Sqitch workflows.
* **Python Dependencies:** `.devcontainer/post-create.sh` installs `requirements.txt`, currently `psycopg[binary]` for database-backed CLI workflows.

The core TWR engine uses only the Python standard library. Database-backed commands additionally require the committed `requirements.txt` dependencies.
```

- [ ] **Step 2: Update README Sqitch install section**

Replace the section that starts with `### Install Sqitch locally` through the command block ending in `sqitch --version` with:

```markdown
### Sqitch availability

The devcontainer installs Sqitch and its PostgreSQL driver automatically. In a non-devcontainer environment, install the same packages before running migrations:

```bash
sudo apt-get update
sudo apt-get install -y sqitch libdbd-pg-perl postgresql-client
sqitch --version
```
```

- [ ] **Step 3: Update AGENTS command guidance**

In `AGENTS.md`, replace the Commands And Tooling bullets with:

```markdown
## Commands And Tooling
- There is no `package.json` or frontend app yet; do not invent npm build, lint, or dev commands.
- Devcontainer rebuilds install Python dependencies from `requirements.txt` via `.devcontainer/post-create.sh`. Outside the devcontainer, run `python -m pip install -r requirements.txt` before database-backed workflows.
- Run Python tests with `python -m unittest discover -s tests -v`. The current test suite uses `unittest`; do not add or require pytest unless the repo adopts it explicitly.
- The devcontainer image installs `sqitch`, `libdbd-pg-perl`, and `postgresql-client`. For database migrations, configure `DATABASE_URL`/`SQITCH_TARGET` as described in [README.md](README.md). Do not print database connection strings.
```

- [ ] **Step 4: Check Markdown references**

Run:

```bash
grep -nE 'Sqitch is not yet installed|No third-party Python packages are required|python -m pytest|pytest is available' README.md AGENTS.md || true
```

Expected: no output.

- [ ] **Step 5: Commit documentation updates**

Run:

```bash
git add README.md AGENTS.md
git commit -m "docs: document devcontainer setup tools" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: commit succeeds.

### Task 4: Validate the full setup change

**Files:**
- Read: `.devcontainer/Dockerfile`
- Read: `.devcontainer/post-create.sh`
- Read: `README.md`
- Read: `AGENTS.md`

- [ ] **Step 1: Verify command availability in the current environment**

Run:

```bash
sqitch --version
psql --version
python - <<'PY'
import psycopg
print(psycopg.__version__)
PY
```

Expected: `sqitch --version` and `psql --version` print versions, and Python prints a Psycopg 3 version.

- [ ] **Step 2: Run the current test suite**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 3: Inspect the final diff**

Run:

```bash
git --no-pager diff --stat HEAD~3..HEAD
git status --short
```

Expected: diff stat includes `.devcontainer/Dockerfile`, `.devcontainer/post-create.sh`, `README.md`, and `AGENTS.md`; status has no uncommitted task changes except any pre-existing unrelated changes.

- [ ] **Step 4: Commit any missed validation/documentation fixes**

If Task 4 reveals a needed fix, apply it and run:

```bash
git add .devcontainer/Dockerfile .devcontainer/post-create.sh README.md AGENTS.md
git commit -m "chore: finalize devcontainer setup" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: commit succeeds only if a fix was necessary.
