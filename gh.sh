#!/usr/bin/env bash
set -euo pipefail

git add \
  .dockerignore \
  .gitignore \
  .env.example \
  README.md \
  scripts/deploy-pi.sh \
  kiosk/index.html \
  PROJECT_STATE.md \
  collector/config.py \
  collector/main.py \
  collector/solarman.py \
  grafana/assets/nrgmon/battery.svg \
  grafana/assets/nrgmon/energy-flow.svg \
  grafana/dashboards/solar-generation.json \
  tests/test_solarman.py \
  tests/test_kiosk.cjs \
  postman/NRGMon-Solarman.postman_collection.json \
  gh.sh
git commit -m "adapt kiosk panels to Galaxy Tab A9+ viewport and restore full dashboard sizes"
git push origin main
