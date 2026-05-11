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
