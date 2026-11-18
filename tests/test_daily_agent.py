import datetime as dt
import json
import tempfile
import unittest
import sys
import types
from pathlib import Path
from unittest.mock import patch

# Keep unit tests independent of network SDK installation.
yf_stub = types.ModuleType("yfinance")
yf_stub.Ticker = None
google_stub = types.ModuleType("google")
genai_stub = types.SimpleNamespace(Client=None)
google_stub.genai = genai_stub
sys.modules.setdefault("yfinance", yf_stub)
sys.modules.setdefault("google", google_stub)
sys.modules.setdefault("google.genai", genai_stub)

import daily_agent as agent


class FakeSeries:
    def __init__(self, values, index):
        self.values = list(values)
        self.index = list(index)
        self.iloc = self
    def dropna(self):
        pairs = [(v, i) for v, i in zip(self.values, self.index) if v is not None]
        return FakeSeries([p[0] for p in pairs], [p[1] for p in pairs])
    def astype(self, _kind):
        return self
    def __gt__(self, other):
        return [v > other for v in self.values]
    def __getitem__(self, key):
        if isinstance(key, list):
            pairs = [(v, i) for v, i, keep in zip(self.values, self.index, key) if keep]
            return FakeSeries([p[0] for p in pairs], [p[1] for p in pairs])
        if isinstance(key, int):
            return self.values[key]
        raise TypeError(key)
    def __len__(self):
        return len(self.values)


class FakeHistory:
    def __init__(self, values, dates):
        self.empty = not bool(values)
        self.close = FakeSeries(values, dates)
    def __contains__(self, key):
        return key == "Close"
    def __getitem__(self, key):
        if key != "Close":
            raise KeyError(key)
        return self.close


class ParseOutputTests(unittest.TestCase):
    def test_parses_valid_machine_lines(self):
        action, ticker, lesson, body = agent.parse_model_output(
            "## Analysis\nGood evidence.\nPITCH_ACTION: BUY\n"
            "PITCH_TICKER: MSFT\nNEW_LESSON: Require cash-flow confirmation."
        )
        self.assertEqual((action, ticker), ("BUY", "MSFT"))
        self.assertEqual(lesson, "Require cash-flow confirmation.")
        self.assertIn("Good evidence.", body)

    def test_rejects_missing_action(self):
        with self.assertRaises(ValueError):
            agent.parse_model_output("PITCH_TICKER: XLU\nNEW_LESSON: NONE")

    def test_rejects_invalid_ticker(self):
        with self.assertRaises(ValueError):
            agent.parse_model_output(
                "PITCH_ACTION: BUY\nPITCH_TICKER: BAD TICKER\nNEW_LESSON: NONE"
            )

    def test_none_lesson_is_empty(self):
        result = agent.parse_model_output(
            "PITCH_ACTION: HOLD\nPITCH_TICKER: XLU\nNEW_LESSON: NONE"
        )
        self.assertEqual(result[2], "")


class MemoryTests(unittest.TestCase):
    def test_loads_existing_memory_shape(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "memory.json"
            path.write_text(json.dumps({"portfolio": {"XLU": .5, "GRID": .3, "UTES": .2},
                                        "past_pitches": [], "lessons_learned": []}))
            memory = agent.load_memory(path)
            self.assertAlmostEqual(sum(memory["portfolio"].values()), 1.0)

    def test_rejects_invalid_portfolio_weight(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "memory.json"
            path.write_text(json.dumps({"portfolio": {"XLU": -0.5}}))
            with self.assertRaises(ValueError):
                agent.load_memory(path)

    def test_atomic_save_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "memory.json"
            agent.save_json_atomic({"ok": True}, path)
            self.assertEqual(json.loads(path.read_text()), {"ok": True})


class MarketDataTests(unittest.TestCase):
    def test_rejects_stale_market_data(self):
        class FakeTicker:
            def history(self, **kwargs):
                return FakeHistory([10.0, 11.0], [dt.datetime(2026, 10, 1), dt.datetime(2026, 10, 2)])
        with patch.object(agent.yf, "Ticker", return_value=FakeTicker()):
            with self.assertRaises(agent.DataIntegrityError):
                agent.get_market_data("XLU", now=dt.datetime(2026, 11, 18, tzinfo=dt.timezone.utc))

    def test_validates_close_and_timestamp(self):
        class FakeTicker:
            def history(self, **kwargs):
                return FakeHistory([10.0, 11.0], [dt.datetime(2026, 11, 16), dt.datetime(2026, 11, 17)])
        with patch.object(agent.yf, "Ticker", return_value=FakeTicker()):
            data = agent.get_market_data("XLU", now=dt.datetime(2026, 11, 18, tzinfo=dt.timezone.utc))
        self.assertEqual(data["price"], 11.0)
        self.assertAlmostEqual(data["change_pct"], 10.0)
        self.assertIn("price_as_of", data)

    def test_news_failure_does_not_destroy_price_snapshot(self):
        class FakeTicker:
            def history(self, **kwargs):
                return FakeHistory([10.0, 11.0], [dt.datetime(2026, 11, 16), dt.datetime(2026, 11, 17)])
            @property
            def news(self):
                raise RuntimeError("news service down")
        with patch.object(agent.yf, "Ticker", return_value=FakeTicker()):
            snapshot, headlines = agent.collect_portfolio_snapshot(
                {"XLU": .5}, now=dt.datetime(2026, 11, 18, tzinfo=dt.timezone.utc))
        self.assertIn("XLU", snapshot)
        self.assertEqual(headlines, [])


class FailClosedRunTests(unittest.TestCase):
    def test_data_failure_writes_failure_report_without_calling_gemini_or_mutating_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            memory_path = Path(folder) / "memory.json"
            briefing_path = Path(folder) / "latest_briefing.md"
            original = {"portfolio": {"XLU": 0.5, "GRID": 0.3, "UTES": 0.2},
                        "past_pitches": [{"date": "2026-11-17", "action": "TRIM",
                                          "ticker": "GRID", "entry_price": 156.14}],
                        "lessons_learned": ["Existing lesson"]}
            memory_path.write_text(json.dumps(original))
            with patch.object(agent, "MEMORY_FILE", memory_path), \
                 patch.object(agent, "BRIEFING_FILE", briefing_path), \
                 patch.object(agent, "collect_portfolio_snapshot",
                              side_effect=agent.DataIntegrityError("GRID price unavailable")), \
                 patch.object(agent.genai, "Client") as client_factory:
                code = agent.run()
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(memory_path.read_text()), original)
            self.assertIn("DATA FAILURE", briefing_path.read_text())
            client_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
