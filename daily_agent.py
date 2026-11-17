import os
import json
import datetime
import yfinance as yf
from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

with open("memory.json", "r") as f:
    memory = json.load(f)

market_snapshot = {}
live_headlines = []

for ticker in memory["portfolio"].keys():
    t = yf.Ticker(ticker)
    price = t.fast_info["last_price"]
    prev_close = t.fast_info["previous_close"]
    change_pct = ((price - prev_close) / prev_close) * 100
    market_snapshot[ticker] = f"${price:.2f} ({change_pct:+.2f}%)"
    for article in (t.news or [])[:3]:
        title = article.get("content", {}).get("title") or article.get("title")
        if title:
            live_headlines.append(f"[{ticker}] {title}")

prompt = f"""
You are Aegis Research, an autonomous institutional investment analyst running an automated morning check.
Current Portfolio & Latest Prices: {market_snapshot}
Today's Live Market Headlines: {live_headlines}
Your Past Lessons Learned (MUST FOLLOW): {memory['lessons_learned']}

Analyze the live prices and news headlines critically, then write a structured daily report:
1. 🛡️ AEGIS RESEARCH // DAILY BRIEFING
2. 📊 PORTFOLIO PULSE: Key moves in XLU, GRID, and UTES and what today's headlines mean.
3. 🐂 vs 🐻 CRITICAL DEBATE: One major opportunity vs. one major risk based on today's news and prices.
4. 💡 PROACTIVE PITCH: Suggest 1 concrete investment idea or portfolio adjustment with hard reasoning (or say 'Hold steady' if no strong setup exists).
5. NEW_LESSON: End with one single sentence starting with 'NEW_LESSON:' capturing a rule to remember for future checks.
"""

response = client.models.generate_content(model="gemini-3.8-flash", contents=prompt)
report = response.text

if "NEW_LESSON:" in report:
    parts = report.split("NEW_LESSON:", 1)
    clean_report = parts[0].strip()
    new_lesson = parts[1].strip().lstrip("*:- ")
    if new_lesson:
        memory["lessons_learned"].append(new_lesson)
        memory["lessons_learned"] = memory["lessons_learned"][-15:]
        with open("memory.json", "w") as f:
            json.dump(memory, f, indent=2)
else:
    clean_report = report

today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M UTC")
with open("latest_briefing.md", "w") as f:
    f.write(f"# 🛡️ Aegis Research Daily Briefing ({today})\n\n{clean_report}\n")
