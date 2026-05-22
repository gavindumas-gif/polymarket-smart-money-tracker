from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from polymarket_tracker.alerts.manager import AlertManager
from polymarket_tracker.api.polymarket import PolymarketClient
from polymarket_tracker.config.settings import AppConfig
from polymarket_tracker.consensus.engine import ConsensusEngine
from polymarket_tracker.dashboard.console import ConsoleDashboard
from polymarket_tracker.db.repositories import Repository
from polymarket_tracker.db.sqlite import Database
from polymarket_tracker.health import record_health
from polymarket_tracker.traders.discovery import TraderRegistry
from polymarket_tracker.trades.processor import TradeProcessor
from polymarket_tracker.utils.time import iso_now, utc_now

LOGGER = logging.getLogger(__name__)


def open_database(config: AppConfig) -> Database:
    db = Database(config.database.url, config.database.busy_timeout_ms)
    db.migrate()
    return db


def reset_database_if_requested(config: AppConfig, should_reset: bool) -> None:
    if not should_reset:
        return
    from polymarket_tracker.config.settings import sqlite_path

    path = sqlite_path(config.database.url)
    for candidate in [path, Path(str(path) + "-wal"), Path(str(path) + "-shm")]:
        if candidate.exists():
            candidate.unlink()


def run_dry_run(config: AppConfig) -> dict[str, Any]:
    reset_database_if_requested(config, config.dry_run.reset_database)
    db = open_database(config)
    try:
        registry = TraderRegistry(db, config.traders)
        registry.load_manual()
        processor = TradeProcessor(db)
        results = _ingest_fixture(processor, config.dry_run.fixture_path)
        consensus = ConsensusEngine(db, config.consensus, config.scoring)
        signals = consensus.evaluate()
        alerts = AlertManager(db, config.alerts, config.consensus).process(signals)
        record_health(db, websocket_status="dry_run_not_used", polling_status="dry_run_complete")
        dashboard = ConsoleDashboard(db, config.dashboard.max_rows).render()
        return {
            "results": results,
            "signal_count": len(signals),
            "alert_count": len(alerts),
            "dashboard": dashboard,
            "database": str(db.path),
        }
    finally:
        db.close()


def run_replay(config: AppConfig) -> dict[str, Any]:
    reset_database_if_requested(config, config.replay.reset_database)
    db = open_database(config)
    try:
        registry = TraderRegistry(db, config.traders)
        registry.load_manual()
        processor = TradeProcessor(db)
        events = _load_fixture_events(config.replay.fixture_path)
        events.sort(key=lambda item: item.get("timestamp_offset_seconds", 0), reverse=True)
        replayed = 0
        for event in events:
            if event.get("malformed_expected"):
                continue
            payload = _materialize_event(event)
            processor.ingest(payload, "fixture:replay", "replay")
            replayed += 1
        signals = ConsensusEngine(db, config.consensus, config.scoring).evaluate()
        record_health(db, websocket_status="replay_not_used", polling_status="replay_complete")
        summary = _backtest_summary(db)
        return {"replayed": replayed, "signals": len(signals), "summary": summary}
    finally:
        db.close()


def run_live(config: AppConfig, once: bool = False) -> dict[str, Any]:
    db = open_database(config)
    client = PolymarketClient(config.api)
    registry = TraderRegistry(db, config.traders)
    processor = TradeProcessor(db)
    status = {"poll_cycles": 0, "ingested": 0, "duplicates": 0, "errors": 0}
    try:
        registry.load_manual()
        try:
            discovered = registry.discover_from_leaderboard(client)
            LOGGER.info("discovered %s traders from leaderboard", discovered)
        except Exception as exc:
            Repository(db).insert_api_error("data-api:/v1/leaderboard", type(exc).__name__, str(exc))
            LOGGER.warning("leaderboard discovery degraded: %s", exc)

        while True:
            status["poll_cycles"] += 1
            for wallet in registry.tracked_wallets():
                try:
                    trades = client.fetch_trades(user=wallet, limit=config.ingestion.max_events_per_poll)
                    for raw in trades:
                        result = processor.ingest(raw, "data-api:/trades", "polling")
                        if result.status == "ingested":
                            status["ingested"] += 1
                        elif result.status == "duplicate":
                            status["duplicates"] += 1
                except Exception as exc:
                    status["errors"] += 1
                    Repository(db).insert_api_error(
                        "data-api:/trades", type(exc).__name__, str(exc), raw_payload={"wallet": wallet}
                    )
                    LOGGER.warning("polling failed for wallet %s: %s", wallet, exc)
            signals = ConsensusEngine(db, config.consensus, config.scoring).evaluate()
            AlertManager(db, config.alerts, config.consensus).process(signals)
            record_health(db, websocket_status="not_started_optional", polling_status="running")
            if once:
                break
            time.sleep(config.ingestion.poll_interval_seconds)
        return status
    finally:
        db.close()


def run_dashboard(config: AppConfig, market_id: str | None = None) -> str:
    db = open_database(config)
    try:
        dashboard = ConsoleDashboard(db, config.dashboard.max_rows)
        return dashboard.market_detail(market_id) if market_id else dashboard.render()
    finally:
        db.close()


def run_health(config: AppConfig) -> str:
    db = open_database(config)
    try:
        record_health(db)
        return ConsoleDashboard(db, config.dashboard.max_rows).system_health()
    finally:
        db.close()


def _ingest_fixture(processor: TradeProcessor, fixture_path: str) -> dict[str, int]:
    counts = {"ingested": 0, "duplicate": 0, "malformed": 0}
    for event in _load_fixture_events(fixture_path):
        payload = _materialize_event(event)
        result = processor.ingest(payload, "fixture:mock_trades", "dry-run")
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def _load_fixture_events(fixture_path: str) -> list[dict[str, Any]]:
    data = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("fixture must be a list of events")
    return data


def _materialize_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value for key, value in event.items() if key not in {"timestamp_offset_seconds", "malformed_expected"}
    }
    if "timestamp_offset_seconds" in event:
        payload["timestamp"] = int((utc_now().timestamp()) - float(event["timestamp_offset_seconds"]))
    if "createdAt_offset_seconds" in event:
        payload["createdAt"] = iso_now()
    return payload


def _backtest_summary(db: Database) -> list[dict[str, Any]]:
    rows = db.fetchall(
        """
        SELECT signal_id, trigger_timestamp, market_title, outcome, direction,
               trader_count, weighted_average_entry_price, latest_price, score
        FROM consensus_signals
        ORDER BY trigger_timestamp
        """
    )
    return [
        {
            "signal_time": row["trigger_timestamp"],
            "market": row["market_title"],
            "outcome": row["outcome"],
            "direction": row["direction"],
            "traders": row["trader_count"],
            "entry_price": row["weighted_average_entry_price"],
            "latest_price": row["latest_price"],
            "score": row["score"],
            "note": "Fixture replay cannot infer later 1h/6h/24h prices unless price history is supplied.",
        }
        for row in rows
    ]
