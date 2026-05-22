from __future__ import annotations

from polymarket_tracker.markets.normalization import normalize_outcome
from polymarket_tracker.trades.models import NormalizedTrade, PositionState, ValidatedTradeEvent
from polymarket_tracker.utils.json import loads


def position_direction_for_trade(event: ValidatedTradeEvent) -> str:
    outcome = normalize_outcome(event.outcome_name)
    if outcome == "YES":
        return "LONG_YES"
    if outcome == "NO":
        return "LONG_NO"
    if outcome:
        return "LONG_OUTCOME"
    return "UNKNOWN"


def position_key_for(event: ValidatedTradeEvent, direction: str | None = None) -> str:
    position_direction = direction or position_direction_for_trade(event)
    return "|".join(
        [
            (event.proxy_wallet_address or event.trader_address).lower(),
            event.market_id,
            event.condition_id or "",
            event.outcome_token_id or "",
            position_direction,
        ]
    )


class PositionEngine:
    def classify_and_update(
        self,
        previous_row: object | None,
        event: ValidatedTradeEvent,
        direction: str,
        trader_id: str | None,
    ) -> tuple[str, PositionState]:
        previous = _row_to_state(previous_row)
        position_direction = position_direction_for_trade(event)
        delta = event.size if event.raw_side == "BUY" else -event.size
        previous_net = previous.observed_net_size if previous else 0.0
        new_net = previous_net + delta
        action = classify_trade(previous_net, delta, new_net)

        total_bought = (previous.total_bought if previous else 0.0) + (event.size if delta > 0 else 0.0)
        total_sold = (previous.total_sold if previous else 0.0) + (event.size if delta < 0 else 0.0)
        weighted_average_entry = _weighted_entry(previous, event, delta)
        average_exit = _average_exit(previous, event, delta)
        first_entry = previous.first_observed_entry if previous else None
        if delta > 0 and not first_entry:
            first_entry = event.timestamp

        status = "OPEN" if abs(new_net) > 1e-9 else "CLOSED"
        if action == "REVERSE":
            status = "REVERSED"
        certainty = "PARTIAL_HISTORY"
        notes = "Position is inferred from observed events only; historical activity before tracker start is unknown."
        exposure = new_net * event.price
        state = PositionState(
            position_key=position_key_for(event, position_direction),
            trader_id=trader_id,
            trader_address=event.trader_address,
            proxy_wallet_address=event.proxy_wallet_address,
            market_id=event.market_id,
            condition_id=event.condition_id,
            outcome_token_id=event.outcome_token_id,
            normalized_outcome=normalize_outcome(event.outcome_name),
            normalized_direction=position_direction,
            observed_net_size=new_net,
            total_bought=total_bought,
            total_sold=total_sold,
            weighted_average_entry=weighted_average_entry,
            average_exit=average_exit,
            estimated_current_exposure=exposure,
            realized_change=None,
            unrealized_change=None,
            first_observed_entry=first_entry,
            last_update=event.timestamp,
            position_status=status,
            completeness_flag=certainty,
            uncertainty_notes=notes,
            raw_state={"last_delta": delta, "last_price": event.price},
        )
        return action, state


def classify_trade(previous_net: float, delta: float, new_net: float) -> str:
    if delta == 0:
        return "UNKNOWN"
    if previous_net == 0:
        return "NEW_ENTRY" if delta > 0 else "UNKNOWN"
    if previous_net > 0 and delta > 0:
        return "ADD"
    if previous_net > 0 and delta < 0:
        if new_net > 0:
            return "REDUCE"
        if abs(new_net) <= 1e-9:
            return "EXIT"
        return "REVERSE"
    if previous_net < 0 and delta < 0:
        return "ADD"
    if previous_net < 0 and delta > 0:
        if new_net < 0:
            return "REDUCE"
        if abs(new_net) <= 1e-9:
            return "EXIT"
        return "REVERSE"
    return "UNKNOWN"


def _weighted_entry(previous: PositionState | None, event: ValidatedTradeEvent, delta: float) -> float | None:
    if delta <= 0:
        return previous.weighted_average_entry if previous else None
    prev_size = max(previous.observed_net_size, 0.0) if previous else 0.0
    prev_avg = previous.weighted_average_entry or event.price if previous else event.price
    total = prev_size + event.size
    if total <= 0:
        return None
    return ((prev_size * prev_avg) + (event.size * event.price)) / total


def _average_exit(previous: PositionState | None, event: ValidatedTradeEvent, delta: float) -> float | None:
    if delta >= 0:
        return previous.average_exit if previous else None
    prev_sold = previous.total_sold if previous else 0.0
    prev_avg = previous.average_exit or event.price if previous else event.price
    total_sold = prev_sold + event.size
    if total_sold <= 0:
        return None
    return ((prev_sold * prev_avg) + (event.size * event.price)) / total_sold


def _row_to_state(row: object | None) -> PositionState | None:
    if row is None:
        return None
    return PositionState(
        position_key=row["position_key"],
        trader_id=row["trader_id"],
        trader_address=row["trader_address"],
        proxy_wallet_address=row["proxy_wallet_address"],
        market_id=row["market_id"],
        condition_id=row["condition_id"],
        outcome_token_id=row["outcome_token_id"],
        normalized_outcome=row["normalized_outcome"],
        normalized_direction=row["normalized_direction"],
        observed_net_size=float(row["observed_net_size"]),
        total_bought=float(row["total_bought"]),
        total_sold=float(row["total_sold"]),
        weighted_average_entry=row["weighted_average_entry"],
        average_exit=row["average_exit"],
        estimated_current_exposure=row["estimated_current_exposure"],
        realized_change=row["realized_change"],
        unrealized_change=row["unrealized_change"],
        first_observed_entry=row["first_observed_entry"],
        last_update=row["last_update"],
        position_status=row["position_status"],
        completeness_flag=row["completeness_flag"],
        uncertainty_notes=row["uncertainty_notes"],
        raw_state=loads(row["raw_state"], {}),
    )


def build_normalized_trade(
    event: ValidatedTradeEvent,
    raw_event_id: int | None,
    trader_id: str | None,
    direction: str,
    action: str,
    ingestion_timestamp: str,
) -> NormalizedTrade:
    return NormalizedTrade(
        dedupe_key=event.dedupe_key,
        raw_event_id=raw_event_id,
        source_event_id=event.source_event_id,
        trader_id=trader_id,
        trader_address=event.trader_address,
        proxy_wallet_address=event.proxy_wallet_address,
        market_id=event.market_id,
        condition_id=event.condition_id,
        question=event.question,
        slug=event.slug,
        market_url=event.market_url,
        outcome_token_id=event.outcome_token_id,
        outcome_name=event.outcome_name,
        raw_side=event.raw_side,
        normalized_direction=direction,
        price=event.price,
        size=event.size,
        notional=event.notional,
        transaction_hash=event.transaction_hash,
        block_number=event.block_number,
        trade_timestamp=event.timestamp,
        source_endpoint=event.source_endpoint,
        action_classification=action,
        position_certainty="PARTIAL_HISTORY",
        uncertainty_notes=(
            "Observed trade is real input data, but current position is only inferred from tracker-observed history."
        ),
        raw_payload=event.raw_payload,
        ingestion_timestamp=ingestion_timestamp,
    )
