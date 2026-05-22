# Polymarket Endpoint Research

Research date: 2026-05-22.

Verified from official documentation and live probes:

- API overview: `https://docs.polymarket.com/api-reference/introduction`
- Market data overview: `https://docs.polymarket.com/market-data/overview`
- WebSocket overview: `https://docs.polymarket.com/market-data/websocket/overview`
- Data API trades: `GET https://data-api.polymarket.com/trades`
- Data API leaderboard: `GET https://data-api.polymarket.com/v1/leaderboard`
- Gamma markets: `GET https://gamma-api.polymarket.com/markets`
- CLOB price history: `GET https://clob.polymarket.com/prices-history`
- CLOB health: `GET https://clob.polymarket.com/ok`

Live probes performed:

- `https://data-api.polymarket.com/trades?limit=1` returned `200 OK` with fields including `proxyWallet`, `side`, `asset`, `conditionId`, `size`, `price`, `timestamp`, `title`, `slug`, `outcome`, `outcomeIndex`, and `transactionHash`.
- `https://data-api.polymarket.com/v1/leaderboard?limit=1` returned `200 OK` with `rank`, `proxyWallet`, `userName`, `vol`, `pnl`, and profile fields.
- `https://gamma-api.polymarket.com/markets?limit=1` returned `200 OK` with market metadata, outcomes, `outcomePrices`, `clobTokenIds`, liquidity, volume, and order-book flags. The response included deprecation/sunset headers in this environment, so the URL is configurable and should be rechecked periodically.
- `https://clob.polymarket.com/prices-history?...` returned `200 OK` with a `history` array of `{t, p}` records.
- `https://clob.polymarket.com/ok` returned `OK`.

Rejected or degraded:

- `https://data-api.polymarket.com/ok` returned `404 page not found` despite rate-limit docs referencing a Data API health check.
- `https://gamma-api.polymarket.com/ok` returned `404 page not found`.
- Public CLOB market websockets provide market/orderbook/trade-execution events but do not prove which wallet traded. This tracker does not use those events to claim smart-money wallet activity. It uses Data API wallet trade polling for wallet-attributed activity.
- The CLOB user websocket requires authenticated credentials and is not used by default because this project does not require private keys or trading credentials.

Data honesty notes:

- Observed trades are stored as raw payloads and normalized trades.
- Current position is always marked `PARTIAL_HISTORY` unless a future ingestion mode can prove complete history.
- BUY YES is not automatically treated as SELL NO. Economic equivalence is disabled by default because it is only safe when binary market structure and token mapping are proven.

