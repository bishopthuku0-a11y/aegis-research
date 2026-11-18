
import os
import json
import time
import datetime
import tempfile

import yfinance as yf
from google import genai


# ============================================================
# AEGIS RESEARCH - CONFIGURATION
# ============================================================

API_KEY = os.environ.get("GEMINI_API_KEY")

if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing from environment variables.")

client = genai.Client(api_key=API_KEY)

MEMORY_FILE = "memory.json"
BRIEFING_FILE = "latest_briefing.md"

MAX_PAST_PITCHES = 30
MAX_LESSONS = 12

FALLBACK_TICKER = "GRID"


# ============================================================
# GEMINI MODEL SELECTION
# ============================================================

def get_available_models():
    """Retrieve usable Gemini model names."""
    try:
        models = client.models.list()
        available = []

        for model in models:
            name = getattr(model, "name", "")
            supported_methods = getattr(
                model, "supported_actions", None
            )

            if not name:
                continue

            clean_name = name.replace("models/", "")

            if supported_methods:
                if "generateContent" not in supported_methods:
                    continue

            if "flash" in clean_name.lower():
                available.append(clean_name)

        return available

    except Exception as e:
        print(f"Model discovery warning: {e}")
        return []


def ask_aegis(prompt_text):
    """Generate the Aegis investment report using available Gemini models."""

    candidates = get_available_models()

    # Prefer stable Flash models when available.
    preferred = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.5-flash-lite",
    ]

    ordered_models = []

    for model in preferred:
        if model in candidates and model not in ordered_models:
            ordered_models.append(model)

    for model in candidates:
        if model not in ordered_models:
            ordered_models.append(model)

    # Last-resort model if model discovery fails.
    if not ordered_models:
        ordered_models = ["gemini-2.5-flash"]

    for model_name in ordered_models[:5]:
        for attempt in range(2):
            try:
                print(f"Trying Gemini model: {model_name}")

                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt_text,
                )

                if response.text:
                    print(f"Successfully generated report using {model_name}")
                    return response.text

                print(f"{model_name} returned an empty response.")

            except Exception as e:
                print(
                    f"Attempt {attempt + 1} failed on "
                    f"{model_name}: {e}"
                )
                time.sleep(3)

    raise RuntimeError("All available Gemini models failed.")


# ============================================================
# MEMORY MANAGEMENT
# ============================================================

def load_memory():
    """Load memory safely and validate the expected structure."""

    if not os.path.exists(MEMORY_FILE):
        raise FileNotFoundError(
            f"{MEMORY_FILE} was not found. "
            "Create it before running Aegis."
        )

    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        memory = json.load(f)

    if not isinstance(memory, dict):
        raise ValueError("memory.json must contain a JSON object.")

    if "portfolio" not in memory:
        raise ValueError("memory.json is missing the portfolio section.")

    if not isinstance(memory["portfolio"], dict):
        raise ValueError("Portfolio must be a JSON object.")

    memory.setdefault("past_pitches", [])
    memory.setdefault("lessons_learned", [])

    if not isinstance(memory["past_pitches"], list):
        raise ValueError("past_pitches must be a JSON list.")

    if not isinstance(memory["lessons_learned"], list):
        raise ValueError("lessons_learned must be a JSON list.")

    return memory


def save_json_atomic(data, filename):
    """Write JSON safely without leaving a partially-written memory file."""

    directory = os.path.dirname(os.path.abspath(filename))

    fd, temp_path = tempfile.mkstemp(
        dir=directory,
        suffix=".tmp",
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_path, filename)

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


# ============================================================
# MARKET DATA
# ============================================================

def get_market_data(ticker):
    """Fetch price and previous close with basic validation."""

    try:
        stock = yf.Ticker(ticker)
        info = stock.fast_info

        price = info.get("last_price")
        previous_close = info.get("previous_close")

        if price is None or previous_close is None:
            raise ValueError("Price data unavailable.")

        price = float(price)
        previous_close = float(previous_close)

        if price <= 0 or previous_close <= 0:
            raise ValueError("Invalid price received.")

        change_pct = (
            (price - previous_close) / previous_close
        ) * 100

        return {
            "price": round(price, 2),
            "previous_close": round(previous_close, 2),
            "change_pct": round(change_pct, 2),
            "news": stock.news or [],
        }

    except Exception as e:
        print(f"Market data error for {ticker}: {e}")
        return None


