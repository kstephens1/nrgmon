from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import dataclass
from typing import Any

import httpx
from argon2.low_level import Type, hash_secret_raw

from .config import SourceConfig


class SourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Reading:
    power_w: float
    energy_wh: float | None
    timestamp: float


def json_path(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(path)
    return current


class HttpSourceAdapter:
    def __init__(self, config: SourceConfig, timeout_seconds: int):
        self.config = config
        self.timeout = timeout_seconds
        self._oauth_token: str | None = None
        self._oauth_expires_at = 0.0

    def _auth(self) -> httpx.Auth | None:
        if self.config.auth_mode == "basic":
            return httpx.BasicAuth(self.config.username or "", self.config.password or "")
        if self.config.auth_mode == "digest":
            return httpx.DigestAuth(self.config.username or "", self.config.password or "")
        return None

    def _oauth_headers(self) -> dict[str, str]:
        if self._oauth_token and time.time() < self._oauth_expires_at - 30:
            return {"Authorization": f"Bearer {self._oauth_token}"}
        if not all((self.config.token_url, self.config.client_id, self.config.client_secret)):
            raise SourceError("OAuth client credentials require TOKEN_URL, CLIENT_ID, and CLIENT_SECRET")
        data = {"grant_type": "client_credentials"}
        if self.config.scope:
            data["scope"] = self.config.scope
        try:
            response = httpx.post(
                self.config.token_url,
                data=data,
                auth=(self.config.client_id, self.config.client_secret),
                timeout=self.timeout,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"OAuth token request failed: {exc}") from exc
        token = body.get("access_token")
        if not isinstance(token, str):
            raise SourceError("OAuth response did not contain access_token")
        self._oauth_token = token
        self._oauth_expires_at = time.time() + float(body.get("expires_in", 300))
        return {"Authorization": f"Bearer {token}"}

    def fetch(self) -> Reading:
        headers = dict(self.config.headers)
        if self.config.auth_mode == "bearer":
            if not self.config.token:
                raise SourceError("Bearer authentication requires TOKEN")
            headers["Authorization"] = f"Bearer {self.config.token}"
        elif self.config.auth_mode == "api_key":
            if not self.config.api_key:
                raise SourceError("API-key authentication requires API_KEY")
            headers[self.config.api_key_header] = self.config.api_key
        elif self.config.auth_mode == "oauth_client_credentials":
            headers.update(self._oauth_headers())
        try:
            response = httpx.get(self.config.status_url, headers=headers, auth=self._auth(), timeout=self.timeout)
            response.raise_for_status()
            body = response.json()
            power_w = float(json_path(body, self.config.power_path)) * self.config.power_multiplier
            energy_wh = None if self.config.energy_value_type == "derived_from_power" else float(json_path(body, self.config.energy_path)) * self.config.energy_multiplier
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise SourceError(str(exc)) from exc
        if power_w < 0 or energy_wh is not None and energy_wh < 0:
            raise SourceError("Generation values cannot be negative")
        return Reading(power_w=power_w, energy_wh=energy_wh, timestamp=time.time())


class HoymilesSCloudAdapter:
    """Read-only S-Miles Home adapter ported from the ioBroker Hoymiles flow."""

    default_host = "https://neapi.hoymiles.com"

    def __init__(self, config: SourceConfig, timeout_seconds: int):
        self.config = config
        self.timeout = timeout_seconds
        self.client = httpx.Client(timeout=timeout_seconds)
        self.base_url = self.default_host
        self.data_center = 0
        self.token: str | None = None
        self.token_time = 0.0
        self.profile: str | None = None
        self.station_id = config.station_id

    def _headers(self, authenticated: bool = False) -> dict[str, str]:
        headers = {"User-Agent": f"sma/ad/{self.config.app_version}/159/{self.data_center}"}
        if authenticated and self.token:
            headers["Authorization"] = self.token
        return headers

    def _post(self, path: str, payload: dict[str, object], host: str | None = None, authenticated: bool = False) -> dict[str, Any]:
        try:
            response = self.client.post(f"{host or self.base_url}{path}", json=payload, headers=self._headers(authenticated))
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"S-Miles request failed: {exc}") from exc
        if not isinstance(body, dict):
            raise SourceError("S-Miles response was not an object")
        return body

    @staticmethod
    def _require_success(body: dict[str, Any], label: str) -> dict[str, Any]:
        if str(body.get("status")) != "0":
            raise SourceError(f"S-Miles {label} failed: {body.get('message', 'unknown error')}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise SourceError(f"S-Miles {label} response had no data object")
        return data

    def _discover_region(self) -> None:
        try:
            body = self._post("/iam/pub/0/c/region_c", {"email": self.config.username})
            data = self._require_success(body, "region discovery")
            host = data.get("login_url")
            if isinstance(host, str) and host.startswith("https://"):
                self.base_url = host.rstrip("/")
            if isinstance(data.get("dc"), int):
                self.data_center = data["dc"]
        except SourceError:
            # Region discovery is optional; the default host is the documented fallback.
            return

    def _challenge(self, salt: str | None) -> str:
        password = (self.config.password or "").encode()
        if salt:
            try:
                return hash_secret_raw(
                    secret=password,
                    salt=bytes.fromhex(salt),
                    time_cost=3,
                    memory_cost=32768,
                    parallelism=1,
                    hash_len=32,
                    type=Type.ID,
                    version=19,
                ).hex()
            except (TypeError, ValueError) as exc:
                raise SourceError("S-Miles returned an invalid password salt") from exc
        return f"{hashlib.md5(password).hexdigest()}.{base64.b64encode(hashlib.sha256(password).digest()).decode()}"

    def _login(self) -> None:
        self._discover_region()
        pre = self._require_success(self._post("/iam/pub/3/auth/pre-insp", {"u": self.config.username}), "pre-login")
        nonce = pre.get("n")
        if not isinstance(nonce, str):
            raise SourceError("S-Miles pre-login response had no nonce")
        challenge = self._challenge(pre.get("a") if isinstance(pre.get("a"), str) else None)
        login = self._require_success(
            self._post("/iam/pub/3/auth/login", {"u": self.config.username, "ch": challenge, "n": nonce}),
            "login",
        )
        token = login.get("token")
        if not isinstance(token, str) or not token:
            raise SourceError("S-Miles login response had no token")
        self.token = token
        self.token_time = time.time()
        try:
            probe = self._post("/pvm/api/0/station/select_by_page", {"page": 1, "page_size": 1}, authenticated=True)
            self.profile = "installer" if str(probe.get("status")) == "0" else "home"
        except SourceError:
            self.profile = "home"

    def _ensure_login(self) -> None:
        if not self.token or time.time() - self.token_time > 3300:
            self._login()

    def _data_path(self, home: str, installer: str) -> tuple[str, str]:
        if self.profile == "home":
            return self.default_host, home
        return self.base_url, installer

    def _discover_station(self) -> int:
        host, path = self._data_path("/pvmc/api/0/station/select_by_page_c", "/pvm/api/0/station/select_by_page")
        data = self._require_success(self._post(path, {"page": 1, "page_size": 100}, host, authenticated=True), "station discovery")
        stations = data.get("list")
        if not isinstance(stations, list):
            raise SourceError("S-Miles station list was missing")
        for station in stations:
            if not isinstance(station, dict):
                continue
            identifier = station.get("sid", station.get("id"))
            if isinstance(identifier, int) and (self.station_id is None or identifier == self.station_id):
                self.station_id = identifier
                return identifier
        raise SourceError("Configured S-Miles station was not found")

    def fetch(self) -> Reading:
        self._ensure_login()
        station_id = self.station_id or self._discover_station()
        host, path = self._data_path(
            "/pvmc/api/0/station_data/count_station_real_data_c",
            "/pvm-data/api/0/station/data/count_station_real_data",
        )
        data = self._require_success(self._post(path, {"sid": station_id}, host, authenticated=True), "generation query")
        try:
            power_w = float(data["real_power"])
            energy_wh = float(data["total_eq"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceError("S-Miles generation response was missing power or energy") from exc
        if power_w < 0 or energy_wh < 0:
            raise SourceError("S-Miles generation values cannot be negative")
        return Reading(power_w=power_w, energy_wh=energy_wh, timestamp=time.time())
