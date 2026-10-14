#!/usr/bin/env bash
set -euo pipefail

git add \
  .dockerignore \
  .gitignore \
  .env.example \
  README.md \
  PROJECT_STATE.md \
  collector/config.py \
  collector/main.py \
  collector/solarman.py \
  grafana/assets/nrgmon/battery.svg \
  grafana/dashboards/solar-generation.json \
  tests/test_solarman.py \
  postman/NRGMon-Solarman.postman_collection.json \
  gh.sh
git commit -m "add battery monitoring and diagnostics; align arrows, combine history and simplify and reposition battery labels"
git push origin main