def extract_headlines(ticker, articles):
    """Extract headlines from different yfinance news formats."""

    headlines = []

    for article in articles[:3]:
        title = None

        content = article.get("content", {})

        if isinstance(content, dict):
            title = content.get("title")

        if not title:
            title = article.get("title")

        if title:
            headlines.append(f"[{ticker}] {title}")

    return headlines


# ============================================================
# LOAD MEMORY
# ============================================================

memory = load_memory()

portfolio = memory["portfolio"]
past_pitches = memory["past_pitches"]
lessons_learned = memory["lessons_learned"]

if not portfolio:
    raise ValueError("Your portfolio is empty in memory.json.")


# ============================================================
# FETCH PORTFOLIO PRICES AND NEWS
# ============================================================

market_snapshot = {}
current_prices = {}
live_headlines = []

for ticker in portfolio.keys():

    print(f"Fetching {ticker}...")

    market_data = get_market_data(ticker)

    if market_data is None:
        market_snapshot[ticker] = "Price unavailable"
        continue

    price = market_data["price"]
    change_pct = market_data["change_pct"]

    current_prices[ticker] = price

    market_snapshot[ticker] = (
        f"${price:.2f} ({change_pct:+.2f}%)"
    )

    live_headlines.extend(
        extract_headlines(
            ticker,
            market_data["news"],
        )
    )


# ============================================================
# GRADE PAST INVESTMENT CALLS
# ============================================================

scoreboard = []

for pitch in past_pitches[-10:]:

    p_ticker = pitch.get("ticker", FALLBACK_TICKER)
    entry_price = pitch.get("entry_price")

    try:

        latest_price = current_prices.get(p_ticker)

        if latest_price is None:
            market_data = get_market_data(p_ticker)

            if market_data is None:
                continue

            latest_price = market_data["price"]

        if entry_price is None:
            continue

        entry_price = float(entry_price)

        if entry_price <= 0:
            continue

        performance_pct = (
            (latest_price - entry_price) / entry_price
        ) * 100

        pitch["latest_price"] = round(latest_price, 2)
        pitch["return_pct"] = round(performance_pct, 2)

        scoreboard.append(
            f"{pitch.get('date', 'Unknown date')} | "
            f"Call: {pitch.get('action', 'UNKNOWN')} "
            f"{p_ticker} @ ${entry_price:.2f} -> "
            f"Now ${latest_price:.2f} "
            f"({performance_pct:+.2f}%)"
        )

    except Exception as e:
        print(f"Pitch grading warning: {e}")


# ============================================================
# DATE AND WEEKLY REVIEW
# ============================================================

today_dt = datetime.datetime.now(datetime.timezone.utc)

is_friday = today_dt.weekday() == 4

pruning_instruction = ""

if is_friday:

    pruning_instruction = """
TODAY IS FRIDAY - WEEKLY STRATEGY REVIEW.

Review all Past Lessons Learned alongside the Track Record.

Identify:
- Duplicate lessons.
- Rules that helped generate better calls.
- Rules that repeatedly led to poor calls.
- Rules that are outdated or contradicted by evidence.

Produce a refined, ranked list of your TOP 8 investment rules.

Do not blindly delete a rule because of one losing trade.
Consider sample size, market conditions, and whether the rule
was followed correctly.
"""


# ============================================================
# AEGIS INVESTMENT ANALYSIS
# ============================================================

