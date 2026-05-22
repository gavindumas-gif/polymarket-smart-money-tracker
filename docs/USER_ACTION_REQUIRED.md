# User Action Required

The tracker itself is runnable locally now. Dry-run, replay, tests, lint, formatting checks, and live public endpoint smoke testing were automated.

## Docker Is Not Installed

Issue: `docker --version` failed because Docker is not installed or not on PATH.

Why Codex could not fix it automatically: installing Docker Desktop on Windows usually requires a GUI installer, OS-level services, and possibly admin approval.

What still works without Docker:

- local Python dry-run
- local Python replay
- local Python live polling
- SQLite persistence
- tests/lint/format checks
- VS Code extensions

To enable Docker later:

1. Install Docker Desktop from `https://www.docker.com/products/docker-desktop/`.
2. Start Docker Desktop and wait until it reports that the engine is running.
3. Open a new PowerShell terminal.
4. Verify:

```powershell
docker --version
docker compose version
```

5. From this repository, run:

```powershell
docker build -t polymarket-smart-money-tracker .
docker compose up --build
```

How to resume after fixing Docker:

```powershell
cd "C:\Users\dumasg\Documents\New project\polymarket-smart-money-tracker"
docker build -t polymarket-smart-money-tracker .
```

## Optional WebSocket Dependency

The default installation intentionally avoids runtime dependencies. Wallet-attributed smart-money tracking uses public Data API polling. To experiment with public market websocket telemetry:

```powershell
python -m pip install -e ".[websocket]"
```

This does not provide wallet identity on public market events; it is useful for market telemetry and reconnect/backoff testing.

