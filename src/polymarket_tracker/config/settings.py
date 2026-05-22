from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from polymarket_tracker.config.simple_yaml import load_yaml_file


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class DatabaseConfig:
    url: str = "sqlite:///./data/polymarket_tracker.sqlite"
    busy_timeout_ms: int = 5000


@dataclass(frozen=True)
class ApiConfig:
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    data_base_url: str = "https://data-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    ws_market_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    ws_user_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
    request_timeout_seconds: float = 12.0
    max_retries: int = 3
    backoff_base_seconds: float = 0.5
    backoff_max_seconds: float = 30.0
    jitter_ratio: float = 0.25
    circuit_breaker_failures: int = 5
    circuit_breaker_reset_seconds: float = 45.0
    user_agent: str = "polymarket-smart-money-tracker/0.1"


@dataclass(frozen=True)
class ManualTraderConfig:
    trader_id: str
    display_name: str | None = None
    username: str | None = None
    wallet_address: str | None = None
    proxy_wallet_address: str | None = None
    manual_weight: float = 1.0
    discovery_source: str = "manual"


@dataclass(frozen=True)
class DiscoveryConfig:
    enabled: bool = True
    category: str = "OVERALL"
    time_period: str = "WEEK"
    time_periods: tuple[str, ...] = ("DAY", "WEEK", "MONTH", "ALL")
    order_by: str = "PNL"
    limit: int = 20
    min_volume: float = 0.0
    min_pnl: float | None = None
    refresh_seconds: int = 3600


@dataclass(frozen=True)
class TradersConfig:
    manual: tuple[ManualTraderConfig, ...] = field(default_factory=tuple)
    blacklist: tuple[str, ...] = field(default_factory=tuple)
    whitelist: tuple[str, ...] = field(default_factory=tuple)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)


@dataclass(frozen=True)
class IngestionConfig:
    source_mode: str = "polling"
    poll_interval_seconds: float = 20.0
    lookback_seconds: int = 1800
    max_events_per_poll: int = 200
    websocket_enabled: bool = True
    replay_missed_after_disconnect: bool = True
    malformed_event_retention_days: int = 30


@dataclass(frozen=True)
class NormalizationConfig:
    allow_binary_equivalence: bool = False
    unknown_outcome_direction: str = "UNKNOWN"


@dataclass(frozen=True)
class ConsensusConfig:
    windows_seconds: tuple[int, ...] = (60, 300, 900, 3600, 21600, 86400)
    minimum_traders: int = 2
    minimum_weighted_traders: float = 2.0
    minimum_total_notional: float = 50.0
    minimum_individual_notional: float = 5.0
    minimum_liquidity: float = 0.0
    minimum_trader_quality: float = 0.0
    included_markets: tuple[str, ...] = field(default_factory=tuple)
    excluded_markets: tuple[str, ...] = field(default_factory=tuple)
    included_traders: tuple[str, ...] = field(default_factory=tuple)
    excluded_traders: tuple[str, ...] = field(default_factory=tuple)
    ignore_exits: bool = True
    count_adds: bool = True
    cancel_opposing_signals: bool = False
    cooldown_seconds: int = 900
    alert_score_threshold: float = 55.0


@dataclass(frozen=True)
class ScoringConfig:
    max_score: float = 100.0
    weights: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class AlertChannelConfig:
    enabled: bool = False
    webhook_url_env: str | None = None


@dataclass(frozen=True)
class AlertsConfig:
    console: AlertChannelConfig = field(default_factory=lambda: AlertChannelConfig(enabled=True))
    discord: AlertChannelConfig = field(default_factory=AlertChannelConfig)
    generic_webhook: AlertChannelConfig = field(default_factory=AlertChannelConfig)
    telegram: AlertChannelConfig = field(default_factory=AlertChannelConfig)
    cooldown_seconds: int = 900
    material_score_delta: float = 8.0
    max_per_minute: int = 6


