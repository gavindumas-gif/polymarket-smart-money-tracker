# Self Audit

## Fixed During Build

- CRITICAL: fresh database migration checked `schema_migrations` before creating it. Fixed by bootstrapping the migration table first and added migration tests.
- HIGH: SQLite implicit transactions collided after malformed quarantine writes. Fixed by using explicit autocommit mode plus deliberate transaction blocks.
- HIGH: alert spam across consensus windows. Fixed by grouping alerts across window sizes for the same market/outcome/direction and added alert dedupe coverage.
- MEDIUM: tests used the OS temp directory, which was blocked in this sandbox. Fixed by writing test databases under `.test_tmp/` in the workspace and excluding runtime output from Ruff.
- MEDIUM: package import failed before editable install with `src/` layout. README now uses `python -m pip install -e ".[dev]"` before commands.
- MEDIUM: fixture replay could mix with a prior live database. Fixed by adding `replay.reset_database: true` to the default config.

## Remaining Limitations

- MEDIUM: public data cannot prove full current position unless complete historical activity has been observed. The system marks positions as `PARTIAL_HISTORY` and displays uncertainty.
- MEDIUM: public market websockets do not prove wallet identity. The tracker keeps wallet-attributed smart-money ingestion on Data API polling and treats websockets as optional market telemetry.
- MEDIUM: Gamma `/markets` returned deprecation/sunset headers. Endpoint URLs are configurable, endpoint research is documented, and live failures are stored in `api_errors`.
- LOW: Docker build was not run because Docker is unavailable locally. Docker files are present and recovery steps are documented.
- LOW: SQLite CLI is unavailable, but Python's built-in `sqlite3` module is used and tested.

## Validation Added

- Config validation tests.
- API trade response validation tests.
- Deduplication and restart duplicate tests.
- Position classification tests for new entry, add, reduce, exit, reverse.
- Consensus and scoring tests.
- Alert dedupe tests.
- Dry-run pipeline test with realistic fixture data.
- Replay mode test.
- Websocket degraded-mode test.
