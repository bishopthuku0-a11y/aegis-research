import datetime as dt
import json
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# Stub yfinance so importing the agent never needs network access.
fake_yfinance = types.ModuleType("yfinance")
fake_yfinance.Ticker = lambda ticker: None
sys.modules.setdefault("yfinance", fake_yfinance)

import daily_agent as agent

PORTFOLIO = {"XLU": 0.5, "GRID": 0.3, "UTES": 0.2}


class FakeHistory:
    empty = False
    columns = ["Close"]

    def __init__(self, close, timestamp):
        self.index = [timestamp]
        self.close = close

    def dropna(self, subset=None):
        return self

    class Series:
        def __init__(self, value):
            self.iloc = [value]

    def __getitem__(self, key):
        return self.Series(self.close)


class FakeTicker:
    def __init__(self, history):
        self._history = history

    def history(self, **kwargs):
        return self._history


class DailyAgentTests(unittest.TestCase):
    def test_import_is_safe_without_gemini_key(self):
        self.assertTrue(callable(agent.run))

    def test_memory_accepts_exact_three_etf_portfolio(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "memory.json"
            path.write_text(json.dumps({"portfolio": PORTFOLIO}), encoding="utf-8")
            self.assertEqual(agent.load_memory(path)["portfolio"], PORTFOLIO)

    def test_memory_rejects_external_ticker(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "memory.json"
            path.write_text(json.dumps({"portfolio": {"MSFT": 1.0}}), encoding="utf-8")
            with self.assertRaises(Exception):
                agent.load_memory(path)

    def test_get_market_data_returns_timestamped_daily_close(self):
        timestamp = dt.datetime(2026, 11, 18, tzinfo=dt.timezone.utc)
        history = FakeHistory(43.5, timestamp)
        with patch.object(agent.yf, "Ticker", return_value=FakeTicker(history)):
            quote = agent.get_market_data(
                "XLU", now=dt.datetime(2026, 11, 19, tzinfo=dt.timezone.utc)
            )
        self.assertEqual(quote["price"], 43.5)
        self.assertEqual(quote["price_type"], "UNADJUSTED_DAILY_CLOSE")
        self.assertIn("2026-11-18", quote["price_as_of"])

    def test_get_market_data_rejects_stale_quote(self):
        timestamp = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
        history = FakeHistory(43.5, timestamp)
        with patch.object(agent.yf, "Ticker", return_value=FakeTicker(history)):
            with self.assertRaises(agent.DataIntegrityError):
                agent.get_market_data(
                    "XLU", now=dt.datetime(2026, 11, 19, tzinfo=dt.timezone.utc)
                )

    def test_get_market_data_rejects_unapproved_ticker(self):
        with self.assertRaises(agent.DataIntegrityError):
            agent.get_market_data("MSFT")

    def test_data_failure_blocks_gemini_and_preserves_memory(self):
        with TemporaryDirectory() as folder:
            memory_path = Path(folder) / "memory.json"
            briefing_path = Path(folder) / "briefing.md"
            decision_path = Path(folder) / "decision.json"
            original = {
                "portfolio": PORTFOLIO,
                "past_pitches": [],
                "lessons_learned": ["existing note"],
            }
            memory_path.write_text(json.dumps(original), encoding="utf-8")
            with patch.object(
                agent, "collect_portfolio_snapshot",
                side_effect=agent.DataIntegrityError("test quote failure")
            ), patch.object(agent, "ask_aegis") as ask:
                result = agent.run(memory_path, briefing_path, decision_path)
            self.assertEqual(result, 2)
            ask.assert_not_called()
            self.assertEqual(json.loads(memory_path.read_text()), original)
            self.assertIn("DATA FAILURE", briefing_path.read_text())
            self.assertFalse(decision_path.exists())


if __name__ == "__main__":
    unittest.main()
