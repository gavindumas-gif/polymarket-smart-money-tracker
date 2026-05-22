from __future__ import annotations

from polymarket_tracker.db.sqlite import Database
from polymarket_tracker.utils.json import dumps
from polymarket_tracker.utils.time import iso_now


def record_health(
    db: Database,
    websocket_status: str = "not_started",
    polling_status: str = "not_started",
    degraded_mode_status: str = "OK",
    unresolved_blockers: str | None = None,
) -> None:
    last_event = db.fetchone("SELECT MAX(trade_timestamp) AS last_event_time FROM normalized_trades")
    tracked_traders = db.fetchone("SELECT COUNT(*) AS count FROM traders")
    tracked_markets = db.fetchone("SELECT COUNT(*) AS count FROM markets")
    malformed = db.fetchone("SELECT COUNT(*) AS count FROM malformed_events")
    api_errors = db.fetchone(
        "SELECT COUNT(*) AS count FROM api_errors WHERE occurred_at >= datetime('now', '-10 minutes')"
    )
    raw_payload = {
        "database_path": str(db.path),
        "websocket_status": websocket_status,
        "polling_status": polling_status,
    }
    db.execute(
        """
        INSERT INTO system_health_snapshots (
            captured_at, websocket_status, polling_status, last_event_time, database_status,
            api_error_rate, tracked_trader_count, tracked_market_count, malformed_event_count,
            degraded_mode_status, unresolved_blockers, raw_payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            iso_now(),
            websocket_status,
            polling_status,
            last_event["last_event_time"] if last_event else None,
            db.health(),
            float(api_errors["count"] if api_errors else 0),
            int(tracked_traders["count"] if tracked_traders else 0),
            int(tracked_markets["count"] if tracked_markets else 0),
            int(malformed["count"] if malformed else 0),
            degraded_mode_status,
            unresolved_blockers,
            dumps(raw_payload),
        ),
    )
