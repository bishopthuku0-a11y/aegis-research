"""Daily paper-portfolio valuation runner for Aegis.

This component only marks existing paper holdings to an explicitly requested
market date. It never creates orders, calls Gemini, or connects to a broker.
A valuation is saved only after every held ticker has a verified exact-date
market quote.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from market_data import MarketDataError, fetch_daily_quotes
from simulation_engine import (
    SimulationError,
    load_ledger,
    mark_to_market,
    save_ledger,
)


class ValuationError(RuntimeError):
    """Raised when a daily paper-portfolio valuation cannot be completed."""


def update_valuation(
    market_date: str,
    ledger_path: str | Path = "simulation_ledger.json",
) -> dict[str, Any]:
    """Mark all current holdings to an exact market date and persist a snapshot.

    The date is mandatory and is never inferred. If any quote is missing,
    invalid, or belongs to another date, the existing ledger remains unchanged.
    Re-running the same date replaces that date's snapshot rather than
    duplicating it. Older dates cannot be inserted after a newer valuation.
    """
    path = Path(ledger_path)
    if not path.is_file():
        raise ValuationError(f"Simulation ledger not found: {path}")

    try:
        ledger = load_ledger(str(path))
        requested_date = str(market_date)
        if requested_date < ledger["start_date"]:
            raise ValuationError(
                f"Valuation date {requested_date} is before portfolio start date "
                f"{ledger['start_date']}"
            )
        existing_dates = [str(item.get("date", "")) for item in ledger["snapshots"]]
        latest_date = max(existing_dates, default=ledger["start_date"])
        if requested_date < latest_date:
            raise ValuationError(
                f"Out-of-order valuation rejected: latest saved date is {latest_date}"
            )

        tickers = list(ledger["holdings"].keys())
        quotes = fetch_daily_quotes(tickers, requested_date) if tickers else {}
        snapshot = mark_to_market(ledger, quotes, requested_date)
        save_ledger(ledger, str(path))
        return snapshot
    except (ValuationError, MarketDataError, SimulationError):
        raise
    except Exception as exc:
        raise ValuationError(f"Valuation failed; ledger was not updated: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update Aegis paper-portfolio valuation using exact-date market closes."
    )
    parser.add_argument("--date", required=True, help="Market date in YYYY-MM-DD format")
    parser.add_argument("--ledger", default="simulation_ledger.json")
    args = parser.parse_args()
    try:
        snapshot = update_valuation(args.date, args.ledger)
    except (ValuationError, MarketDataError, SimulationError) as exc:
        parser.exit(2, f"DATA FAILURE — {exc}\n")

    print("PAPER PORTFOLIO VALUATION UPDATED")
    print(f"Date: {snapshot['date']}")
    print(f"Equity: ${snapshot['equity']:,.2f}")
    print(f"Cash: ${snapshot['cash']:,.2f}")
    print(f"Holdings: ${snapshot['holdings_value']:,.2f}")
    print(f"Total P/L: ${snapshot['total_pnl']:,.2f}")
    print(f"Return: {snapshot['return_pct']:+.4f}%")
    print("Simulation mode: PAPER_ONLY; no orders were placed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
