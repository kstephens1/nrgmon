"""Read-only Solarman station battery monitoring; no inverter control calls."""
from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass

import httpx

from .adapters import SourceError
from .config import SolarmanConfig


@dataclass(frozen=True)
class BatteryReading:
    soc_percent: float | None
    charge_w: float | None
    discharge_w: float | None
    timestamp: float
    stored_wh: float | None = None


class SolarmanAdapter:
    def __init__(self, config: SolarmanConfig, timeout_seconds: int):
        self.config = config
        self.client = httpx.Client(timeout=timeout_seconds)
        self.token: str | None = None
        self.expires_at = 0.0
        self.station_id = config.station_id

    def _post(self, path: str, payload: dict, authenticated: bool = True, retry: bool = True) -> dict:
        params = {"language": "en"}
        headers = {}
        if authenticated:
            self._ensure_token()
            headers["Authorization"] = f"bearer {self.token}"
        else:
            params["appId"] = self.config.app_id
        try:
            response = self.client.post(self.config.base_url + path, params=params, json=payload, headers=headers)
            if authenticated and retry and response.status_code == 401:
                self.token = None
                return self._post(path, payload, retry=False)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Never include request URLs, payloads, response bodies, or tokens in logs.
            raise SourceError("Solarman request failed (network, HTTP, or JSON error)") from exc
        if not isinstance(body, dict):
            raise SourceError("Solarman response was not an object")
        code = str(body.get("code"))
        if authenticated and retry and code in ("2101019", "AUTH_INVALID_TOKEN", "TOKEN_EXPIRED", "INVALID_TOKEN"):
            self.token = None
            return self._post(path, payload, retry=False)
        if body.get("success") is not True:
            # Only fixed descriptions/codes are safe to log; API messages can
            # contain account identifiers or echoed credentials.
            reasons = {
                "2101002": "request frequency limit",
                "2101009": "application or API locked",
                "2101010": "application allowance exhausted",
                "2101018": "application ID not found",
                "2101019": "invalid token",
                "2101020": "invalid organisation ID",
                "2101021": "invalid application ID",
                "2101023": "access denied",
                "2101025": "authentication failed; verify app ID, app secret, account email, and normal password",
                "2101031": "station not found",
            }
            reason = f"{reasons[code]} ({code})" if code in reasons else "request rejected; check credentials and account permissions"
            operation = "login" if not authenticated else "data query"
            raise SourceError(f"Solarman {operation} failed: {reason}")
        return body

    def _ensure_token(self) -> None:
        if self.token and time.time() < self.expires_at - 60:
            return
        payload = {"email": self.config.email, "appSecret": self.config.app_secret,
                   "password": hashlib.sha256(self.config.password.encode("utf-8")).hexdigest()}
        if self.config.org_id is not None:
            payload["orgId"] = self.config.org_id
        body = self._post("/account/v1.0/token", payload, authenticated=False)
        token = body.get("access_token")
        expiry = self._number(body, "expires_in")
        if not isinstance(token, str) or not token or expiry is None or expiry <= 60:
            raise SourceError("Solarman token response was missing a valid token or expiry")
        self.token = token
        self.expires_at = time.time() + expiry

    def _discover_station(self) -> int:
        body = self._post("/station/v1.0/list", {"page": 1, "size": 2})
        stations = body.get("stationList")
        total = self._number(body, "total")
        if not isinstance(stations, list) or len(stations) != 1 or total is None or total != 1:
            raise SourceError("Set SOLARMAN_STATION_ID: automatic discovery requires exactly one station")
        identifier = stations[0].get("id") if isinstance(stations[0], dict) else None
        if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier <= 0:
            raise SourceError("Solarman station response had no valid ID")
        self.station_id = identifier
        return identifier

    @staticmethod
    def _number(body: dict, key: str) -> float | None:
        raw = body.get(key)
        if isinstance(raw, bool):
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    def fetch(self) -> BatteryReading:
        station_id = self.station_id or self._discover_station()
        body = self._post("/station/v1.0/realTime", {"stationId": station_id})
        timestamp = self._number(body, "lastUpdateTime")
        if timestamp is not None and timestamp > 1e12:
            timestamp /= 1000
        if timestamp is None or timestamp <= 0 or timestamp > time.time() + 60:
            raise SourceError("Solarman battery data has no valid collection timestamp")
        if time.time() - timestamp > self.config.max_age_seconds:
            raise SourceError("Solarman battery data is stale")
        soc = self._number(body, "batterySoc")
        if soc is not None and not 0 <= soc <= 100:
            soc = None
        # Named directional fields can be signed in Solarman responses. Their
        # magnitude is used; never infer direction from undocumented batteryPower.
        charge = self._number(body, "chargePower")
        discharge = self._number(body, "dischargePower")
        charge = None if charge is None else abs(charge) * self.config.power_multiplier
        discharge = None if discharge is None else abs(discharge) * self.config.power_multiplier
        charge = charge if charge is None or math.isfinite(charge) else None
        discharge = discharge if discharge is None or math.isfinite(discharge) else None
        if soc is None and charge is None and discharge is None:
            raise SourceError("Solarman station has no supported battery readings")
        stored = None if soc is None or self.config.capacity_kwh is None else soc / 100 * self.config.capacity_kwh * 1000
        stored = stored if stored is None or math.isfinite(stored) else None
        return BatteryReading(soc, charge, discharge, timestamp, stored)
