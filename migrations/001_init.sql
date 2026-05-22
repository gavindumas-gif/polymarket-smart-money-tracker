PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS traders (
    trader_id TEXT PRIMARY KEY,
    display_name TEXT,
    username TEXT,
    profile_url TEXT,
    wallet_address TEXT,
    proxy_wallet_address TEXT,
    discovery_source TEXT NOT NULL,
    manual_weight REAL NOT NULL DEFAULT 1.0,
    derived_weight REAL NOT NULL DEFAULT 1.0,
    volume REAL,
    pnl REAL,
    win_rate REAL,
    recent_activity_score REAL,
    consistency_score REAL,
    specialization_score REAL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    raw_profile_payload TEXT
);

CREATE INDEX IF NOT EXISTS idx_traders_proxy_wallet ON traders(proxy_wallet_address);
CREATE INDEX IF NOT EXISTS idx_traders_wallet ON traders(wallet_address);

CREATE TABLE IF NOT EXISTS trader_discovery_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    raw_payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wallets (
    wallet_address TEXT PRIMARY KEY,
    proxy_wallet_address TEXT,
    trader_id TEXT,
    wallet_type TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    raw_payload TEXT,
    FOREIGN KEY(trader_id) REFERENCES traders(trader_id)
);

CREATE TABLE IF NOT EXISTS markets (
    market_id TEXT PRIMARY KEY,
    condition_id TEXT,
    question TEXT,
    slug TEXT,
    market_url TEXT,
    outcomes_json TEXT,
    outcome_prices_json TEXT,
    clob_token_ids_json TEXT,
    liquidity REAL,
    volume REAL,
    active INTEGER,
    closed INTEGER,
    raw_payload TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_markets_condition ON markets(condition_id);

CREATE TABLE IF NOT EXISTS market_metadata_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT,
    condition_id TEXT,
    captured_at TEXT NOT NULL,
    source_endpoint TEXT NOT NULL,
    raw_payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_trade_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT NOT NULL UNIQUE,
    source_event_id TEXT,
    source_endpoint TEXT NOT NULL,
    source_type TEXT NOT NULL,
    received_at TEXT NOT NULL,
    event_timestamp TEXT,
    raw_payload TEXT NOT NULL,
    payload_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_trade_events_received_at ON raw_trade_events(received_at);
CREATE INDEX IF NOT EXISTS idx_raw_trade_events_source_event ON raw_trade_events(source_event_id);

CREATE TABLE IF NOT EXISTS malformed_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT,
    source_endpoint TEXT NOT NULL,
    received_at TEXT NOT NULL,
    validation_error TEXT NOT NULL,
    raw_payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_malformed_events_received_at ON malformed_events(received_at);

CREATE TABLE IF NOT EXISTS normalized_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT NOT NULL UNIQUE,
    raw_event_id INTEGER,
    source_event_id TEXT,
    trader_id TEXT,
    trader_address TEXT NOT NULL,
    proxy_wallet_address TEXT,
    market_id TEXT NOT NULL,
    condition_id TEXT,
    question TEXT,
    slug TEXT,
    market_url TEXT,
    outcome_token_id TEXT,
    outcome_name TEXT,
    raw_side TEXT NOT NULL,
    normalized_direction TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    notional REAL NOT NULL,
    transaction_hash TEXT,
    block_number INTEGER,
    trade_timestamp TEXT NOT NULL,
    source_endpoint TEXT NOT NULL,
    action_classification TEXT NOT NULL,
    position_certainty TEXT NOT NULL,
    uncertainty_notes TEXT,
    raw_payload TEXT NOT NULL,
    ingestion_timestamp TEXT NOT NULL,
    FOREIGN KEY(raw_event_id) REFERENCES raw_trade_events(id),
    FOREIGN KEY(trader_id) REFERENCES traders(trader_id)
);

CREATE INDEX IF NOT EXISTS idx_normalized_trades_time ON normalized_trades(trade_timestamp);
CREATE INDEX IF NOT EXISTS idx_normalized_trades_group ON normalized_trades(market_id, condition_id, outcome_token_id, normalized_direction);
CREATE INDEX IF NOT EXISTS idx_normalized_trades_trader ON normalized_trades(trader_address);

