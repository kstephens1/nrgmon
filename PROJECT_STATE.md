# Project state

## Current baseline

- The latest coding cycle is committed and pushed as `1a2b2e1` (`added animated arrows`).
- That change updates the Grafana solar-generation dashboard and its energy-flow SVG assets.
- `gh.sh` records the corresponding add, commit, and push commands for that cycle.

## Local development

- On 2026-10-14, moved House battery and its percentage into the space left of the battery icon, then shifted Charging and Discharging left into the next two columns. Label/value pairs retain their vertical alignment; icon and arrow positions are unchanged. README and `gh.sh` updated. All 25 tests passed in the local Docker image; JSON, whitespace, and shell syntax checks passed. Running local Grafana confirmed House battery at 22%, icon at 36%, Charging at 45%, and Discharging at 62% of canvas width, with matching label/value columns and clearance before the icon. Production unchanged.

- On 2026-10-14, renamed the battery flow labels to Charging and Discharging and removed the Battery status label/value, unused query, and formatting override. README and `gh.sh` updated. All 25 tests passed in the local Docker image; JSON, whitespace, and shell syntax checks passed. The running local Grafana dashboard confirmed both new labels and removal of the status section/query. Production unchanged.

- On 2026-10-14, corrected battery arrows to use named house/battery endpoints instead of canvas-corner coordinates. Removed the separate Battery Charge Level panel and combined its percentage series into Energy History on a right-hand 0–100% axis. README and `gh.sh` updated. Local Grafana loaded both panels; Safari accessibility inspection confirmed all seven Energy History series and no separate battery panel. All 25 tests passed in the local Docker image, all 28 dashboard queries passed against Prometheus, named endpoint geometry is reciprocal and inside the house/battery corridor, and JSON, whitespace, shell syntax, and private-file exclusion checks passed. Default host Python lacks `httpx`; Docker provided the required dependencies. Screenshot verification remains unavailable due to a ScreenCaptureKit capture failure. Production unchanged.

- On 2026-10-14, confirmed the documented local URLs after `docker compose up -d --build`: Grafana dashboard at `http://localhost:3000/d/solar-generation/solar-generation` and kiosk at `http://localhost:8080`. This was a documentation/configuration review; service availability was not checked.

- Added `postman/NRGMon-Solarman.postman_collection.json` on 2026-10-14 for manual API diagnosis. It uses placeholder variables, collector-equivalent token/station-list/real-time requests, automatic lowercase SHA-256 password hashing via Web Crypto, token capture, single-station ID discovery, and battery field/freshness checks. README explains import and request order. No private `.env` values were copied, no API requests were executed for this artifact, and production is unchanged. Synthetic Node checks passed for JSON/script syntax, empty credential defaults, exact UTF-8 password hashing, merchant ID handling, token capture/clearing, station selection/ambiguity, request bodies, and battery response checks. `git diff --check` and `gh.sh` shell syntax passed. Postman UI import was not exercised; `gh.sh` includes the collection in its explicit add/commit/push commands.

- On 2026-10-14, investigated the live local battery `Field not found` screenshot. Solarman is enabled and all required settings are present, but a sanitized token-endpoint diagnostic returned HTTP 200, `success=false`, code `2101025` (authentication failed), and no token. Credentials were not printed or changed. Updated battery queries to retain an explicit NaN-valued field when data is absent and zero-valued inactive flow indicators; added safe operation/error-code diagnostics and numeric invalid-token refresh handling. Rebuilt the local collector; all 25 tests passed locally and inside Docker, all 28 queries passed, and Grafana's query API confirmed all four battery fields resolve by their configured names with unavailable values. Live monitoring remains blocked by Solarman authentication; user must verify private login settings. README and `gh.sh` updated; production unchanged.

- Battery monitoring implementation on 2026-10-14 adds an optional read-only Solarman station adapter with SHA-256 email login, token caching, single-station discovery, collection-time freshness checks, and separate battery metrics. The energy-flow canvas now includes battery level, state, estimated stored energy, charge/discharge indicators, and history. `env.local` and `.env.local` are excluded from Git; private configurations are also excluded from Docker build context. Production has not been changed.
- Validation passed: all 23 unit tests run without skips locally and inside the collector's Python 3.12 Docker image; Compose and Prometheus configuration checks, all four running local services, collector metrics endpoint, `git diff --check`, and shell syntax for `gh.sh`. README documents setup, source fields/units, cloud freshness, and CT-dependent consumption. `gh.sh` contains explicit add/commit/push commands for this change, excluding private configuration and the pre-existing untracked `AGENTS.md`; no commit or push was performed.
- Local development stack was rebuilt successfully with the existing `.env` (battery disabled). Grafana loaded the three-panel dashboard, all 28 dashboard queries were accepted by Prometheus, and Grafana health, kiosk, and battery artwork endpoints passed. Visual inspection could not be completed because computer-use permissions were unavailable.
- To enable Solarman locally, add the documented settings to private `env.local`, retaining existing solar settings, and run `ENV_FILE=env.local docker compose --env-file env.local up -d --build`. Credentials were not provided as usable values and no live Solarman request has been made. Station battery fields/units must be verified against live readings after configuration. Stored kWh is optional and estimated from configured usable capacity.
- Myenergi home-consumption behavior is preserved by default because CT wiring is unconfirmed. Set `MYENERGI_GENERATION_INCLUDES_BATTERY=false` only for a solar-only generation CT; this enables battery charge/discharge correction and marks consumption unavailable when battery flows are missing.

- On 2026-10-14, reviewed the local development instructions and confirmed `docker compose config --quiet` passes with the existing private `.env`. Start Docker Desktop on macOS, then run `docker compose up --build` from the repository root. This review did not start or deploy services.
- The local Docker Compose configuration was validated on 2026-09-01 with the existing private `.env`.
- Start the development stack with `docker compose up --build`; Grafana is available at `http://localhost:3000` and the kiosk at `http://localhost:8080`.

## Production deployment

- Commit `1a2b2e1` was deployed to `192.168.6.238` on 2026-09-01.
- Local unit tests passed (4 run, 1 skipped), and the production smoke test passed for all four services, Grafana health, and the kiosk endpoint.
- Historical data was preserved in the existing `nrgmon_prometheus-data`, `nrgmon_grafana-data`, and `nrgmon_collector-state` volumes. A post-deployment query confirmed Prometheus samples from 2026-08-28 remain available.
- The corrected kiosk configuration was redeployed on 2026-09-01. Production smoke tests passed, and the live generated configuration now uses `https://dinnerlist-prod-ks-2026.web.app/?kiosk`. Grafana and Prometheus remained running with their existing persistent volumes during the redeployment.
- The live kiosk configuration and client code were checked after deployment. The iframe is assigned the configured `/?kiosk` URL, and Dinner List reads the `kiosk` query parameter without rewriting it. An already-open kiosk page retains its old in-memory page list until the browser is refreshed or restarted because configuration is loaded only at page startup.

## Repository review

- The application stack and notable components were reviewed on 2026-09-06. This was a documentation-only inspection; no application or deployment behavior changed.
