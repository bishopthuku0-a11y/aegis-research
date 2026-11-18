import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portfolio_initializer import (
    PortfolioInitializationError,
    initialize_from_market_data,
)


DATE = "2026-11-17"


def quotes_for(date=DATE):
    return {
        "XLU": {
            "ticker": "XLU", "price": 42.50, "market_date": date,
            "timestamp": f"{date}T16:00:00-05:00", "retrieved_at": "2026-11-18T10:00:00+00:00",
            "source": "Yahoo Finance via yfinance", "price_type": "UNADJUSTED_DAILY_CLOSE",
        },
        "GRID": {
            "ticker": "GRID", "price": 120.00, "market_date": date,
            "timestamp": f"{date}T16:00:00-05:00", "retrieved_at": "2026-11-18T10:00:00+00:00",
            "source": "Yahoo Finance via yfinance", "price_type": "UNADJUSTED_DAILY_CLOSE",
        },
        "UTES": {
            "ticker": "UTES", "price": 30.00, "market_date": date,
            "timestamp": f"{date}T16:00:00-05:00", "retrieved_at": "2026-11-18T10:00:00+00:00",
            "source": "Yahoo Finance via yfinance", "price_type": "UNADJUSTED_DAILY_CLOSE",
        },
    }


class PortfolioInitializerTests(unittest.TestCase):
    def test_initializes_expected_paper_allocations_and_persists_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ledger.json"
            with patch("portfolio_initializer.fetch_daily_quotes", return_value=quotes_for()) as fetch:
                ledger = initialize_from_market_data(DATE, path)
            fetch.assert_called_once_with(["XLU", "GRID", "UTES"], DATE)
            self.assertEqual(ledger["simulation_type"], "PAPER_ONLY")
            self.assertEqual(ledger["initial_capital"], 10000.0)
            self.assertEqual(set(ledger["holdings"]), {"XLU", "GRID", "UTES"})
            self.assertTrue(path.exists())
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["start_date"], DATE)
            self.assertEqual(len(saved["transactions"]), 3)

    def test_missing_required_quote_writes_no_ledger(self):
        incomplete = quotes_for()
        del incomplete["UTES"]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ledger.json"
            with patch("portfolio_initializer.fetch_daily_quotes", return_value=incomplete):
                with self.assertRaises(PortfolioInitializationError):
                    initialize_from_market_data(DATE, path)
            self.assertFalse(path.exists())

    def test_wrong_date_quote_writes_no_ledger(self):
        wrong_day = quotes_for()
        wrong_day["GRID"]["market_date"] = "2026-11-16"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ledger.json"
            with patch("portfolio_initializer.fetch_daily_quotes", return_value=wrong_day):
                with self.assertRaises(PortfolioInitializationError):
                    initialize_from_market_data(DATE, path)
            self.assertFalse(path.exists())

    def test_existing_ledger_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ledger.json"
            path.write_text('{"keep": true}', encoding="utf-8")
            with patch("portfolio_initializer.fetch_daily_quotes") as fetch:
                with self.assertRaisesRegex(PortfolioInitializationError, "refusing to overwrite"):
                    initialize_from_market_data(DATE, path)
            fetch.assert_not_called()
            self.assertEqual(json.loads(path.read_text()), {"keep": True})

    def test_market_data_failure_writes_no_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ledger.json"
            with patch("portfolio_initializer.fetch_daily_quotes", side_effect=RuntimeError("provider down")):
                with self.assertRaisesRegex(PortfolioInitializationError, "provider down"):
                    initialize_from_market_data(DATE, path)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
