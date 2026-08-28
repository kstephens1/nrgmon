# NRGMon

NRGMon is a Raspberry Pi-hosted solar and home-energy dashboard for two solar arrays:

- Array 1: Hoymiles S-Miles Cloud, using the same read-only community login flow as [ioBroker Hoymiles](https://github.com/Eistee82/ioBroker.hoymiles).
- Array 2: Myenergi API.

The collector polls each configured source every 60 seconds and exports Prometheus metrics. Grafana shows live and historical solar generation, grid import/export, whole-property consumption, and Eddi hot-water status. No battery, appliance-specific, EV-status, or device-control fields are collected or stored.

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

The kiosk display fills the browser window with an iframe and changes its target every 30 seconds. It is available at port `8080` by default. With its default configuration it shows the NRGMon Grafana dashboard first.

Set `KIOSK_INTERVAL_SECONDS` to change the delay, and set `KIOSK_PAGES` to a JSON array of page URLs. The `{{HOST}}` token is replaced in the browser with the hostname or IP address used to open the kiosk, which keeps Grafana links portable between Pi deployments. For example:

```dotenv
KIOSK_INTERVAL_SECONDS=45
KIOSK_PAGES=["http://{{HOST}}:3000/d/solar-generation/solar-generation?orgId=1&kiosk","https://example.net/status"]
```

Leave `KIOSK_PAGES=[]` to use only the default NRGMon Grafana page. Pages hosted by other services must permit being displayed in an iframe.

### Deploy from a Mac

To deploy to a Raspberry Pi over SSH, copy the private deployment configuration and set the Pi connection details plus your Hoymiles and Myenergi credentials:

```sh
cp deploy.env.example deploy.env
```

Run the deployment script from the repository root:

```sh
./scripts/deploy-pi.sh
```

The script installs Docker, Docker Compose, and curl when needed on a Debian/Raspberry Pi OS host; it adds the SSH user to Docker’s group, then starts Docker, copies the application and its private `.env`, builds and starts the stack, and checks that all three containers are running and Grafana is healthy. It enables Docker at boot only after those checks pass; the Compose services use `restart: unless-stopped`, so they start again after the Pi reboots. The SSH user must be able to run `sudo systemctl` and Docker commands on the Pi. `DEPLOY_PASSWORD` is optional: leave it blank to use an SSH key or interactive prompt; if you set it, the script supplies it to SSH/SCP without printing it. Keep `deploy.env` private.

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