@dataclass(frozen=True)
class DashboardConfig:
    refresh_seconds: float = 5.0
    max_rows: int = 20


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    json: bool = False
    file: str | None = "logs/tracker.log"


@dataclass(frozen=True)
class DryRunConfig:
    fixture_path: str = "fixtures/mock_trades.json"
    reset_database: bool = True


@dataclass(frozen=True)
class ReplayConfig:
    fixture_path: str = "fixtures/mock_trades.json"
    speed_multiplier: float = 1000.0
    reset_database: bool = True


@dataclass(frozen=True)
class AppConfig:
    mode: str = "dry-run"
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    traders: TradersConfig = field(default_factory=TradersConfig)
    ingestion: IngestionConfig = field(default_factory=IngestionConfig)
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    consensus: ConsensusConfig = field(default_factory=ConsensusConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    dry_run: DryRunConfig = field(default_factory=DryRunConfig)
    replay: ReplayConfig = field(default_factory=ReplayConfig)


def load_config(path: str | Path | None = None) -> AppConfig:
    chosen_path = path or os.getenv("PM_TRACKER_CONFIG")
    raw: dict[str, Any] = {}
    if chosen_path:
        raw = load_yaml_file(chosen_path)
    elif Path("config.yaml").exists():
        raw = load_yaml_file("config.yaml")
    elif Path("config.example.yaml").exists():
        raw = load_yaml_file("config.example.yaml")

    if os.getenv("PM_TRACKER_MODE"):
        raw["mode"] = os.environ["PM_TRACKER_MODE"]
    if os.getenv("PM_TRACKER_DATABASE_URL"):
        raw.setdefault("database", {})["url"] = os.environ["PM_TRACKER_DATABASE_URL"]
    return config_from_dict(raw)


def config_from_dict(raw: dict[str, Any]) -> AppConfig:
    scoring_weights = {
        "trader_count": 18.0,
        "weighted_trader_count": 18.0,
        "total_notional": 16.0,
        "concentration": 10.0,
        "trader_quality": 12.0,
        "recency": 8.0,
        "speed": 6.0,
        "agreement_ratio": 8.0,
        "liquidity": 4.0,
        "price_movement": 4.0,
        "opposing_penalty": -14.0,
        "late_entry_penalty": -5.0,
        "uncertainty_penalty": -10.0,
    }
    if isinstance(raw.get("scoring", {}).get("weights"), dict):
        scoring_weights.update({k: float(v) for k, v in raw["scoring"]["weights"].items()})

    traders_raw = raw.get("traders", {})
    discovery_raw = traders_raw.get("discovery", {})
    discovery_periods = _discovery_time_periods(discovery_raw)
    discovery_values = {
        key: value
        for key, value in discovery_raw.items()
        if key in DiscoveryConfig.__dataclass_fields__ and key not in {"time_period", "time_periods"}
    }
    discovery = DiscoveryConfig(
        **discovery_values,
        time_period=discovery_periods[0],
        time_periods=discovery_periods,
    )

    config = AppConfig(
        mode=str(raw.get("mode", "dry-run")),
        database=_build(DatabaseConfig, raw.get("database", {})),
        api=_build(ApiConfig, raw.get("api", {})),
        traders=TradersConfig(
            manual=tuple(ManualTraderConfig(**item) for item in traders_raw.get("manual", [])),
            blacklist=tuple(traders_raw.get("blacklist", [])),
            whitelist=tuple(traders_raw.get("whitelist", [])),
            discovery=discovery,
        ),
        ingestion=_build(IngestionConfig, raw.get("ingestion", {})),
        normalization=_build(NormalizationConfig, raw.get("normalization", {})),
        consensus=ConsensusConfig(
            **{
                **raw.get("consensus", {}),
                "windows_seconds": tuple(
                    raw.get("consensus", {}).get("windows_seconds", (60, 300, 900, 3600, 21600, 86400))
                ),
                "included_markets": tuple(raw.get("consensus", {}).get("included_markets", [])),
                "excluded_markets": tuple(raw.get("consensus", {}).get("excluded_markets", [])),
                "included_traders": tuple(raw.get("consensus", {}).get("included_traders", [])),
                "excluded_traders": tuple(raw.get("consensus", {}).get("excluded_traders", [])),
            }
        ),
        scoring=ScoringConfig(max_score=float(raw.get("scoring", {}).get("max_score", 100.0)), weights=scoring_weights),
        alerts=AlertsConfig(
            console=_build(AlertChannelConfig, raw.get("alerts", {}).get("console", {"enabled": True})),
            discord=_build(AlertChannelConfig, raw.get("alerts", {}).get("discord", {})),
            generic_webhook=_build(AlertChannelConfig, raw.get("alerts", {}).get("generic_webhook", {})),
            telegram=_build(AlertChannelConfig, raw.get("alerts", {}).get("telegram", {})),
            cooldown_seconds=int(raw.get("alerts", {}).get("cooldown_seconds", 900)),
            material_score_delta=float(raw.get("alerts", {}).get("material_score_delta", 8.0)),
            max_per_minute=int(raw.get("alerts", {}).get("max_per_minute", 6)),
        ),
        dashboard=_build(DashboardConfig, raw.get("dashboard", {})),
        logging=_build(LoggingConfig, raw.get("logging", {})),
        dry_run=_build(DryRunConfig, raw.get("dry_run", {})),
        replay=_build(ReplayConfig, raw.get("replay", {})),
    )
    validate_config(config)
    return config


def validate_config(config: AppConfig) -> None:
    if not config.database.url.startswith("sqlite:///"):
        raise ConfigError("Only sqlite:/// database URLs are supported by this local build")
    if config.consensus.minimum_traders < 1:
        raise ConfigError("consensus.minimum_traders must be at least 1")
    if config.consensus.minimum_weighted_traders <= 0:
        raise ConfigError("consensus.minimum_weighted_traders must be positive")
    if config.ingestion.poll_interval_seconds <= 0:
        raise ConfigError("ingestion.poll_interval_seconds must be positive")
    if config.api.max_retries < 0:
        raise ConfigError("api.max_retries cannot be negative")
    if config.traders.discovery.limit < 1:
        raise ConfigError("traders.discovery.limit must be at least 1")
    if not config.traders.discovery.time_periods:
        raise ConfigError("traders.discovery.time_periods must include at least one period")
    for name, url in {
        "gamma_base_url": config.api.gamma_base_url,
        "data_base_url": config.api.data_base_url,
        "clob_base_url": config.api.clob_base_url,
    }.items():
        if not (url.startswith("https://") or url.startswith("http://")):
            raise ConfigError(f"api.{name} must be an HTTP(S) URL")
    if config.ingestion.websocket_enabled and not config.api.ws_market_url.startswith("wss://"):
        raise ConfigError("api.ws_market_url must be a wss:// URL when websocket is enabled")
    for trader in config.traders.manual:
        if not trader.wallet_address and not trader.proxy_wallet_address:
            raise ConfigError(f"manual trader {trader.trader_id} needs wallet_address or proxy_wallet_address")


def sqlite_path(database_url: str) -> Path:
    if not database_url.startswith("sqlite:///"):
        raise ConfigError("Only sqlite:/// database URLs are supported")
    raw_path = database_url.removeprefix("sqlite:///")
    return Path(raw_path)


def _build(cls: type[Any], values: dict[str, Any]) -> Any:
    if not values:
        return cls()
    allowed = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
    return cls(**{key: value for key, value in values.items() if key in allowed})


def _discovery_time_periods(discovery: dict[str, Any]) -> tuple[str, ...]:
    if "time_periods" in discovery:
        raw_periods = discovery["time_periods"]
    elif "time_period" in discovery:
        raw_periods = [discovery["time_period"]]
    else:
        raw_periods = list(DiscoveryConfig.time_periods)
    if isinstance(raw_periods, str):
        raw_periods = [raw_periods]
    return tuple(dict.fromkeys(str(period).upper() for period in raw_periods if str(period).strip()))
