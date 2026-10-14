import hashlib
import math
import os
import time
import unittest
from dataclasses import replace
from unittest.mock import patch

import httpx

from collector.adapters import SourceError
from collector.config import ConfigError, SolarmanConfig, load_config
from collector.main import BATTERY_SOC, BATTERY_STATE, BATTERY_UP, grid_flows, poll_battery
from collector.solarman import SolarmanAdapter


class SolarmanTests(unittest.TestCase):
    def setUp(self):
        self.config = SolarmanConfig("https://example.test", "test-app", "test-secret", "test@example.test",
                                     "password with spaces ", station_id=123, capacity_kwh=10)
        self.requests = []
        self.responses = []
        self.adapter = SolarmanAdapter(self.config, 5)
        self.adapter.client.close()
        self.adapter.client = httpx.Client(transport=httpx.MockTransport(self.handle))
        self.addCleanup(self.adapter.client.close)

    def handle(self, request):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, int):
            return httpx.Response(response)
        return httpx.Response(200, json=response)

    def token(self, **overrides):
        return dict(success=True, access_token="test-token", expires_in="3600", **overrides)

    def reading(self, **overrides):
        body = dict(success=True, batterySoc=72, chargePower=1000, dischargePower=0, lastUpdateTime=time.time())
        body.update(overrides)
        return body

    def test_login_hash_caching_and_directional_power(self):
        import json
        self.responses = [self.token(), self.reading(chargePower=-1000), self.reading(chargePower=0, dischargePower=450)]
        reading = self.adapter.fetch()
        self.assertEqual((reading.soc_percent, reading.charge_w, reading.discharge_w), (72, 1000, 0))
        self.assertAlmostEqual(reading.stored_wh, 7200)
        outgoing = self.adapter.fetch()
        self.assertEqual(outgoing.discharge_w, 450)
        self.assertEqual(len(self.requests), 3)
        login = self.requests[0]
        self.assertEqual(login.url.params['appId'], 'test-app')
        body = json.loads(login.content)
        self.assertEqual(body['password'], hashlib.sha256(self.config.password.encode()).hexdigest())
        self.assertEqual(body['email'], self.config.email)
        self.assertEqual(body['appSecret'], self.config.app_secret)
        self.assertNotIn('orgId', body)
        self.assertEqual(self.requests[1].headers['authorization'], 'bearer test-token')
        self.assertNotIn('appId', self.requests[1].url.params)

    def test_token_refresh_on_expiry_and_unauthorized_retry_is_bounded(self):
        self.responses = [self.token(), self.reading()]
        self.adapter.fetch()
        self.adapter.expires_at = 0
        self.responses = [self.token(), 401, self.token(), self.reading()]
        self.adapter.fetch()
        self.assertEqual(len(self.requests), 6)
        self.responses = [401, self.token(), 401]
        with self.assertRaises(SourceError):
            self.adapter.fetch()
        self.assertEqual(len(self.requests), 9)

    def test_discovery_requires_exactly_one_station_and_is_cached(self):
        self.adapter.station_id = None
        self.responses = [self.token(), {'success': True, 'total': 1, 'stationList': [{'id': 789}]}, self.reading(), self.reading()]
        self.adapter.fetch()
        self.adapter.fetch()
        self.assertEqual(self.adapter.station_id, 789)
        self.assertEqual(len(self.requests), 4)
        self.adapter.station_id = None
        self.responses = [{'success': True, 'total': 2, 'stationList': [{'id': 123}, {'id': 789}]}]
        with self.assertRaisesRegex(SourceError, 'SOLARMAN_STATION_ID'):
            self.adapter.fetch()

    def test_missing_values_are_unavailable_not_zero(self):
        self.responses = [self.token(), self.reading(chargePower=None, dischargePower=None, batterySoc=150)]
        with self.assertRaises(SourceError):
            self.adapter.fetch()
        self.responses = [self.reading(chargePower=None, batterySoc=0)]
        reading = self.adapter.fetch()
        self.assertIsNone(reading.charge_w)
        self.assertEqual(reading.soc_percent, 0)
        self.assertEqual(reading.stored_wh, 0)
        self.assertEqual(reading.discharge_w, 0)

    def test_stale_invalid_and_future_collection_times_are_rejected(self):
        self.adapter.token = 'test-token'
        self.adapter.expires_at = time.time() + 1000
        for timestamp in (None, float('nan'), time.time()-1000, time.time()+1000, 0):
            with self.subTest(timestamp=timestamp):
                # JSON does not support NaN; numeric strings test the same invalid input.
                self.responses = [self.reading(lastUpdateTime=str(timestamp))]
                with self.assertRaises(SourceError):
                    self.adapter.fetch()
        self.responses = [self.reading(lastUpdateTime=time.time()*1000)]
        self.assertLess(abs(self.adapter.fetch().timestamp-time.time()), 5)

    def test_failures_clear_old_metrics_and_recover(self):
        self.responses = [self.token(), self.reading(), {'success': False, 'msg': 'test-secret password with spaces '}, self.reading(chargePower=0, dischargePower=250)]
        poll_battery(self.adapter)
        self.assertEqual(BATTERY_SOC.labels('solarman')._value.get(), 72)
        with self.assertLogs(level='WARNING') as logs:
            self.assertIsNone(poll_battery(self.adapter))
        self.assertNotIn('test-secret', ''.join(logs.output))
        self.assertTrue(math.isnan(BATTERY_SOC.labels('solarman')._value.get()))
        self.assertEqual(BATTERY_UP.labels('solarman')._value.get(), 0)
        self.assertEqual(BATTERY_STATE.labels('solarman')._value.get(), -1)
        poll_battery(self.adapter)
        self.assertEqual(BATTERY_STATE.labels('solarman')._value.get(), 2)

    def test_network_and_malformed_response_errors_do_not_leak_secrets(self):
        self.adapter.token = 'test-token'
        self.adapter.expires_at = time.time() + 1000
        for response in ([1, 2], httpx.ConnectError('test-secret')):
            self.responses = [response]
            with self.assertRaises(SourceError) as error:
                self.adapter.fetch()
            self.assertNotIn('test-secret', str(error.exception))

    def test_house_calculation_handles_solar_only_ct_and_missing_battery(self):
        self.assertEqual(grid_flows(-600, 4200, 1000, 0), (0, 600, 2600))
        self.assertEqual(grid_flows(100, 0, 0, 900), (100, 0, 1000))
        self.assertTrue(math.isnan(grid_flows(100, 0, None, None)[2]))
        self.assertTrue(math.isnan(grid_flows(0, 0, 1000, 0)[2]))

    def test_idle_partial_readings_and_unknown_capacity(self):
        self.adapter.config = replace(self.config, capacity_kwh=None)
        self.responses = [self.token(), self.reading(chargePower=0), self.reading(dischargePower=None)]
        reading = poll_battery(self.adapter)
        self.assertIsNone(reading.stored_wh)
        self.assertEqual(BATTERY_STATE.labels('solarman')._value.get(), 0)
        poll_battery(self.adapter)
        self.assertEqual(BATTERY_STATE.labels('solarman')._value.get(), -1)

    def test_merchant_org_and_overflowing_power(self):
        import json
        self.adapter.config = replace(self.config, org_id=456, power_multiplier=1000)
        self.responses = [self.token(), self.reading(chargePower=1e308, dischargePower=0)]
        reading = self.adapter.fetch()
        self.assertEqual(json.loads(self.requests[0].content)['orgId'], 456)
        self.assertIsNone(reading.charge_w)

    def test_numeric_invalid_token_refreshes_once(self):
        self.responses = [self.token(), {'success': False, 'code': 2101019}, self.token(), self.reading()]
        self.assertEqual(self.adapter.fetch().soc_percent, 72)
        self.assertEqual(len(self.requests), 4)

    def test_authentication_failure_identifies_login_without_echoing_api_message(self):
        self.responses = [{'success': False, 'code': '2101025', 'msg': 'test-secret test@example.test'}]
        with self.assertRaisesRegex(SourceError, 'Solarman login failed: authentication failed') as error:
            self.adapter.fetch()
        self.assertIn('2101025', str(error.exception))
        self.assertNotIn('test-secret', str(error.exception))
        self.assertNotIn('test@example.test', str(error.exception))


