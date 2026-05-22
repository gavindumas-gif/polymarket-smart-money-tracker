from __future__ import annotations

from typing import Any

from polymarket_tracker.api.http import HttpClient
from polymarket_tracker.config.settings import ApiConfig, DiscoveryConfig


class PolymarketClient:
    def __init__(self, config: ApiConfig, http_client: HttpClient | None = None) -> None:
        self.config = config
        self.http = http_client or HttpClient(config)

    def fetch_trades(
        self,
        user: str | None = None,
        market: str | None = None,
        limit: int = 100,
        offset: int = 0,
        side: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {"user": user, "market": market, "limit": limit, "offset": offset, "side": side}
        data = self.http.get_json(self.config.data_base_url, "/trades", params)
        if not isinstance(data, list):
            raise ValueError("Data API /trades returned non-list payload")
        return data

    def fetch_leaderboard(self, discovery: DiscoveryConfig) -> list[dict[str, Any]]:
        data = self.http.get_json(
            self.config.data_base_url,
            "/v1/leaderboard",
            {
                "category": discovery.category,
                "timePeriod": discovery.time_period,
                "orderBy": discovery.order_by,
                "limit": discovery.limit,
            },
        )
        if not isinstance(data, list):
            raise ValueError("Data API /v1/leaderboard returned non-list payload")
        return data

    def fetch_markets(self, limit: int = 100, offset: int = 0, active: bool | None = True) -> list[dict[str, Any]]:
        data = self.http.get_json(
            self.config.gamma_base_url,
            "/markets",
            {"limit": limit, "offset": offset, "active": str(active).lower() if active is not None else None},
        )
        if not isinstance(data, list):
            raise ValueError("Gamma API /markets returned non-list payload")
        return data

    def fetch_price_history(self, token_id: str, interval: str = "1d") -> list[dict[str, Any]]:
        data = self.http.get_json(
            self.config.clob_base_url,
            "/prices-history",
            {"market": token_id, "interval": interval},
        )
        if isinstance(data, dict) and isinstance(data.get("history"), list):
            return data["history"]
        raise ValueError("CLOB /prices-history returned unexpected payload")

    def clob_health(self) -> str:
        import urllib.request

        request = urllib.request.Request(
            f"{self.config.clob_base_url.rstrip('/')}/ok",
            headers={"User-Agent": self.config.user_agent},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=self.config.request_timeout_seconds) as response:
            return response.read().decode("utf-8") or "OK"
