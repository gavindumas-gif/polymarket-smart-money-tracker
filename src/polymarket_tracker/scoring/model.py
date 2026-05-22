from __future__ import annotations

import math
from dataclasses import dataclass

from polymarket_tracker.config.settings import ScoringConfig


@dataclass(frozen=True)
class ScoreInput:
    trader_count: int
    weighted_trader_count: float
    total_notional: float
    largest_trader_notional: float
    average_trader_quality: float
    age_seconds: float
    accumulation_seconds: float
    agreement_ratio: float
    market_liquidity: float | None
    price_movement_since_first: float | None
    opposing_notional: float
    total_group_notional_with_opposition: float
    partial_history_ratio: float


@dataclass(frozen=True)
class ScoreResult:
    score: float
    confidence_tier: str
    explanation: str
    components: dict[str, float]


class ScoringModel:
    def __init__(self, config: ScoringConfig) -> None:
        self.config = config

    def score(self, data: ScoreInput) -> ScoreResult:
        w = self.config.weights
        concentration_ratio = data.largest_trader_notional / data.total_notional if data.total_notional > 0 else 1.0
        components = {
            "trader_count": _bounded_log(data.trader_count, 8) * w.get("trader_count", 0),
            "weighted_trader_count": _bounded_log(data.weighted_trader_count, 8) * w.get("weighted_trader_count", 0),
            "total_notional": _bounded_log(data.total_notional / 100.0, 20) * w.get("total_notional", 0),
            "concentration": (1.0 - min(concentration_ratio, 1.0)) * w.get("concentration", 0),
            "trader_quality": min(max(data.average_trader_quality, 0.0), 2.0) / 2.0 * w.get("trader_quality", 0),
            "recency": _recency_score(data.age_seconds) * w.get("recency", 0),
            "speed": _speed_score(data.accumulation_seconds) * w.get("speed", 0),
            "agreement_ratio": min(max(data.agreement_ratio, 0.0), 1.0) * w.get("agreement_ratio", 0),
            "liquidity": _liquidity_score(data.market_liquidity, data.total_notional) * w.get("liquidity", 0),
            "price_movement": _price_movement_score(data.price_movement_since_first) * w.get("price_movement", 0),
            "opposing_penalty": _opposition_score(data.opposing_notional, data.total_group_notional_with_opposition)
            * abs(w.get("opposing_penalty", 0)),
            "late_entry_penalty": _late_entry_penalty(data.price_movement_since_first)
            * abs(w.get("late_entry_penalty", 0)),
            "uncertainty_penalty": data.partial_history_ratio * abs(w.get("uncertainty_penalty", 0)),
        }
        positive = sum(value for key, value in components.items() if not key.endswith("penalty"))
        penalty = sum(value for key, value in components.items() if key.endswith("penalty"))
        raw_score = max(0.0, min(self.config.max_score, positive - penalty))
        tier = confidence_tier(raw_score)
        explanation = (
            f"{data.trader_count} traders, weighted count {data.weighted_trader_count:.2f}, "
            f"${data.total_notional:,.2f} observed notional, agreement {data.agreement_ratio:.0%}, "
            f"opposing notional ${data.opposing_notional:,.2f}; confidence {tier}."
        )
        return ScoreResult(
            score=round(raw_score, 2), confidence_tier=tier, explanation=explanation, components=components
        )


def confidence_tier(score: float) -> str:
    if score >= 90:
        return "EXTREME"
    if score >= 78:
        return "VERY_HIGH"
    if score >= 65:
        return "HIGH"
    if score >= 48:
        return "MEDIUM"
    if score >= 28:
        return "LOW"
    return "VERY_LOW"


def _bounded_log(value: float, cap: float) -> float:
    if value <= 0:
        return 0.0
    return min(math.log1p(value) / math.log1p(cap), 1.0)


def _recency_score(age_seconds: float) -> float:
    if age_seconds <= 60:
        return 1.0
    if age_seconds >= 86400:
        return 0.0
    return max(0.0, 1.0 - (age_seconds / 86400.0))


def _speed_score(accumulation_seconds: float) -> float:
    if accumulation_seconds <= 60:
        return 1.0
    if accumulation_seconds >= 3600:
        return 0.1
    return max(0.1, 1.0 - (accumulation_seconds / 3600.0))


def _liquidity_score(liquidity: float | None, notional: float) -> float:
    if liquidity is None or liquidity <= 0:
        return 0.25
    if notional <= 0:
        return 0.0
    return min(liquidity / max(notional, 1.0), 1.0)


def _price_movement_score(price_movement: float | None) -> float:
    if price_movement is None:
        return 0.25
    return max(0.0, min(price_movement / 0.15, 1.0))


def _late_entry_penalty(price_movement: float | None) -> float:
    if price_movement is None:
        return 0.0
    return max(0.0, min((price_movement - 0.08) / 0.20, 1.0))


def _opposition_score(opposing: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(opposing / total, 1.0))
