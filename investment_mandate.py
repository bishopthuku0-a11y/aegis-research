"""Aegis's fixed electricity and grid-infrastructure investment mandate.

This file defines the strategic investment universe. Research may investigate
companies, technologies, policies, and industries outside the portfolio, but
only the three mandate ETFs may be recommended as portfolio actions.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

MANDATE_VERSION = 1
MANDATE_NAME = "Electricity and Grid Infrastructure"
ALLOWED_TICKERS = ("XLU", "GRID", "UTES")
INITIAL_TARGET_WEIGHTS = {
    "XLU": Decimal("0.50"),
    "GRID": Decimal("0.30"),
    "UTES": Decimal("0.20"),
}

MANDATE_THESIS = (
    "Study the investment opportunity created by electricity demand growth, "
    "AI and data-centre power requirements, utility investment, transmission "
    "and distribution upgrades, smart-grid equipment, grid modernization, "
    "electrification, and related policy and financing conditions."
)


class MandateViolation(ValueError):
    """Raised when a portfolio or proposed action violates the mandate."""


def normalize_ticker(ticker: Any) -> str:
    if not isinstance(ticker, str):
        raise MandateViolation("Ticker must be a string.")
    symbol = ticker.strip().upper()
    if symbol not in ALLOWED_TICKERS:
        allowed = ", ".join(ALLOWED_TICKERS)
        raise MandateViolation(
            f"Ticker {symbol or '<empty>'!r} is outside Aegis's investment mandate. "
            f"Eligible portfolio tickers: {allowed}."
        )
    return symbol


def validate_portfolio_weights(
    portfolio: Mapping[str, Any], *, tolerance: Decimal = Decimal("0.000001")
) -> dict[str, float]:
    """Validate strategic target weights, not live ledger weights.

    The three-ticker universe is fixed, but weights may change when evidence
    justifies rebalancing. The original 50/30/20 split is the starting baseline,
    not a permanent allocation lock. Actual quantities belong in the ledger.
    """
    if not isinstance(portfolio, Mapping):
        raise MandateViolation("Portfolio target weights must be a JSON object.")

    normalized: dict[str, Decimal] = {}
    for raw_ticker, raw_weight in portfolio.items():
        ticker = normalize_ticker(raw_ticker)
        if isinstance(raw_weight, bool):
            raise MandateViolation(f"Target weight for {ticker} must be numeric.")
        try:
            weight = Decimal(str(raw_weight))
        except (InvalidOperation, TypeError, ValueError):
            raise MandateViolation(f"Target weight for {ticker} must be numeric.") from None
        if not weight.is_finite() or weight <= 0:
            raise MandateViolation(f"Target weight for {ticker} must be finite and greater than zero.")
        normalized[ticker] = weight

    expected = set(ALLOWED_TICKERS)
    actual = set(normalized)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing required tickers: {', '.join(missing)}")
        if extra:
            details.append(f"unexpected tickers: {', '.join(extra)}")
        raise MandateViolation("Portfolio does not match the fixed mandate (" + "; ".join(details) + ").")

    # Weights may evolve as research justifies rebalancing. The ticker universe
    # is fixed; the original 50/30/20 split is a baseline, not a permanent lock.
    if abs(sum(normalized.values(), Decimal("0")) - Decimal("1")) > tolerance:
        raise MandateViolation("Mandate target weights must sum to 1.0.")

    return {ticker: float(normalized[ticker]) for ticker in ALLOWED_TICKERS}


def mandate_prompt_text() -> str:
    """Return concise, model-facing mandate instructions."""
    return (
        f"Aegis mandate v{MANDATE_VERSION}: {MANDATE_NAME}.\n"
        f"Core thesis: {MANDATE_THESIS}\n"
        "The only eligible portfolio holdings and action tickers are XLU, GRID, and UTES. "
        "Do not recommend adding any other ticker to the portfolio. You may research "
        "other companies, suppliers, technologies, utilities, policies, or industries "
        "as evidence about the electricity and grid thesis, but those are research "
        "subjects only and are not eligible portfolio holdings. Do not treat the "
        "intentional thematic concentration as an automatic mandate breach. Assess "
        "correlation, underlying holdings overlap, valuation, business exposure, "
        "policy, financing, liquidity, and thesis deterioration instead."
    )
