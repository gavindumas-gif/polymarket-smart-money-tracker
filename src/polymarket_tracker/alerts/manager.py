from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections import deque
from typing import Any

from polymarket_tracker.config.settings import AlertsConfig, ConsensusConfig
from polymarket_tracker.consensus.engine import ConsensusSignal
from polymarket_tracker.db.sqlite import Database
from polymarket_tracker.utils.json import dumps, stable_hash
from polymarket_tracker.utils.time import iso_now, parse_iso

LOGGER = logging.getLogger(__name__)


class AlertManager:
    def __init__(self, db: Database, alert_config: AlertsConfig, consensus_config: ConsensusConfig) -> None:
        self.db = db
        self.alert_config = alert_config
        self.consensus_config = consensus_config
        self.recent_alert_times: deque[float] = deque()

    def process(self, signals: list[ConsensusSignal]) -> list[dict[str, Any]]:
        delivered: list[dict[str, Any]] = []
        for signal in signals:
            if signal.score < self.consensus_config.alert_score_threshold:
                continue
            if not self._should_alert(signal):
                continue
            payload = self._payload(signal)
            if self.alert_config.console.enabled:
                self._console_alert(payload)
                self._record(signal, "console", payload, "delivered", None)
                delivered.append(payload)
            for channel, cfg in {
                "discord": self.alert_config.discord,
                "generic_webhook": self.alert_config.generic_webhook,
                "telegram": self.alert_config.telegram,
            }.items():
                if not cfg.enabled or not cfg.webhook_url_env:
                    continue
                url = os.getenv(cfg.webhook_url_env)
                if not url:
                    self._record(signal, channel, payload, "skipped_missing_webhook", cfg.webhook_url_env)
                    continue
                status, error = self._post_json(url, payload)
                self._record(signal, channel, payload, status, error)
        return delivered

    def _should_alert(self, signal: ConsensusSignal) -> bool:
        now = time.time()
        while self.recent_alert_times and now - self.recent_alert_times[0] > 60:
            self.recent_alert_times.popleft()
        if len(self.recent_alert_times) >= self.alert_config.max_per_minute:
            return False

        alert_group = self._alert_group(signal)
        latest = self.db.fetchone(
            """
            SELECT * FROM alerts
            WHERE alert_group_key = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (alert_group,),
        )
        if latest:
            age = (parse_iso(iso_now()) - parse_iso(latest["created_at"])).total_seconds()
            score_delta = abs(float(latest["score"]) - signal.score)
            if age < self.alert_config.cooldown_seconds and score_delta < self.alert_config.material_score_delta:
                return False
        self.recent_alert_times.append(now)
        return True

    def _payload(self, signal: ConsensusSignal) -> dict[str, Any]:
        return {
            "type": "POLYMARKET_SMART_MONEY_CONSENSUS",
            "confidence_tier": signal.confidence_tier,
            "score": signal.score,
            "market": signal.market_title,
            "link": signal.market_url,
            "outcome": signal.outcome,
            "direction": signal.direction,
            "traders_involved": signal.traders_involved,
            "weighted_trader_count": signal.weighted_trader_count,
            "total_notional": signal.total_notional,
            "weighted_average_entry": signal.weighted_average_entry_price,
            "latest_price": signal.latest_price,
            "trigger_reason": signal.signal_explanation,
            "risks_uncertainties": signal.uncertainty_notes,
            "timestamp": signal.trigger_timestamp,
            "time_window_seconds": signal.time_window_seconds,
        }

    def _console_alert(self, payload: dict[str, Any]) -> None:
        LOGGER.warning(
            "ALERT %s score=%.2f market=%s outcome=%s direction=%s notional=$%.2f",
            payload["confidence_tier"],
            payload["score"],
            payload["market"],
            payload["outcome"],
            payload["direction"],
            payload["total_notional"],
        )

    def _record(
        self,
        signal: ConsensusSignal,
        channel: str,
        payload: dict[str, Any],
        delivery_status: str,
        delivery_error: str | None,
    ) -> None:
        bucket = int(signal.score // self.alert_config.material_score_delta)
        alert_group = self._alert_group(signal)
        dedupe = stable_hash(
            {"group": alert_group, "channel": channel, "tier": signal.confidence_tier, "bucket": bucket}
        )
        self.db.execute(
            """
            INSERT OR IGNORE INTO alerts (
                alert_dedupe_key, alert_group_key, signal_id, channel, created_at, score,
                confidence_tier, payload_json, delivery_status, delivery_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dedupe,
                alert_group,
                signal.signal_id,
                channel,
                iso_now(),
                signal.score,
                signal.confidence_tier,
                dumps(payload),
                delivery_status,
                delivery_error,
            ),
        )

    def _alert_group(self, signal: ConsensusSignal) -> str:
        parts = signal.group_key.split("|")
        if len(parts) >= 5:
            return "|".join(parts[:-1])
        return signal.group_key

    def _post_json(self, url: str, payload: dict[str, Any]) -> tuple[str, str | None]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "polymarket-smart-money-tracker/0.1"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if 200 <= response.status < 300:
                    return "delivered", None
                return "failed", f"HTTP {response.status}"
        except urllib.error.URLError as exc:
            LOGGER.warning("webhook delivery failed: %s", exc)
            return "failed", str(exc)
