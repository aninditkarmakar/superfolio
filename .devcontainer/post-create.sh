#!/usr/bin/env bash
set -euo pipefail

npm install -g @github/copilot

mkdir -p .projectCopilot
chmod -R a+rwX .projectCopilot

# Redirect installed-plugins to container-local filesystem to avoid
# chmod failures on the fakeowner bind-mount (Docker Desktop on macOS/Windows).
mkdir -p ~/.copilot/installed-plugins
rm -rf .projectCopilot/installed-plugins
ln -s ~/.copilot/installed-plugins .projectCopilot/installed-plugins

# Configure git identity from .env if present
if [ -f .env ]; then
  GITHUB_NAME=$(grep -E '^GITHUB_NAME=' .env | cut -d '=' -f2- | tr -d '"' | tr -d "'")
  GITHUB_EMAIL=$(grep -E '^GITHUB_EMAIL=' .env | cut -d '=' -f2- | tr -d '"' | tr -d "'")
  [ -n "$GITHUB_NAME" ] && git config --global user.name "$GITHUB_NAME"
  [ -n "$GITHUB_EMAIL" ] && git config --global user.email "$GITHUB_EMAIL"
fi
