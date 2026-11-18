"""Aegis Research paper-portfolio ledger.

This module performs simulation accounting only. It never connects to a broker
or submits real orders. Market quotes must be supplied by a separate, trusted
market-data layer and must include price, market_date, timestamp, and source.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from typing import Any, Mapping

SCHEMA_VERSION = 1
DEFAULT_ALLOCATIONS = {"XLU": 0.50, "GRID": 0.30, "UTES": 0.20}
SHARE_QUANTUM = Decimal("0.00000001")
MONEY_QUANTUM = Decimal("0.01")
PRICE_QUANTUM = Decimal("0.000001")


class SimulationError(ValueError):
    """Raised when a simulated portfolio operation is invalid."""


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise SimulationError(f"{field} must be a valid number") from None
    if not result.is_finite():
        raise SimulationError(f"{field} must be finite")
    return result


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _price(value: Decimal) -> Decimal:
    return value.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)


def _shares(value: Decimal) -> Decimal:
    return value.quantize(SHARE_QUANTUM, rounding=ROUND_DOWN)


def _iso_date(value: str, field: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        raise SimulationError(f"{field} must be YYYY-MM-DD") from None


def validate_quote(quote: Mapping[str, Any], expected_market_date: str) -> dict[str, Any]:
    """Validate a quote and return a normalized copy.

    A quote is accepted only when its explicitly supplied market_date matches
    the requested simulation/trade date. The timestamp must be timezone-aware.
    """
    if not isinstance(quote, Mapping):
        raise SimulationError("Quote must be an object")

    market_date = _iso_date(quote.get("market_date"), "quote.market_date")
    expected_market_date = _iso_date(expected_market_date, "expected_market_date")
    if market_date != expected_market_date:
        raise SimulationError(
            f"Quote date mismatch: expected {expected_market_date}, received {market_date}"
        )

    price_value = _decimal(quote.get("price"), "quote.price")
    if price_value <= 0:
        raise SimulationError("Quote price must be greater than zero")

    timestamp_value = quote.get("timestamp")
    if not isinstance(timestamp_value, str) or not timestamp_value.strip():
        raise SimulationError("Quote timestamp is required")
    try:
        timestamp = datetime.fromisoformat(timestamp_value.replace("Z", "+00:00"))
    except ValueError:
        raise SimulationError("Quote timestamp must be ISO-8601") from None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise SimulationError("Quote timestamp must include a timezone")

    source = quote.get("source")
    if not isinstance(source, str) or not source.strip():
        raise SimulationError("Quote source is required")

    return {
        "price": float(_price(price_value)),
        "market_date": market_date,
        "timestamp": timestamp.isoformat(),
        "source": source.strip(),
    }


def _validate_allocations(allocations: Mapping[str, Any]) -> dict[str, Decimal]:
    if not isinstance(allocations, Mapping) or not allocations:
        raise SimulationError("Allocations must be a non-empty object")
    normalized: dict[str, Decimal] = {}
    for ticker, weight in allocations.items():
        symbol = str(ticker).strip().upper()
        if not symbol or len(symbol) > 15 or not symbol.replace(".", "").isalnum():
            raise SimulationError(f"Invalid ticker: {ticker!r}")
        value = _decimal(weight, f"allocation[{symbol}]")
        if value <= 0:
            raise SimulationError(f"Allocation for {symbol} must be greater than zero")
        normalized[symbol] = value
    total = sum(normalized.values(), Decimal("0"))
    if abs(total - Decimal("1")) > Decimal("0.000001"):
        raise SimulationError("Allocation weights must sum to 1.0")
    return normalized


def initialize_portfolio(
    quotes: Mapping[str, Mapping[str, Any]],
    start_date: str,
    initial_capital: Any = "10000.00",
    allocations: Mapping[str, Any] = DEFAULT_ALLOCATIONS,
    fee_bps: Any = 0,
    slippage_bps: Any = 0,
) -> dict[str, Any]:
    """Create the initial paper portfolio using verified, date-matched quotes.

    Fractional shares are supported to eight decimal places. No holdings are
    created if any required quote is missing or invalid.
    """
    start_date = _iso_date(start_date, "start_date")
    capital = _money(_decimal(initial_capital, "initial_capital"))
    if capital <= 0:
        raise SimulationError("Initial capital must be greater than zero")
    weights = _validate_allocations(allocations)
    fee_rate = _decimal(fee_bps, "fee_bps") / Decimal("10000")
    slip_rate = _decimal(slippage_bps, "slippage_bps") / Decimal("10000")
    if fee_rate < 0 or slip_rate < 0 or fee_rate >= 1 or slip_rate >= 1:
        raise SimulationError("Fee and slippage basis points are out of range")

    normalized_quotes: dict[str, dict[str, Any]] = {}
    for ticker in weights:
        if ticker not in quotes:
            raise SimulationError(f"Missing opening quote for {ticker}; portfolio not initialized")
        normalized_quotes[ticker] = validate_quote(quotes[ticker], start_date)

    cash = capital
    holdings: dict[str, dict[str, Any]] = {}
    transactions: list[dict[str, Any]] = []
    for ticker, weight in weights.items():
        quote = normalized_quotes[ticker]
        reference_price = _decimal(quote["price"], f"{ticker}.price")
        fill_price = _price(reference_price * (Decimal("1") + slip_rate))
        budget = capital * weight
        quantity = _shares(budget / (fill_price * (Decimal("1") + fee_rate)))
        if quantity <= 0:
            raise SimulationError(f"Opening allocation for {ticker} is too small to purchase")
        notional = _money(quantity * fill_price)
        fee = _money(notional * fee_rate)
        total_cost = notional + fee
        if total_cost > cash:
            raise SimulationError("Insufficient cash while creating opening portfolio")
        cash = _money(cash - total_cost)
        holdings[ticker] = {
            "quantity": float(quantity),
            "average_cost": float(_price(total_cost / quantity)),
            "total_cost_basis": float(_money(total_cost)),
            "market_price": float(reference_price),
            "market_value": float(_money(quantity * reference_price)),
            "price_timestamp": quote["timestamp"],
            "price_source": quote["source"],
        }
        transactions.append({
            "transaction_id": f"TX{len(transactions) + 1:06d}",
            "date": start_date,
            "timestamp": quote["timestamp"],
            "ticker": ticker,
            "side": "BUY",
            "quantity": float(quantity),
            "reference_price": float(reference_price),
            "fill_price": float(fill_price),
            "notional": float(notional),
            "fee": float(fee),
            "slippage_bps": float(_decimal(slippage_bps, "slippage_bps")),
            "reason": "Initial target allocation",
            "source": quote["source"],
            "realized_pnl": 0.0,
        })

    ledger = {
        "schema_version": SCHEMA_VERSION,
        "simulation_type": "PAPER_ONLY",
        "currency": "USD",
        "start_date": start_date,
        "initial_capital": float(capital),
        "cash": float(cash),
        "allocations": {ticker: float(weight) for ticker, weight in weights.items()},
        "holdings": holdings,
        "transactions": transactions,
        "snapshots": [],
        "realized_pnl": 0.0,
        "fees_paid": float(sum((_decimal(tx["fee"], "fee") for tx in transactions), Decimal("0"))),
    }
    return ledger


def _validate_ledger(ledger: Mapping[str, Any]) -> None:
    if not isinstance(ledger, Mapping):
        raise SimulationError("Ledger must be an object")
    if ledger.get("schema_version") != SCHEMA_VERSION:
        raise SimulationError("Unsupported ledger schema version")
    if ledger.get("simulation_type") != "PAPER_ONLY":
        raise SimulationError("Ledger is not marked PAPER_ONLY")
    if not isinstance(ledger.get("holdings"), dict):
        raise SimulationError("Ledger holdings are invalid")
    if not isinstance(ledger.get("transactions"), list) or not isinstance(ledger.get("snapshots"), list):
        raise SimulationError("Ledger transaction or snapshot history is invalid")
    if _decimal(ledger.get("cash"), "ledger.cash") < 0:
        raise SimulationError("Ledger cash cannot be negative")


def execute_order(
    ledger: dict[str, Any],
    ticker: str,
    side: str,
    quantity: Any,
    quote: Mapping[str, Any],
    trade_date: str,
    reason: str,
    fee_bps: Any = 0,
    slippage_bps: Any = 0,
) -> dict[str, Any]:
    """Execute a simulated BUY or SELL against a validated quote."""
    _validate_ledger(ledger)
    symbol = str(ticker).strip().upper()
    if not symbol or len(symbol) > 15 or not symbol.replace(".", "").isalnum():
        raise SimulationError("Invalid ticker")
    action = str(side).strip().upper()
    if action not in {"BUY", "SELL"}:
        raise SimulationError("Order side must be BUY or SELL")
    qty = _shares(_decimal(quantity, "quantity"))
    if qty <= 0:
        raise SimulationError("Order quantity must be greater than zero")
    if not isinstance(reason, str) or not reason.strip():
        raise SimulationError("A non-empty trade reason is required")
    normalized_quote = validate_quote(quote, trade_date)
    reference_price = _decimal(normalized_quote["price"], "quote.price")
    fee_rate = _decimal(fee_bps, "fee_bps") / Decimal("10000")
    slip_rate = _decimal(slippage_bps, "slippage_bps") / Decimal("10000")
    if fee_rate < 0 or slip_rate < 0 or fee_rate >= 1 or slip_rate >= 1:
        raise SimulationError("Fee and slippage basis points are out of range")

    # Slippage works against the simulated trader: higher BUY fill, lower SELL fill.
    multiplier = Decimal("1") + slip_rate if action == "BUY" else Decimal("1") - slip_rate
    fill_price = _price(reference_price * multiplier)
    notional = _money(qty * fill_price)
    fee = _money(notional * fee_rate)
    cash = _money(_decimal(ledger["cash"], "ledger.cash"))
    realized_pnl = Decimal("0")

    current = ledger["holdings"].get(symbol)
    if action == "BUY":
        total_debit = notional + fee
        if total_debit > cash:
            raise SimulationError("Insufficient simulated cash for BUY")
        old_qty = _decimal(current["quantity"], "holding.quantity") if current else Decimal("0")
        old_basis = _decimal(current["total_cost_basis"], "holding.total_cost_basis") if current else Decimal("0")
        new_qty = old_qty + qty
        new_basis = old_basis + total_debit
        ledger["holdings"][symbol] = {
            "quantity": float(new_qty),
            "average_cost": float(_price(new_basis / new_qty)),
            "total_cost_basis": float(_money(new_basis)),
            "market_price": float(reference_price),
            "market_value": float(_money(new_qty * reference_price)),
            "price_timestamp": normalized_quote["timestamp"],
            "price_source": normalized_quote["source"],
        }
        cash = _money(cash - total_debit)
    else:
        if not current or _decimal(current["quantity"], "holding.quantity") < qty:
            raise SimulationError("Insufficient holdings for SELL; short selling is disabled")
        old_qty = _decimal(current["quantity"], "holding.quantity")
        old_basis = _decimal(current["total_cost_basis"], "holding.total_cost_basis")
        basis_removed = old_basis * qty / old_qty
        realized_pnl = notional - fee - basis_removed
        remaining_qty = old_qty - qty
        cash = _money(cash + notional - fee)
        if remaining_qty == 0:
            del ledger["holdings"][symbol]
        else:
            remaining_basis = old_basis - basis_removed
            ledger["holdings"][symbol] = {
                "quantity": float(remaining_qty),
                "average_cost": float(_price(remaining_basis / remaining_qty)),
                "total_cost_basis": float(_money(remaining_basis)),
                "market_price": float(reference_price),
                "market_value": float(_money(remaining_qty * reference_price)),
                "price_timestamp": normalized_quote["timestamp"],
                "price_source": normalized_quote["source"],
            }

    ledger["cash"] = float(cash)
    ledger["realized_pnl"] = float(_money(_decimal(ledger.get("realized_pnl", 0), "realized_pnl") + realized_pnl))
    ledger["fees_paid"] = float(_money(_decimal(ledger.get("fees_paid", 0), "fees_paid") + fee))
    transaction = {
        "transaction_id": f"TX{len(ledger['transactions']) + 1:06d}",
        "date": _iso_date(trade_date, "trade_date"),
        "timestamp": normalized_quote["timestamp"],
        "ticker": symbol,
        "side": action,
        "quantity": float(qty),
        "reference_price": float(reference_price),
        "fill_price": float(fill_price),
        "notional": float(notional),
        "fee": float(fee),
        "slippage_bps": float(_decimal(slippage_bps, "slippage_bps")),
        "reason": reason.strip(),
        "source": normalized_quote["source"],
        "realized_pnl": float(_money(realized_pnl)),
    }
    ledger["transactions"].append(transaction)
    return transaction


def mark_to_market(
    ledger: dict[str, Any], quotes: Mapping[str, Mapping[str, Any]], valuation_date: str
) -> dict[str, Any]:
    """Update holding marks and append/replace the daily portfolio snapshot."""
    _validate_ledger(ledger)
    valuation_date = _iso_date(valuation_date, "valuation_date")
    staged: dict[str, dict[str, Any]] = {}
    for ticker in ledger["holdings"]:
        if ticker not in quotes:
            raise SimulationError(f"Missing valuation quote for {ticker}; snapshot not written")
        staged[ticker] = validate_quote(quotes[ticker], valuation_date)

    market_value = Decimal("0")
    total_cost_basis = Decimal("0")
    for ticker, quote in staged.items():
        holding = ledger["holdings"][ticker]
        qty = _decimal(holding["quantity"], f"{ticker}.quantity")
        price_value = _decimal(quote["price"], f"{ticker}.price")
        value = _money(qty * price_value)
        holding.update({
            "market_price": float(price_value),
            "market_value": float(value),
            "price_timestamp": quote["timestamp"],
            "price_source": quote["source"],
        })
        market_value += value
        total_cost_basis += _decimal(holding["total_cost_basis"], f"{ticker}.cost_basis")

    cash = _decimal(ledger["cash"], "ledger.cash")
    equity = _money(cash + market_value)
    initial = _decimal(ledger["initial_capital"], "initial_capital")
    unrealized = _money(market_value - total_cost_basis)
    total_pnl = _money(equity - initial)
    snapshot = {
        "date": valuation_date,
        "cash": float(_money(cash)),
        "holdings_value": float(_money(market_value)),
        "equity": float(equity),
        "cost_basis": float(_money(total_cost_basis)),
        "unrealized_pnl": float(unrealized),
        "realized_pnl": float(_money(_decimal(ledger.get("realized_pnl", 0), "realized_pnl"))),
        "total_pnl": float(total_pnl),
        "return_pct": float((total_pnl / initial * Decimal("100")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
    }
    # Idempotent daily marking: rerunning the same date replaces that day's snapshot.
    ledger["snapshots"] = [s for s in ledger["snapshots"] if s.get("date") != valuation_date]
    ledger["snapshots"].append(snapshot)
    ledger["snapshots"].sort(key=lambda item: item["date"])
    return snapshot


def save_ledger(ledger: Mapping[str, Any], filename: str) -> None:
    """Atomically persist the ledger JSON."""
    _validate_ledger(ledger)
    directory = os.path.dirname(os.path.abspath(filename))
    fd, temp_path = tempfile.mkstemp(dir=directory, suffix=".tmp", prefix=".aegis-ledger-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(ledger, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, filename)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def load_ledger(filename: str) -> dict[str, Any]:
    """Load and validate an existing simulation ledger."""
    with open(filename, "r", encoding="utf-8") as handle:
        ledger = json.load(handle)
    _validate_ledger(ledger)
    return ledger
