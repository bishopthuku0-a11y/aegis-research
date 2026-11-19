"""Aegis Research daily agent.

Research only. This module never places orders and never edits
simulation_ledger.json. Portfolio decisions are restricted to XLU, GRID, UTES.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

import yfinance as yf

from investment_mandate import ALLOWED_TICKERS, validate_portfolio_weights
from research_decision import (
    RESEARCH_DECISION_SCHEMA,
    parse_research_decision,
    validate_decision,
)

MEMORY_FILE = "memory.json"
BRIEFING_FILE = "latest_briefing.md"
DECISION_FILE = "latest_research_decision.json"
MAX_MARKET_DATA_AGE_DAYS = 5
DEFAULT_MODEL = "gemini-2.5-flash"


class DataIntegrityError(RuntimeError):
    """Raised when required market data cannot be trusted."""


def _utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware.")
    return value.astimezone(dt.timezone.utc)


def load_memory(path: str | os.PathLike = MEMORY_FILE) -> dict:
    """Load and validate the fixed three-ETF portfolio memory."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"{file_path} was not found.")
    with file_path.open("r", encoding="utf-8") as handle:
        memory = json.load(handle)
    if not isinstance(memory, dict):
        raise ValueError("Memory must be a JSON object.")
    portfolio = memory.get("portfolio")
    if not isinstance(portfolio, dict):
        raise ValueError("Memory is missing a portfolio object.")
    validate_portfolio_weights(portfolio)
    memory.setdefault("past_pitches", [])
    memory.setdefault("lessons_learned", [])
    if not isinstance(memory["past_pitches"], list):
        raise ValueError("past_pitches must be a list.")
    if not isinstance(memory["lessons_learned"], list):
        raise ValueError("lessons_learned must be a list.")
    return memory


def save_json_atomic(data: Any, filename: str | os.PathLike) -> None:
    """Atomically save JSON. Research run does not call this for memory/ledger."""
    destination = Path(filename)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=str(destination.parent), prefix=f".{destination.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def get_market_data(
    ticker: str,
    now: dt.datetime | None = None,
    max_age_days: int = MAX_MARKET_DATA_AGE_DAYS,
) -> dict:
    """Fetch the latest timestamped daily close; reject missing/stale data."""
    symbol = str(ticker).strip().upper()
    if symbol not in ALLOWED_TICKERS:
        raise DataIntegrityError(
            f"{symbol or 'EMPTY TICKER'} is outside the approved portfolio universe."
        )
    current_time = _utc(now or dt.datetime.now(dt.timezone.utc))

    try:
        history = yf.Ticker(symbol).history(
            period="10d", interval="1d", auto_adjust=False, actions=False
        )
    except Exception as exc:
        raise DataIntegrityError(f"Could not retrieve {symbol} history: {exc}") from exc

    if history is None or getattr(history, "empty", True):
        raise DataIntegrityError(f"No daily price history returned for {symbol}.")
    if "Close" not in history.columns:
        raise DataIntegrityError(f"Daily close is missing for {symbol}.")

    try:
        rows = history.dropna(subset=["Close"])
        if rows.empty:
            raise DataIntegrityError(f"No valid daily close returned for {symbol}.")
        timestamp = rows.index[-1]
        if getattr(timestamp, "tzinfo", None) is None:
            raise DataIntegrityError(f"{symbol} daily timestamp has no timezone.")
        price_as_of = timestamp.to_pydatetime().astimezone(dt.timezone.utc)
        age = current_time - price_as_of
        if age.total_seconds() < -86400:
            raise DataIntegrityError(f"{symbol} price timestamp is in the future.")
        if age > dt.timedelta(days=max_age_days):
            raise DataIntegrityError(f"{symbol} daily close is stale ({age.days} days old).")
        price = float(rows["Close"].iloc[-1])
    except DataIntegrityError:
        raise
    except Exception as exc:
        raise DataIntegrityError(f"Could not validate {symbol} daily close: {exc}") from exc

    if not math.isfinite(price) or price <= 0:
        raise DataIntegrityError(f"{symbol} close is not a positive finite number.")

    return {
        "ticker": symbol,
        "price": round(price, 6),
        "price_as_of": price_as_of.isoformat(),
        "price_type": "UNADJUSTED_DAILY_CLOSE",
        "source": "Yahoo Finance via yfinance",
    }


def collect_portfolio_snapshot(
    portfolio: dict,
    now: dt.datetime | None = None,
) -> dict:
    """Require valid, recent daily closes for all three portfolio ETFs."""
    validate_portfolio_weights(portfolio)
    snapshot = {}
    errors = []
    for ticker in ALLOWED_TICKERS:
        try:
            snapshot[ticker] = get_market_data(ticker, now=now)
        except Exception as exc:
            errors.append(f"{ticker}: {exc}")
    if errors:
        raise DataIntegrityError(
            "Portfolio snapshot incomplete; AI analysis blocked. " + " | ".join(errors)
        )
    return snapshot


