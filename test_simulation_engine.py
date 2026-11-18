import json
import tempfile
import unittest
from pathlib import Path

from simulation_engine import (
    SimulationError,
    execute_order,
    initialize_portfolio,
    load_ledger,
    mark_to_market,
    save_ledger,
)

DATE = "2026-11-18"


def quote(price, day=DATE, source="TEST FIXTURE"):
    return {
        "price": price,
        "market_date": day,
        "timestamp": f"{day}T16:00:00+00:00",
        "source": source,
    }


class SimulationEngineTests(unittest.TestCase):
    def setUp(self):
        self.opening_quotes = {
            "XLU": quote("40"),
            "GRID": quote("100"),
            "UTES": quote("50"),
        }

    def make_portfolio(self):
        return initialize_portfolio(self.opening_quotes, DATE)

    def test_initializes_10000_with_target_weights(self):
        ledger = self.make_portfolio()
        self.assertEqual(ledger["initial_capital"], 10000.0)
        self.assertEqual(ledger["simulation_type"], "PAPER_ONLY")
        self.assertEqual(set(ledger["holdings"]), {"XLU", "GRID", "UTES"})
        self.assertEqual(len(ledger["transactions"]), 3)
        self.assertGreaterEqual(ledger["cash"], 0)
        self.assertLess(ledger["cash"], 0.01)

    def test_missing_opening_quote_fails_without_partial_ledger(self):
        del self.opening_quotes["UTES"]
        with self.assertRaisesRegex(SimulationError, "Missing opening quote"):
            initialize_portfolio(self.opening_quotes, DATE)

    def test_wrong_day_quote_is_rejected(self):
        self.opening_quotes["GRID"] = quote("100", day="2026-11-17")
        with self.assertRaisesRegex(SimulationError, "Quote date mismatch"):
            initialize_portfolio(self.opening_quotes, DATE)

    def test_quote_requires_timezone_and_source(self):
        self.opening_quotes["XLU"]["timestamp"] = f"{DATE}T16:00:00"
        with self.assertRaisesRegex(SimulationError, "timezone"):
            initialize_portfolio(self.opening_quotes, DATE)

    def test_mark_to_market_calculates_equity_and_return(self):
        ledger = self.make_portfolio()
        next_quotes = {"XLU": quote("44"), "GRID": quote("105"), "UTES": quote("52")}
        snapshot = mark_to_market(ledger, next_quotes, DATE)
        self.assertGreater(snapshot["equity"], 10000)
        self.assertGreater(snapshot["return_pct"], 0)
        self.assertEqual(snapshot["date"], DATE)

    def test_mark_to_market_is_idempotent_for_same_day(self):
        ledger = self.make_portfolio()
        quotes = {"XLU": quote("40"), "GRID": quote("100"), "UTES": quote("50")}
        mark_to_market(ledger, quotes, DATE)
        mark_to_market(ledger, quotes, DATE)
        self.assertEqual(len(ledger["snapshots"]), 1)

    def test_buy_updates_cash_quantity_and_fee(self):
        ledger = self.make_portfolio()
        original_quantity = ledger["holdings"]["XLU"]["quantity"]
        execute_order(ledger, "XLU", "SELL", original_quantity / 2, quote("40"), DATE,
                      "Create cash for buy test")
        before_cash = ledger["cash"]
        tx = execute_order(ledger, "XLU", "BUY", "1.5", quote("40"), DATE,
                           "Test buy", fee_bps=10, slippage_bps=5)
        self.assertGreater(tx["fee"], 0)
        self.assertLess(ledger["cash"], before_cash)
        self.assertGreater(ledger["holdings"]["XLU"]["quantity"], original_quantity / 2)

    def test_sell_realizes_pnl_and_cannot_short(self):
        ledger = self.make_portfolio()
        qty = ledger["holdings"]["XLU"]["quantity"]
        tx = execute_order(ledger, "XLU", "SELL", qty / 2, quote("45"), DATE,
                           "Test partial sale")
        self.assertGreater(tx["realized_pnl"], 0)
        self.assertGreater(ledger["realized_pnl"], 0)
        with self.assertRaisesRegex(SimulationError, "Insufficient holdings"):
            execute_order(ledger, "XLU", "SELL", 999999, quote("45"), DATE,
                          "Attempt short")

    def test_buy_rejects_insufficient_cash(self):
        ledger = self.make_portfolio()
        with self.assertRaisesRegex(SimulationError, "Insufficient simulated cash"):
            execute_order(ledger, "NEW", "BUY", 100000, quote("100"), DATE,
                          "Too large")

    def test_invalid_side_and_zero_quantity_rejected(self):
        ledger = self.make_portfolio()
        with self.assertRaisesRegex(SimulationError, "BUY or SELL"):
            execute_order(ledger, "XLU", "HOLD", 1, quote("40"), DATE, "No")
        with self.assertRaisesRegex(SimulationError, "greater than zero"):
            execute_order(ledger, "XLU", "BUY", 0, quote("40"), DATE, "No")

    def test_save_and_load_round_trip(self):
        ledger = self.make_portfolio()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "simulation_ledger.json"
            save_ledger(ledger, str(path))
            loaded = load_ledger(str(path))
            self.assertEqual(loaded, ledger)
            self.assertEqual(json.loads(path.read_text())["simulation_type"], "PAPER_ONLY")

    def test_bad_allocation_weights_rejected(self):
        with self.assertRaisesRegex(SimulationError, "sum to 1.0"):
            initialize_portfolio(
                self.opening_quotes,
                DATE,
                allocations={"XLU": 0.5, "GRID": 0.5, "UTES": 0.5},
            )


if __name__ == "__main__":
    unittest.main()
