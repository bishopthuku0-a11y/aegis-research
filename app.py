import streamlit as st
import yfinance as yf
import json
import os
import time
from google import genai

# 1. Command Center Setup
st.set_page_config(page_title="Aegis Research", page_icon="🛡️", layout="wide")
st.title("🛡️ AEGIS RESEARCH // Autonomous Investment Intelligence")
st.caption("Live Portfolio Monitor • Real-Time News Feed • Bull vs. Bear Debate")

# Connect Free Gemini API
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

# Load Memory
with open("memory.json", "r") as f:
    memory = json.load(f)

# Helper: Auto-discovers working Gemini models on your key & retries safely
def ask_aegis(prompt_text):
    last_err = ""
    candidates = ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.0-flash"]
    try:
        for m in client.models.list():
            name = m.name.replace("models/", "")
            if "flash" in name and name not in candidates:
                candidates.append(name)
    except Exception:
        pass

    for model_name in candidates[:4]:
        for attempt in range(2):
            try:
                res = client.models.generate_content(model=model_name, contents=prompt_text)
                return res.text
            except Exception as e:
                last_err = str(e)
                time.sleep(2)
    return f"⚠️ Google AI servers returned a temporary error ({last_err[:120]}). Wait 15 seconds and click Run Critical Analysis again."

# 2. Sidebar: Live Portfolio, Headlines & Memory Bank
live_headlines = []
with st.sidebar:
    st.header("📊 Core Portfolio (50/30/20)")
    for ticker, weight in memory["portfolio"].items():
        t = yf.Ticker(ticker)
        price = t.fast_info["last_price"]
        st.metric(label=f"{ticker} ({int(weight*100)}%)", value=f"${price:.2f}")
        for article in (t.news or [])[:2]:
            title = article.get("content", {}).get("title") or article.get("title")
            if title:
                live_headlines.append(f"[{ticker}] {title}")
    
    st.divider()
    st.header("🧬 Learned Rules (Memory)")
    for i, lesson in enumerate(memory["lessons_learned"], 1):
        st.info(f"{i}. {lesson}")

# 3. Main Area: Live Briefing + Interactive Desk
col1, col2 = st.columns([1, 1.2])

with col1:
    st.subheader("💡 Desk Query & Thesis Generator")
    user_query = st.text_area(
        "Ask about your ETFs or request a new market pitch:",
        "Analyze XLU, GRID, and UTES with today's news and pitch 1 complementary idea."
    )
    
    if st.button("🚀 Run Critical Analysis", type="primary"):
        with st.spinner("Aegis Bull and Bear desks are debating..."):
            prompt = f"""
            You are Aegis Research, an institutional-grade, critical-thinking investment analyst.
            User Portfolio: {memory['portfolio']}
            Today's Live Headlines: {live_headlines}
            Your Past Lessons Learned (MUST FOLLOW): {memory['lessons_learned']}
            User Request: {user_query}
            
            Respond strictly in 4 sections:
            1. 🐂 THE BULL CASE (Why this works)
            2. 🐻 THE BEAR CASE (How this could fail / risks)
            3. ⚖️ SKEPTICAL VERDICT & PITCH (Your human-like recommendation with concrete reasons)
            4. 📝 NEW LESSON TO REMEMBER (1 short rule to add to your memory)
            """
            st.session_state["last_analysis"] = ask_aegis(prompt)

    if os.path.exists("latest_briefing.md"):
        st.divider()
        with st.expander("📰 Read Latest 8:00 AM Autonomous Briefing"):
            with open("latest_briefing.md", "r") as bf:
                st.markdown(bf.read())

with col2:
    st.subheader("⚖️ Aegis Research Output")
    if "last_analysis" in st.session_state:
        st.markdown(st.session_state["last_analysis"])
        if st.button("💾 Save New Lesson to Memory"):
            new_rule = st.session_state["last_analysis"].split("NEW LESSON TO REMEMBER")[-1].strip(": \n*")
            if new_rule:
                memory["lessons_learned"].append(new_rule)
                with open("memory.json", "w") as f:
                    json.dump(memory, f, indent=2)
                st.success("Memory updated! Reloading...")
                st.rerun()
    else:
        st.write("Click **Run Critical Analysis** to wake up Aegis Research.")
