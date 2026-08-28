import os
import unittest
from unittest.mock import patch

try:
    import httpx

    from collector.adapters import HttpSourceAdapter
    from collector.config import SourceConfig, _device_status_url
    from collector.main import grid_flows
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("adapter tests require the collector dependencies") from exc


class FakeResponse:
    def __init__(self, body=None, error=None):
        self.body = body
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.body


def myenergi_config(**overrides):
    values = {
        "source": "myenergi",
        "array": "array_2",
        "enabled": True,
        "status_url": "https://example.test/cgi-jstatus-E",
        "auth_mode": "none",
        "power_path": "eddi.0.gen",
        "energy_path": "eddi.0.energy",
        "energy_value_type": "cumulative",
        "power_multiplier": 1,
        "energy_multiplier": 1,
        "headers": {},
        "hot_water_temperature_path": "eddi.0.tp1",
        "eddi_status_url": "https://example.test/cgi-jstatus-E",
        "zappi_status_url": "https://example.test/cgi-jstatus-Z",
        "zappi_grid_power_path": "zappi.0.grd",
        "zappi_generation_power_path": "zappi.0.gen",
    }
    values.update(overrides)
    return SourceConfig(**values)


class HttpSourceAdapterTests(unittest.TestCase):
    def test_collects_eddi_and_zappi_live_readings(self):
        eddi = {"eddi": [{"gen": 500, "energy": 1000, "tp1": 52, "sta": 3, "div": 1800}]}
        zappi = {"zappi": [{"grd": -300, "gen": 2500}]}
        adapter = HttpSourceAdapter(myenergi_config(), 5)
        with patch("collector.adapters.httpx.get", side_effect=[FakeResponse(eddi), FakeResponse(zappi)]):
            reading = adapter.fetch()

        self.assertEqual(reading.hot_water_temperature_c, 52)
        self.assertTrue(reading.eddi_solar_diversion_active)
        self.assertEqual(reading.eddi_solar_diverted_power_w, 1800)
        self.assertEqual(reading.grid_power_w, -300)
        self.assertEqual(reading.site_generation_power_w, 2500)
        self.assertTrue(reading.eddi_status_up)
        self.assertTrue(reading.zappi_status_up)

    def test_primary_zappi_response_is_reused_while_eddi_is_fetched_separately(self):
        zappi = {"zappi": [{"grd": 400, "gen": 1200}]}
        eddi = {"eddi": [{"tp1": 48, "sta": 1}]}
        adapter = HttpSourceAdapter(
            myenergi_config(
                status_url="https://example.test/cgi-jstatus-Z",
                power_path="zappi.0.gen",
                energy_value_type="derived_from_power",
            ),
            5,
        )
        with patch("collector.adapters.httpx.get", side_effect=[FakeResponse(zappi), FakeResponse(eddi)]) as get:
            reading = adapter.fetch()

        self.assertEqual(get.call_count, 2)
        self.assertEqual(reading.hot_water_temperature_c, 48)
        self.assertEqual(reading.grid_power_w, 400)
        self.assertTrue(reading.eddi_status_up)
        self.assertTrue(reading.zappi_status_up)

    def test_unavailable_temperature_and_boost_are_not_solar_diversion(self):
        eddi = {"eddi": [{"gen": 500, "energy": 1000, "tp1": 127, "sta": 4, "div": 3000}]}
        adapter = HttpSourceAdapter(myenergi_config(zappi_status_url=""), 5)
        with patch("collector.adapters.httpx.get", return_value=FakeResponse(eddi)):
            reading = adapter.fetch()

        self.assertIsNone(reading.hot_water_temperature_c)
        self.assertFalse(reading.eddi_solar_diversion_active)
        self.assertEqual(reading.eddi_solar_diverted_power_w, 0)

    def test_omitted_zappi_zero_values_are_zero_and_failed_request_is_unavailable(self):
        eddi = {"eddi": [{"gen": 500, "energy": 1000, "tp1": -1, "sta": 3}]}
        adapter = HttpSourceAdapter(myenergi_config(), 5)
        with patch("collector.adapters.httpx.get", side_effect=[FakeResponse(eddi), FakeResponse({"zappi": [{}]})]):
            reading = adapter.fetch()
        self.assertEqual((reading.grid_power_w, reading.site_generation_power_w, reading.zappi_status_up), (0, 0, True))
        self.assertFalse(reading.eddi_solar_diversion_active)
        self.assertEqual(reading.eddi_solar_diverted_power_w, 0)

        adapter = HttpSourceAdapter(myenergi_config(), 5)
        with patch("collector.adapters.httpx.get", side_effect=[FakeResponse(eddi), FakeResponse(error=httpx.HTTPError("offline"))]):
            reading = adapter.fetch()
        self.assertIsNone(reading.grid_power_w)
        self.assertFalse(reading.zappi_status_up)

    def test_missing_or_malformed_zappi_device_is_unavailable(self):
        eddi = {"eddi": [{"gen": 500, "energy": 1000, "tp1": 50, "sta": 1}]}
        for zappi in ({}, {"zappi": [{"grd": "unknown", "gen": 1000}]}):
            adapter = HttpSourceAdapter(myenergi_config(), 5)
            with self.subTest(zappi=zappi), patch(
                "collector.adapters.httpx.get", side_effect=[FakeResponse(eddi), FakeResponse(zappi)]
            ):
                reading = adapter.fetch()
            self.assertIsNone(reading.grid_power_w)
            self.assertIsNone(reading.site_generation_power_w)
            self.assertFalse(reading.zappi_status_up)


class GridFlowsTests(unittest.TestCase):
    def test_import_and_export_are_separated(self):
        self.assertEqual(grid_flows(400, 2000), (400, 0, 2400))
        self.assertEqual(grid_flows(-400, 2000), (0, 400, 1600))
        self.assertIsNone(grid_flows(None, 2000))


class MyenergiConfigTests(unittest.TestCase):
    def test_device_urls_are_derived_from_either_status_url_and_can_be_overridden(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                _device_status_url("MYENERGI", "myenergi", "https://s18.myenergi.net/cgi-jstatus-E", "ZAPPI"),
                "https://s18.myenergi.net/cgi-jstatus-Z",
            )
            self.assertEqual(
                _device_status_url("MYENERGI", "myenergi", "https://s18.myenergi.net/cgi-jstatus-Z", "EDDI"),
                "https://s18.myenergi.net/cgi-jstatus-E",
            )
        with patch.dict(os.environ, {"MYENERGI_ZAPPI_STATUS_URL": "https://example.test/zappi"}, clear=True):
            self.assertEqual(
                _device_status_url("MYENERGI", "myenergi", "https://s18.myenergi.net/cgi-jstatus-E", "ZAPPI"),
                "https://example.test/zappi",
            )


if __name__ == "__main__":
    unittest.main()
