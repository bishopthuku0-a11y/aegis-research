"""Aegis market-data adapter for date-specific Yahoo Finance daily bars.

This module fetches historical daily closing prices only. It does not infer a
missing trading-day price, substitute a nearby date, or fabricate timestamps.
It is a data adapter, not an investment recommendation engine.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping



TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")
SOURCE_NAME = "Yahoo Finance via yfinance"


class MarketDataError(RuntimeError):
    """Raised when requested market data cannot be verified."""


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise MarketDataError("market_date must use YYYY-MM-DD format") from None


def _normalize_ticker(ticker: str) -> str:
    symbol = str(ticker).strip().upper()
    if not TICKER_PATTERN.fullmatch(symbol):
        raise MarketDataError(f"Invalid ticker symbol: {ticker!r}")
    return symbol


def fetch_daily_quote(
    ticker: str,
    market_date: str,
    *,
    ticker_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Fetch the exact daily Close for ``market_date`` or fail closed.

    The returned ``timestamp`` is the timezone-aware timestamp attached to
    Yahoo's daily bar (normally the exchange-local bar label), not the time
    this function downloaded the data. ``retrieved_at`` separately records
    when this process fetched the response.

    If Yahoo returns no bar for the requested date (weekend, holiday, outage,
    delisting, etc.), this function raises MarketDataError. It never silently
    falls back to the previous or next trading day.
    """
    symbol = _normalize_ticker(ticker)
    requested_day = _parse_date(market_date)
    if ticker_factory is None:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise MarketDataError("yfinance is required to fetch market data") from exc
        factory = yf.Ticker
    else:
        factory = ticker_factory

    try:
        instrument = factory(symbol)
        history = instrument.history(
            start=requested_day.isoformat(),
            end=(requested_day + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,
            actions=False,
        )
    except Exception as exc:
        raise MarketDataError(f"Market-data request failed for {symbol}: {exc}") from exc

    if history is None or getattr(history, "empty", True):
        raise MarketDataError(
            f"No daily market bar returned for {symbol} on {requested_day.isoformat()}"
        )

    matches: list[tuple[Any, Any]] = []
    try:
        rows = history.iterrows()
        for index_value, row in rows:
            bar_timestamp = index_value.to_pydatetime() if hasattr(index_value, "to_pydatetime") else index_value
            if not isinstance(bar_timestamp, datetime):
                continue
            # Daily bars are dated in the exchange timezone carried by the index.
            if bar_timestamp.date() == requested_day:
                matches.append((bar_timestamp, row["Close"]))
    except Exception as exc:
        raise MarketDataError(f"Could not interpret daily bar for {symbol}: {exc}") from exc

    if len(matches) != 1:
        raise MarketDataError(
            f"Expected exactly one daily bar for {symbol} on {requested_day.isoformat()}, "
            f"received {len(matches)}"
        )

    bar_timestamp, raw_close = matches[0]
    if bar_timestamp.tzinfo is None or bar_timestamp.utcoffset() is None:
        raise MarketDataError(
            f"Yahoo daily bar timestamp for {symbol} has no timezone; refusing to guess"
        )

    try:
        close = float(raw_close)
    except (TypeError, ValueError):
        raise MarketDataError(f"Invalid closing price returned for {symbol}") from None
    if not math.isfinite(close) or close <= 0:
        raise MarketDataError(f"Non-positive or non-finite closing price returned for {symbol}")

    return {
        "ticker": symbol,
        "price": close,
        "market_date": requested_day.isoformat(),
        "timestamp": bar_timestamp.isoformat(),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_NAME,
        "price_type": "UNADJUSTED_DAILY_CLOSE",
    }


def fetch_daily_quotes(
    tickers: list[str] | tuple[str, ...],
    market_date: str,
    *,
    ticker_factory: Callable[[str], Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch all requested symbols atomically; return no partial quote set."""
    if not tickers:
        raise MarketDataError("At least one ticker is required")

    normalized = [_normalize_ticker(ticker) for ticker in tickers]
    if len(set(normalized)) != len(normalized):
        raise MarketDataError("Duplicate ticker symbols are not allowed")

    quotes: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for symbol in normalized:
        try:
            quotes[symbol] = fetch_daily_quote(
                symbol, market_date, ticker_factory=ticker_factory
            )
        except MarketDataError as exc:
            failures.append(str(exc))

    if failures:
        details = "; ".join(failures)
        raise MarketDataError(
            "Market-data batch rejected; no partial quote set returned. " + details
        )
    return quotes
