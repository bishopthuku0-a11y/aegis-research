"""Aegis Research daily agent.

Research calls are observations, not simulated executions. This module deliberately
fails closed: incomplete or stale portfolio prices prevent AI recommendations.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

import yfinance as yf
from google import genai

MEMORY_FILE = Path(os.environ.get("AEGIS_MEMORY_FILE", "memory.json"))
BRIEFING_FILE = Path(os.environ.get("AEGIS_BRIEFING_FILE", "latest_briefing.md"))
MAX_PAST_PITCHES = 30
MAX_LESSONS = 12
MAX_PRICE_AGE_DAYS = 5
FALLBACK_TICKER = "GRID"
PREFERRED_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
)
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")
VALID_ACTIONS = {"BUY", "TRIM", "HOLD"}


class DataIntegrityError(RuntimeError):
    """Raised when required market data is missing, invalid, or stale."""


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def load_memory(filename: Path | None = None) -> dict[str, Any]:
    filename = Path(filename) if filename is not None else MEMORY_FILE
    if not filename.exists():
        raise FileNotFoundError(f"{filename} was not found. Create it before running Aegis.")
    with filename.open("r", encoding="utf-8") as handle:
        memory = json.load(handle)
    if not isinstance(memory, dict):
        raise ValueError("memory.json must contain a JSON object.")
    portfolio = memory.get("portfolio")
    if not isinstance(portfolio, dict) or not portfolio:
        raise ValueError("Portfolio must be a non-empty JSON object.")
    for ticker, weight in portfolio.items():
        if not isinstance(ticker, str) or not TICKER_PATTERN.fullmatch(ticker.upper()):
            raise ValueError(f"Invalid portfolio ticker: {ticker!r}")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight < 0:
            raise ValueError(f"Invalid portfolio weight for {ticker}: {weight!r}")
    memory.setdefault("past_pitches", [])
    memory.setdefault("lessons_learned", [])
    if not isinstance(memory["past_pitches"], list):
        raise ValueError("past_pitches must be a JSON list.")
    if not isinstance(memory["lessons_learned"], list):
        raise ValueError("lessons_learned must be a JSON list.")
    return memory


def save_json_atomic(data: dict[str, Any], filename: Path) -> None:
    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=str(filename.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, filename)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def write_briefing(content: str, filename: Path | None = None) -> None:
    filename = Path(filename) if filename is not None else BRIEFING_FILE
    filename.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=str(filename.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, filename)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def _to_utc_timestamp(value: Any) -> dt.datetime:
    stamp = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    if not isinstance(stamp, dt.datetime):
        stamp = dt.datetime.combine(stamp, dt.time.min)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    return stamp.astimezone(dt.timezone.utc)


def get_market_data(ticker: str, *, now: dt.datetime | None = None,
                    max_age_days: int = MAX_PRICE_AGE_DAYS) -> dict[str, Any]:
    """Fetch the latest daily close and its prior close; never invent a price."""
    ticker = ticker.upper().strip()
    if not TICKER_PATTERN.fullmatch(ticker):
        raise DataIntegrityError(f"Invalid ticker symbol: {ticker!r}")
    now = now or utc_now()
    try:
        history = yf.Ticker(ticker).history(period="10d", interval="1d", auto_adjust=False)
    except Exception as exc:
        raise DataIntegrityError(f"{ticker}: market-data request failed: {exc}") from exc
    if history is None or history.empty or "Close" not in history:
        raise DataIntegrityError(f"{ticker}: no daily closing-price history returned.")
    closes = history["Close"].dropna()
    closes = closes[closes.astype(float) > 0]
    if len(closes) < 2:
        raise DataIntegrityError(f"{ticker}: fewer than two valid daily closes returned.")
    latest_stamp = _to_utc_timestamp(closes.index[-1])
    age = now.astimezone(dt.timezone.utc) - latest_stamp
    if age < dt.timedelta(days=-1):
        raise DataIntegrityError(f"{ticker}: returned price timestamp is in the future.")
    if age > dt.timedelta(days=max_age_days):
        raise DataIntegrityError(
            f"{ticker}: latest daily close is stale ({latest_stamp.date().isoformat()}, "
            f"{age.days} days old; maximum {max_age_days})."
        )
    price = float(closes.iloc[-1])
    previous_close = float(closes.iloc[-2])
    if not (price > 0 and previous_close > 0):
        raise DataIntegrityError(f"{ticker}: non-positive closing price returned.")
    change_pct = ((price - previous_close) / previous_close) * 100
    return {
        "ticker": ticker,
        "price": round(price, 4),
        "previous_close": round(previous_close, 4),
        "change_pct": round(change_pct, 4),
        "price_as_of": latest_stamp.isoformat(),
        "price_age_days": max(0, age.days),
        "price_source": "Yahoo Finance daily historical Close",
    }


def get_news_headlines(ticker: str, limit: int = 3) -> list[dict[str, Any]]:
    """Fetch headline metadata independently; headlines are not article evidence."""
    try:
        articles = yf.Ticker(ticker).news or []
    except Exception as exc:
        print(f"News collection warning for {ticker}: {exc}")
        return []
    result: list[dict[str, Any]] = []
    for article in articles[:limit]:
        content = article.get("content") if isinstance(article, dict) else None
        content = content if isinstance(content, dict) else {}
        title = content.get("title") or article.get("title")
        if not title:
            continue
        provider = content.get("provider") or article.get("publisher") or {}
        if isinstance(provider, dict):
            publisher = provider.get("displayName") or provider.get("name")
        else:
            publisher = str(provider) if provider else None
        canonical = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        if isinstance(canonical, dict):
            url = canonical.get("url")
        else:
            url = canonical
        pub_date = content.get("pubDate") or article.get("providerPublishTime")
        if isinstance(pub_date, (int, float)):
            pub_date = dt.datetime.fromtimestamp(pub_date, dt.timezone.utc).isoformat()
        result.append({
            "ticker": ticker,
            "title": str(title).strip(),
            "publisher": publisher,
            "published_at": pub_date,
            "url": url,
            "evidence_type": "headline_only",
        })
    return result


def collect_portfolio_snapshot(portfolio: dict[str, Any], *, now: dt.datetime | None = None
                               ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    snapshot: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    headlines: list[dict[str, Any]] = []
    for raw_ticker in portfolio:
        ticker = raw_ticker.upper()
        try:
            snapshot[ticker] = get_market_data(ticker, now=now)
        except DataIntegrityError as exc:
            failures.append(str(exc))
            continue
        # News is deliberately independent: a news outage does not invalidate a valid price.
        headlines.extend(get_news_headlines(ticker))
    if failures:
        missing = sorted(set(portfolio) - set(snapshot))
        details = "\n".join(f"- {failure}" for failure in failures)
        raise DataIntegrityError(
            "Required portfolio price data failed validation. Missing/invalid tickers: "
            f"{', '.join(missing)}\n{details}"
        )
    return snapshot, headlines


def get_available_models(client: Any) -> list[str]:
    try:
        available = []
        for model in client.models.list():
            name = getattr(model, "name", "")
            methods = getattr(model, "supported_actions", None)
            if not name:
                continue
            clean = name.replace("models/", "")
            if methods and "generateContent" not in methods:
                continue
            if "flash" in clean.lower():
                available.append(clean)
        return available
    except Exception as exc:
        print(f"Model discovery warning: {exc}")
        return []


def ask_aegis(prompt_text: str, client: Any) -> str:
    candidates = get_available_models(client)
    ordered = [model for model in PREFERRED_MODELS if model in candidates]
    ordered.extend(model for model in candidates if model not in ordered)
    if not ordered:
        ordered = [PREFERRED_MODELS[0]]
    for model_name in ordered[:5]:
        for attempt in range(2):
            try:
                print(f"Trying Gemini model: {model_name}")
                response = client.models.generate_content(model=model_name, contents=prompt_text)
                text = getattr(response, "text", None)
                if text and text.strip():
                    return text.strip()
                print(f"{model_name} returned an empty response.")
            except Exception as exc:
                print(f"Attempt {attempt + 1} failed on {model_name}: {exc}")
                if attempt == 0:
                    time.sleep(2)
    raise RuntimeError("All available Gemini models failed.")


def build_prompt(portfolio: dict[str, Any], snapshot: dict[str, Any],
                 headlines: list[dict[str, Any]], pitches: list[dict[str, Any]],
                 lessons: list[str], now: dt.datetime) -> str:
    return f"""You are Aegis Research, a skeptical investment research analyst.

