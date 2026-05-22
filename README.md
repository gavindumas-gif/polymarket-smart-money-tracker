# Polymarket Smart-Money Consensus Tracker

A local-first, restart-safe Polymarket smart-money consensus tracker. It ingests wallet-attributed trade activity, stores raw and normalized data separately, infers observed partial-history positions, detects clustered trader agreement, scores consensus strength, displays a console dashboard, and sends deduped alerts.

This is an analytics and alerting system only. It does not trade, sign orders, request private keys, or require Polymarket credentials for the default public-data workflow.

## Stack

- Python 3.11+ with a `src/` package layout
- SQLite for durable local storage and restart-safe dedupe
- Standard-library runtime for dry-run/live polling/replay
- Optional `websockets` extra for public market websocket telemetry
- Ruff for linting and formatting
- VS Code extensions for Python, Ruff, Docker, and SQLite inspection

Why this stack: Python and SQLite were available locally, Node/npm/Docker/sqlite CLI were not. The standard-library runtime keeps dry-run, replay, live polling, tests, and persistence working without heavy system installs. SQLite WAL mode and database unique constraints give reliable local restart behavior while leaving a clear path to a future PostgreSQL adapter.

## Architecture

Pipeline:

`tracked traders -> trade ingestion -> raw event storage -> schema validation -> malformed quarantine -> normalization -> dedupe -> position inference -> consensus grouping -> scoring -> alert output -> dashboard -> persisted state`

Important data-honesty choices:

- Raw events are stored before normalization.
- Invalid events go to `malformed_events`.
- Duplicate trades are rejected in memory and by unique SQLite constraints.
- Inferred positions are marked `PARTIAL_HISTORY` because public data cannot prove pre-tracker inventory.
- BUY YES is not treated as SELL NO unless a future config and market-proof path enables safe equivalence.
- Public CLOB market websockets are not wallet-attributed, so wallet-specific smart-money tracking uses the Data API polling path.

## Verified Polymarket Endpoints

Verified on 2026-05-22:

- `GET https://data-api.polymarket.com/trades`
- `GET https://data-api.polymarket.com/v1/leaderboard`
- `GET https://gamma-api.polymarket.com/markets`
- `GET https://clob.polymarket.com/prices-history`
- `GET https://clob.polymarket.com/ok`

The documented `data-api` and `gamma-api` `/ok` endpoints returned 404 here. Gamma `/markets` returned useful data but also deprecation/sunset headers, so URLs are configurable. Details are in [docs/API_RESEARCH.md](docs/API_RESEARCH.md).

## Setup

From this repository:

```powershell
python -m pip install -e ".[dev]"
```

Validate the installation:

```powershell
python -m ruff format --check .
python -m ruff check .
python -m compileall src
python -m unittest discover -s tests
```

Initialize or migrate the database:

```powershell
python -m polymarket_tracker.cli --config config.example.yaml init-db
```

The console script `pm-smart.exe` may not be on PATH on this machine, so the documented commands use `python -m polymarket_tracker.cli`.

## Configure Traders

Edit `config.example.yaml`, or copy it to `config.yaml` and use that file. Manual traders live under:

```yaml
traders:
  manual:
    - trader_id: alpha_mock
      display_name: Alpha Mock
      wallet_address: 0x1111111111111111111111111111111111111111
      proxy_wallet_address: 0x1111111111111111111111111111111111111111
      manual_weight: 1.5
```

Manual config always works even if leaderboard discovery fails. Leaderboard discovery is public and configurable under `traders.discovery`.

## Run Dry Mode

Dry-run uses clearly labeled mock Polymarket-shaped fixture events and exercises the full pipeline:

```powershell
python -m polymarket_tracker.cli --config config.example.yaml dry-run
```

Expected behavior:

- 6 events ingested
- 1 duplicate rejected
- 1 malformed event quarantined
- consensus signals generated
- 1 console alert emitted after alert dedupe
- dashboard printed

## Run Replay Mode

Replay mode replays the fixture chronologically through the same position and consensus engines:

```powershell
python -m polymarket_tracker.cli --config config.example.yaml replay
```

Fixture replay cannot prove later 1h/6h/24h outcomes unless later price history is supplied, so the output labels that limitation.
The default config resets the local SQLite database before fixture replay to avoid mixing replay results with prior live-mode data.

## Run Live Mode

One-cycle public endpoint smoke test:

```powershell
python -m polymarket_tracker.cli --config config.example.yaml live --once
```

