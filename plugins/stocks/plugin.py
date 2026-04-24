"""Stocks plugin — price, volume, and news for a configurable watchlist."""

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any

import yfinance as yf

from jarvis.core.exceptions import PluginFetchError
from jarvis.core.plugin import DataSourcePlugin, FetchResult

__all__ = ["StocksPlugin"]

log = logging.getLogger(__name__)

_INDEX_SYMBOLS = {
    "^GSPC": "S&P 500",
    "^DJI": "Dow Jones",
    "^IXIC": "Nasdaq",
    "^VIX": "VIX",
}


def _parse_tickers() -> list[str]:
    raw = os.environ.get("STOCKS_TICKERS", "")
    return [t.strip().upper() for t in raw.split(",") if t.strip()]


def _include_indices() -> bool:
    return os.environ.get("STOCKS_INCLUDE_INDICES", "true").lower() not in {"false", "0", "no"}


def _news_per_ticker() -> int:
    try:
        return int(os.environ.get("STOCKS_NEWS_PER_TICKER", "3"))
    except ValueError:
        return 3


def _provider() -> str:
    return os.environ.get("STOCKS_PROVIDER", "yfinance").lower()


def _safe_float(value: Any) -> float | None:
    """Coerce a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct_change(current: float | None, previous: float | None) -> float | None:
    """Compute percentage change from previous to current."""
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 4)


def _52w_position(last: float | None, low: float | None, high: float | None) -> float | None:
    """Compute where the current price sits in its 52-week range (0.0–1.0)."""
    if last is None or low is None or high is None:
        return None
    span = high - low
    if span <= 0:
        return None
    raw = (last - low) / span
    return round(max(0.0, min(1.0, raw)), 4)


def _parse_news_item(item: dict, limit: int) -> list[dict]:
    """Extract and normalize up to `limit` news items from yfinance news list."""
    out: list[dict] = []
    for entry in item[:limit]:
        try:
            # yfinance news items may have varying structures across versions
            title = entry.get("title") or entry.get("content", [{}])[0].get("value", "")
            publisher = entry.get("publisher") or entry.get("source", {}).get("label", "")
            url = (
                entry.get("link")
                or entry.get("clickThroughUrl", {}).get("url", "")
                or entry.get("canonicalUrl", {}).get("url", "")
            )
            # providerPublishTime is a unix timestamp in some versions
            raw_ts = entry.get("providerPublishTime") or entry.get("pubDate")
            if isinstance(raw_ts, (int, float)):
                published = datetime.fromtimestamp(raw_ts, tz=UTC).isoformat()
            elif isinstance(raw_ts, str):
                published = raw_ts
            else:
                published = None

            if title:
                out.append(
                    {
                        "title": title,
                        "publisher": publisher,
                        "published": published,
                        "url": url,
                    }
                )
        except Exception as exc:
            log.debug("Skipping malformed news item: %s", exc)
    return out


def _fetch_ticker_sync(symbol: str, news_limit: int, include_news: bool) -> dict:
    """Synchronous yfinance fetch for a single symbol.

    Designed to run inside asyncio.to_thread().
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}

        last = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        previous_close = _safe_float(
            info.get("regularMarketPreviousClose") or info.get("previousClose")
        )
        week_high = _safe_float(info.get("fiftyTwoWeekHigh"))
        week_low = _safe_float(info.get("fiftyTwoWeekLow"))
        volume = info.get("regularMarketVolume") or info.get("volume")
        avg_volume = info.get("averageVolume") or info.get("averageDailyVolume30Day")

        # Fallback: regularMarketDayHigh/Low are not 52w fields — only use fiftyTwoWeek*
        change_pct_day = _pct_change(last, previous_close)

        # Week/month/YTD changes via fast_info when available
        fast = getattr(ticker, "fast_info", None)
        change_pct_week = None
        change_pct_month = None
        change_pct_ytd = None
        if fast:
            try:
                week_ago_close = getattr(fast, "five_day_close", None)
                if week_ago_close and last:
                    change_pct_week = _pct_change(last, float(week_ago_close))
            except Exception:
                pass
            try:
                ytd_change = getattr(fast, "ytd_return", None)
                if ytd_change is not None:
                    change_pct_ytd = round(float(ytd_change) * 100, 4)
            except Exception:
                pass

        # info dict sometimes carries week/month deltas directly
        # Note: 52WeekChange is an annualised figure — not appropriate for week delta.
        # We leave change_pct_week as None when fast_info doesn't provide it.
        if change_pct_ytd is None:
            ytd_raw = _safe_float(info.get("52WeekChange"))
            if ytd_raw is not None:
                change_pct_ytd = round(ytd_raw * 100, 4)

        volume_int = int(volume) if volume is not None else None
        avg_volume_int = int(avg_volume) if avg_volume is not None else None
        volume_ratio = None
        if volume_int and avg_volume_int and avg_volume_int > 0:
            volume_ratio = round(volume_int / avg_volume_int, 4)

        market_state: str = info.get("marketState", "unknown")

        news_items: list[dict] = []
        if include_news and news_limit > 0:
            try:
                raw_news = ticker.news or []
                news_items = _parse_news_item(raw_news, news_limit)
            except Exception as exc:
                log.debug("Could not fetch news for %s: %s", symbol, exc)

        return {
            "symbol": symbol,
            "name": info.get("longName") or info.get("shortName") or symbol,
            "last": last,
            "previous_close": previous_close,
            "change_pct_day": change_pct_day,
            "change_pct_week": change_pct_week,
            "change_pct_month": change_pct_month,
            "change_pct_ytd": change_pct_ytd,
            "52w_high": week_high,
            "52w_low": week_low,
            "52w_position": _52w_position(last, week_low, week_high),
            "volume": volume_int,
            "avg_volume_30d": avg_volume_int,
            "volume_ratio": volume_ratio,
            "news": news_items,
            "_market_state": market_state,
            "_error": None,
        }

    except Exception as exc:
        log.warning("yfinance fetch failed for %s: %s", symbol, exc)
        return {
            "symbol": symbol,
            "name": symbol,
            "last": None,
            "previous_close": None,
            "change_pct_day": None,
            "change_pct_week": None,
            "change_pct_month": None,
            "change_pct_ytd": None,
            "52w_high": None,
            "52w_low": None,
            "52w_position": None,
            "volume": None,
            "avg_volume_30d": None,
            "volume_ratio": None,
            "news": [],
            "_market_state": "unknown",
            "_error": str(exc),
        }


