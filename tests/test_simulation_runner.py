import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import simulation_runner as runner
from simulation_engine import initialize_portfolio, save_ledger


class SimulationRunnerTests(unittest.TestCase):
    def _ledger_file(self, folder):
        quotes = {
            "XLU": {"price": 50, "market_date": "2026-11-17", "timestamp": "2026-11-17T16:00:00-05:00", "source": "test"},
            "GRID": {"price": 100, "market_date": "2026-11-17", "timestamp": "2026-11-17T16:00:00-05:00", "source": "test"},
            "UTES": {"price": 25, "market_date": "2026-11-17", "timestamp": "2026-11-17T16:00:00-05:00", "source": "test"},
        }
        ledger = initialize_portfolio(quotes, "2026-11-17")
        path = Path(folder) / "simulation_ledger.json"
        save_ledger(ledger, str(path))
        return path

    def test_updates_snapshot_and_saves_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._ledger_file(folder)
            quotes = {
                "XLU": {"price": 51, "market_date": "2026-11-18", "timestamp": "2026-11-18T16:00:00-05:00", "source": "test"},
                "GRID": {"price": 99, "market_date": "2026-11-18", "timestamp": "2026-11-18T16:00:00-05:00", "source": "test"},
                "UTES": {"price": 26, "market_date": "2026-11-18", "timestamp": "2026-11-18T16:00:00-05:00", "source": "test"},
            }
            with patch.object(runner, "fetch_daily_quotes", return_value=quotes):
                snapshot = runner.update_valuation("2026-11-18", path)
            saved = json.loads(path.read_text())
            self.assertEqual(snapshot["date"], "2026-11-18")
            self.assertEqual(len(saved["snapshots"]), 1)
            self.assertAlmostEqual(saved["snapshots"][0]["equity"], snapshot["equity"])

    def test_same_date_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._ledger_file(folder)
            quotes = {
                "XLU": {"price": 50, "market_date": "2026-11-18", "timestamp": "2026-11-18T16:00:00-05:00", "source": "test"},
                "GRID": {"price": 100, "market_date": "2026-11-18", "timestamp": "2026-11-18T16:00:00-05:00", "source": "test"},
                "UTES": {"price": 25, "market_date": "2026-11-18", "timestamp": "2026-11-18T16:00:00-05:00", "source": "test"},
            }
            with patch.object(runner, "fetch_daily_quotes", return_value=quotes):
                runner.update_valuation("2026-11-18", path)
                runner.update_valuation("2026-11-18", path)
            saved = json.loads(path.read_text())
            self.assertEqual(len(saved["snapshots"]), 1)

    def test_missing_quote_leaves_ledger_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._ledger_file(folder)
            before = path.read_bytes()
            with patch.object(runner, "fetch_daily_quotes", side_effect=runner.MarketDataError("missing GRID")):
                with self.assertRaises(runner.MarketDataError):
                    runner.update_valuation("2026-11-18", path)
            self.assertEqual(path.read_bytes(), before)

    def test_older_date_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._ledger_file(folder)
            with self.assertRaises(runner.ValuationError):
                runner.update_valuation("2026-11-16", path)

    def test_missing_ledger_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(runner.ValuationError):
                runner.update_valuation("2026-11-18", Path(folder) / "missing.json")


if __name__ == "__main__":
    unittest.main()
