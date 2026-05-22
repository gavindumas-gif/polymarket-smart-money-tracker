from __future__ import annotations

import unittest

from polymarket_tracker.alerts.manager import AlertManager
from polymarket_tracker.config.settings import config_from_dict
from polymarket_tracker.consensus.engine import ConsensusEngine
from polymarket_tracker.dashboard.web import WebDashboard
from polymarket_tracker.db.sqlite import Database
from polymarket_tracker.runner import run_dry_run, run_replay
from polymarket_tracker.traders.discovery import TraderRegistry
from polymarket_tracker.trades.processor import TradeProcessor
from polymarket_tracker.utils.json import loads
from tests.helpers import make_temp_dir


def make_config(tmp):
    db_path = (tmp / "tracker.sqlite").as_posix()
    return config_from_dict(
        {
            "database": {"url": f"sqlite:///{db_path}"},
            "traders": {
                "manual": [
                    {
                        "trader_id": "alpha_mock",
                        "display_name": "Alpha Mock",
                        "wallet_address": "0x1111111111111111111111111111111111111111",
                        "proxy_wallet_address": "0x1111111111111111111111111111111111111111",
                        "manual_weight": 1.5,
                    },
                    {
                        "trader_id": "beta_mock",
                        "display_name": "Beta Mock",
                        "wallet_address": "0x2222222222222222222222222222222222222222",
                        "proxy_wallet_address": "0x2222222222222222222222222222222222222222",
                        "manual_weight": 1.25,
                    },
                ],
                "discovery": {"enabled": False},
            },
            "dry_run": {"fixture_path": "fixtures/mock_trades.json", "reset_database": True},
            "replay": {"fixture_path": "fixtures/mock_trades.json"},
            "consensus": {"alert_score_threshold": 48.0},
            "logging": {"file": None},
        }
    )


class PipelineTests(unittest.TestCase):
    def test_database_migration_and_dry_run_pipeline(self) -> None:
        tmp = make_temp_dir()
        config = make_config(tmp)
        result = run_dry_run(config)
        self.assertEqual(result["results"]["ingested"], 6)
        self.assertEqual(result["results"]["duplicate"], 1)
        self.assertEqual(result["results"]["malformed"], 1)
        self.assertGreaterEqual(result["signal_count"], 1)
        self.assertEqual(result["alert_count"], 1)
        self.assertIn("CONSENSUS SIGNALS", result["dashboard"])

    def test_restart_dedupe_is_database_enforced(self) -> None:
        tmp = make_temp_dir()
        config = make_config(tmp)
        db = Database(config.database.url)
        db.migrate()
        registry = TraderRegistry(db, config.traders)
        registry.load_manual()
        processor = TradeProcessor(db)
        raw = {
            "proxyWallet": "0x1111111111111111111111111111111111111111",
            "side": "BUY",
            "asset": "asset-1",
            "conditionId": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "size": 10,
            "price": 0.4,
            "timestamp": 1779469124,
            "title": "Dedupe market",
            "slug": "dedupe-market",
            "outcome": "Yes",
            "transactionHash": "0xdupe",
        }
        first = processor.ingest(raw, "fixture")
        second_processor = TradeProcessor(db)
        second = second_processor.ingest(raw, "fixture")
        row = db.fetchone("SELECT COUNT(*) AS count FROM normalized_trades")
        db.close()
        self.assertEqual(first.status, "ingested")
        self.assertEqual(second.status, "duplicate")
        self.assertEqual(row["count"], 1)

    def test_consensus_and_alert_deduplication(self) -> None:
        tmp = make_temp_dir()
        config = make_config(tmp)
        run_dry_run(config)
        db = Database(config.database.url)
        db.migrate()
        signals = ConsensusEngine(db, config.consensus, config.scoring).evaluate()
        alerts = AlertManager(db, config.alerts, config.consensus).process(signals)
        rows = db.fetchall("SELECT * FROM alerts")
        db.close()
        self.assertEqual(alerts, [])
        self.assertEqual(len(rows), 1)
        payload = loads(rows[0]["payload_json"], {})
        self.assertIn("risks_uncertainties", payload)

    def test_replay_mode_runs_with_fixture(self) -> None:
        tmp = make_temp_dir()
        config = make_config(tmp)
        result = run_replay(config)
        self.assertGreaterEqual(result["replayed"], 1)
        self.assertIn("summary", result)

    def test_web_dashboard_snapshot_uses_pipeline_data(self) -> None:
        tmp = make_temp_dir()
        config = make_config(tmp)
        run_dry_run(config)
        db = Database(config.database.url)
        db.migrate()
        dashboard = WebDashboard(db, max_rows=5)
        snapshot = dashboard.snapshot()
        html = dashboard.html()
        db.close()
        self.assertGreaterEqual(snapshot["summary"]["signals"], 1)
        self.assertGreaterEqual(len(snapshot["trades"]), 1)
        self.assertIn("Consensus Dashboard", html)


if __name__ == "__main__":
    unittest.main()
