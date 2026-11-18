import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd

from market_data import MarketDataError, fetch_daily_quote, fetch_daily_quotes


class FakeTicker:
    def __init__(self, frame=None, error=None):
        self.frame = frame
        self.error = error
        self.calls = []

    def history(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.frame


def make_frame(day="2026-11-18", close=42.5, timezone_name="America/New_York"):
    index = pd.DatetimeIndex([pd.Timestamp(f"{day} 16:00:00", tz=timezone_name)])
    return pd.DataFrame({"Close": [close]}, index=index)


class MarketDataTests(unittest.TestCase):
    def test_fetches_exact_date_and_returns_source_timestamp(self):
        instrument = FakeTicker(make_frame())
        quote = fetch_daily_quote("xlu", "2026-11-18", ticker_factory=lambda _: instrument)
        self.assertEqual(quote["ticker"], "XLU")
        self.assertEqual(quote["price"], 42.5)
        self.assertEqual(quote["market_date"], "2026-11-18")
        self.assertIn("-05:00", quote["timestamp"])
        self.assertEqual(quote["price_type"], "UNADJUSTED_DAILY_CLOSE")
        self.assertEqual(instrument.calls[0]["interval"], "1d")
        self.assertFalse(instrument.calls[0]["auto_adjust"])

    def test_missing_date_does_not_fall_back_to_neighbouring_day(self):
        instrument = FakeTicker(make_frame(day="2026-11-17"))
        with self.assertRaisesRegex(MarketDataError, "received 0"):
            fetch_daily_quote("XLU", "2026-11-18", ticker_factory=lambda _: instrument)

    def test_empty_response_fails(self):
        instrument = FakeTicker(pd.DataFrame())
        with self.assertRaisesRegex(MarketDataError, "No daily market bar"):
            fetch_daily_quote("XLU", "2026-11-18", ticker_factory=lambda _: instrument)

    def test_naive_timestamp_fails_closed(self):
        frame = pd.DataFrame(
            {"Close": [42.5]},
            index=pd.DatetimeIndex([datetime(2026, 11, 18, 16, 0)]),
        )
        instrument = FakeTicker(frame)
        with self.assertRaisesRegex(MarketDataError, "no timezone"):
            fetch_daily_quote("XLU", "2026-11-18", ticker_factory=lambda _: instrument)

    def test_invalid_prices_fail(self):
        for price in [0, -1, float("nan"), float("inf")]:
            with self.subTest(price=price):
                instrument = FakeTicker(make_frame(close=price))
                with self.assertRaises(MarketDataError):
                    fetch_daily_quote("XLU", "2026-11-18", ticker_factory=lambda _: instrument)

    def test_provider_error_is_reported(self):
        instrument = FakeTicker(error=TimeoutError("provider timeout"))
        with self.assertRaisesRegex(MarketDataError, "provider timeout"):
            fetch_daily_quote("XLU", "2026-11-18", ticker_factory=lambda _: instrument)

    def test_batch_is_all_or_nothing(self):
        def factory(symbol):
            if symbol == "GRID":
                return FakeTicker(pd.DataFrame())
            return FakeTicker(make_frame())

        with self.assertRaisesRegex(MarketDataError, "no partial quote set"):
            fetch_daily_quotes(["XLU", "GRID", "UTES"], "2026-11-18", ticker_factory=factory)

    def test_batch_returns_all_requested_symbols(self):
        quotes = fetch_daily_quotes(
            ["XLU", "GRID", "UTES"],
            "2026-11-18",
            ticker_factory=lambda _: FakeTicker(make_frame()),
        )
        self.assertEqual(set(quotes), {"XLU", "GRID", "UTES"})

    def test_duplicate_or_invalid_ticker_rejected(self):
        with self.assertRaisesRegex(MarketDataError, "Duplicate"):
            fetch_daily_quotes(["XLU", "xlu"], "2026-11-18", ticker_factory=lambda _: None)
        with self.assertRaisesRegex(MarketDataError, "Invalid ticker"):
            fetch_daily_quote("XLU/GRID", "2026-11-18", ticker_factory=lambda _: None)

    def test_invalid_date_rejected(self):
        with self.assertRaisesRegex(MarketDataError, "YYYY-MM-DD"):
            fetch_daily_quote("XLU", "18-11-2026", ticker_factory=lambda _: None)


if __name__ == "__main__":
    unittest.main()
