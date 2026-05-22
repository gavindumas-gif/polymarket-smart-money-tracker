from __future__ import annotations

import sqlite3
from dataclasses import asdict
from typing import Any

from polymarket_tracker.db.sqlite import Database
from polymarket_tracker.trades.models import NormalizedTrade, PositionState, RawEventRecord
from polymarket_tracker.utils.json import dumps, stable_hash
from polymarket_tracker.utils.time import iso_now


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert_trader(self, trader: dict[str, Any]) -> None:
        now = iso_now()
        trader_id = trader["trader_id"]
        existing = self.db.fetchone("SELECT trader_id FROM traders WHERE trader_id = ?", (trader_id,))
        payload = (
            dumps(trader.get("raw_profile_payload"))
            if not isinstance(trader.get("raw_profile_payload"), str)
            else trader.get("raw_profile_payload")
        )
        if existing:
            self.db.execute(
                """
                UPDATE traders
                SET display_name = COALESCE(?, display_name),
                    username = COALESCE(?, username),
                    profile_url = COALESCE(?, profile_url),
                    wallet_address = COALESCE(?, wallet_address),
                    proxy_wallet_address = COALESCE(?, proxy_wallet_address),
                    discovery_source = ?,
                    manual_weight = ?,
                    derived_weight = ?,
                    volume = COALESCE(?, volume),
                    pnl = COALESCE(?, pnl),
                    win_rate = COALESCE(?, win_rate),
                    recent_activity_score = COALESCE(?, recent_activity_score),
                    consistency_score = COALESCE(?, consistency_score),
                    specialization_score = COALESCE(?, specialization_score),
                    last_seen = ?,
                    raw_profile_payload = COALESCE(?, raw_profile_payload)
                WHERE trader_id = ?
                """,
                (
                    trader.get("display_name"),
                    trader.get("username"),
                    trader.get("profile_url"),
                    trader.get("wallet_address"),
                    trader.get("proxy_wallet_address"),
                    trader.get("discovery_source", "manual"),
                    float(trader.get("manual_weight", 1.0)),
                    float(trader.get("derived_weight", trader.get("manual_weight", 1.0))),
                    trader.get("volume"),
                    trader.get("pnl"),
                    trader.get("win_rate"),
                    trader.get("recent_activity_score"),
                    trader.get("consistency_score"),
                    trader.get("specialization_score"),
                    now,
                    payload,
                    trader_id,
                ),
            )
        else:
            self.db.execute(
                """
                INSERT INTO traders (
                    trader_id, display_name, username, profile_url, wallet_address, proxy_wallet_address,
                    discovery_source, manual_weight, derived_weight, volume, pnl, win_rate,
                    recent_activity_score, consistency_score, specialization_score, first_seen, last_seen,
                    raw_profile_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trader_id,
                    trader.get("display_name"),
                    trader.get("username"),
                    trader.get("profile_url"),
                    trader.get("wallet_address"),
                    trader.get("proxy_wallet_address"),
                    trader.get("discovery_source", "manual"),
                    float(trader.get("manual_weight", 1.0)),
                    float(trader.get("derived_weight", trader.get("manual_weight", 1.0))),
                    trader.get("volume"),
                    trader.get("pnl"),
                    trader.get("win_rate"),
                    trader.get("recent_activity_score"),
                    trader.get("consistency_score"),
                    trader.get("specialization_score"),
                    now,
                    now,
                    payload,
                ),
            )

    def find_trader_by_wallet(self, wallet: str | None) -> sqlite3.Row | None:
        if not wallet:
            return None
        normalized = wallet.lower()
        return self.db.fetchone(
            """
            SELECT * FROM traders
            WHERE lower(wallet_address) = ? OR lower(proxy_wallet_address) = ?
            """,
            (normalized, normalized),
        )

    def list_traders(self) -> list[sqlite3.Row]:
        return self.db.fetchall("SELECT * FROM traders ORDER BY derived_weight DESC, trader_id")

    def upsert_market(self, market: dict[str, Any]) -> None:
        now = iso_now()
        market_id = str(market.get("market_id") or market.get("id") or market.get("condition_id") or "unknown")
        existing = self.db.fetchone("SELECT market_id FROM markets WHERE market_id = ?", (market_id,))
        values = (
            market.get("condition_id") or market.get("conditionId"),
            market.get("question") or market.get("title"),
            market.get("slug"),
            market.get("market_url"),
            dumps(market.get("outcomes", [])),
            dumps(market.get("outcome_prices", market.get("outcomePrices", []))),
            dumps(market.get("clob_token_ids", market.get("clobTokenIds", []))),
            _maybe_float(market.get("liquidity")),
            _maybe_float(market.get("volume")),
            _maybe_bool_int(market.get("active")),
            _maybe_bool_int(market.get("closed")),
            dumps(market.get("raw_payload", market)),
            now,
            market_id,
        )
        if existing:
            self.db.execute(
                """
                UPDATE markets
                SET condition_id = COALESCE(?, condition_id),
                    question = COALESCE(?, question),
                    slug = COALESCE(?, slug),
                    market_url = COALESCE(?, market_url),
                    outcomes_json = ?,
                    outcome_prices_json = ?,
                    clob_token_ids_json = ?,
                    liquidity = COALESCE(?, liquidity),
                    volume = COALESCE(?, volume),
                    active = COALESCE(?, active),
                    closed = COALESCE(?, closed),
                    raw_payload = ?,
                    last_seen = ?
                WHERE market_id = ?
                """,
                values,
            )
        else:
            self.db.execute(
                """
                INSERT INTO markets (
                    market_id, condition_id, question, slug, market_url, outcomes_json,
                    outcome_prices_json, clob_token_ids_json, liquidity, volume, active,
                    closed, raw_payload, first_seen, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (market_id, *values[:-2], now, now),
            )

    def insert_raw_event(self, record: RawEventRecord) -> int | None:
        try:
            cursor = self.db.execute(
                """
                INSERT INTO raw_trade_events (
                    dedupe_key, source_event_id, source_endpoint, source_type, received_at,
                    event_timestamp, raw_payload, payload_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.dedupe_key,
                    record.source_event_id,
                    record.source_endpoint,
                    record.source_type,
                    record.received_at,
                    record.event_timestamp,
                    dumps(record.raw_payload),
                    stable_hash(record.raw_payload),
                ),
            )
            return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None

    def insert_malformed_event(
        self,
        dedupe_key: str | None,
        source_endpoint: str,
        raw_payload: dict[str, Any],
        validation_error: str,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO malformed_events(dedupe_key, source_endpoint, received_at, validation_error, raw_payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (dedupe_key, source_endpoint, iso_now(), validation_error, dumps(raw_payload)),
        )

    def insert_normalized_trade(self, trade: NormalizedTrade) -> bool:
        data = asdict(trade)
        try:
            self.db.execute(
                """
                INSERT INTO normalized_trades (
                    dedupe_key, raw_event_id, source_event_id, trader_id, trader_address,
                    proxy_wallet_address, market_id, condition_id, question, slug, market_url,
                    outcome_token_id, outcome_name, raw_side, normalized_direction, price, size,
                    notional, transaction_hash, block_number, trade_timestamp, source_endpoint,
                    action_classification, position_certainty, uncertainty_notes, raw_payload,
                    ingestion_timestamp
                ) VALUES (
                    :dedupe_key, :raw_event_id, :source_event_id, :trader_id, :trader_address,
                    :proxy_wallet_address, :market_id, :condition_id, :question, :slug, :market_url,
                    :outcome_token_id, :outcome_name, :raw_side, :normalized_direction, :price, :size,
                    :notional, :transaction_hash, :block_number, :trade_timestamp, :source_endpoint,
                    :action_classification, :position_certainty, :uncertainty_notes, :raw_payload,
                    :ingestion_timestamp
                )
                """,
                {**data, "raw_payload": dumps(trade.raw_payload)},
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_position(self, position_key: str) -> sqlite3.Row | None:
        return self.db.fetchone("SELECT * FROM inferred_positions WHERE position_key = ?", (position_key,))

    def upsert_position(self, state: PositionState) -> None:
        data = asdict(state)
        data["raw_state"] = dumps(state.raw_state)
        existing = self.get_position(state.position_key)
        if existing:
            self.db.execute(
                """
                UPDATE inferred_positions
                SET trader_id = :trader_id,
                    trader_address = :trader_address,
                    proxy_wallet_address = :proxy_wallet_address,
                    market_id = :market_id,
                    condition_id = :condition_id,
                    outcome_token_id = :outcome_token_id,
                    normalized_outcome = :normalized_outcome,
                    normalized_direction = :normalized_direction,
                    observed_net_size = :observed_net_size,
                    total_bought = :total_bought,
                    total_sold = :total_sold,
                    weighted_average_entry = :weighted_average_entry,
                    average_exit = :average_exit,
                    estimated_current_exposure = :estimated_current_exposure,
                    realized_change = :realized_change,
                    unrealized_change = :unrealized_change,
                    first_observed_entry = :first_observed_entry,
                    last_update = :last_update,
                    position_status = :position_status,
                    completeness_flag = :completeness_flag,
                    uncertainty_notes = :uncertainty_notes,
                    raw_state = :raw_state
                WHERE position_key = :position_key
                """,
                data,
            )
        else:
            self.db.execute(
                """
                INSERT INTO inferred_positions (
                    position_key, trader_id, trader_address, proxy_wallet_address, market_id,
                    condition_id, outcome_token_id, normalized_outcome, normalized_direction,
                    observed_net_size, total_bought, total_sold, weighted_average_entry,
                    average_exit, estimated_current_exposure, realized_change, unrealized_change,
                    first_observed_entry, last_update, position_status, completeness_flag,
                    uncertainty_notes, raw_state
                ) VALUES (
                    :position_key, :trader_id, :trader_address, :proxy_wallet_address, :market_id,
                    :condition_id, :outcome_token_id, :normalized_outcome, :normalized_direction,
                    :observed_net_size, :total_bought, :total_sold, :weighted_average_entry,
                    :average_exit, :estimated_current_exposure, :realized_change, :unrealized_change,
                    :first_observed_entry, :last_update, :position_status, :completeness_flag,
                    :uncertainty_notes, :raw_state
                )
                """,
                data,
            )

    def insert_api_error(
        self,
        source_endpoint: str,
        error_type: str,
        message: str,
        status_code: int | None = None,
        raw_payload: Any = None,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO api_errors(source_endpoint, occurred_at, error_type, status_code, message, raw_payload)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (source_endpoint, iso_now(), error_type, status_code, message, dumps(raw_payload)),
        )


def _maybe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _maybe_bool_int(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0
