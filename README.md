# NRGMon

NRGMon is a Raspberry Pi-hosted, generation-only dashboard for two solar arrays:

- Array 1: Hoymiles S-Miles Cloud, using the same read-only community login flow as [ioBroker Hoymiles](https://github.com/Eistee82/ioBroker.hoymiles).
- Array 2: Myenergi API.

The collector polls each configured source every 60 seconds, exports Prometheus metrics, and Grafana shows live, daily, monthly, and combined generation. No grid, household consumption, battery, appliance, EV, or device-control fields are collected or stored.

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

5. Open `http://<pi-lan-address>:3000`. Grafana is intentionally anonymous and view-only; do not expose this port to the public internet.

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

Myenergi uses the configurable HTTP adapter. It sends a read-only `GET` to `MYENERGI_STATUS_URL`, reads numeric fields from the JSON response, and supports nested object paths and array indexes such as `data.devices.0.power_w`.

`MYENERGI_AUTH_MODE` may be `oauth_client_credentials`, `bearer`, `api_key`, `basic`, `digest`, or `none`. Use only the official credential flow documented by Myenergi. OAuth needs `TOKEN_URL`, `CLIENT_ID`, and `CLIENT_SECRET`; API-key auth needs `API_KEY` and optionally `API_KEY_HEADER`.

Set `MYENERGI_POWER_PATH` to instantaneous generation and `MYENERGI_ENERGY_PATH` to cumulative energy. Set the corresponding multipliers to `1` for W/Wh, or `1000` for kW/kWh, so the exported metrics are always W/Wh. Choose one `MYENERGI_ENERGY_VALUE_TYPE`:

- `cumulative`: a lifetime counter; a source reset is normalized into a continuously increasing Prometheus value.
- `daily_counter`: a counter that resets daily; readings are accumulated locally.
- `derived_from_power`: ignore `ENERGY_PATH` and estimate Wh from successive power samples.

The collector deliberately rejects negative generation readings.

## Operations

View collector health in Grafana, or inspect logs with `docker compose logs -f collector`. Persistent data is stored in Docker volumes: `collector-state`, `prometheus-data`, and `grafana-data`. Back up these volumes before Raspberry Pi maintenance or SD-card replacement.

Run the included normalizer tests with:

```sh
python3 -m unittest discover -s tests
```
