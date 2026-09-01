# Project state

## Current baseline

- The latest coding cycle is committed and pushed as `1a2b2e1` (`added animated arrows`).
- That change updates the Grafana solar-generation dashboard and its energy-flow SVG assets.
- `gh.sh` records the corresponding add, commit, and push commands for that cycle.

## Local development

- The local Docker Compose configuration was validated on 2026-09-01 with the existing private `.env`.
- Start the development stack with `docker compose up --build`; Grafana is available at `http://localhost:3000` and the kiosk at `http://localhost:8080`.

## Production deployment

- Commit `1a2b2e1` was deployed to `192.168.6.238` on 2026-09-01.
- Local unit tests passed (4 run, 1 skipped), and the production smoke test passed for all four services, Grafana health, and the kiosk endpoint.
- Historical data was preserved in the existing `nrgmon_prometheus-data`, `nrgmon_grafana-data`, and `nrgmon_collector-state` volumes. A post-deployment query confirmed Prometheus samples from 2026-08-28 remain available.
- The corrected kiosk configuration was redeployed on 2026-09-01. Production smoke tests passed, and the live generated configuration now uses `https://dinnerlist-prod-ks-2026.web.app/?kiosk`. Grafana and Prometheus remained running with their existing persistent volumes during the redeployment.
- The live kiosk configuration and client code were checked after deployment. The iframe is assigned the configured `/?kiosk` URL, and Dinner List reads the `kiosk` query parameter without rewriting it. An already-open kiosk page retains its old in-memory page list until the browser is refreshed or restarted because configuration is loaded only at page startup.
