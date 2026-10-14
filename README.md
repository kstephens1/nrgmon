# NRGMon

NRGMon is a Raspberry Pi-hosted solar and home-energy dashboard for two solar arrays:

- Array 1: Hoymiles S-Miles Cloud, using the same read-only community login flow as [ioBroker Hoymiles](https://github.com/Eistee82/ioBroker.hoymiles).
- Array 2: Myenergi API.

The collector polls each configured source every 60 seconds and exports Prometheus metrics. Grafana shows live and historical solar generation, grid import/export, whole-property consumption, Eddi hot-water status, and optional Solarman house-battery monitoring. No appliance-specific, EV-status, or device-control fields are collected or stored.

## Deploy

1. Install Docker Engine and Docker Compose. Start Docker for your platform:

   On a 64-bit Raspberry Pi OS host, start Docker and enable it at boot:

   ```sh
   sudo systemctl enable --now docker
   ```

   To start it for the current session only:

   ```sh
   sudo systemctl start docker
   ```

   On macOS, install and start Docker Desktop (or start it from Terminal):

   ```sh
   open -a Docker
   ```

2. Create your private configuration: `cp .env.example .env`.
3. Add the S-Miles email/password and optional station ID for Hoymiles, then populate the Myenergi API URL, authentication values, and JSON paths. Do not commit `.env`.
4. Validate the configuration and start the stack:

   ```sh
   docker compose config
   docker compose up -d --build
   ```

5. Open `http://<pi-lan-address>:3000` for Grafana, or `http://<pi-lan-address>:8080` for the rotating kiosk display. Grafana is intentionally anonymous and view-only; do not expose either port to the public internet.

## Kiosk display

The kiosk display fills the browser window and changes pages every 30 seconds. NRGMon pages use two Grafana solo panels: the live diagram gets 68% of the available height and Energy History gets 32%, without the dashboard toolbar or scrolling. Panel text and spacing scale together on smaller Android viewports, and panel layouts refresh after rotation or viewport changes. This adapts to the Samsung Galaxy Tab A9+ landscape screen and the actual viewport reported by its kiosk app. Open `http://<pi-lan-address>:8080/` in landscape, full-screen kiosk mode at 100% browser zoom. Other configured pages retain their full-window iframe. It is available at port `8080` by default. With its default configuration it shows the NRGMon Grafana dashboard first.

Set `KIOSK_INTERVAL_SECONDS` to change the delay, and set `KIOSK_PAGES` to a JSON array of page URLs. The `{{HOST}}` token is replaced in the browser with the hostname or IP address used to open the kiosk, which keeps Grafana links portable between Pi deployments. For example:

```dotenv
KIOSK_INTERVAL_SECONDS=45
KIOSK_PAGES=["http://{{HOST}}:3000/d/solar-generation/solar-generation?orgId=1&kiosk","https://example.net/status"]
```

Leave `KIOSK_PAGES=[]` to use only the default NRGMon Grafana page. Pages hosted by other services must permit being displayed in an iframe.

## Solarman battery monitoring (local development)

Keep existing solar settings by copying `.env` to `env.local` **only if `env.local` does not already exist**. Both files are ignored by Git. Add:

```dotenv
SOLARMAN_ENABLED=true
SOLARMAN_BASE_URL=https://globalapi.solarmanpv.com
SOLARMAN_APP_ID=YOUR_APP_ID
SOLARMAN_APP_SECRET=YOUR_API_SECRET
SOLARMAN_EMAIL=YOUR_SOLARMAN_EMAIL
SOLARMAN_PASSWORD='YOUR_NORMAL_SOLARMAN_PASSWORD'
SOLARMAN_STATION_ID=
SOLARMAN_ORG_ID=
SOLARMAN_BATTERY_CAPACITY_KWH=
SOLARMAN_MAX_AGE_SECONDS=900
SOLARMAN_POWER_MULTIPLIER=1
MYENERGI_GENERATION_INCLUDES_BATTERY=true
```

Use your normal, unhashed password. The adapter hashes its exact UTF-8 value to lowercase SHA-256 and sends it with `email` and `appSecret` in the JSON body of the token request; `appId` and `language=en` are URL parameters. Tokens are cached in memory until expiry and refreshed once on an unauthorized response. Request bodies, tokens, and API error bodies are not logged. Only login, station-list discovery, and station real-time queries are called; no device control is performed. See [Solarman authentication](https://doc.solarmanpv.com/en/Account%20Interface/2.1Obtain%20Token) and the [Solarman OpenAPI reference, section 4.5](https://manuals.plus/m/7156e9068460c7164fee85e9e73b687c15453c065d7b3a3c70f9fb9c1d8a6c95.pdf).

Leave `SOLARMAN_STATION_ID` blank only if the account has exactly one station. Otherwise set its numeric plant ID. `SOLARMAN_ORG_ID` is needed only for a merchant account. Optional `SOLARMAN_BATTERY_CAPACITY_KWH` is the battery's usable full capacity; stored energy is an **estimate** calculated as capacity multiplied by charge percentage. Leave it blank to show `N/A` for stored energy.

The adapter reads station `batterySoc`, `chargePower`, `dischargePower`, and `lastUpdateTime`. Direction comes from the named charging/discharging fields, whose magnitudes are displayed in watts; it does not guess the sign of `batteryPower`. Missing fields show `N/A`, not zero. A station that does not expose these fields needs a device-specific mapping before its battery flows can be shown. Power is treated as W by default; use multiplier `1000` only if verified API readings are in kW.

The dashboard adds battery level, estimated stored energy, and Charging/Discharging power readings to the existing energy diagram. House battery and its percentage sit to the left of the battery icon, with Charging and Discharging readings to its right. Animated battery arrows connect the house and battery icon. The regular dashboard retains its full-size energy diagram and history panel; tablet kiosk mode fits both panels to the available viewport. The diagram artwork scales with the canvas to retain label alignment. Energy History combines solar, grid import, battery charging/discharging power, and battery level on one graph, with battery percentage on the right axis. Data older than `SOLARMAN_MAX_AGE_SECONDS` (15 minutes by default) is rejected; failed/stale polls clear live battery readings and show `N/A`. Polling every minute does not increase the inverter's cloud upload frequency. Live dashboard values also disappear if the collector has not polled for three minutes. Existing historical Docker volumes are preserved.

If battery status is `Unavailable`, inspect `docker compose logs --tail=50 collector`. Solarman error `2101025` means authentication failed: check the application ID/secret and the email and normal password used to sign in to Solarman. Do not put a pre-hashed password in `SOLARMAN_PASSWORD`; the adapter hashes it. Merchant accounts may also require `SOLARMAN_ORG_ID`. Recreate the collector after editing `.env`: `docker compose up -d --build collector`. Missing battery readings display `N/A`, including when authentication fails before the first reading.

For manual API diagnosis, import [the Postman collection](postman/NRGMon-Solarman.postman_collection.json) into a current Postman release. In its Variables tab, fill `SOLARMAN_APP_ID`, `SOLARMAN_APP_SECRET`, `SOLARMAN_EMAIL`, and your normal `SOLARMAN_PASSWORD` using local values. Send **1 - Obtain token**, **2 - List stations**, then **3 - Battery real-time data**. Password hashing and token capture are automatic. Station ID is populated only for a single-station account; otherwise set the correct plant ID yourself. Set optional `SOLARMAN_ORG_ID` for a merchant account. Request bodies and headers match the collector; responses remain unchanged for inspection. The shipped file contains no credentials. Keep any re-export containing secrets or tokens private.

The house calculation depends on the Myenergi generation CT:

- Leave `MYENERGI_GENERATION_INCLUDES_BATTERY=true` when it measures net solar/battery inverter output, or until the wiring is confirmed; the existing calculation is preserved.
- Set it to `false` only when the CT measures solar alone. House power then becomes generation + net grid import + battery discharge − battery charge. If battery flows are unavailable, house power shows `N/A` while grid readings remain available. Eddi diversion is already included in house consumption.

Start the local stack using both environment selection mechanisms (Compose interpolation and collector configuration):

```sh
ENV_FILE=env.local docker compose --env-file env.local config --quiet
ENV_FILE=env.local docker compose --env-file env.local up -d --build
```

Open [Grafana](http://localhost:3000/d/solar-generation/solar-generation) or the [kiosk](http://localhost:8080). To disable battery collection, set `SOLARMAN_ENABLED=false` and recreate the collector. For Pi deployment, add the same settings to private `deploy.env`; the existing deployment script copies runtime settings into the Pi's private `.env`. Never commit either private configuration file.

### Deploy from a Mac

To deploy to a Raspberry Pi over SSH, copy the private deployment configuration and set the Pi connection details plus your Hoymiles and Myenergi credentials:

```sh
cp deploy.env.example deploy.env
```

Run the deployment script from the repository root:

```sh
./scripts/deploy-pi.sh
```

The script copies `.dockerignore` so private configuration files stay out of the Pi Docker build context. The script installs Docker, Docker Compose, and curl when needed on a Debian/Raspberry Pi OS host; it adds the SSH user to Docker’s group, then starts Docker, copies the application and its private `.env`, builds and starts the stack, and checks that all four containers are running and Grafana is healthy. It enables Docker at boot only after those checks pass; the Compose services use `restart: unless-stopped`, so they start again after the Pi reboots. The SSH user must be able to run `sudo systemctl` and Docker commands on the Pi. `DEPLOY_PASSWORD` is optional: leave it blank to use an SSH key or interactive prompt; if you set it, the script supplies it to SSH/SCP without printing it. Keep `deploy.env` private.

Production was updated on 2026-10-14 with the combined history graph and revised battery layout. Deployment and extended smoke tests passed, including live battery/source metrics and retained historical samples.

## Adapter configuration

Hoymiles uses the S-Miles cloud-login flow. Set `HOYMILES_USERNAME` and `HOYMILES_PASSWORD` to the same credentials used in the S-Miles app. Leave `HOYMILES_STATION_ID` blank to select the first plant in the account, or set it to lock collection to a specific plant. The implementation only calls login/discovery and station-generation endpoints; it never sends control commands or queries grid, battery, consumption, appliance, or EV data.

Myenergi uses the configurable HTTP adapter. It sends read-only `GET` requests to `MYENERGI_STATUS_URL` and the derived or configured Eddi/Zappi status URLs; it supports nested object paths and array indexes such as `data.devices.0.power_w`.

`MYENERGI_AUTH_MODE` may be `oauth_client_credentials`, `bearer`, `api_key`, `basic`, `digest`, or `none`. Use only the official credential flow documented by Myenergi. OAuth needs `TOKEN_URL`, `CLIENT_ID`, and `CLIENT_SECRET`; API-key auth needs `API_KEY` and optionally `API_KEY_HEADER`.

Set `MYENERGI_POWER_PATH` to instantaneous generation and `MYENERGI_ENERGY_PATH` to cumulative energy. Set the corresponding multipliers to `1` for W/Wh, or `1000` for kW/kWh, so the exported metrics are always W/Wh. Choose one `MYENERGI_ENERGY_VALUE_TYPE`:

- `cumulative`: a lifetime counter; a source reset is normalized into a continuously increasing Prometheus value.
- `daily_counter`: a counter that resets daily; readings are accumulated locally.
- `derived_from_power`: ignore `ENERGY_PATH` and estimate Wh from successive power samples.

The collector deliberately rejects negative generation readings.

### Eddi and Zappi live metrics

Set `MYENERGI_HOT_WATER_TEMPERATURE_PATH=eddi.0.tp1` to show the Eddi primary temperature probe in Celsius. The collector displays `N/A` for Myenergi's unavailable-probe values (`-1` and `127`). It also detects solar hot-water diversion from Eddi status `3` and its `div` wattage; boost status `4` is deliberately excluded from solar-diversion power.

Set `MYENERGI_EDDI_STATUS_URL` and `MYENERGI_ZAPPI_STATUS_URL` to the same Myenergi server with `/cgi-jstatus-E` and `/cgi-jstatus-Z` paths. When either is omitted and `MYENERGI_STATUS_URL` uses one of those paths, the collector derives both device URLs automatically and reuses the primary response. The default Zappi paths are `zappi.0.grd` and `zappi.0.gen`. Positive `grd` means grid import and negative `grd` means export. Whole-property consumption is calculated as `gen + grd`, so it includes all load measured at the grid connection, including EV charging and hot-water diversion. Myenergi may omit zero-valued fields; omitted Zappi grid/generation values are interpreted as `0 W`.

## Operations

View collector health in Grafana, or inspect logs with `docker compose logs -f collector`. Persistent data is stored in Docker volumes: `collector-state`, `prometheus-data`, and `grafana-data`. Back up these volumes before Raspberry Pi maintenance or SD-card replacement.

Run the included collector tests with:

```sh
python3 -m unittest discover -s tests
```

Install `requirements.txt` in your active Python environment before running the tests, so the adapter tests execute as well. Run kiosk page-selection and rotation checks with `node --test tests/test_kiosk.cjs`.
