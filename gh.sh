#!/usr/bin/env bash
set -euo pipefail

git add collector/main.py tests/test_solarman.py README.md PROJECT_STATE.md gh.sh
git commit -m "fix solar-only home consumption and record production deployment"
git push origin main
