from __future__ import annotations

from typing import Any

from polymarket_tracker.trades.models import ValidatedTradeEvent
from polymarket_tracker.utils.json import stable_hash
from polymarket_tracker.utils.time import to_iso


class ValidationError(ValueError):
    pass


def validate_trade_event(raw: dict[str, Any], source_endpoint: str) -> ValidatedTradeEvent:
    proxy_wallet = _string(raw, "proxyWallet", "proxy_wallet", "user", "trader")
    trader_address = proxy_wallet or _string(raw, "wallet", "walletAddress", "maker", "owner")
    if not trader_address:
        raise ValidationError("missing trader/proxy wallet address")

    raw_side = _string(raw, "side", "rawSide")
    if raw_side not in {"BUY", "SELL"}:
        raise ValidationError(f"unsupported or missing side: {raw_side!r}")

    price = _float(raw, "price")
    size = _float(raw, "size")
    if price is None or price < 0 or price > 1:
        raise ValidationError(f"price must be between 0 and 1, got {price!r}")
    if size is None or size <= 0:
        raise ValidationError(f"size must be positive, got {size!r}")

    condition_id = _string(raw, "conditionId", "condition_id", "market")
    asset = _string(raw, "asset", "assetId", "outcomeTokenId", "token_id")
    market_id = _string(raw, "marketId", "market_id", "market", "conditionId", "condition_id")
    if not market_id:
        raise ValidationError("missing market or condition identifier")

    timestamp_value = raw.get("timestamp") or raw.get("matchTime") or raw.get("createdAt")
    timestamp = to_iso(timestamp_value)
    tx_hash = _string(raw, "transactionHash", "transaction_hash", "hash")
    source_event_id = _string(raw, "id", "eventId", "tradeId") or tx_hash
    dedupe_key = _dedupe_key(raw, trader_address, market_id, asset, raw_side, price, size, timestamp, tx_hash)

    title = _string(raw, "title", "question")
    slug = _string(raw, "slug")
    market_url = f"https://polymarket.com/event/{slug}" if slug else None
    outcome_index = _int(raw, "outcomeIndex")
    notional = _float(raw, "notional", "sizeUsdc")
    if notional is None:
        notional = price * size

    return ValidatedTradeEvent(
        dedupe_key=dedupe_key,
        source_event_id=source_event_id,
        trader_address=trader_address,
        proxy_wallet_address=proxy_wallet,
        market_id=market_id,
        condition_id=condition_id,
        question=title,
        slug=slug,
        market_url=market_url,
        outcome_token_id=asset,
        outcome_name=_string(raw, "outcome", "outcomeName"),
        outcome_index=outcome_index,
        raw_side=raw_side,
        price=price,
        size=size,
        notional=notional,
        transaction_hash=tx_hash,
        block_number=_int(raw, "blockNumber", "block_number"),
        timestamp=timestamp,
        source_endpoint=source_endpoint,
        raw_payload=raw,
    )


def quarantine_key(raw: dict[str, Any]) -> str:
    return stable_hash(raw)


def _dedupe_key(
    raw: dict[str, Any],
    trader_address: str,
    market_id: str,
    asset: str | None,
    side: str,
    price: float,
    size: float,
    timestamp: str,
    tx_hash: str | None,
) -> str:
    if tx_hash:
        return f"tx:{tx_hash.lower()}:{asset or market_id}:{side}:{size:g}:{price:g}"
    if raw.get("id"):
        return f"id:{raw['id']}:{asset or market_id}:{side}"
    return stable_hash(
        {
            "trader": trader_address.lower(),
            "market": market_id,
            "asset": asset,
            "side": side,
            "price": round(price, 8),
            "size": round(size, 8),
            "timestamp": timestamp,
        }
    )


def _string(raw: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = raw.get(key)
        if value is not None and value != "":
            return str(value)
    return None


def _float(raw: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = raw.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValidationError(f"{key} must be numeric, got {value!r}") from None
    return None


def _int(raw: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = raw.get(key)
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValidationError(f"{key} must be integer-like, got {value!r}") from None
    return None
