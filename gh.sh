#!/usr/bin/env bash
set -euo pipefail

git add \
  PROJECT_STATE.md \
  gh.sh
git commit -m "document kiosk refresh requirement"
git push origin main
