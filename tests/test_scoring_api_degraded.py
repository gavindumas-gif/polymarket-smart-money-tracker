from __future__ import annotations

import asyncio
import builtins
import unittest
from unittest.mock import patch

from polymarket_tracker.api.websocket import MarketWebSocketClient, WebSocketUnavailable
from polymarket_tracker.config.settings import ApiConfig, ScoringConfig
from polymarket_tracker.scoring.model import ScoreInput, ScoringModel, confidence_tier


class ScoringAndDegradedTests(unittest.TestCase):
    def test_scoring_tiers(self) -> None:
        self.assertEqual(confidence_tier(95), "EXTREME")
        model = ScoringModel(ScoringConfig(weights={"trader_count": 20, "total_notional": 20}))
        result = model.score(
            ScoreInput(
                trader_count=4,
                weighted_trader_count=4,
                total_notional=500,
                largest_trader_notional=200,
                average_trader_quality=1.0,
                age_seconds=30,
                accumulation_seconds=120,
                agreement_ratio=0.9,
                market_liquidity=5000,
                price_movement_since_first=0.02,
                opposing_notional=10,
                total_group_notional_with_opposition=510,
                partial_history_ratio=1.0,
            )
        )
        self.assertGreater(result.score, 0)
        self.assertIn("confidence", result.explanation)

    def test_websocket_missing_dependency_degrades(self) -> None:
        client = MarketWebSocketClient(ApiConfig(), ["asset"], lambda event: None)

        original_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "websockets":
                raise ModuleNotFoundError("forced missing optional dependency")
            return original_import(name, *args, **kwargs)

        with (
            patch("builtins.__import__", side_effect=blocked_import),
            self.assertRaises(WebSocketUnavailable),
        ):
            asyncio.run(client.run_forever())
        self.assertEqual(client.status, "degraded_missing_websockets_dependency")


if __name__ == "__main__":
    unittest.main()