prompt = f"""
You are Aegis Research, an independent, critical institutional
investment analyst.

Your role is to evaluate evidence, challenge assumptions,
identify risks, and avoid emotional or impulsive investing.

CURRENT PORTFOLIO:
{json.dumps(portfolio, indent=2)}

CURRENT MARKET PRICES:
{json.dumps(market_snapshot, indent=2)}

LIVE MARKET HEADLINES:
{json.dumps(live_headlines, indent=2)}

REAL-WORLD TRACK RECORD:
{json.dumps(scoreboard, indent=2) if scoreboard else "No past calls graded yet."}

PAST LESSONS LEARNED:
{json.dumps(lessons_learned, indent=2)}

{pruning_instruction}

ANALYSIS REQUIREMENTS:

1. SELF-AUDIT
Review previous recommendations.
Identify what worked, what failed, and whether the
original reasoning was correct.
Do not confuse a profitable outcome with a good decision
or a losing outcome with a bad decision.

2. PORTFOLIO PULSE
Analyze XLU, GRID, and UTES.
Discuss price action, portfolio concentration, sector exposure,
potential risks, and the implications of the available news.

3. BULL VS BEAR DEBATE
Present the strongest bullish case.
Present the strongest bearish case.
Challenge both sides.
Do not invent news or facts.

4. PROACTIVE INVESTMENT PITCH
Recommend exactly ONE action:

BUY <TICKER>
TRIM <TICKER>
HOLD <TICKER>

Only recommend an action when the evidence supports it.
Otherwise choose HOLD.

Do not invent live prices, financial data, or news.
If market data is unavailable, clearly state that it is unavailable.

Do not claim to have reviewed an article when only its headline
was supplied.

Do not present this report as guaranteed financial advice.

REPORT FORMAT:

# 🛡️ AEGIS RESEARCH // DAILY BRIEFING

## Self-Audit & Track Record

## Portfolio Pulse

## Bull vs Bear Debate

## Proactive Investment Pitch

## Lessons & Strategy Update

At the end, output exactly these three machine-readable lines.
Do not place them inside a code block.

PITCH_ACTION: <HOLD, BUY, or TRIM>
PITCH_TICKER: <valid ticker>
NEW_LESSON: <one concise investment rule>
"""


# ============================================================
# GENERATE REPORT
# ============================================================

print("Generating Aegis Research briefing...")

report = ask_aegis(prompt)


# ============================================================
# PARSE MACHINE-READABLE OUTPUT
# ============================================================

clean_lines = []

pitch_action = "HOLD"
pitch_ticker = FALLBACK_TICKER
new_lesson = ""

for line in report.splitlines():

    line = line.strip()

    if line.startswith("PITCH_ACTION:"):

        # FIX: split() returns a list.
        # [1] extracts the text after the colon.
        pitch_action = (
            line.split(":", 1)[1].strip().upper()
        )

    elif line.startswith("PITCH_TICKER:"):

        pitch_ticker = (
            line.split(":", 1)[1]
            .strip()
            .upper()
            .replace("$", "")
        )

    elif line.startswith("NEW_LESSON:"):

        new_lesson = (
            line.split(":", 1)[1]
            .strip()
            .lstrip("*:- ")
        )

    else:

        clean_lines.append(line)


# ============================================================
# VALIDATE AI OUTPUT
# ============================================================

valid_actions = {"HOLD", "BUY", "TRIM"}

if pitch_action not in valid_actions:
    print(f"Invalid action received: {pitch_action}")
    pitch_action = "HOLD"

if not pitch_ticker or len(pitch_ticker) > 15:
    print("Invalid ticker received. Using GRID.")
    pitch_ticker = FALLBACK_TICKER

clean_report = "\n".join(clean_lines).strip()


# ============================================================
# RECORD TODAY'S INVESTMENT CALL
# ============================================================

try:

    tracked_price = current_prices.get(pitch_ticker)

    if tracked_price is None:
        market_data = get_market_data(pitch_ticker)

        if market_data is not None:
            tracked_price = market_data["price"]

    if tracked_price is not None:

        memory["past_pitches"].append({
            "date": today_dt.strftime("%Y-%m-%d"),
            "action": pitch_action,
            "ticker": pitch_ticker,
            "entry_price": round(tracked_price, 2),
        })

        memory["past_pitches"] = (
            memory["past_pitches"][-MAX_PAST_PITCHES:]
        )

    else:
        print(
            f"Warning: Unable to record entry price "
            f"for {pitch_ticker}."
        )

except Exception as e:
    print(f"Pitch logging error: {e}")


# ============================================================
# UPDATE LESSONS LEARNED
# ============================================================

if new_lesson:

    memory["lessons_learned"].append(new_lesson)

    memory["lessons_learned"] = (
        memory["lessons_learned"][-MAX_LESSONS:]
    )


# ============================================================
# SAVE PERMANENT MEMORY
# ============================================================

save_json_atomic(memory, MEMORY_FILE)

print("Memory successfully updated.")


# ============================================================
# SAVE DAILY BRIEFING
# ============================================================

today_str = today_dt.strftime("%Y-%m-%d %H:%M UTC")

briefing_content = (
    f"# 🛡️ Aegis Research Daily Briefing "
    f"({today_str})\n\n"
    f"{clean_report}\n"
)

with open(BRIEFING_FILE, "w", encoding="utf-8") as f:
    f.write(briefing_content)

print("Daily briefing saved successfully.")
print("Aegis Research run completed.")
