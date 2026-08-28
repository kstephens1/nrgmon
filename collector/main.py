from __future__ import annotations

import logging
import math
import time

from prometheus_client import Counter, Gauge, start_http_server

from .adapters import HoymilesSCloudAdapter, HttpSourceAdapter, SourceError
from .config import ConfigError, load_config
from .normalizer import EnergyNormalizer

POWER = Gauge("solar_generation_power_watts", "Current solar generation", ["source", "array"])
ENERGY = Gauge("solar_energy_generated_watt_hours_total", "Cumulative solar energy generated", ["source", "array"])
UP = Gauge("solar_source_up", "Whether the last source poll succeeded", ["source", "array"])
LAST_SUCCESS = Gauge("solar_source_last_success_unixtime", "Unix time of the last successful source poll", ["source", "array"])
FAILURES = Counter("solar_source_poll_failures_total", "Failed source polls", ["source", "array"])
HOT_WATER_TEMPERATURE = Gauge("hot_water_temperature_celsius", "Current hot water temperature", ["source", "array"])
EDDI_SOLAR_DIVERSION_ACTIVE = Gauge("eddi_solar_diversion_active", "Whether Eddi is actively diverting solar power", ["source", "array"])
EDDI_SOLAR_DIVERTED_POWER = Gauge("eddi_solar_diverted_power_watts", "Solar power currently diverted by Eddi", ["source", "array"])
GRID_IMPORT_POWER = Gauge("grid_import_power_watts", "Current power imported from the grid", ["source", "array"])
GRID_EXPORT_POWER = Gauge("grid_export_power_watts", "Current power exported to the grid", ["source", "array"])
HOUSE_CONSUMPTION_POWER = Gauge("house_consumption_power_watts", "Current whole-property power consumption", ["source", "array"])
MYENERGI_EDDI_UP = Gauge("myenergi_eddi_status_up", "Whether the last MyEnergi Eddi status poll succeeded", ["source", "array"])
MYENERGI_ZAPPI_UP = Gauge("myenergi_zappi_status_up", "Whether the last MyEnergi Zappi status poll succeeded", ["source", "array"])


def _set_optional(gauge: Gauge, labels: tuple[str, str], value: float | None) -> None:
    gauge.labels(*labels).set(math.nan if value is None else value)


def grid_flows(grid_power_w: float | None, generation_power_w: float | None) -> tuple[float, float, float] | None:
    if grid_power_w is None or generation_power_w is None:
        return None
    return max(grid_power_w, 0), max(-grid_power_w, 0), generation_power_w + grid_power_w


def _set_myenergi_metrics(labels: tuple[str, str], reading) -> None:
    _set_optional(HOT_WATER_TEMPERATURE, labels, reading.hot_water_temperature_c)
    _set_optional(
        EDDI_SOLAR_DIVERSION_ACTIVE,
        labels,
        None if reading.eddi_solar_diversion_active is None else float(reading.eddi_solar_diversion_active),
    )
    _set_optional(EDDI_SOLAR_DIVERTED_POWER, labels, reading.eddi_solar_diverted_power_w)
    flows = grid_flows(reading.grid_power_w, reading.site_generation_power_w)
    if flows is None:
        _set_optional(GRID_IMPORT_POWER, labels, None)
        _set_optional(GRID_EXPORT_POWER, labels, None)
        _set_optional(HOUSE_CONSUMPTION_POWER, labels, None)
    else:
        GRID_IMPORT_POWER.labels(*labels).set(flows[0])
        GRID_EXPORT_POWER.labels(*labels).set(flows[1])
        HOUSE_CONSUMPTION_POWER.labels(*labels).set(flows[2])
    _set_optional(MYENERGI_EDDI_UP, labels, None if reading.eddi_status_up is None else float(reading.eddi_status_up))
    _set_optional(MYENERGI_ZAPPI_UP, labels, None if reading.zappi_status_up is None else float(reading.zappi_status_up))


def poll(adapter: HttpSourceAdapter, normalizer: EnergyNormalizer) -> None:
    config = adapter.config
    labels = (config.source, config.array)
    try:
        reading = adapter.fetch()
        energy_wh = normalizer.normalize(config.source, reading.power_w, reading.energy_wh, config.energy_value_type, reading.timestamp)
        POWER.labels(*labels).set(reading.power_w)
        ENERGY.labels(*labels).set(energy_wh)
        UP.labels(*labels).set(1)
        LAST_SUCCESS.labels(*labels).set(reading.timestamp)
        if config.source == "myenergi":
            _set_myenergi_metrics(labels, reading)
    except SourceError as exc:
        UP.labels(*labels).set(0)
        FAILURES.labels(*labels).inc()
        if config.source == "myenergi":
            _set_optional(HOT_WATER_TEMPERATURE, labels, None)
            _set_optional(EDDI_SOLAR_DIVERSION_ACTIVE, labels, None)
            _set_optional(EDDI_SOLAR_DIVERTED_POWER, labels, None)
            _set_optional(GRID_IMPORT_POWER, labels, None)
            _set_optional(GRID_EXPORT_POWER, labels, None)
            _set_optional(HOUSE_CONSUMPTION_POWER, labels, None)
            MYENERGI_EDDI_UP.labels(*labels).set(0)
            MYENERGI_ZAPPI_UP.labels(*labels).set(0)
        logging.warning("%s poll failed: %s", config.source, exc)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = load_config()
    except (ConfigError, ValueError) as exc:
        raise SystemExit(f"Configuration error: {exc}")
    adapters = [
        HoymilesSCloudAdapter(source, config.request_timeout_seconds)
        if source.auth_mode == "smiles_cloud"
        else HttpSourceAdapter(source, config.request_timeout_seconds)
        for source in config.sources
    ]
    normalizer = EnergyNormalizer(config.state_file)
    start_http_server(config.metrics_port)
    logging.info("Collector started for %s", ", ".join(adapter.config.source for adapter in adapters))
    while True:
        started = time.monotonic()
        for adapter in adapters:
            poll(adapter, normalizer)
        time.sleep(max(0, config.poll_interval_seconds - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