IMPORTANT EVIDENCE RULES:
- Use ONLY the supplied market snapshot and headline metadata as current inputs.
- Prices are daily closing prices, not necessarily live intraday quotes. Respect each price_as_of timestamp.
- Headlines are headline-only metadata. Do not claim to have read the underlying articles.
- Do not invent prices, facts, sources, earnings, financial metrics, or article contents.
- Separate sourced facts, interpretation, and uncertainty.
- The portfolio weights are target allocations, not proof of owned shares or historical purchases.
- Past research calls are not executed trades and are not realized portfolio performance.
- Aegis may propose a new ticker, but it must explain what independent evidence is still needed.
- If evidence is insufficient for an action, return HOLD and explain the limitation.

AS-OF (UTC): {now.isoformat()}
PORTFOLIO TARGET WEIGHTS: {json.dumps(portfolio, indent=2)}
VERIFIED MARKET SNAPSHOT: {json.dumps(snapshot, indent=2)}
HEADLINE METADATA (NOT FULL ARTICLES): {json.dumps(headlines, indent=2)}
PRIOR RESEARCH CALLS (NOT EXECUTED TRADES): {json.dumps(pitches[-10:], indent=2)}
LESSONS: {json.dumps(lessons, indent=2)}

Produce a concise but substantive briefing with:
1. Data quality and as-of statement.
2. Portfolio concentration and ticker-by-ticker pulse.
3. Bull and bear cases, clearly distinguishing evidence from inference.
4. One best-supported research action, or HOLD if evidence is insufficient.
5. Risks, missing evidence, and one proposed lesson (only if genuinely supported).