def _strip_internal(record: dict, include_news: bool = True) -> dict:
    """Remove internal fields and optionally the news list from a record."""
    out = {k: v for k, v in record.items() if not k.startswith("_")}
    if not include_news:
        out.pop("news", None)
    return out


class StocksPlugin(DataSourcePlugin):
    """Fetch price, volume, and news for a configurable watchlist via yfinance."""

    name = "stocks"
    display_name = "Stocks"
    required_env_vars = ["STOCKS_TICKERS"]
    temperature = 0.2
    max_tokens = 600

    async def fetch(self, window_hours: int) -> FetchResult:
        """Pull latest price/volume data and headlines for the configured watchlist."""
        provider = _provider()
        if provider == "alpha_vantage":
            raise PluginFetchError("alpha_vantage provider not yet implemented")
        if provider != "yfinance":
            raise PluginFetchError(f"Unknown STOCKS_PROVIDER: {provider!r}")

        tickers = _parse_tickers()
        if not tickers:
            raise PluginFetchError("STOCKS_TICKERS is set but contains no valid symbols")

        news_limit = _news_per_ticker()
        include_indices = _include_indices()

        all_symbols: list[tuple[str, bool]] = []  # (symbol, is_index)
        if include_indices:
            for sym in _INDEX_SYMBOLS:
                all_symbols.append((sym, True))
        for sym in tickers:
            all_symbols.append((sym, False))

        log.info(
            "Fetching %d symbols (%d indices, %d tickers) via yfinance",
            len(all_symbols),
            sum(1 for _, is_idx in all_symbols if is_idx),
            len(tickers),
        )

        # yfinance is synchronous — run each fetch in a thread
        tasks = [
            asyncio.to_thread(
                _fetch_ticker_sync,
                symbol,
                0 if is_index else news_limit,
                not is_index,
            )
            for symbol, is_index in all_symbols
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Extract market_state from the first successful non-VIX result
        market_state = "unknown"
        for (symbol, _), result in zip(all_symbols, results):
            if isinstance(result, dict) and result.get("_market_state") not in (None, "unknown"):
                market_state = result["_market_state"]
                break

        indices: list[dict] = []
        ticker_records: list[dict] = []

        for (symbol, is_index), result in zip(all_symbols, results):
            if isinstance(result, Exception):
                log.warning("Thread exception for %s: %s", symbol, result)
                record = {
                    "symbol": symbol,
                    "name": _INDEX_SYMBOLS.get(symbol, symbol),
                    "last": None,
                    "previous_close": None,
                    "change_pct_day": None,
                    "change_pct_week": None,
                    "change_pct_month": None,
                    "change_pct_ytd": None,
                    "52w_high": None,
                    "52w_low": None,
                    "52w_position": None,
                    "_error": str(result),
                }
                if not is_index:
                    record.update({"volume": None, "avg_volume_30d": None, "volume_ratio": None, "news": []})
            else:
                if result.get("_error"):
                    log.warning("yfinance returned error for %s: %s", symbol, result["_error"])
                record = result
                if is_index:
                    record["name"] = _INDEX_SYMBOLS.get(symbol, record.get("name", symbol))

            if is_index:
                indices.append(_strip_internal(record, include_news=False))
            else:
                ticker_records.append(_strip_internal(record, include_news=True))

        payload = {
            "as_of": datetime.now(tz=UTC).isoformat(),
            "market_state": market_state,
            "currency": "USD",
            "indices": indices,
            "tickers": ticker_records,
        }

        links = [
            item["url"]
            for rec in ticker_records
            for item in rec.get("news", [])
            if item.get("url")
        ]

        return FetchResult(
            source_name=self.display_name,
            raw_payload=payload,
            metadata={
                "ticker_count": len(tickers),
                "index_count": len(indices),
                "market_state": market_state,
                "provider": provider,
                "window_hours": window_hours,
            },
            links=links[:10],
        )

    def redact(self, payload: Any) -> Any:
        """No redaction required — stock data is public market information."""
        return payload