class BatteryConfigTests(unittest.TestCase):
    def env(self):
        return {'SOLARMAN_ENABLED': 'true', 'SOLARMAN_APP_ID': 'app', 'SOLARMAN_APP_SECRET': 'secret',
                'SOLARMAN_EMAIL': 'user@example.test', 'SOLARMAN_PASSWORD': ' spaces '}

    def test_disabled_battery_preserves_existing_configuration(self):
        with patch.dict(os.environ, {'MYENERGI_ENABLED':'true', 'MYENERGI_STATUS_URL':'https://example.test',
                                     'MYENERGI_POWER_PATH':'power', 'MYENERGI_ENERGY_VALUE_TYPE':'derived_from_power'}, clear=True):
            config = load_config()
        self.assertIsNone(config.solarman)
        self.assertTrue(config.myenergi_generation_includes_battery)

    def test_enabled_configuration_preserves_password_and_supports_battery_only(self):
        with patch.dict(os.environ, self.env(), clear=True):
            config = load_config()
        self.assertEqual(config.solarman.password, ' spaces ')
        self.assertEqual(config.sources, ())
        self.assertNotIn('secret', repr(config.solarman))
        self.assertNotIn('user@example.test', repr(config.solarman))

    def test_rejects_missing_credentials_and_invalid_numeric_configuration(self):
        for key, value in [('SOLARMAN_APP_ID',''), ('SOLARMAN_STATION_ID','bad'),
                           ('SOLARMAN_BATTERY_CAPACITY_KWH','nan'), ('SOLARMAN_POWER_MULTIPLIER','inf'),
                           ('SOLARMAN_MAX_AGE_SECONDS','0'), ('SOLARMAN_BASE_URL','http://example.test')]:
            env = self.env()
            env[key] = value
            with self.subTest(key=key), patch.dict(os.environ, env, clear=True), self.assertRaises(ConfigError):
                load_config()
