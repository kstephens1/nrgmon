import tempfile
import unittest
from pathlib import Path

from collector.normalizer import EnergyNormalizer


class EnergyNormalizerTests(unittest.TestCase):
    def test_daily_counter_accumulates_and_handles_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            normalizer = EnergyNormalizer(str(Path(directory) / "state.json"))
            self.assertEqual(normalizer.normalize("a", 100, 10, "daily_counter", 100), 0)
            self.assertEqual(normalizer.normalize("a", 100, 15, "daily_counter", 160), 5)
            self.assertEqual(normalizer.normalize("a", 100, 2, "daily_counter", 220), 7)

    def test_cumulative_counter_survives_reset_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            state = str(Path(directory) / "state.json")
            normalizer = EnergyNormalizer(state)
            self.assertEqual(normalizer.normalize("a", 100, 100, "cumulative", 100), 100)
            self.assertEqual(normalizer.normalize("a", 100, 110, "cumulative", 160), 110)
            restarted = EnergyNormalizer(state)
            self.assertEqual(restarted.normalize("a", 100, 5, "cumulative", 220), 115)

    def test_power_integration(self):
        with tempfile.TemporaryDirectory() as directory:
            normalizer = EnergyNormalizer(str(Path(directory) / "state.json"))
            self.assertEqual(normalizer.normalize("a", 100, None, "derived_from_power", 0), 0)
            self.assertEqual(normalizer.normalize("a", 200, None, "derived_from_power", 3600), 150)


if __name__ == "__main__":
    unittest.main()
