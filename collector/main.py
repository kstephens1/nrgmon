from __future__ import annotations

import logging
import math
import time

from prometheus_client import Counter, Gauge, start_http_server

from .adapters import HoymilesSCloudAdapter, HttpSourceAdapter, SourceError
from .config import ConfigError, load_config
from .normalizer import EnergyNormalizer
from .solarman import SolarmanAdapter

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

BATTERY_SOC = Gauge("battery_state_of_charge_percent", "Battery state of charge", ["source"])
BATTERY_CHARGE = Gauge("battery_charge_power_watts", "Power flowing into the battery", ["source"])
BATTERY_DISCHARGE = Gauge("battery_discharge_power_watts", "Power flowing out of the battery", ["source"])
BATTERY_STORED = Gauge("battery_stored_energy_watt_hours", "Estimated stored energy from configured capacity and SOC", ["source"])
BATTERY_UP = Gauge("battery_source_up", "Whether the last battery poll succeeded", ["source"])
BATTERY_LAST_SUCCESS = Gauge("battery_source_last_success_unixtime", "Last successful battery API poll", ["source"])
BATTERY_LAST_POLL = Gauge("battery_source_last_poll_unixtime", "Last battery poll attempt", ["source"])
BATTERY_TIMESTAMP = Gauge("battery_reading_unixtime", "Battery API collection timestamp", ["source"])
BATTERY_FAILURES = Counter("battery_source_poll_failures_total", "Failed battery polls", ["source"])
BATTERY_STATE = Gauge("battery_state", "Battery state: -1 unavailable, 0 idle, 1 charging, 2 discharging, 3 both flows", ["source"])


def poll_battery(adapter: SolarmanAdapter):
    labels = ("solarman",)
    BATTERY_LAST_POLL.labels(*labels).set(time.time())
    try:
        reading = adapter.fetch()
        for gauge, value in ((BATTERY_SOC, reading.soc_percent), (BATTERY_CHARGE, reading.charge_w),
                             (BATTERY_DISCHARGE, reading.discharge_w), (BATTERY_STORED, reading.stored_wh)):
            _set_optional(gauge, labels, value)
        BATTERY_UP.labels(*labels).set(1)
        BATTERY_LAST_SUCCESS.labels(*labels).set(time.time())
        BATTERY_TIMESTAMP.labels(*labels).set(reading.timestamp)
        state = -1 if reading.charge_w is None or reading.discharge_w is None else (
            int(reading.charge_w > 0) + 2 * int(reading.discharge_w > 0))
        BATTERY_STATE.labels(*labels).set(state)
        return reading
    except SourceError as exc:
        BATTERY_UP.labels(*labels).set(0)
        BATTERY_FAILURES.labels(*labels).inc()
        BATTERY_STATE.labels(*labels).set(-1)
        for gauge in (BATTERY_SOC, BATTERY_CHARGE, BATTERY_DISCHARGE, BATTERY_STORED):
            _set_optional(gauge, labels, None)
        logging.warning("Battery poll failed: %s", exc)
        return None


def _set_optional(gauge: Gauge, labels: tuple[str, ...], value: float | None) -> None:
    gauge.labels(*labels).set(math.nan if value is None else value)


def grid_flows(grid_power_w: float | None, generation_power_w: float | None,
               charge_w: float | None = 0, discharge_w: float | None = 0) -> tuple[float, float, float] | None:
    if grid_power_w is None or generation_power_w is None:
        return None
    house = math.nan if charge_w is None or discharge_w is None else generation_power_w + grid_power_w + discharge_w - charge_w
    return max(grid_power_w, 0), max(-grid_power_w, 0), house if house >= 0 else math.nan


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


def poll(adapter: HttpSourceAdapter, normalizer: EnergyNormalizer):
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
        return reading
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
        return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # httpx INFO request logs contain the Solarman appId query parameter.
    logging.getLogger("httpx").setLevel(logging.WARNING)
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
    battery = SolarmanAdapter(config.solarman, config.request_timeout_seconds) if config.solarman else None
    start_http_server(config.metrics_port)
    logging.info("Collector started for %s", ", ".join(adapter.config.source for adapter in adapters))
    while True:
        started = time.monotonic()
        myenergi_reading = None
        for adapter in adapters:
            reading = poll(adapter, normalizer)
            if adapter.config.source == "myenergi":
                myenergi_reading = reading
        if battery:
            battery_reading = poll_battery(battery)
            if not config.myenergi_generation_includes_battery and myenergi_reading is not None:
                flows = grid_flows(myenergi_reading.grid_power_w, myenergi_reading.site_generation_power_w,
                                   battery_reading.charge_w if battery_reading else None,
                                   battery_reading.discharge_w if battery_reading else None)
                if flows is not None:
                    HOUSE_CONSUMPTION_POWER.labels("myenergi", "array_2").set(flows[2])
        time.sleep(max(0, config.poll_interval_seconds - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