def _get_client(client=None):
    if client is not None:
        return client
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing from environment variables.")
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError("google-genai is not installed.") from exc
    return genai.Client(api_key=api_key)


def ask_aegis(prompt_text: str, client=None, model: str = DEFAULT_MODEL) -> str:
    """Ask Gemini for one schema-constrained research decision."""
    active_client = _get_client(client)
    response = active_client.models.generate_content(
        model=model,
        contents=prompt_text,
        config={
            "response_mime_type": "application/json",
            "response_schema": RESEARCH_DECISION_SCHEMA,
        },
    )
    response_text = getattr(response, "text", None)
    if not response_text:
        raise RuntimeError("Gemini returned an empty response.")
    return response_text


def build_prompt(memory: dict, snapshot: dict, today: dt.date) -> str:
    from investment_mandate import mandate_prompt_text

    return f"""
You are Aegis Research, a critical institutional investment research analyst.

{mandate_prompt_text()}

DATE: {today.isoformat()}

PORTFOLIO WEIGHTS:
{json.dumps(memory["portfolio"], indent=2)}

VERIFIED MARKET SNAPSHOT (daily closes, not live quotes):
{json.dumps(snapshot, indent=2)}

PAST RESEARCH CALLS (not executed trades):
{json.dumps(memory.get("past_pitches", [])[-10:], indent=2)}

HISTORICAL LESSONS (may be incomplete or contradictory; assess critically):
{json.dumps(memory.get("lessons_learned", []), indent=2)}

Return exactly one JSON object matching the supplied decision schema.
Use only the supplied snapshot as current price evidence. No news articles,
fundamentals, or external research were supplied; do not claim to have reviewed
them or invent facts. Outside securities may be discussed as industry context
only and must never be proposed as portfolio holdings.

Choose BUY, TRIM, or HOLD for XLU, GRID, or UTES only when the supplied evidence
supports it. If evidence is insufficient, return NO_DECISION with ticker null,
empty evidence, and clearly explain what information is missing. Confidence
is not proof. Do not create a lesson unless it is specific and supported.
""".strip()


def _failure_report(reason: str, run_time: dt.datetime) -> str:
    return (
        "# AEGIS RESEARCH // DATA FAILURE\n\n"
        f"Run time: {_utc(run_time).isoformat()}\n\n"
        "**NO DECISION.** A required check failed, so AI analysis was not trusted.\n\n"
        f"Reason: {reason}\n"
    )


def run(
    memory_path: str | os.PathLike | None = None,
    briefing_path: str | os.PathLike | None = None,
    decision_path: str | os.PathLike | None = None,
    now: dt.datetime | None = None,
    client=None,
) -> int:
    """Run one research cycle. Return 0 on success, 2 on fail-closed failure."""
    memory_file = Path(memory_path or MEMORY_FILE)
    briefing_file = Path(briefing_path or BRIEFING_FILE)
    decision_file = Path(decision_path or DECISION_FILE)
    run_time = _utc(now or dt.datetime.now(dt.timezone.utc))

    try:
        memory = load_memory(memory_file)
        snapshot = collect_portfolio_snapshot(memory["portfolio"], now=run_time)
        prompt = build_prompt(memory, snapshot, run_time.date())
        raw_result = ask_aegis(prompt, client=client)
        parsed = parse_research_decision(raw_result)
        parsed_payload = parsed.to_dict() if hasattr(parsed, "to_dict") else parsed
        validated = validate_decision(parsed_payload)
        decision = validated.to_dict() if hasattr(validated, "to_dict") else dict(validated)

        # Persist only the validated research decision, in its own file.
        save_json_atomic(decision, decision_file)

        snapshot_lines = [
            f"- **{ticker}:** ${item['price']:.2f} "
            f"(daily close as of {item['price_as_of']})"
            for ticker, item in snapshot.items()
        ]
        report = (
            "# AEGIS RESEARCH // DAILY BRIEFING\n\n"
            f"Run time: {run_time.isoformat()}\n\n"
            "## Verified market snapshot\n\n"
            + "\n".join(snapshot_lines)
            + "\n\n## Validated research decision\n\n"
            + "```json\n"
            + json.dumps(decision, indent=2, ensure_ascii=False)
            + "\n```\n\n"
            + "**Execution status:** Research only. No paper order was placed.\n"
        )
        briefing_file.parent.mkdir(parents=True, exist_ok=True)
        briefing_file.write_text(report, encoding="utf-8")
        print("Aegis research completed. No paper trade was executed.")
        return 0

    except Exception as exc:
        briefing_file.parent.mkdir(parents=True, exist_ok=True)
        briefing_file.write_text(_failure_report(str(exc), run_time), encoding="utf-8")
        print(f"AEGIS DATA FAILURE: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
