from __future__ import annotations

import unittest

from polymarket_tracker.config.settings import ConfigError, config_from_dict, load_config
from tests.helpers import make_temp_dir


class ConfigTests(unittest.TestCase):
    def test_example_config_loads(self) -> None:
        config = load_config("config.example.yaml")
        self.assertEqual(config.mode, "dry-run")
        self.assertTrue(config.api.data_base_url.startswith("https://"))
        self.assertGreaterEqual(len(config.traders.manual), 2)
        self.assertEqual(config.traders.discovery.limit, 20)
        self.assertEqual(config.traders.discovery.time_periods, ("DAY", "WEEK", "MONTH", "ALL"))

    def test_invalid_database_url_fails_fast(self) -> None:
        with self.assertRaises(ConfigError):
            config_from_dict({"database": {"url": "postgres://localhost/db"}})

    def test_envless_temp_config(self) -> None:
        tmp = make_temp_dir()
        config = config_from_dict(
            {
                "database": {"url": f"sqlite:///{(tmp / 'tracker.sqlite').as_posix()}"},
                "traders": {
                    "manual": [
                        {
                            "trader_id": "a",
                            "wallet_address": "0x1111111111111111111111111111111111111111",
                        }
                    ]
                },
            }
        )
        self.assertEqual(config.database.busy_timeout_ms, 5000)

    def test_legacy_single_discovery_time_period_still_loads(self) -> None:
        config = config_from_dict({"traders": {"discovery": {"time_period": "week", "limit": 5}}})
        self.assertEqual(config.traders.discovery.time_period, "WEEK")
        self.assertEqual(config.traders.discovery.time_periods, ("WEEK",))
        self.assertEqual(config.traders.discovery.limit, 5)


if __name__ == "__main__":
    unittest.main()
