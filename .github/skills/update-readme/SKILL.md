---
name: update-readme
description: 'Update the repository README.md from the current project state. Use when refreshing project overview, implemented features, setup/run instructions, architecture, roadmap, privacy notes, or known limitations.'
argument-hint: 'Optional focus area, for example: Python engine, CLI usage, dev environment, roadmap, privacy posture'
---

# Update README.md

Use this skill to refresh the root [README.md](../../../README.md) so it accurately explains what the project is, what is implemented now, and what remains planned.

## Outcome

- A current, user-facing `README.md` that separates implemented functionality from roadmap items.
- Setup and usage instructions backed by files that actually exist in the repository.
- Architecture notes that match the current source tree, dev container, and scripts.
- Privacy-sensitive local sample data described only at a high level.
- A reviewed diff with stale claims removed or clearly marked as planned.

## Procedure

1. Discover the current documentation and customization context.
   - Read `README.md`, `AGENTS.md`, `.github/skills/**/SKILL.md`, `docs/**/*.md`, `CONTRIBUTING.md`, and architecture notes if they exist.
   - Treat `README.md` as the reader-facing source of truth, and use `AGENTS.md` for agent-specific project rules that may affect the edit.

2. Inspect the repository state before changing prose.
   - Inventory top-level directories and important files.
   - Check manifests and configs before naming setup commands: `package.json`, lockfiles, `pyproject.toml`, `requirements.txt`, test configs, workflow files, and `.devcontainer/devcontainer.json`.
   - Review implemented source modules and scripts, especially `portfolio_engine/` and `scripts/` in this repo.
   - Note ignored/local-only data such as `scratch/`, but do not quote raw account data, balances, transaction amounts, account IDs, or private report contents.

3. Classify claims as current, planned, or unknown.
   - Current: features supported by source files, scripts, configs, tests, or committed docs.
   - Planned: roadmap architecture such as dashboard UI, Supabase, Next.js API routes, automation, or hosting when the matching files are not present yet.
   - Unknown: details that cannot be verified from the repo; omit them or phrase them as assumptions only when useful.

4. Edit `README.md` conservatively.
   - Lead with the product purpose and current implementation status.
   - Add or update a small project structure section when it helps readers orient themselves.
   - Include runnable commands only when they are backed by actual scripts or manifests.
   - Prefer examples that use synthetic or redacted paths/data. For this repo, `scratch/` may be mentioned as local private sample input, but its contents should not be copied into the README.
   - Keep planned architecture and roadmap clearly labeled so readers can distinguish scaffolded goals from implemented code.
   - Use relative Markdown links for workspace files.

5. Validate the README update.
   - Check Markdown formatting by reading the final file or running an available formatter/linter if the repo provides one.
   - Run `git status --short` and inspect the diff for `README.md`.
   - Do not invent or run build/test commands unless manifests or scripts prove they exist.

## Quality Checklist

- The README no longer claims unimplemented systems are already present.
- Current Python modules, CLI behavior, inputs, and outputs are represented accurately.
- Dev environment details match `.devcontainer/devcontainer.json`.
- Commands are reproducible from the repository root and do not require private data unless clearly labeled as local-only.
- Roadmap items remain visible but are labeled as future work.
- No secrets, raw broker records, balances, account numbers, or transaction details are included.

## Branching Logic

- If `README.md` does not exist, create a concise one from the verified repository state.
- If manifests are missing, avoid dependency installation claims and explain the current script/module usage directly.
- If source code has outpaced docs, update the README to prioritize implemented workflows before planned architecture.
- If docs describe a target architecture that is not implemented, preserve it under a roadmap or planned architecture section.
- If the requested focus area is narrow, limit edits to that section while still removing directly conflicting stale claims.
- If private sample data is required to verify an example, use placeholders or synthetic fixture names instead.
