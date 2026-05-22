from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from polymarket_tracker.config.settings import ConfigError, load_config
from polymarket_tracker.runner import run_dashboard, run_dry_run, run_health, run_live, run_replay
from polymarket_tracker.utils.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Polymarket Smart-Money Consensus Tracker")
    parser.add_argument("--config", default=None, help="Path to config YAML")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Create or migrate the SQLite database")
    sub.add_parser("dry-run", help="Run the full mock-data pipeline")
    live = sub.add_parser("live", help="Run live public Data API polling")
    live.add_argument("--once", action="store_true", help="Run one polling cycle and exit")
    sub.add_parser("replay", help="Replay fixture trades through the same pipeline")
    dashboard = sub.add_parser("dashboard", help="Print the console dashboard")
    dashboard.add_argument("--market-id", default=None, help="Show one market detail view")
    web = sub.add_parser("web", help="Serve the local web dashboard")
    web.add_argument("--host", default="127.0.0.1", help="Dashboard bind host")
    web.add_argument("--port", type=int, default=8765, help="Dashboard port")
    sub.add_parser("health", help="Record and print a health snapshot")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    configure_logging(config.logging.level, config.logging.json, config.logging.file)
    if args.command == "init-db":
        from polymarket_tracker.runner import open_database

        db = open_database(config)
        try:
            print(f"Database ready: {Path(db.path).resolve()}")
        finally:
            db.close()
        return 0
    if args.command == "dry-run":
        result = run_dry_run(config)
        print(json.dumps({k: v for k, v in result.items() if k != "dashboard"}, indent=2))
        print()
        print(result["dashboard"])
        return 0
    if args.command == "live":
        result = run_live(config, once=args.once)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "replay":
        result = run_replay(config)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "dashboard":
        print(run_dashboard(config, args.market_id))
        return 0
    if args.command == "web":
        from polymarket_tracker.dashboard.web import serve_web_dashboard

        return serve_web_dashboard(config, args.host, args.port)
    if args.command == "health":
        print(run_health(config))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
