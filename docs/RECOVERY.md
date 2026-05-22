# Recovery And Operations

## Restart Safety

SQLite runs in WAL mode. Raw trade events and normalized trades both have unique dedupe keys. If the process stops and the same trade is ingested again, the database unique constraints prevent duplicates.

## Malformed Events

Malformed external payloads are inserted into `malformed_events` with the raw payload, source endpoint, validation error, and timestamp. They do not crash the process.

Inspect them with:

```powershell
python -m polymarket_tracker.cli --config config.example.yaml dashboard
```

or open `data/polymarket_tracker.sqlite` with the SQLite Viewer VS Code extension.

## Endpoint Failures

HTTP calls use retries, backoff, jitter, and per-origin circuit breakers. Live mode records endpoint failures in `api_errors` and continues polling other wallets.

If one endpoint is unavailable:

- leaderboard failure: manual configured traders still run
- trade polling failure for one wallet: other wallets continue
- websocket unavailable: polling remains the wallet-attributed source of truth
- webhook failure: console alerts and alert history still work

## Reset Local State

Dry-run resets the default database when `dry_run.reset_database: true`.

For a manual reset, stop the process and remove:

```powershell
Remove-Item .\data\polymarket_tracker.sqlite*
```

Then run:

```powershell
python -m polymarket_tracker.cli --config config.example.yaml init-db
```

## Backups

For long-running live mode, copy the SQLite database while the app is stopped:

```powershell
Copy-Item .\data\polymarket_tracker.sqlite .\data\polymarket_tracker.backup.sqlite
```

