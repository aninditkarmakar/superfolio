---
name: update-agents
description: 'Update the root AGENTS.md from the current repository state. Use when refreshing AI coding-agent instructions, repo conventions, architecture notes, build/test commands, privacy rules, or project pitfalls.'
argument-hint: 'Optional focus area, for example: Python ETL, dashboard UI, database schema, dev environment'
---

# Update Root AGENTS.md

Use this skill to refresh the root [AGENTS.md](../../../AGENTS.md) so AI coding agents can quickly understand the repository as it exists now.

## Outcome

- A concise, current root-level `AGENTS.md`.
- Existing useful guidance preserved and outdated guidance corrected.
- Build/test commands documented only when they are backed by actual manifests, scripts, or project files.
- Sensitive local data called out without copying private contents.

## Procedure

1. Discover existing customization and docs.
   - Search for `AGENTS.md`, `.github/copilot-instructions.md`, `.github/instructions/**`, `.github/skills/**/SKILL.md`, `README.md`, `docs/**/*.md`, `CONTRIBUTING.md`, and `ARCHITECTURE.md`.
   - Prefer updating the existing root `AGENTS.md`. Do not create a duplicate instruction file unless the user asks for one.

2. Inspect the current repository state.
   - Read the README and any architecture or contributing docs.
   - Inventory manifests before naming commands: `package.json`, lockfiles, `pyproject.toml`, `requirements.txt`, workflow files, test configs, and framework configs.
   - Review top-level directories and important ignored/local directories. For this repo, treat `scratch/` as private IBKR sample data and do not quote raw account data.
   - Check dev environment files such as `.devcontainer/devcontainer.json`; note mismatches between planned docs and actual config.

3. Extract agent-useful facts.
   - Product goal and source-of-truth docs.
   - Current vs. planned architecture.
   - Build, test, lint, and run commands that can actually be executed.
   - Data and domain conventions that are easy to get wrong.
   - Privacy, security, or local-data handling rules.
   - Areas where no source tree or command exists yet.

4. Edit `AGENTS.md` conservatively.
   - Link to existing docs instead of copying them.
   - Keep guidance concise, actionable, and specific to the repo.
   - Preserve valuable existing sections; remove duplication and stale statements.
   - Use relative Markdown links for workspace files.
   - Do not include raw secrets, account numbers, transaction amounts, or private sample data.

5. Validate the update.
   - Check the file for Markdown/frontmatter problems if available.
   - Run `git status --short` and inspect the diff for `AGENTS.md`.
   - Do not run build or test commands unless current manifests/configs prove they exist.

## Quality Checklist

- `AGENTS.md` reflects the repository state, not only the roadmap.
- Commands are absent or clearly conditional when no manifest exists.
- Local/private data handling is explicit.
- Domain-specific pitfalls are included only when they guide future work.
- The final response lists changed customization files and what each one helps agents do.

## Branching Logic

- If there is no `AGENTS.md`, create one at the repository root.
- If both `AGENTS.md` and `.github/copilot-instructions.md` exist, update the file already serving as the main project instruction source and avoid contradictory guidance.
- If the repo has grown into distinct subsystems, keep root `AGENTS.md` high-level and suggest scoped instructions or skills for Python ETL, frontend UI, database, or automation.
- If the requested focus area is unclear, ask what outcome the refreshed agent guidance should optimize for before editing.