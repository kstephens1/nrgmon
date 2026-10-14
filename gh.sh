#!/usr/bin/env bash
set -euo pipefail

git add \
  .dockerignore \
  .gitignore \
  .env.example \
  README.md \
  scripts/deploy-pi.sh \
  PROJECT_STATE.md \
  collector/config.py \
  collector/main.py \
  collector/solarman.py \
  grafana/assets/nrgmon/battery.svg \
  grafana/assets/nrgmon/energy-flow.svg \
  grafana/dashboards/solar-generation.json \
  tests/test_solarman.py \
  postman/NRGMon-Solarman.postman_collection.json \
  gh.sh
git commit -m "fit dashboard history on landscape tablets and protect production build context"
git push origin main
