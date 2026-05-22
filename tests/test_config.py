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


if __name__ == "__main__":
    unittest.main()
