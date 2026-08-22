from __future__ import annotations

import logging
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
    except SourceError as exc:
        UP.labels(*labels).set(0)
        FAILURES.labels(*labels).inc()
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
