from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from polymarket_tracker.config.settings import ConsensusConfig, ScoringConfig
from polymarket_tracker.db.sqlite import Database
from polymarket_tracker.markets.normalization import opposite_direction
from polymarket_tracker.scoring.model import ScoreInput, ScoringModel
from polymarket_tracker.utils.json import dumps, stable_hash
from polymarket_tracker.utils.time import iso_now, parse_iso, utc_now


@dataclass(frozen=True)
class ConsensusSignal:
    signal_id: str
    group_key: str
    market_id: str
    condition_id: str | None
    market_title: str | None
    market_url: str | None
    outcome_token_id: str | None
    outcome: str | None
    direction: str
    time_window_seconds: int
    trader_count: int
    weighted_trader_count: float
    traders_involved: list[dict[str, Any]]
    total_token_size: float
    total_notional: float
    average_entry_price: float | None
    weighted_average_entry_price: float | None
    latest_price: float | None
    market_liquidity: float | None
    price_movement_since_first: float | None
    first_trade_timestamp: str
    latest_trade_timestamp: str
    trigger_timestamp: str
    score: float
    confidence_tier: str
    opposing_trader_count: int
    opposing_notional: float
    signal_explanation: str
    uncertainty_notes: str
    raw_components: dict[str, Any]


class ConsensusEngine:
    def __init__(self, db: Database, config: ConsensusConfig, scoring_config: ScoringConfig) -> None:
        self.db = db
        self.config = config
        self.scoring = ScoringModel(scoring_config)

    def evaluate(self) -> list[ConsensusSignal]:
        signals: list[ConsensusSignal] = []
        for window in self.config.windows_seconds:
            signals.extend(self._evaluate_window(window))
        return signals

    def _evaluate_window(self, window_seconds: int) -> list[ConsensusSignal]:
        cutoff = (utc_now() - timedelta(seconds=window_seconds)).isoformat().replace("+00:00", "Z")
        rows = self.db.fetchall(
            """
            SELECT nt.*, t.derived_weight, t.manual_weight, t.display_name, t.username,
                   m.liquidity, m.market_url AS stored_market_url
            FROM normalized_trades nt
            LEFT JOIN traders t ON t.trader_id = nt.trader_id
            LEFT JOIN markets m ON m.market_id = nt.market_id
            WHERE nt.trade_timestamp >= ?
            ORDER BY nt.trade_timestamp ASC
            """,
            (cutoff,),
        )
        grouped: dict[tuple[str, str | None, str | None, str], list[Any]] = defaultdict(list)
        for row in rows:
            if row["action_classification"] in {"EXIT", "REDUCE"} and self.config.ignore_exits:
                continue
            if row["action_classification"] == "ADD" and not self.config.count_adds:
                continue
            if self.config.included_markets and row["market_id"] not in self.config.included_markets:
                continue
            if row["market_id"] in self.config.excluded_markets:
                continue
            if self.config.included_traders and row["trader_id"] not in self.config.included_traders:
                continue
            if row["trader_id"] in self.config.excluded_traders:
                continue
            if row["notional"] < self.config.minimum_individual_notional:
                continue
            grouped[
                (
                    row["market_id"],
                    row["condition_id"],
                    row["outcome_token_id"],
                    row["normalized_direction"],
                )
            ].append(row)

        all_rows_by_key = defaultdict(list)
        for row in rows:
            all_rows_by_key[(row["market_id"], row["condition_id"], row["outcome_token_id"])].append(row)

        signals: list[ConsensusSignal] = []
        for (market_id, condition_id, token_id, direction), group_rows in grouped.items():
            signal = self._build_signal(
                market_id,
                condition_id,
                token_id,
                direction,
                group_rows,
                all_rows_by_key[(market_id, condition_id, token_id)],
                window_seconds,
            )
            if signal:
                self._persist_signal(signal)
                signals.append(signal)
        return signals

    def _build_signal(
        self,
        market_id: str,
        condition_id: str | None,
        token_id: str | None,
        direction: str,
        rows: list[Any],
        market_rows: list[Any],
        window_seconds: int,
    ) -> ConsensusSignal | None:
        trader_map: dict[str, dict[str, Any]] = {}
        total_size = 0.0
        total_notional = 0.0
        weighted_notional_price = 0.0
        weighted_price_weight = 0.0
        partial_count = 0
        largest = 0.0
        latest_price: float | None = None
        for row in rows:
            trader_key = row["trader_id"] or row["trader_address"]
            weight = float(row["derived_weight"] or row["manual_weight"] or 1.0)
            notional = float(row["notional"])
            total_size += float(row["size"])
            total_notional += notional
            weighted_notional_price += float(row["price"]) * notional
            weighted_price_weight += notional
            latest_price = float(row["price"])
            if row["position_certainty"] != "COMPLETE":
                partial_count += 1
            entry = trader_map.setdefault(
                trader_key,
                {
                    "trader_id": trader_key,
                    "display_name": row["display_name"] or row["username"] or trader_key[:10],
                    "weight": weight,
                    "notional": 0.0,
                    "size": 0.0,
                    "latest_action": row["action_classification"],
                },
            )
            entry["notional"] += notional
            entry["size"] += float(row["size"])
            largest = max(largest, entry["notional"])

        trader_count = len(trader_map)
        weighted_count = sum(entry["weight"] for entry in trader_map.values())
        if trader_count < self.config.minimum_traders:
            return None
        if weighted_count < self.config.minimum_weighted_traders:
            return None
        if total_notional < self.config.minimum_total_notional:
            return None

        market_liquidity = rows[-1]["liquidity"]
        if market_liquidity is not None and float(market_liquidity) < self.config.minimum_liquidity:
            return None
        first_ts = rows[0]["trade_timestamp"]
        latest_ts = rows[-1]["trade_timestamp"]
        first_price = float(rows[0]["price"])
        price_movement = latest_price - first_price if latest_price is not None else None
        opposite = opposite_direction(direction)
        opposing_rows = [row for row in market_rows if row["normalized_direction"] == opposite]
        opposing_traders = {row["trader_id"] or row["trader_address"] for row in opposing_rows}
        opposing_notional = sum(float(row["notional"]) for row in opposing_rows)
        total_with_opposition = total_notional + opposing_notional
        agreement_ratio = total_notional / total_with_opposition if total_with_opposition else 1.0
        age_seconds = (utc_now() - parse_iso(latest_ts)).total_seconds()
        accumulation_seconds = max(1.0, (parse_iso(latest_ts) - parse_iso(first_ts)).total_seconds())
        partial_ratio = partial_count / max(len(rows), 1)
        average_quality = weighted_count / max(trader_count, 1)
        score = self.scoring.score(
            ScoreInput(
                trader_count=trader_count,
                weighted_trader_count=weighted_count,
                total_notional=total_notional,
                largest_trader_notional=largest,
                average_trader_quality=average_quality,
                age_seconds=age_seconds,
                accumulation_seconds=accumulation_seconds,
                agreement_ratio=agreement_ratio,
                market_liquidity=float(market_liquidity) if market_liquidity is not None else None,
                price_movement_since_first=price_movement,
                opposing_notional=opposing_notional,
                total_group_notional_with_opposition=total_with_opposition,
                partial_history_ratio=partial_ratio,
            )
        )
        uncertainty = (
            "Current positions are partial-history inferences. Public market websocket events "
            "do not prove wallet identity; this signal is based on observed Data API trades "
            "for tracked wallets."
        )
        group_key = "|".join([market_id, condition_id or "", token_id or "", direction, str(window_seconds)])
        signal_id = stable_hash({"group": group_key, "latest": latest_ts, "score": score.score})
        return ConsensusSignal(
            signal_id=signal_id,
            group_key=group_key,
            market_id=market_id,
            condition_id=condition_id,
            market_title=rows[-1]["question"],
            market_url=rows[-1]["market_url"] or rows[-1]["stored_market_url"],
            outcome_token_id=token_id,
            outcome=rows[-1]["outcome_name"],
            direction=direction,
            time_window_seconds=window_seconds,
            trader_count=trader_count,
            weighted_trader_count=round(weighted_count, 4),
            traders_involved=list(trader_map.values()),
            total_token_size=round(total_size, 8),
            total_notional=round(total_notional, 8),
            average_entry_price=round(sum(float(row["price"]) for row in rows) / len(rows), 6),
            weighted_average_entry_price=round(weighted_notional_price / weighted_price_weight, 6)
            if weighted_price_weight
            else None,
            latest_price=latest_price,
            market_liquidity=float(market_liquidity) if market_liquidity is not None else None,
            price_movement_since_first=round(price_movement, 6) if price_movement is not None else None,
            first_trade_timestamp=first_ts,
            latest_trade_timestamp=latest_ts,
            trigger_timestamp=iso_now(),
            score=score.score,
            confidence_tier=score.confidence_tier,
            opposing_trader_count=len(opposing_traders),
            opposing_notional=round(opposing_notional, 8),
            signal_explanation=score.explanation,
            uncertainty_notes=uncertainty,
            raw_components=score.components,
        )

    def _persist_signal(self, signal: ConsensusSignal) -> None:
        self.db.execute(
            """
            INSERT OR REPLACE INTO consensus_signals (
                signal_id, group_key, market_id, condition_id, market_title, market_url,
                outcome_token_id, outcome, direction, time_window_seconds, trader_count,
                weighted_trader_count, traders_involved_json, total_token_size, total_notional,
                average_entry_price, weighted_average_entry_price, latest_price, market_liquidity,
                price_movement_since_first, first_trade_timestamp, latest_trade_timestamp,
                trigger_timestamp, score, confidence_tier, opposing_trader_count, opposing_notional,
                signal_explanation, uncertainty_notes, raw_components_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.signal_id,
                signal.group_key,
                signal.market_id,
                signal.condition_id,
                signal.market_title,
                signal.market_url,
                signal.outcome_token_id,
                signal.outcome,
                signal.direction,
                signal.time_window_seconds,
                signal.trader_count,
                signal.weighted_trader_count,
                dumps(signal.traders_involved),
                signal.total_token_size,
                signal.total_notional,
                signal.average_entry_price,
                signal.weighted_average_entry_price,
                signal.latest_price,
                signal.market_liquidity,
                signal.price_movement_since_first,
                signal.first_trade_timestamp,
                signal.latest_trade_timestamp,
                signal.trigger_timestamp,
                signal.score,
                signal.confidence_tier,
                signal.opposing_trader_count,
                signal.opposing_notional,
                signal.signal_explanation,
                signal.uncertainty_notes,
                dumps(signal.raw_components),
            ),
        )
