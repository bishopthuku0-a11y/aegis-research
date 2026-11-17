import streamlit as st
import yfinance as yf
import json
from google import genai
from google.genai.errors import ClientError

# 1. Command Center Setup
st.set_page_config(page_title="Aegis Research", page_icon="🛡️", layout="wide")
st.title("🛡️ AEGIS RESEARCH // Autonomous Investment Intelligence")
st.caption("Live Portfolio Monitor • Bull vs. Bear Debate • Self-Updating Memory")

# Connect Free Gemini API
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

# Load Memory
with open("memory.json", "r") as f:
    memory = json.load(f)

# 2. Sidebar: Live Portfolio & Memory Bank
with st.sidebar:
    st.header("📊 Core Portfolio (50/30/20)")
    for ticker, weight in memory["portfolio"].items():
        price = yf.Ticker(ticker).fast_info["last_price"]
        st.metric(label=f"{ticker} ({int(weight*100)}%)", value=f"${price:.2f}")
    
    st.divider()
    st.header("🧬 Learned Rules (Memory)")
    for i, lesson in enumerate(memory["lessons_learned"], 1):
        st.info(f"{i}. {lesson}")

# 3. Main Area: Proactive Pitch & Critical Thinking Debate
col1, col2 = st.columns([1, 1.2])

with col1:
    st.subheader("💡 Desk Query & Thesis Generator")
    user_query = st.text_area(
        "Ask about your ETFs or request a new market pitch:",
        "Analyze XLU, GRID, and UTES right now and pitch 1 complementary idea."
    )
    
    if st.button("🚀 Run Critical Analysis", type="primary"):
        with st.spinner("Aegis Bull and Bear desks are debating..."):
            prompt = f"""
            You are Aegis Research, an institutional-grade, critical-thinking investment analyst.
            User Portfolio: {memory['portfolio']}
            Your Past Lessons Learned (MUST FOLLOW): {memory['lessons_learned']}
            User Request: {user_query}
            
            Respond strictly in 4 sections:
            1. 🐂 THE BULL CASE (Why this works)
            2. 🐻 THE BEAR CASE (How this could fail / risks)
            3. ⚖️ SKEPTICAL VERDICT & PITCH (Your human-like recommendation with concrete reasons)
            4. 📝 NEW LESSON TO REMEMBER (1 short rule to add to your memory)
            """
            try:
                response = client.models.generate_content(
                    model="gemini-4-hydrogen",
                    contents=prompt
                )
                st.session_state["last_analysis"] = response.text
            except ClientError as e:
                st.error(f"API Error ({e.code}): {e.message}")

with col2:
    st.subheader("⚖️ Aegis Research Output")
    if "last_analysis" in st.session_state:
        st.markdown(st.session_state["last_analysis"])
        if st.button("💾 Save New Lesson to Memory"):
            new_rule = st.session_state["last_analysis"].split("NEW LESSON TO REMEMBER")[-1].strip(": \n*")
            memory["lessons_learned"].append(new_rule)
            with open("memory.json", "w") as f:
                json.dump(memory, f, indent=2)
            st.success("Memory updated! Reloading...")
            st.rerun()
    else:
        st.write("Click **Run Critical Analysis** to wake up Aegis Research.")
