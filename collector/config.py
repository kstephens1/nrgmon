from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Mapping


class ConfigError(ValueError):
    """Raised when required collector configuration is missing or invalid."""


@dataclass(frozen=True)
class SourceConfig:
    source: str
    array: str
    enabled: bool
    status_url: str
    auth_mode: str
    power_path: str
    energy_path: str
    energy_value_type: str
    power_multiplier: float
    energy_multiplier: float
    headers: Mapping[str, str]
    hot_water_temperature_path: str = ""
    eddi_status_url: str = ""
    zappi_status_url: str = ""
    zappi_grid_power_path: str = "zappi.0.grd"
    zappi_generation_power_path: str = "zappi.0.gen"
    api_key: str | None = None
    api_key_header: str = "X-API-Key"
    token: str | None = None
    username: str | None = None
    password: str | None = None
    token_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scope: str | None = None
    station_id: int | None = None
    app_version: str = "2.9.0"


@dataclass(frozen=True)
class AppConfig:
    poll_interval_seconds: int
    request_timeout_seconds: int
    metrics_port: int
    state_file: str
    sources: tuple[SourceConfig, ...]


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool(name: str, default: bool = False) -> bool:
    value = _env(name, str(default)).lower()
    return value in {"1", "true", "yes", "on"}


def _headers(prefix: str) -> Mapping[str, str]:
    raw = _env(f"{prefix}_HEADERS_JSON", "{}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{prefix}_HEADERS_JSON must contain a JSON object") from exc
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ConfigError(f"{prefix}_HEADERS_JSON must be a string-to-string JSON object")
    return value


def _device_status_url(prefix: str, source: str, status_url: str, device: str) -> str:
    configured = _env(f"{prefix}_{device}_STATUS_URL")
    if configured:
        return configured
    if source == "myenergi" and status_url.endswith(("/cgi-jstatus-E", "/cgi-jstatus-Z")):
        return f"{status_url[:-1]}{device[0]}"
    return ""


def _source(prefix: str, source: str, array: str) -> SourceConfig:
    enabled = _bool(f"{prefix}_ENABLED")
    status_url = _env(f"{prefix}_STATUS_URL")
    config = SourceConfig(
        source=source,
        array=array,
        enabled=enabled,
        status_url=status_url,
        auth_mode=_env(f"{prefix}_AUTH_MODE", "none").lower(),
        power_path=_env(f"{prefix}_POWER_PATH"),
        energy_path=_env(f"{prefix}_ENERGY_PATH"),
        energy_value_type=_env(f"{prefix}_ENERGY_VALUE_TYPE", "cumulative").lower(),
        power_multiplier=float(_env(f"{prefix}_POWER_MULTIPLIER", "1")),
        energy_multiplier=float(_env(f"{prefix}_ENERGY_MULTIPLIER", "1")),
        headers=_headers(prefix),
        hot_water_temperature_path=_env(
            f"{prefix}_HOT_WATER_TEMPERATURE_PATH",
            "eddi.0.tp1" if source == "myenergi" else "",
        ),
        eddi_status_url=_device_status_url(prefix, source, status_url, "EDDI"),
        zappi_status_url=_device_status_url(prefix, source, status_url, "ZAPPI"),
        zappi_grid_power_path=_env(f"{prefix}_ZAPPI_GRID_POWER_PATH", "zappi.0.grd"),
        zappi_generation_power_path=_env(f"{prefix}_ZAPPI_GENERATION_POWER_PATH", "zappi.0.gen"),
        api_key=_env(f"{prefix}_API_KEY") or None,
        api_key_header=_env(f"{prefix}_API_KEY_HEADER", "X-API-Key"),
        token=_env(f"{prefix}_TOKEN") or None,
        username=_env(f"{prefix}_USERNAME") or None,
        password=_env(f"{prefix}_PASSWORD") or None,
        token_url=_env(f"{prefix}_TOKEN_URL") or None,
        client_id=_env(f"{prefix}_CLIENT_ID") or None,
        client_secret=_env(f"{prefix}_CLIENT_SECRET") or None,
        scope=_env(f"{prefix}_SCOPE") or None,
        station_id=int(_env(f"{prefix}_STATION_ID")) if _env(f"{prefix}_STATION_ID") else None,
        app_version=_env(f"{prefix}_APP_VERSION", "2.9.0"),
    )
    if not enabled:
        return config
    if config.auth_mode == "smiles_cloud":
        if source != "hoymiles":
            raise ConfigError("smiles_cloud authentication is only valid for Hoymiles")
        if not config.username or not config.password:
            raise ConfigError("HOYMILES_USERNAME and HOYMILES_PASSWORD are required")
        return config
    required = [("STATUS_URL", config.status_url), ("POWER_PATH", config.power_path)]
    if config.energy_value_type != "derived_from_power":
        required.append(("ENERGY_PATH", config.energy_path))
    missing = [name for name, value in required if not value]
    if missing:
        raise ConfigError(f"{prefix} is enabled but missing {', '.join(missing)}")
    if config.auth_mode not in {"none", "bearer", "api_key", "basic", "digest", "oauth_client_credentials", "smiles_cloud"}:
        raise ConfigError(f"{prefix}_AUTH_MODE is not supported")
    if config.energy_value_type not in {"cumulative", "daily_counter", "derived_from_power"}:
        raise ConfigError(f"{prefix}_ENERGY_VALUE_TYPE is not supported")
    if config.zappi_status_url and (not config.zappi_grid_power_path or not config.zappi_generation_power_path):
        raise ConfigError(
            f"{prefix}_ZAPPI_STATUS_URL requires {prefix}_ZAPPI_GRID_POWER_PATH "
            f"and {prefix}_ZAPPI_GENERATION_POWER_PATH"
        )
    if config.power_multiplier <= 0 or config.energy_multiplier <= 0:
        raise ConfigError(f"{prefix} multipliers must be positive")
    return config


def load_config() -> AppConfig:
    sources = (_source("HOYMILES", "hoymiles", "array_1"), _source("MYENERGI", "myenergi", "array_2"))
    active = tuple(source for source in sources if source.enabled)
    if not active:
        raise ConfigError("At least one source must be enabled")
    return AppConfig(
        poll_interval_seconds=int(_env("POLL_INTERVAL_SECONDS", "60")),
        request_timeout_seconds=int(_env("REQUEST_TIMEOUT_SECONDS", "20")),
        metrics_port=int(_env("METRICS_PORT", "8000")),
        state_file=_env("STATE_FILE", "/state/normalizer-state.json"),
        sources=active,
    )
