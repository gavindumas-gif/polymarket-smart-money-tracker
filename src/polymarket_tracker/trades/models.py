from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RawEventRecord:
    dedupe_key: str
    source_event_id: str | None
    source_endpoint: str
    source_type: str
    received_at: str
    event_timestamp: str | None
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class ValidatedTradeEvent:
    dedupe_key: str
    source_event_id: str | None
    trader_address: str
    proxy_wallet_address: str | None
    market_id: str
    condition_id: str | None
    question: str | None
    slug: str | None
    market_url: str | None
    outcome_token_id: str | None
    outcome_name: str | None
    outcome_index: int | None
    raw_side: str
    price: float
    size: float
    notional: float
    transaction_hash: str | None
    block_number: int | None
    timestamp: str
    source_endpoint: str
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class NormalizedTrade:
    dedupe_key: str
    raw_event_id: int | None
    source_event_id: str | None
    trader_id: str | None
    trader_address: str
    proxy_wallet_address: str | None
    market_id: str
    condition_id: str | None
    question: str | None
    slug: str | None
    market_url: str | None
    outcome_token_id: str | None
    outcome_name: str | None
    raw_side: str
    normalized_direction: str
    price: float
    size: float
    notional: float
    transaction_hash: str | None
    block_number: int | None
    trade_timestamp: str
    source_endpoint: str
    action_classification: str
    position_certainty: str
    uncertainty_notes: str | None
    raw_payload: dict[str, Any]
    ingestion_timestamp: str


@dataclass
class PositionState:
    position_key: str
    trader_id: str | None
    trader_address: str
    proxy_wallet_address: str | None
    market_id: str
    condition_id: str | None
    outcome_token_id: str | None
    normalized_outcome: str | None
    normalized_direction: str
    observed_net_size: float
    total_bought: float
    total_sold: float
    weighted_average_entry: float | None
    average_exit: float | None
    estimated_current_exposure: float | None
    realized_change: float | None
    unrealized_change: float | None
    first_observed_entry: str | None
    last_update: str
    position_status: str
    completeness_flag: str
    uncertainty_notes: str | None
    raw_state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestionResult:
    status: str
    dedupe_key: str | None
    trade: NormalizedTrade | None = None
    validation_error: str | None = None
