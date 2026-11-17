import os
import json
import datetime
import yfinance as yf
from google import genai

client = genai.Client(api_key=os.environ["AQ.Ab8RN6IeMe-QeuwGGiF8oW9QxRakqA0mfIyJnyZuHDt18SUp8A"])

with open("memory.json", "r") as f:
    memory = json.load(f)

if "past_pitches" not in memory:
    memory["past_pitches"] = []

# 1. Fetch Live Prices & Today's Financial Headlines
market_snapshot = {}
current_prices = {}
live_headlines = []

for ticker in memory["portfolio"].keys():
    t = yf.Ticker(ticker)
    price = float(t.fast_info["last_price"])
    prev_close = float(t.fast_info["previous_close"])
    change_pct = ((price - prev_close) / prev_close) * 100
    current_prices[ticker] = round(price, 2)
    market_snapshot[ticker] = f"${price:.2f} ({change_pct:+.2f}%)"
    for article in (t.news or [])[:3]:
        title = article.get("content", {}).get("title") or article.get("title")
        if title:
            live_headlines.append(f"[{ticker}] {title}")

# 2. Level 2: Grade Past Pitches Against Real Market Prices
scoreboard = []
for pitch in memory["past_pitches"][-10:]:
    p_ticker = pitch.get("ticker", "GRID")
    entry_price = pitch.get("entry_price")
    try:
        latest_p = current_prices.get(p_ticker) or float(yf.Ticker(p_ticker).fast_info["last_price"])
        if entry_price and entry_price > 0:
            perf_pct = ((latest_p - entry_price) / entry_price) * 100
            pitch["latest_price"] = round(latest_p, 2)
            pitch["return_pct"] = round(perf_pct, 2)
            scoreboard.append(
                f"{pitch['date']} | Call: {pitch['action']} {p_ticker} @ ${entry_price:.2f} -> Now ${latest_p:.2f} ({perf_pct:+.2f}%)"
            )
    except Exception:
        pass

today_dt = datetime.datetime.now()
is_friday = today_dt.weekday() == 4
pruning_instruction = (
    "TODAY IS FRIDAY (WEEKLY STRATEGY REVIEW): Review all rules in 'Past Lessons Learned' alongside your Track Record. "
    "Merge duplicates, delete rules that led to bad calls, and output a refined, ranked list of your top 8 rules."
    if is_friday else ""
)

# 3. Critical Thinking, Self-Grading & Evolution Prompt
prompt = f"""
You are Aegis Research, a self-improving institutional investment analyst.
Current Portfolio & Latest Prices: {market_snapshot}
Today's Live Market Headlines: {live_headlines}
Your Real-World Track Record (Past Calls vs. Actual Prices): {scoreboard if scoreboard else "No past calls graded yet."}
Your Past Lessons Learned (MUST FOLLOW): {memory['lessons_learned']}
{pruning_instruction}

Critically evaluate your past track record, today's prices, and live headlines. Write a sharp daily report:
1. 🛡️ AEGIS RESEARCH // DAILY BRIEFING
2. 📈 SELF-AUDIT & TRACK RECORD: Briefly grade your past calls above (what worked, what failed, and why).
3. 📊 PORTFOLIO PULSE: Key moves in XLU, GRID, and UTES and what today's headlines mean.
4. 🐂 vs 🐻 CRITICAL DEBATE: One major opportunity vs. one major risk based on today's news and prices.
5. 💡 PROACTIVE PITCH: Suggest 1 concrete action (e.g., BUY <TICKER>, TRIM <TICKER>, or HOLD GRID) with hard reasoning.

At the very end, output these exact machine-readable lines so your memory system updates itself:
PITCH_ACTION: <HOLD or BUY or TRIM>
PITCH_TICKER: <Single valid US stock/ETF ticker, e.g., GRID, XLU, UTES, PWR, URNM>
NEW_LESSON: <One sharp rule capturing what to repeat or avoid based on your self-audit>
"""

response = client.models.generate_content(model="gemini-3.8-flash", contents=prompt)
report = response.text

# 4. Parse Self-Audit Outputs & Update Permanent Memory
clean_lines = []
pitch_action = "HOLD"
pitch_ticker = "GRID"
new_lesson = ""

for line in report.splitlines():
    if line.startswith("PITCH_ACTION:"):
        pitch_action = line.split(":", 1)[1].strip().upper()
    elif line.startswith("PITCH_TICKER:"):
        pitch_ticker = line.split(":", 1)[1].strip().upper().replace("$", "")
    elif line.startswith("NEW_LESSON:"):
        new_lesson = line.split(":", 1)[1].strip().lstrip("*:- ")
    else:
        clean_lines.append(line)

clean_report = "\n".join(clean_lines).strip()

# Log today's call into past_pitches for future grading
try:
    tracked_price = current_prices.get(pitch_ticker) or float(yf.Ticker(pitch_ticker).fast_info["last_price"])
    memory["past_pitches"].append({
        "date": today_dt.strftime("%Y-%m-%d"),
        "action": pitch_action,
        "ticker": pitch_ticker,
        "entry_price": round(tracked_price, 2)
    })
    memory["past_pitches"] = memory["past_pitches"][-30:]
except Exception:
    pass

# Save new learned rule
if new_lesson:
    memory["lessons_learned"].append(new_lesson)
    memory["lessons_learned"] = memory["lessons_learned"][-12:]

with open("memory.json", "w") as f:
    json.dump(memory, f, indent=2)

# 5. Save Briefing Directly to GitHub
today_str = today_dt.strftime("%Y-%m-%d %H:%M UTC")
with open("latest_briefing.md", "w") as f:
    f.write(f"# 🛡️ Aegis Research Daily Briefing ({today_str})\n\n{clean_report}\n")