CREATE TABLE IF NOT EXISTS inferred_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_key TEXT NOT NULL UNIQUE,
    trader_id TEXT,
    trader_address TEXT NOT NULL,
    proxy_wallet_address TEXT,
    market_id TEXT NOT NULL,
    condition_id TEXT,
    outcome_token_id TEXT,
    normalized_outcome TEXT,
    normalized_direction TEXT NOT NULL,
    observed_net_size REAL NOT NULL,
    total_bought REAL NOT NULL,
    total_sold REAL NOT NULL,
    weighted_average_entry REAL,
    average_exit REAL,
    estimated_current_exposure REAL,
    realized_change REAL,
    unrealized_change REAL,
    first_observed_entry TEXT,
    last_update TEXT NOT NULL,
    position_status TEXT NOT NULL,
    completeness_flag TEXT NOT NULL,
    uncertainty_notes TEXT,
    raw_state TEXT,
    FOREIGN KEY(trader_id) REFERENCES traders(trader_id)
);

CREATE INDEX IF NOT EXISTS idx_positions_market ON inferred_positions(market_id, condition_id, outcome_token_id);
CREATE INDEX IF NOT EXISTS idx_positions_trader ON inferred_positions(trader_address);

CREATE TABLE IF NOT EXISTS consensus_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL UNIQUE,
    group_key TEXT NOT NULL,
    market_id TEXT NOT NULL,
    condition_id TEXT,
    market_title TEXT,
    market_url TEXT,
    outcome_token_id TEXT,
    outcome TEXT,
    direction TEXT NOT NULL,
    time_window_seconds INTEGER NOT NULL,
    trader_count INTEGER NOT NULL,
    weighted_trader_count REAL NOT NULL,
    traders_involved_json TEXT NOT NULL,
    total_token_size REAL NOT NULL,
    total_notional REAL NOT NULL,
    average_entry_price REAL,
    weighted_average_entry_price REAL,
    latest_price REAL,
    market_liquidity REAL,
    price_movement_since_first REAL,
    first_trade_timestamp TEXT NOT NULL,
    latest_trade_timestamp TEXT NOT NULL,
    trigger_timestamp TEXT NOT NULL,
    score REAL NOT NULL,
    confidence_tier TEXT NOT NULL,
    opposing_trader_count INTEGER NOT NULL,
    opposing_notional REAL NOT NULL,
    signal_explanation TEXT NOT NULL,
    uncertainty_notes TEXT,
    raw_components_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_consensus_signals_group ON consensus_signals(group_key);
CREATE INDEX IF NOT EXISTS idx_consensus_signals_score ON consensus_signals(score);
CREATE INDEX IF NOT EXISTS idx_consensus_signals_trigger ON consensus_signals(trigger_timestamp);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_dedupe_key TEXT NOT NULL UNIQUE,
    alert_group_key TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    created_at TEXT NOT NULL,
    score REAL NOT NULL,
    confidence_tier TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    delivery_status TEXT NOT NULL,
    delivery_error TEXT,
    FOREIGN KEY(signal_id) REFERENCES consensus_signals(signal_id)
);

CREATE INDEX IF NOT EXISTS idx_alerts_group ON alerts(alert_group_key);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at);

CREATE TABLE IF NOT EXISTS api_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_endpoint TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    error_type TEXT NOT NULL,
    status_code INTEGER,
    message TEXT NOT NULL,
    raw_payload TEXT
);

CREATE TABLE IF NOT EXISTS system_health_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    websocket_status TEXT,
    polling_status TEXT,
    last_event_time TEXT,
    database_status TEXT NOT NULL,
    api_error_rate REAL NOT NULL,
    tracked_trader_count INTEGER NOT NULL,
    tracked_market_count INTEGER NOT NULL,
    malformed_event_count INTEGER NOT NULL,
    degraded_mode_status TEXT NOT NULL,
    unresolved_blockers TEXT,
    raw_payload TEXT
);

CREATE TABLE IF NOT EXISTS blocker_recovery_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    blocker_key TEXT NOT NULL UNIQUE,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    description TEXT NOT NULL,
    recovery_steps TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

