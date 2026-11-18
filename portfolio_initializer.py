"""Safely initialize Aegis's first paper portfolio from verified daily quotes.

This module never selects a date automatically and never contacts a broker.
The caller must supply an explicit market date. Existing ledgers are never
silently overwritten.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping

from market_data import fetch_daily_quotes
from simulation_engine import (
    DEFAULT_ALLOCATIONS,
    SimulationError,
    initialize_portfolio,
    save_ledger,
)


class PortfolioInitializationError(RuntimeError):
    """Raised when the opening paper portfolio cannot be safely created."""


def initialize_from_market_data(
    market_date: str,
    ledger_path: str | Path = "simulation_ledger.json",
    *,
    initial_capital: Any = "10000.00",
    allocations: Mapping[str, Any] = DEFAULT_ALLOCATIONS,
    fee_bps: Any = 0,
    slippage_bps: Any = 0,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Fetch all opening quotes, build the ledger, then save it atomically.

    The date must be explicit. All required symbols must return exactly that
    date's verified daily bar. If any quote or validation fails, no ledger is
    written. By default, an existing ledger is protected from overwrite.
    """
    destination = Path(ledger_path)
    if destination.exists() and not overwrite:
        raise PortfolioInitializationError(
            f"Ledger already exists at {destination}; refusing to overwrite it"
        )

    symbols = list(allocations.keys())
    try:
        quotes = fetch_daily_quotes(symbols, market_date)
        ledger = initialize_portfolio(
            quotes=quotes,
            start_date=market_date,
            initial_capital=initial_capital,
            allocations=allocations,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        # Save only after the entire quote batch and ledger validate successfully.
        save_ledger(ledger, str(destination))
    except Exception as exc:
        if isinstance(exc, PortfolioInitializationError):
            raise
        raise PortfolioInitializationError(
            f"Opening portfolio was not created: {exc}"
        ) from exc
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Initialize Aegis's paper-only portfolio from exact-date market data."
    )
    parser.add_argument(
        "--date", required=True,
        help="Explicit market date in YYYY-MM-DD format; no automatic date selection.",
    )
    parser.add_argument(
        "--ledger", default="simulation_ledger.json",
        help="Output ledger path (default: simulation_ledger.json).",
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="Confirm creation of the initial $10,000 paper portfolio.",
    )
    args = parser.parse_args()

    if not args.confirm:
        parser.error("Pass --confirm only after reviewing the chosen market date.")

    try:
        ledger = initialize_from_market_data(args.date, args.ledger)
    except (PortfolioInitializationError, SimulationError) as exc:
        parser.exit(2, f"DATA FAILURE — {exc}\n")

    print("PAPER PORTFOLIO INITIALIZED")
    print(f"Start date: {ledger['start_date']}")
    print(f"Initial capital: ${ledger['initial_capital']:,.2f}")
    print(f"Cash remaining: ${ledger['cash']:,.2f}")
    print("Opening holdings:")
    for ticker, holding in ledger["holdings"].items():
        print(
            f"  {ticker}: {holding['quantity']:.8f} shares @ "
            f"${holding['market_price']:.6f} "
            f"(value ${holding['market_value']:,.2f})"
        )
    print(f"Ledger saved to: {args.ledger}")
    print("Simulation mode: PAPER_ONLY; no broker orders were placed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
