from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from polymarket_tracker.config.settings import AppConfig
from polymarket_tracker.db.sqlite import Database
from polymarket_tracker.utils.json import loads
from polymarket_tracker.utils.time import iso_now


class WebDashboard:
    def __init__(self, db: Database, max_rows: int = 20, refresh_seconds: float = 5.0) -> None:
        self.db = db
        self.max_rows = max_rows
        self.refresh_seconds = refresh_seconds

    def html(self) -> str:
        return DASHBOARD_HTML.replace("__REFRESH_SECONDS__", str(max(2, int(self.refresh_seconds))))

    def snapshot(self) -> dict[str, Any]:
        health = self._health()
        return {
            "generated_at": iso_now(),
            "refresh_seconds": self.refresh_seconds,
            "summary": self._summary(health),
            "health": health,
            "signals": self._signals(),
            "trades": self._trades(),
            "traders": self._traders(),
            "markets": self._markets(),
            "api_errors": self._api_errors(),
        }

    def _summary(self, health: dict[str, Any] | None) -> dict[str, Any]:
        row = self.db.fetchone(
            """
            SELECT
                (SELECT COUNT(*) FROM consensus_signals) AS signals,
                (SELECT COUNT(*) FROM normalized_trades) AS trades,
                (SELECT COUNT(*) FROM alerts) AS alerts,
                (SELECT COUNT(*) FROM malformed_events) AS malformed,
                (SELECT COUNT(*) FROM traders) AS traders,
                (SELECT COUNT(DISTINCT market_id) FROM normalized_trades) AS markets,
                (SELECT MAX(trader_count) FROM consensus_signals) AS top_cluster,
                (SELECT SUM(notional) FROM normalized_trades) AS total_notional
            """
        )
        status = "No health data"
        if health:
            degraded = str(health.get("degraded_mode_status") or "").upper()
            database = str(health.get("database_status") or "").upper()
            if database == "OK" and degraded == "OK":
                status = "Healthy"
            elif database == "OK":
                status = "Degraded"
            else:
                status = "Database issue"
        return {
            "status": status,
            "signals": int(row["signals"] or 0),
            "trades": int(row["trades"] or 0),
            "alerts": int(row["alerts"] or 0),
            "malformed": int(row["malformed"] or 0),
            "traders": int(row["traders"] or 0),
            "markets": int(row["markets"] or 0),
            "top_cluster": int(row["top_cluster"] or 0),
            "total_notional": _round(row["total_notional"]),
        }

    def _signals(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT signal_id, market_id, market_title, market_url, outcome_token_id,
                   outcome, direction, time_window_seconds,
                   trader_count, weighted_trader_count, traders_involved_json, total_notional,
                   weighted_average_entry_price, latest_price, score, confidence_tier,
                   opposing_trader_count, opposing_notional, uncertainty_notes, trigger_timestamp
            FROM consensus_signals
            ORDER BY trader_count DESC, weighted_trader_count DESC, score DESC,
                     total_notional DESC, latest_trade_timestamp DESC
            LIMIT ?
            """,
            (self.max_rows * 6,),
        )
        signals = []
        for row in _dedupe_signal_rows(rows, self.max_rows):
            traders = loads(row["traders_involved_json"], [])
            names = [item.get("display_name") or item.get("trader_id") or "Unknown" for item in traders[:5]]
            signals.append(
                {
                    "signal_id": row["signal_id"],
                    "market_title": row["market_title"] or "Untitled market",
                    "market_url": row["market_url"],
                    "outcome": row["outcome"] or "Unknown",
                    "direction": row["direction"],
                    "window": _window_label(row["time_window_seconds"]),
                    "trader_count": int(row["trader_count"] or 0),
                    "weighted_trader_count": _round(row["weighted_trader_count"]),
                    "trader_names": names,
                    "total_notional": _round(row["total_notional"]),
                    "entry": _round(row["weighted_average_entry_price"]),
                    "latest_price": _round(row["latest_price"]),
                    "score": _round(row["score"]),
                    "score_percent": min(100, max(0, float(row["score"] or 0))),
                    "confidence_tier": row["confidence_tier"],
                    "opposing_trader_count": int(row["opposing_trader_count"] or 0),
                    "opposing_notional": _round(row["opposing_notional"]),
                    "uncertainty_notes": row["uncertainty_notes"],
                    "trigger_timestamp": row["trigger_timestamp"],
                }
            )
        return signals

    def _trades(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT trade_timestamp, trader_id, question, outcome_name, raw_side,
                   normalized_direction, price, size, notional
            FROM normalized_trades
            ORDER BY trade_timestamp DESC
            LIMIT ?
            """,
            (self.max_rows,),
        )
        return [
            {
                "time": row["trade_timestamp"],
                "trader": row["trader_id"] or "Unknown",
                "market": row["question"] or "Untitled market",
                "outcome": row["outcome_name"] or "Unknown",
                "side": row["raw_side"],
                "direction": row["normalized_direction"],
                "price": _round(row["price"], 4),
                "size": _round(row["size"]),
                "notional": _round(row["notional"]),
            }
            for row in rows
        ]

    def _traders(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            WITH trade_stats AS (
                SELECT trader_id, COUNT(*) AS trades,
                       COALESCE(SUM(notional), 0) AS notional,
                       MAX(trade_timestamp) AS latest_trade
                FROM normalized_trades
                GROUP BY trader_id
            ),
            position_stats AS (
                SELECT trader_id, COUNT(DISTINCT position_key) AS active_positions
                FROM inferred_positions
                WHERE position_status != 'CLOSED'
                GROUP BY trader_id
            )
            SELECT t.trader_id, t.display_name, t.discovery_source, t.derived_weight,
                   COALESCE(ts.trades, 0) AS trades,
                   COALESCE(ts.notional, 0) AS notional,
                   COALESCE(ps.active_positions, 0) AS active_positions,
                   ts.latest_trade
            FROM traders t
            LEFT JOIN trade_stats ts ON ts.trader_id = t.trader_id
            LEFT JOIN position_stats ps ON ps.trader_id = t.trader_id
            ORDER BY notional DESC, latest_trade DESC
            LIMIT ?
            """,
            (self.max_rows,),
        )
        return [
            {
                "trader_id": row["trader_id"],
                "display_name": row["display_name"] or row["trader_id"],
                "source": row["discovery_source"],
                "weight": _round(row["derived_weight"]),
                "trades": int(row["trades"] or 0),
                "notional": _round(row["notional"]),
                "active_positions": int(row["active_positions"] or 0),
                "latest_trade": row["latest_trade"] or "Never",
            }
            for row in rows
        ]

    def _markets(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT market_id, question, COUNT(*) AS trades, SUM(notional) AS notional,
                   MAX(trade_timestamp) AS latest_trade,
                   COUNT(DISTINCT trader_id) AS traders
            FROM normalized_trades
            GROUP BY market_id
            ORDER BY notional DESC, latest_trade DESC
            LIMIT ?
            """,
            (self.max_rows,),
        )
        return [
            {
                "market_id": row["market_id"],
                "question": row["question"] or row["market_id"],
                "trades": int(row["trades"] or 0),
                "notional": _round(row["notional"]),
                "latest_trade": row["latest_trade"],
                "traders": int(row["traders"] or 0),
            }
            for row in rows
        ]

    def _api_errors(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT source_endpoint, occurred_at, error_type, status_code, message
            FROM api_errors
            ORDER BY occurred_at DESC
            LIMIT 6
            """
        )
        return [
            {
                "endpoint": row["source_endpoint"],
                "time": row["occurred_at"],
                "type": row["error_type"],
                "status": row["status_code"],
                "message": row["message"],
            }
            for row in rows
        ]

    def _health(self) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT *
            FROM system_health_snapshots
            ORDER BY captured_at DESC
            LIMIT 1
            """
        )
        if not row:
            return None
        return {
            "captured_at": row["captured_at"],
            "websocket_status": row["websocket_status"],
            "polling_status": row["polling_status"],
            "last_event_time": row["last_event_time"],
            "database_status": row["database_status"],
            "api_error_rate": _round(row["api_error_rate"], 4),
            "tracked_trader_count": int(row["tracked_trader_count"] or 0),
            "tracked_market_count": int(row["tracked_market_count"] or 0),
            "malformed_event_count": int(row["malformed_event_count"] or 0),
            "degraded_mode_status": row["degraded_mode_status"],
            "unresolved_blockers": row["unresolved_blockers"],
        }


