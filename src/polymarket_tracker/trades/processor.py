from __future__ import annotations

import logging
from typing import Any

from polymarket_tracker.db.repositories import Repository
from polymarket_tracker.db.sqlite import Database
from polymarket_tracker.markets.normalization import normalize_direction
from polymarket_tracker.positions.engine import PositionEngine, build_normalized_trade, position_key_for
from polymarket_tracker.trades.models import IngestionResult, RawEventRecord
from polymarket_tracker.trades.validation import ValidationError, quarantine_key, validate_trade_event
from polymarket_tracker.utils.time import iso_now

LOGGER = logging.getLogger(__name__)


class TradeProcessor:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.repo = Repository(db)
        self.positions = PositionEngine()
        self._seen_keys: set[str] = set()

    def ingest(
        self, raw_payload: dict[str, Any], source_endpoint: str, source_type: str = "polling"
    ) -> IngestionResult:
        received_at = iso_now()
        try:
            event = validate_trade_event(raw_payload, source_endpoint)
        except ValidationError as exc:
            dedupe = quarantine_key(raw_payload)
            self.repo.insert_malformed_event(dedupe, source_endpoint, raw_payload, str(exc))
            LOGGER.warning("quarantined malformed event: %s", exc)
            return IngestionResult(status="malformed", dedupe_key=dedupe, validation_error=str(exc))

        if event.dedupe_key in self._seen_keys:
            return IngestionResult(status="duplicate", dedupe_key=event.dedupe_key)
        raw_record = RawEventRecord(
            dedupe_key=event.dedupe_key,
            source_event_id=event.source_event_id,
            source_endpoint=source_endpoint,
            source_type=source_type,
            received_at=received_at,
            event_timestamp=event.timestamp,
            raw_payload=raw_payload,
        )

        with self.db.transaction():
            raw_event_id = self.repo.insert_raw_event(raw_record)
            if raw_event_id is None:
                self._seen_keys.add(event.dedupe_key)
                return IngestionResult(status="duplicate", dedupe_key=event.dedupe_key)

            trader = self.repo.find_trader_by_wallet(event.proxy_wallet_address or event.trader_address)
            trader_id = trader["trader_id"] if trader else None
            if not trader_id:
                trader_id = (event.proxy_wallet_address or event.trader_address).lower()
                self.repo.upsert_trader(
                    {
                        "trader_id": trader_id,
                        "display_name": raw_payload.get("name") or raw_payload.get("pseudonym") or trader_id[:10],
                        "username": raw_payload.get("pseudonym") or raw_payload.get("name"),
                        "wallet_address": event.trader_address,
                        "proxy_wallet_address": event.proxy_wallet_address,
                        "manual_weight": 1.0,
                        "derived_weight": 1.0,
                        "discovery_source": "observed_trade",
                        "raw_profile_payload": raw_payload,
                    }
                )

            self.repo.upsert_market(
                {
                    "market_id": event.market_id,
                    "condition_id": event.condition_id,
                    "question": event.question,
                    "slug": event.slug,
                    "market_url": event.market_url,
                    "raw_payload": raw_payload,
                }
            )

            direction = normalize_direction(event.raw_side, event.outcome_name)
            previous = self.repo.get_position(position_key_for(event))
            action, state = self.positions.classify_and_update(previous, event, direction, trader_id)
            trade = build_normalized_trade(event, raw_event_id, trader_id, direction, action, received_at)
            inserted = self.repo.insert_normalized_trade(trade)
            if not inserted:
                self._seen_keys.add(event.dedupe_key)
                return IngestionResult(status="duplicate", dedupe_key=event.dedupe_key)
            self.repo.upsert_position(state)

        self._seen_keys.add(event.dedupe_key)
        return IngestionResult(status="ingested", dedupe_key=event.dedupe_key, trade=trade)
