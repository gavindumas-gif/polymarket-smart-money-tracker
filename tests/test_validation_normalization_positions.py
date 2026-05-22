from __future__ import annotations

import unittest

from polymarket_tracker.markets.normalization import normalize_direction, normalize_outcome
from polymarket_tracker.positions.engine import PositionEngine, classify_trade
from polymarket_tracker.trades.validation import ValidationError, validate_trade_event

SAMPLE = {
    "proxyWallet": "0x1111111111111111111111111111111111111111",
    "side": "BUY",
    "asset": "123",
    "conditionId": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size": 10,
    "price": 0.52,
    "timestamp": 1779469124,
    "title": "Sample market",
    "slug": "sample-market",
    "outcome": "Yes",
    "transactionHash": "0xabc",
}


class ValidationNormalizationPositionTests(unittest.TestCase):
    def test_api_response_validation(self) -> None:
        event = validate_trade_event(SAMPLE, "fixture")
        self.assertEqual(event.raw_side, "BUY")
        self.assertEqual(event.notional, 5.2)
        self.assertTrue(event.dedupe_key.startswith("tx:"))

    def test_malformed_event_rejected(self) -> None:
        bad = dict(SAMPLE)
        bad.pop("price")
        with self.assertRaises(ValidationError):
            validate_trade_event(bad, "fixture")

    def test_outcome_and_direction_normalization(self) -> None:
        self.assertEqual(normalize_outcome(" yes "), "YES")
        self.assertEqual(normalize_direction("BUY", "Yes"), "LONG_YES")
        self.assertEqual(normalize_direction("SELL", "No"), "SELL_NO")
        self.assertEqual(normalize_direction("BUY", "OpenAI"), "LONG_OUTCOME")

    def test_trade_classification(self) -> None:
        self.assertEqual(classify_trade(0, 10, 10), "NEW_ENTRY")
        self.assertEqual(classify_trade(10, 5, 15), "ADD")
        self.assertEqual(classify_trade(10, -4, 6), "REDUCE")
        self.assertEqual(classify_trade(10, -10, 0), "EXIT")
        self.assertEqual(classify_trade(10, -15, -5), "REVERSE")

    def test_position_inference_marks_partial_history(self) -> None:
        event = validate_trade_event(SAMPLE, "fixture")
        action, state = PositionEngine().classify_and_update(None, event, "LONG_YES", "alpha")
        self.assertEqual(action, "NEW_ENTRY")
        self.assertEqual(state.completeness_flag, "PARTIAL_HISTORY")
        self.assertIn("historical activity", state.uncertainty_notes)


if __name__ == "__main__":
    unittest.main()