For continuous operation, run the same command without `--once` and stop with Ctrl+C. Live mode discovers leaderboard traders if enabled, polls Data API trades by wallet, records endpoint errors, continues when one wallet fails, and keeps all dedupe constraints active.

## Dashboard And Health

Open the readable local web dashboard:

```powershell
python -m polymarket_tracker.cli --config config.example.yaml web
```

Then visit `http://127.0.0.1:8765`. The page auto-refreshes from the SQLite database while live mode is running.

Print the terminal dashboard:

```powershell
python -m polymarket_tracker.cli --config config.example.yaml dashboard
```

Record and print a health snapshot:

```powershell
python -m polymarket_tracker.cli --config config.example.yaml health
```

The dashboards include live trades, consensus signals, trader activity, market detail via `--market-id`, and system health.

## Alerts

Console alerts are enabled by default. Optional webhooks are configured through `.env`:

- `DISCORD_WEBHOOK_URL`
- `GENERIC_WEBHOOK_URL`
- `TELEGRAM_WEBHOOK_URL`

Enable channels in `config.example.yaml` under `alerts`. Alert payloads include confidence tier, score, market link, outcome, direction, traders involved, notional, weighted average entry, latest price if available, trigger reason, uncertainty notes, and timestamp.

Alert protections:

- cross-window dedupe for the same market/outcome/direction
- cooldowns
- material score-change threshold
- max alerts per minute
- persistent alert history

## Scoring

The scoring model is configurable under `scoring.weights`. It considers trader count, weighted trader count, total notional, concentration, trader quality, recency, speed of accumulation, agreement ratio, liquidity, price movement, opposing activity, late-entry risk, and partial-history uncertainty.

Confidence tiers:

- `VERY_LOW`
- `LOW`
- `MEDIUM`
- `HIGH`
- `VERY_HIGH`
- `EXTREME`

## Position Inference

Observed positions track net observed size, total bought, total sold, weighted average entry, average exit when inferable, estimated exposure, first observed entry, latest update, position status, and completeness.

Trade classifications:

- `NEW_ENTRY`
- `ADD`
- `REDUCE`
- `EXIT`
- `REVERSE`
- `UNKNOWN`

Completeness is `PARTIAL_HISTORY` by default. That is intentional: starting the tracker after a trader already had inventory means the true full position is unknown.

## Optional WebSocket Telemetry

Public market websocket support is implemented with reconnect/backoff/heartbeat behavior, but the dependency is optional:

```powershell
python -m pip install -e ".[websocket]"
```

This is for market telemetry. It is not used to claim wallet-attributed trades because public market websocket messages do not prove trader identity.

## Docker

Docker support files are included, but Docker is not installed in this local environment, so the build could not be validated here. After installing Docker Desktop:

```powershell
docker build -t polymarket-smart-money-tracker .
docker compose up --build
```

See [docs/USER_ACTION_REQUIRED.md](docs/USER_ACTION_REQUIRED.md) for the exact recovery path.

## VS Code

Installed automatically:

- `charliermarsh.ruff`
- `ms-azuretools.vscode-docker`
- `ms-azuretools.vscode-containers`
- `qwtel.sqlite-viewer`

Already present:

- `ms-python.python`
- `ms-python.vscode-pylance`
- `ms-python.debugpy`
- `ms-python.vscode-python-envs`

Details are in [docs/VSCODE_SETUP.md](docs/VSCODE_SETUP.md).

## Troubleshooting

- Config fails fast: read the error and fix the named field.
- Live endpoint fails: check `api_errors` and the dashboard health section.
- Repeated event after restart: expected result is duplicate rejection, not a second normalized trade.
- Malformed payload: inspect `malformed_events`.
- Missing Docker: local Python mode still works.
- Missing sqlite CLI: not required; Python uses the built-in SQLite driver.

Operational docs:

- [docs/RECOVERY.md](docs/RECOVERY.md)
- [docs/USER_ACTION_REQUIRED.md](docs/USER_ACTION_REQUIRED.md)
- [docs/RESUME_CHECKPOINT.md](docs/RESUME_CHECKPOINT.md)
- [docs/SELF_AUDIT.md](docs/SELF_AUDIT.md)

## Future Improvements

- Add a PostgreSQL repository implementation for higher write volume.
- Add authenticated user websocket support if the operator wants to monitor their own account events.
- Add richer market metadata refresh and current-price enrichment in scoring.
- Add richer charting and filters to the web dashboard.
- Add historical price files for fixture backtest result calculations.
