from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Iterable
from typing import Any

from polymarket_tracker.config.settings import ApiConfig

LOGGER = logging.getLogger(__name__)


class WebSocketUnavailable(RuntimeError):
    pass


class MarketWebSocketClient:
    def __init__(self, config: ApiConfig, asset_ids: Iterable[str], on_event: Callable[[dict[str, Any]], None]) -> None:
        self.config = config
        self.asset_ids = list(asset_ids)
        self.on_event = on_event
        self.status = "stopped"
        self._stop = asyncio.Event()

    async def run_forever(self) -> None:
        try:
            import websockets  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            self.status = "degraded_missing_websockets_dependency"
            raise WebSocketUnavailable("Install optional extra: python -m pip install -e .[websocket]") from exc

        attempt = 0
        while not self._stop.is_set():
            try:
                self.status = "connecting"
                async with websockets.connect(self.config.ws_market_url, ping_interval=None) as websocket:
                    self.status = "connected"
                    await websocket.send(
                        json.dumps(
                            {
                                "assets_ids": self.asset_ids,
                                "type": "market",
                                "custom_feature_enabled": True,
                            }
                        )
                    )
                    attempt = 0
                    heartbeat = asyncio.create_task(self._heartbeat(websocket))
                    try:
                        async for message in websocket:
                            if message == "PONG":
                                continue
                            payload = json.loads(message)
                            if isinstance(payload, list):
                                for item in payload:
                                    if isinstance(item, dict):
                                        self.on_event(item)
                            elif isinstance(payload, dict):
                                self.on_event(payload)
                    finally:
                        heartbeat.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - exercised in integration/live use
                attempt += 1
                self.status = f"reconnecting_after_error:{type(exc).__name__}"
                delay = min(self.config.backoff_max_seconds, self.config.backoff_base_seconds * (2**attempt))
                LOGGER.warning("market websocket disconnected: %s; retrying in %.1fs", exc, delay)
                await asyncio.sleep(delay)

    async def stop(self) -> None:
        self._stop.set()

    async def _heartbeat(self, websocket: Any) -> None:
        while True:
            await asyncio.sleep(10)
            await websocket.send("PING")
