# Stocks Plugin

Fetches price, volume, and headline news for a personal ticker watchlist plus major market indices, then summarizes them for the executive brief.

## What it does

- Pulls latest price data for all symbols in `STOCKS_TICKERS` plus major indices (`^GSPC`, `^DJI`, `^IXIC`, `^VIX`) when `STOCKS_INCLUDE_INDICES=true`.
- Per ticker: last price, previous close, day/week/month/YTD percent change, 52-week high/low/position, volume vs. 30-day average.
- Up to `STOCKS_NEWS_PER_TICKER` recent headlines per ticker from Yahoo Finance's news system.
- Indices get the same price fields but no news.
- yfinance calls are run in `asyncio.to_thread()` — they don't block the event loop.
- A ticker that fails (network error, delisted, etc.) is included in the payload with `null` fields rather than failing the whole plugin.

## Authentication

None for the default `yfinance` provider. yfinance reads Yahoo Finance's unofficial endpoints with no registration or API key.

## Environment variables

| Variable | Default | Required | Description |
|---|---|---|---|
| `STOCKS_TICKERS` | — | Yes | Comma-separated ticker symbols, e.g. `AAPL,MSFT,NVDA` |
| `STOCKS_INCLUDE_INDICES` | `true` | No | Include S&P 500, Dow, Nasdaq, VIX |
| `STOCKS_NEWS_PER_TICKER` | `3` | No | Max headlines per ticker |
| `STOCKS_PROVIDER` | `yfinance` | No | `yfinance` or `alpha_vantage` |
| `ALPHA_VANTAGE_API_KEY` | — | Only if `alpha_vantage` | Alpha Vantage API key |

## Providers

**yfinance (default):** Free, no key required. Reads Yahoo Finance's unofficial JSON endpoints. Stable in practice but can break when Yahoo changes its site structure — check for a yfinance library update if data stops appearing.

**alpha_vantage:** Not yet implemented. Setting `STOCKS_PROVIDER=alpha_vantage` raises `PluginFetchError` immediately. Stub is present so the plugin structure supports the provider swap when needed.

## Data timing

- During market hours: data is delayed ~15–20 minutes (Yahoo's standard unauthenticated delay).
- Pre-market: "yesterday's close" is the most recent data point.
- The `market_state` field in the payload reflects the current state so the LLM prompt can phrase correctly.

## Reliability

If yfinance breaks (Yahoo changes endpoints), the plugin section shows "market data unavailable" and the rest of the brief proceeds. Check [yfinance releases](https://github.com/ranaroussi/yfinance/releases) for a fix.