def serve_web_dashboard(config: AppConfig, host: str = "127.0.0.1", port: int = 8765) -> int:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in {"/", "/index.html"}:
                self._send_html()
                return
            if path == "/api/dashboard":
                self._send_json()
                return
            self.send_error(404, "Not found")

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_html(self) -> None:
            db = _open_db(config)
            try:
                body = WebDashboard(db, config.dashboard.max_rows, config.dashboard.refresh_seconds).html()
            finally:
                db.close()
            self._send(body.encode("utf-8"), "text/html; charset=utf-8")

        def _send_json(self) -> None:
            db = _open_db(config)
            try:
                payload = WebDashboard(db, config.dashboard.max_rows, config.dashboard.refresh_seconds).snapshot()
            finally:
                db.close()
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self._send(body, "application/json; charset=utf-8")

        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{server.server_port}"
    print(f"Dashboard running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
    return 0


def _open_db(config: AppConfig) -> Database:
    db = Database(config.database.url, config.database.busy_timeout_ms)
    db.migrate()
    return db


def _round(value: Any, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _window_label(seconds: Any) -> str:
    total = int(seconds or 0)
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m"
    if total < 86400:
        return f"{total // 3600}h"
    return f"{total // 86400}d"


def _dedupe_signal_rows(rows: list[Any], limit: int) -> list[Any]:
    seen: set[tuple[Any, Any, Any]] = set()
    deduped: list[Any] = []
    for row in rows:
        key = (row["market_id"], row["outcome_token_id"], row["direction"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
        if len(deduped) >= limit:
            break
    return deduped


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Polymarket Smart-Money Tracker</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f6f2;
      --panel: #ffffff;
      --panel-soft: #f0f4ee;
      --ink: #252822;
      --muted: #687165;
      --line: #d9dfd5;
      --green: #167a4a;
      --red: #b73535;
      --blue: #245db4;
      --amber: #9a6418;
      --violet: #7a4fa2;
      --shadow: 0 1px 2px rgba(37, 40, 34, 0.06), 0 8px 24px rgba(37, 40, 34, 0.07);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
      line-height: 1.45;
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
    }
    .sidebar {
      position: sticky;
      top: 0;
      height: 100vh;
      padding: 22px 18px;
      background: #20251f;
      color: #f4f5ef;
      border-right: 1px solid #151914;
    }
    .brand {
      display: flex;
      gap: 12px;
      align-items: center;
      margin-bottom: 24px;
    }
    .mark {
      width: 36px;
      height: 36px;
      border-radius: 8px;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.88), rgba(255,255,255,0.18)),
        linear-gradient(135deg, #167a4a 0%, #245db4 54%, #9a6418 100%);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.22);
    }
    h1 {
      margin: 0;
      font-size: 17px;
      line-height: 1.2;
      font-weight: 720;
      letter-spacing: 0;
    }
    .subtitle {
      margin-top: 3px;
      color: #b8c0b2;
      font-size: 12px;
    }
    .nav {
      display: grid;
      gap: 7px;
      margin-top: 18px;
    }
    .nav a {
      color: #dfe5d8;
      text-decoration: none;
      padding: 9px 10px;
      border-radius: 8px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .nav a:hover { background: rgba(255,255,255,0.08); }
    .nav span {
      color: #93a08c;
      font-variant-numeric: tabular-nums;
      font-size: 12px;
    }
    .side-health {
      margin-top: 22px;
      padding: 13px;
      border-radius: 8px;
      background: rgba(255,255,255,0.07);
      border: 1px solid rgba(255,255,255,0.08);
    }
    .side-health dt {
      color: #aeb9a7;
      font-size: 11px;
      text-transform: uppercase;
      margin-top: 10px;
    }
    .side-health dd {
      margin: 2px 0 0;
      color: #ffffff;
      overflow-wrap: anywhere;
    }
    main {
      min-width: 0;
      padding: 24px;
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 18px;
      margin-bottom: 18px;
    }
    .page-title h2 {
      margin: 0;
      font-size: 26px;
      line-height: 1.1;
      letter-spacing: 0;
    }
    .page-title p {
      margin: 7px 0 0;
      color: var(--muted);
      max-width: 720px;
    }
    .status-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 30px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 5px 9px;
      font-size: 12px;
      color: var(--muted);
      white-space: nowrap;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--green);
    }
    .dot.warn { background: var(--amber); }
    .dot.bad { background: var(--red); }
    .metrics {
      display: grid;
      grid-template-columns: repeat(6, minmax(120px, 1fr));
      gap: 10px;
      margin-bottom: 18px;
    }
    .metric {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      box-shadow: var(--shadow);
      min-width: 0;
    }
    .metric label {
      color: var(--muted);
      display: block;
      font-size: 11px;
      text-transform: uppercase;
    }
    .metric strong {
      display: block;
      margin-top: 5px;
      font-size: 21px;
      line-height: 1.05;
      font-variant-numeric: tabular-nums;
      overflow-wrap: anywhere;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr);
      gap: 16px;
      align-items: start;
    }
    section {
      min-width: 0;
      margin-bottom: 16px;
    }
    .section-head {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
    }
    .section-head h3 {
      margin: 0;
      font-size: 14px;
      text-transform: uppercase;
      color: #383d35;
      letter-spacing: 0;
    }
    .section-head small { color: var(--muted); }
    .signal-list {
      display: grid;
      gap: 9px;
    }
    .signal {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      box-shadow: var(--shadow);
    }
    .signal-top {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
    }
    .market {
      font-weight: 700;
      font-size: 14px;
      overflow-wrap: anywhere;
    }
    .chips {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin-top: 8px;
    }
    .chip {
      border: 1px solid var(--line);
      background: var(--panel-soft);
      border-radius: 8px;
      padding: 3px 7px;
      color: var(--muted);
      font-size: 12px;
    }
    .chip.green { color: var(--green); border-color: rgba(22,122,74,0.32); background: #eaf5ee; }
    .chip.red { color: var(--red); border-color: rgba(183,53,53,0.28); background: #faeeee; }
    .score {
      min-width: 118px;
      text-align: right;
    }
    .score strong {
      display: block;
      font-size: 24px;
      line-height: 1;
      font-variant-numeric: tabular-nums;
    }
    .score small { color: var(--muted); }
    .bar {
      height: 8px;
      background: #e5e9df;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 10px;
    }
    .bar span {
      display: block;
      height: 100%;
      background: linear-gradient(90deg, var(--green), var(--blue));
      width: 0%;
    }
    .note {
      color: var(--muted);
      font-size: 12px;
      margin-top: 9px;
      overflow-wrap: anywhere;
    }
    .table-wrap {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }
    th, td {
      padding: 9px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
    }
    th {
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      background: #f7f9f4;
    }
    tr:last-child td { border-bottom: 0; }
    .num {
      text-align: right;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }
    .muted { color: var(--muted); }
    .empty {
      background: var(--panel);
      border: 1px dashed var(--line);
      border-radius: 8px;
      padding: 18px;
      color: var(--muted);
    }
    .small-table td, .small-table th { font-size: 12px; }
    @media (max-width: 1180px) {
      .app { grid-template-columns: 1fr; }
      .sidebar {
        position: static;
        height: auto;
      }
      .grid { grid-template-columns: 1fr; }
      .metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    @media (max-width: 680px) {
      main { padding: 16px; }
      .topbar { display: grid; }
      .status-row { justify-content: flex-start; }
      .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .signal-top { grid-template-columns: 1fr; }
      .score { text-align: left; }
      table { min-width: 680px; }
      .table-wrap { overflow-x: auto; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        <div class="mark" aria-hidden="true"></div>
        <div>
          <h1>Smart-Money Tracker</h1>
          <div class="subtitle">Polymarket consensus</div>
        </div>
      </div>
      <nav class="nav" aria-label="Dashboard sections">
        <a href="#signals">Suggested <span id="navSignals">0</span></a>
        <a href="#trades">Trades <span id="navTrades">0</span></a>
        <a href="#traders">Traders <span id="navTraders">0</span></a>
        <a href="#health">Health <span id="navHealth">--</span></a>
      </nav>
      <dl class="side-health" id="sideHealth"></dl>
    </aside>
    <main>
      <div class="topbar">
        <div class="page-title">
          <h2>Suggested Positions</h2>
          <p id="headline">Loading market activity...</p>
        </div>
        <div class="status-row">
          <span class="pill"><span class="dot" id="statusDot"></span><span id="statusText">Loading</span></span>
          <span class="pill">Last refresh <span id="lastRefresh">--</span></span>
        </div>
      </div>
      <div class="metrics" id="metrics"></div>
      <div class="grid">
        <div>
          <section id="signals">
            <div class="section-head"><h3>Suggested Positions</h3><small id="signalCount">0 positions</small></div>
            <div class="signal-list" id="signalsList"></div>
          </section>
          <section id="trades">
            <div class="section-head"><h3>Latest Trades</h3><small id="tradeCount">0 trades</small></div>
            <div class="table-wrap"><table id="tradesTable"></table></div>
          </section>
        </div>
        <div>
          <section id="traders">
            <div class="section-head"><h3>Trader Activity</h3><small id="traderCount">0 traders</small></div>
            <div class="table-wrap"><table class="small-table" id="tradersTable"></table></div>
          </section>
          <section id="markets">
            <div class="section-head"><h3>Market Exposure</h3><small id="marketCount">0 markets</small></div>
            <div class="table-wrap"><table class="small-table" id="marketsTable"></table></div>
          </section>
          <section id="health">
            <div class="section-head"><h3>API Errors</h3><small id="errorCount">0 recent</small></div>
            <div class="table-wrap"><table class="small-table" id="errorsTable"></table></div>
          </section>
        </div>
      </div>
    </main>
  </div>
  <script>
    const refreshSeconds = __REFRESH_SECONDS__;
    const formatMoney = (value) => value == null
      ? "--"
      : "$" + Number(value).toLocaleString(undefined, {maximumFractionDigits: 2});
    const formatNumber = (value) => value == null
      ? "--"
      : Number(value).toLocaleString(undefined, {maximumFractionDigits: 2});
    const formatPrice = (value) => value == null ? "--" : Number(value).toFixed(3);
    const text = (value) => value == null || value === "" ? "--" : String(value);
    const esc = (value) => text(value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
    }[char]));
    const timeOnly = (value) => {
      if (!value) return "--";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
    };
    const confidenceClass = (direction) => String(direction || "").includes("SELL") ? "red" : "green";

    async function loadDashboard() {
      try {
        const response = await fetch("/api/dashboard", {cache: "no-store"});
        const data = await response.json();
        render(data);
      } catch (error) {
        document.getElementById("statusText").textContent = "Offline";
        document.getElementById("statusDot").className = "dot bad";
        document.getElementById("headline").textContent = "The dashboard server did not return data.";
      }
    }

    function render(data) {
      const summary = data.summary || {};
      const health = data.health || {};
      document.getElementById("statusText").textContent = summary.status || "Unknown";
      const statusClass = (summary.status || "").includes("Degraded")
        ? "warn"
        : (summary.status || "").includes("issue")
          ? "bad"
          : "";
      document.getElementById("statusDot").className = "dot " + statusClass;
      document.getElementById("lastRefresh").textContent = timeOnly(data.generated_at);
      document.getElementById("headline").textContent =
        `${formatNumber(summary.trades)} trades across ${formatNumber(summary.markets)} markets ` +
        `with ${formatNumber(summary.signals)} consensus signals.`;
      document.getElementById("navSignals").textContent = formatNumber(summary.signals);
      document.getElementById("navTrades").textContent = formatNumber(summary.trades);
      document.getElementById("navTraders").textContent = formatNumber(summary.traders);
      document.getElementById("navHealth").textContent = health.polling_status || "--";
      renderSideHealth(health);
      renderMetrics(summary);
      renderSignals(data.signals || []);
      renderTrades(data.trades || []);
      renderTraders(data.traders || []);
      renderMarkets(data.markets || []);
      renderErrors(data.api_errors || []);
    }

    function renderSideHealth(health) {
      const fields = [
        ["Polling", health.polling_status],
        ["Database", health.database_status],
        ["Last event", health.last_event_time],
        ["Blockers", health.unresolved_blockers || "none"]
      ];
      document.getElementById("sideHealth").innerHTML = fields.map(([label, value]) =>
        `<dt>${esc(label)}</dt><dd>${esc(value)}</dd>`
      ).join("");
    }

    function renderMetrics(summary) {
      const metrics = [
        ["Top cluster", `${formatNumber(summary.top_cluster)} traders`],
        ["Total notional", formatMoney(summary.total_notional)],
        ["Signals", formatNumber(summary.signals)],
        ["Alerts", formatNumber(summary.alerts)],
        ["Tracked traders", formatNumber(summary.traders)],
        ["Malformed", formatNumber(summary.malformed)]
      ];
      document.getElementById("metrics").innerHTML = metrics.map(([label, value]) =>
        `<div class="metric"><label>${esc(label)}</label><strong>${esc(value)}</strong></div>`
      ).join("");
    }

    function renderSignals(signals) {
      document.getElementById("signalCount").textContent = `${signals.length} shown`;
      const root = document.getElementById("signalsList");
      if (!signals.length) {
        root.innerHTML = `<div class="empty">No suggested positions yet.</div>`;
        return;
      }
      root.innerHTML = signals.map((signal) => `
        <article class="signal">
          <div class="signal-top">
            <div>
              <div class="market">${esc(signal.market_title)}</div>
              <div class="chips">
                <span class="chip ${confidenceClass(signal.direction)}">
                  ${esc(signal.direction)} ${esc(signal.outcome)}
                </span>
                <span class="chip">${esc(signal.confidence_tier)}</span>
                <span class="chip">${esc(signal.window)}</span>
                <span class="chip">${formatNumber(signal.trader_count)} traders</span>
                <span class="chip">${formatMoney(signal.total_notional)}</span>
              </div>
            </div>
            <div class="score">
              <strong>${formatNumber(signal.score)}</strong>
              <small>score</small>
              <div class="bar"><span style="width:${Number(signal.score_percent || 0)}%"></span></div>
            </div>
          </div>
          <div class="note">${esc((signal.trader_names || []).join(", "))}</div>
          <div class="note">${esc(signal.uncertainty_notes)}</div>
        </article>
      `).join("");
    }

    function renderTrades(trades) {
      document.getElementById("tradeCount").textContent = `${trades.length} shown`;
      renderTable("tradesTable", ["Time", "Trader", "Market", "Side", "Price", "Notional"], trades, (trade) => [
        timeOnly(trade.time),
        trade.trader,
        trade.market,
        `${trade.side} ${trade.direction}`,
        formatPrice(trade.price),
        formatMoney(trade.notional)
      ], [false, false, false, false, true, true]);
    }

    function renderTraders(traders) {
      document.getElementById("traderCount").textContent = `${traders.length} shown`;
      renderTable("tradersTable", ["Trader", "Trades", "Notional", "Positions"], traders, (trader) => [
        trader.display_name,
        formatNumber(trader.trades),
        formatMoney(trader.notional),
        formatNumber(trader.active_positions)
      ], [false, true, true, true]);
    }

    function renderMarkets(markets) {
      document.getElementById("marketCount").textContent = `${markets.length} shown`;
      renderTable("marketsTable", ["Market", "Traders", "Trades", "Notional"], markets, (market) => [
        market.question,
        formatNumber(market.traders),
        formatNumber(market.trades),
        formatMoney(market.notional)
      ], [false, true, true, true]);
    }

    function renderErrors(errors) {
      document.getElementById("errorCount").textContent = `${errors.length} recent`;
      renderTable("errorsTable", ["Time", "Endpoint", "Type"], errors, (error) => [
        timeOnly(error.time),
        error.endpoint,
        error.type
      ], [false, false, false]);
    }

    function renderTable(id, headers, rows, cells, numericColumns) {
      const table = document.getElementById(id);
      const head = `<thead><tr>${headers.map((header, index) =>
        `<th class="${numericColumns[index] ? "num" : ""}">${esc(header)}</th>`).join("")}</tr></thead>`;
      if (!rows.length) {
        table.innerHTML =
          `${head}<tbody><tr><td colspan="${headers.length}" class="muted">No rows yet.</td></tr></tbody>`;
        return;
      }
      const body = rows.map((row) => `<tr>${cells(row).map((cell, index) =>
        `<td class="${numericColumns[index] ? "num" : ""}">${esc(cell)}</td>`).join("")}</tr>`).join("");
      table.innerHTML = `${head}<tbody>${body}</tbody>`;
    }

    loadDashboard();
    setInterval(loadDashboard, refreshSeconds * 1000);
  </script>
</body>
</html>
"""
