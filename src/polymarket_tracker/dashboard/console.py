from __future__ import annotations

from typing import Any

from polymarket_tracker.db.sqlite import Database
from polymarket_tracker.utils.json import loads


class ConsoleDashboard:
    def __init__(self, db: Database, max_rows: int = 20) -> None:
        self.db = db
        self.max_rows = max_rows

    def render(self) -> str:
        sections = [
            self.live_trades(),
            self.consensus_signals(),
            self.trader_activity(),
            self.system_health(),
        ]
        return "\n\n".join(sections)

    def live_trades(self) -> str:
        rows = self.db.fetchall(
            """
            SELECT trade_timestamp, trader_id, question, outcome_name, raw_side,
                   normalized_direction, price, size, notional, source_endpoint
            FROM normalized_trades
            ORDER BY trade_timestamp DESC
            LIMIT ?
            """,
            (self.max_rows,),
        )
        lines = ["LIVE TRADES", "-" * 80]
        for row in rows:
            lines.append(
                f"{row['trade_timestamp']} | {row['trader_id']} | {row['outcome_name']} "
                f"{row['raw_side']} {row['normalized_direction']} @ {row['price']:.3f} "
                f"size={row['size']:.2f} notional=${row['notional']:.2f} | {row['question']}"
            )
        if not rows:
            lines.append("No trades ingested yet.")
        return "\n".join(lines)

    def consensus_signals(self) -> str:
        rows = self.db.fetchall(
            """
            SELECT *
            FROM consensus_signals
            ORDER BY trader_count DESC, weighted_trader_count DESC, score DESC,
                     total_notional DESC, latest_trade_timestamp DESC
            LIMIT ?
            """,
            (self.max_rows * 6,),
        )
        lines = ["CONSENSUS SIGNALS", "-" * 80]
        for row in _dedupe_signal_rows(rows, self.max_rows):
            traders = loads(row["traders_involved_json"], [])
            trader_names = ", ".join(item.get("display_name", item.get("trader_id", "?")) for item in traders[:4])
            lines.append(
                f"{row['confidence_tier']} score={row['score']:.1f} window={row['time_window_seconds']}s "
                f"traders={row['trader_count']} weighted={row['weighted_trader_count']:.2f} "
                f"notional=${row['total_notional']:.2f} {row['direction']} {row['outcome']} | {row['market_title']} "
                f"| {trader_names}"
            )
            lines.append(f"  uncertainty: {row['uncertainty_notes']}")
        if not rows:
            lines.append("No consensus signals yet.")
        return "\n".join(lines)

    def trader_activity(self) -> str:
        rows = self.db.fetchall(
            """
            WITH trade_stats AS (
                SELECT trader_id, COUNT(*) AS trades_today,
                       COALESCE(SUM(notional), 0) AS notional_today,
                       MAX(trade_timestamp) AS latest_trade
                FROM normalized_trades
                GROUP BY trader_id
            ),
            position_stats AS (
                SELECT trader_id, COUNT(DISTINCT position_key) AS active_positions
                FROM inferred_positions
                WHERE position_status != 'CLOSED'
                GROUP BY trader_id
            )
            SELECT t.trader_id, t.display_name,
                   COALESCE(ts.trades_today, 0) AS trades_today,
                   COALESCE(ts.notional_today, 0) AS notional_today,
                   COALESCE(ps.active_positions, 0) AS active_positions,
                   ts.latest_trade
            FROM traders t
            LEFT JOIN trade_stats ts ON ts.trader_id = t.trader_id
            LEFT JOIN position_stats ps ON ps.trader_id = t.trader_id
            ORDER BY notional_today DESC
            LIMIT ?
            """,
            (self.max_rows,),
        )
        lines = ["TRADER ACTIVITY", "-" * 80]
        for row in rows:
            lines.append(
                f"{row['display_name'] or row['trader_id']} | trades={row['trades_today']} "
                f"notional=${row['notional_today']:.2f} active_positions={row['active_positions']} "
                f"latest={row['latest_trade'] or 'never'}"
            )
        if not rows:
            lines.append("No tracked traders yet.")
        return "\n".join(lines)

    def market_detail(self, market_id: str) -> str:
        rows = self.db.fetchall(
            """
            SELECT trader_id, outcome_name, normalized_direction, action_classification,
                   price, size, notional, trade_timestamp
            FROM normalized_trades
            WHERE market_id = ?
            ORDER BY trade_timestamp DESC
            LIMIT ?
            """,
            (market_id, self.max_rows),
        )
        lines = [f"MARKET DETAIL {market_id}", "-" * 80]
        for row in rows:
            lines.append(
                f"{row['trade_timestamp']} | {row['trader_id']} | {row['action_classification']} "
                f"{row['normalized_direction']} {row['outcome_name']} size={row['size']:.2f} "
                f"notional=${row['notional']:.2f}"
            )
        if not rows:
            lines.append("No tracked trades for this market.")
        return "\n".join(lines)

    def system_health(self) -> str:
        row = self.db.fetchone(
            """
            SELECT * FROM system_health_snapshots
            ORDER BY captured_at DESC
            LIMIT 1
            """
        )
        if not row:
            return "SYSTEM HEALTH\n" + "-" * 80 + "\nNo health snapshot recorded yet."
        return "\n".join(
            [
                "SYSTEM HEALTH",
                "-" * 80,
                (
                    f"database={row['database_status']} websocket={row['websocket_status']} "
                    f"polling={row['polling_status']}"
                ),
                f"last_event={row['last_event_time']} api_error_rate={row['api_error_rate']:.2f}",
                f"tracked_traders={row['tracked_trader_count']} tracked_markets={row['tracked_market_count']} "
                f"malformed_events={row['malformed_event_count']}",
                f"degraded={row['degraded_mode_status']} blockers={row['unresolved_blockers'] or 'none'}",
            ]
        )


def _dedupe_signal_rows(rows: list[Any], limit: int) -> list[Any]:
    seen: set[tuple[Any, Any, Any]] = set()
    deduped: list[Any] = []
    for row in rows:
        key = (row["market_id"], row["outcome_token_id"], row["direction"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
        if len(deduped) >= limit:
            break
    return deduped
