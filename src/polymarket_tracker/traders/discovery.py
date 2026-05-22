from __future__ import annotations

from typing import Any

from polymarket_tracker.api.polymarket import PolymarketClient
from polymarket_tracker.config.settings import TradersConfig
from polymarket_tracker.db.repositories import Repository
from polymarket_tracker.db.sqlite import Database
from polymarket_tracker.utils.json import dumps
from polymarket_tracker.utils.time import iso_now


class TraderRegistry:
    def __init__(self, db: Database, config: TradersConfig) -> None:
        self.db = db
        self.repo = Repository(db)
        self.config = config

    def load_manual(self) -> None:
        with self.db.transaction():
            for trader in self.config.manual:
                self.repo.upsert_trader(
                    {
                        "trader_id": trader.trader_id,
                        "display_name": trader.display_name,
                        "username": trader.username,
                        "wallet_address": trader.wallet_address,
                        "proxy_wallet_address": trader.proxy_wallet_address,
                        "manual_weight": trader.manual_weight,
                        "derived_weight": trader.manual_weight,
                        "discovery_source": trader.discovery_source,
                        "raw_profile_payload": {"source": "config"},
                    }
                )

    def discover_from_leaderboard(self, client: PolymarketClient) -> int:
        if not self.config.discovery.enabled:
            return 0
        payload_by_period = self._fetch_leaderboard_periods(client)
        merged = self._merge_leaderboard_payloads(payload_by_period)
        now = iso_now()
        with self.db.transaction():
            for period, payload in payload_by_period:
                self.db.execute(
                    """
                    INSERT INTO trader_discovery_snapshots(source, captured_at, raw_payload)
                    VALUES (?, ?, ?)
                    """,
                    (f"data-api:/v1/leaderboard:{period}", now, dumps(payload)),
                )
            count = 0
            for item in merged:
                if not self._passes_filters(item):
                    continue
                proxy = item.get("proxyWallet")
                if not proxy:
                    continue
                trader_id = str(proxy).lower()
                self.repo.upsert_trader(
                    {
                        "trader_id": trader_id,
                        "display_name": item.get("userName"),
                        "username": item.get("userName"),
                        "profile_url": f"https://polymarket.com/profile/{item.get('userName')}"
                        if item.get("userName")
                        else None,
                        "wallet_address": proxy,
                        "proxy_wallet_address": proxy,
                        "manual_weight": 1.0,
                        "derived_weight": self._derived_weight(item),
                        "volume": item.get("vol"),
                        "pnl": item.get("pnl"),
                        "discovery_source": "data-api-leaderboard:" + ",".join(item.get("_leaderboard_periods", [])),
                        "raw_profile_payload": item,
                    }
                )
                count += 1
        return count

    def _fetch_leaderboard_periods(self, client: PolymarketClient) -> list[tuple[str, list[dict[str, Any]]]]:
        payloads: list[tuple[str, list[dict[str, Any]]]] = []
        for period in self.config.discovery.time_periods:
            try:
                payloads.append((period, client.fetch_leaderboard(self.config.discovery, period)))
            except Exception as exc:
                self.repo.insert_api_error(
                    "data-api:/v1/leaderboard",
                    type(exc).__name__,
                    str(exc),
                    raw_payload={"time_period": period},
                )
        return payloads

    def _merge_leaderboard_payloads(
        self, payload_by_period: list[tuple[str, list[dict[str, Any]]]]
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for period, payload in payload_by_period:
            for item in payload:
                proxy = str(item.get("proxyWallet") or "").lower()
                if not proxy:
                    continue
                existing = merged.get(proxy)
                if existing:
                    periods = existing.setdefault("_leaderboard_periods", [])
                    periods.append(period)
                    existing["_leaderboard_periods"] = list(dict.fromkeys(periods))
                    continue
                merged[proxy] = {**item, "_leaderboard_periods": [period]}
        return list(merged.values())

    def tracked_wallets(self) -> list[str]:
        rows = self.repo.list_traders()
        wallets: list[str] = []
        for row in rows:
            wallet = row["proxy_wallet_address"] or row["wallet_address"]
            if wallet:
                wallets.append(wallet)
        return wallets

    def _passes_filters(self, item: dict[str, Any]) -> bool:
        volume = float(item.get("vol") or 0)
        pnl = item.get("pnl")
        if volume < self.config.discovery.min_volume:
            return False
        if self.config.discovery.min_pnl is not None and float(pnl or 0) < self.config.discovery.min_pnl:
            return False
        proxy = str(item.get("proxyWallet") or "").lower()
        if proxy in {value.lower() for value in self.config.blacklist}:
            return False
        return not (self.config.whitelist and proxy not in {value.lower() for value in self.config.whitelist})

    def _derived_weight(self, item: dict[str, Any]) -> float:
        volume = max(float(item.get("vol") or 0.0), 0.0)
        pnl = float(item.get("pnl") or 0.0)
        volume_score = min(volume / 10000.0, 1.0)
        pnl_score = max(min(pnl / 10000.0, 1.0), -1.0)
        return round(max(0.2, 1.0 + volume_score + (0.5 * pnl_score)), 4)