At the end output exactly these machine-readable lines:
PITCH_ACTION: <HOLD, BUY, or TRIM>
PITCH_TICKER: <ticker symbol>
NEW_LESSON: <one concise rule, or NONE>
"""


def parse_model_output(report: str) -> tuple[str, str, str, str]:
    fields: dict[str, str] = {}
    body: list[str] = []
    for line in report.splitlines():
        stripped = line.strip()
        matched = False
        for key in ("PITCH_ACTION", "PITCH_TICKER", "NEW_LESSON"):
            prefix = key + ":"
            if stripped.startswith(prefix):
                fields[key] = stripped.split(":", 1)[1].strip()
                matched = True
                break
        if not matched:
            body.append(line)
    action = fields.get("PITCH_ACTION", "").upper()
    ticker = fields.get("PITCH_TICKER", "").upper().replace("$", "").strip()
    lesson = fields.get("NEW_LESSON", "").strip().lstrip("*:- ")
    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid or missing PITCH_ACTION: {action!r}")
    if not TICKER_PATTERN.fullmatch(ticker):
        raise ValueError(f"Invalid or missing PITCH_TICKER: {ticker!r}")
    if lesson.upper() == "NONE":
        lesson = ""
    if len(lesson) > 300:
        raise ValueError("NEW_LESSON exceeds 300 characters.")
    return action, ticker, lesson, "\n".join(body).strip()


def data_failure_briefing(message: str, now: dt.datetime) -> str:
    return (
        f"# 🛡️ AEGIS RESEARCH // DAILY BRIEFING ({now:%Y-%m-%d %H:%M UTC})\n\n"
        "## <span style=\"color:#c00\">DATA FAILURE — NO INVESTMENT DECISION</span>\n\n"
        "Required portfolio market data did not pass validation. Gemini analysis was not run, "
        "no recommendation was generated, and research memory was not changed.\n\n"
        f"{message}\n"
    )


def run() -> int:
    now = utc_now()
    memory = load_memory()
    try:
        snapshot, headlines = collect_portfolio_snapshot(memory["portfolio"], now=now)
    except DataIntegrityError as exc:
        message = str(exc)
        write_briefing(data_failure_briefing(message, now))
        print(f"DATA FAILURE: {message}")
        return 2

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        message = "GEMINI_API_KEY is missing. Market data passed, but AI analysis was not run."
        write_briefing(data_failure_briefing(message, now))
        print(message)
        return 2

    client = genai.Client(api_key=api_key)
    prompt = build_prompt(
        memory["portfolio"], snapshot, headlines,
        memory["past_pitches"], memory["lessons_learned"], now,
    )
    print("Generating Aegis Research briefing...")
    try:
        raw_report = ask_aegis(prompt, client)
        action, ticker, lesson, report_body = parse_model_output(raw_report)
        # Validate the proposed symbol against independent market data before recording it.
        proposed_quote = snapshot.get(ticker)
        if proposed_quote is None:
            proposed_quote = get_market_data(ticker, now=now)
    except Exception as exc:
        message = f"NO DECISION — AI output or proposed ticker failed validation: {exc}"
        write_briefing(data_failure_briefing(message, now))
        print(message)
        return 2

    # Preserve the existing memory schema while making the record explicitly a research call.
    # `entry_price` is retained for backward compatibility with the current dashboard.
    memory["past_pitches"].append({
        "date": now.strftime("%Y-%m-%d"),
        "action": action,
        "ticker": ticker,
        "entry_price": proposed_quote["price"],
        "reference_price": proposed_quote["price"],
        "price_as_of": proposed_quote["price_as_of"],
        "record_type": "research_call_not_execution",
    })
    memory["past_pitches"] = memory["past_pitches"][-MAX_PAST_PITCHES:]

    if lesson:
        normalized = lesson.casefold()
        existing = {str(item).strip().casefold() for item in memory["lessons_learned"]}
        if normalized not in existing:
            memory["lessons_learned"].append(lesson)
            memory["lessons_learned"] = memory["lessons_learned"][-MAX_LESSONS:]

    # Only commit memory after all validation and successful report generation.
    save_json_atomic(memory, MEMORY_FILE)
    timestamp = now.strftime("%Y-%m-%d %H:%M UTC")
    output = (
        f"# 🛡️ Aegis Research Daily Briefing ({timestamp})\n\n"
        f"**Data as-of:** daily closing prices; see individual timestamps in the research snapshot.\n\n"
        f"**Important:** this is a research call, not an executed simulated trade.\n\n"
        f"{report_body}\n\n"
        f"---\n\nPITCH_ACTION: {action}\nPITCH_TICKER: {ticker}\n"
        f"NEW_LESSON: {lesson or 'NONE'}\n"
    )
    write_briefing(output)
    print("Memory and daily briefing saved successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
