import os
import json
import time
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from google import genai

# 1. Page Setup & Animated Cyber-Terminal CSS
st.set_page_config(page_title="Aegis Research Terminal", page_icon="⚖️", layout="wide")

st.markdown("""
<style>
@keyframes pulseGlow {
    0% { box-shadow: 0 0 10px rgba(56, 189, 248, 0.25); }
    50% { box-shadow: 0 0 25px rgba(56, 189, 248, 0.75); }
    100% { box-shadow: 0 0 10px rgba(56, 189, 248, 0.25); }
}
@keyframes slideUp {
    from { opacity: 0; transform: translateY(14px); }
    to { opacity: 1; transform: translateY(0); }
}
.aegis-banner {
    background: linear-gradient(135deg, #090d16 0%, #1e293b 100%);
    border: 1px solid #38bdf8;
    border-radius: 14px;
    padding: 22px 26px;
    animation: pulseGlow 3.5s infinite, slideUp 0.6s ease-out;
    margin-bottom: 22px;
}
.aegis-heading {
    font-size: 30px;
    font-weight: 800;
    letter-spacing: 0.5px;
    background: -webkit-linear-gradient(45deg, #38bdf8, #a855f7);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: 0;
}
.aegis-sub {
    color: #94a3b8;
    font-size: 14px;
    margin-top: 4px;
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="aegis-banner">
    <div class="aegis-heading">⚖️ AEGIS AUTONOMOUS RESEARCH TERMINAL</div>
    <div class="aegis-sub">Self-Auditing ETF Intelligence • Live Market Telemetry • Gemini Neural Engine</div>
</div>
""", unsafe_allow_html=True)

# 2. Load Memory & Latest Briefing Safely
memory = {"portfolio": {"XLU": 1, "GRID": 1, "UTES": 1}, "past_pitches": [], "lessons_learned": []}
if os.path.exists("memory.json"):
    try:
        with open("memory.json", "r") as f:
            memory = json.load(f)
    except Exception:
        pass

tickers = list(memory.get("portfolio", {"XLU": 1, "GRID": 1, "UTES": 1}).keys())

# 3. Live Market Metrics & Animated Normalized Growth Graph
@st.cache_data(ttl=300)
def fetch_market_data(ticker_list):
    metrics = {}
    hist_df = pd.DataFrame()
    for sym in ticker_list:
        try:
            df = yf.Ticker(sym).history(period="3mo")
            if not df.empty:
                latest = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2]) if len(df) >= 2 else latest
                chg = ((latest - prev) / prev) * 100 if prev else 0.0
                metrics[sym] = (latest, chg)
                # Normalize to % return from start of 3-month window
                hist_df[sym] = ((df["Close"] / df["Close"].iloc[0]) - 1) * 100
        except Exception:
            metrics[sym] = (0.0, 0.0)
    return metrics, hist_df

metrics, hist_df = fetch_market_data(tickers)

cols = st.columns(len(tickers))
for idx, sym in enumerate(tickers):
    price, chg = metrics.get(sym, (0.0, 0.0))
    cols[idx].metric(label=f"📈 {sym}", value=f"${price:.2f}", delta=f"{chg:+.2f}%")

tab_charts, tab_briefing, tab_generator = st.tabs([
    "📊 Live Graphs & Track Record",
    "📰 8:00 AM Autonomous Briefing",
    "🧠 Run Live Critical Analysis"
])

with tab_charts:
    col_left, col_right = st.columns([3, 2])
    
    with col_left:
        st.subheader("3-Month Relative Performance (%)")
        if not hist_df.empty:
            fig = go.Figure()
            colors = ["#38bdf8", "#a855f7", "#34d399", "#f59e0b"]
            for i, sym in enumerate(hist_df.columns):
                fig.add_trace(go.Scatter(
                    x=hist_df.index,
                    y=hist_df[sym],
                    mode="lines",
                    name=sym,
                    line=dict(width=3, color=colors[i % len(colors)])
                ))
            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(15,23,42,0.65)",
                yaxis_title="Return (%)",
                hovermode="x unified",
                height=370,
                margin=dict(l=10, r=10, t=20, b=10),
                transition={"duration": 700, "easing": "cubic-in-out"}
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Live market chart will load once market data responds.")

    with col_right:
        st.subheader("🎯 Self-Audit Scoreboard")
        pitches = memory.get("past_pitches", [])
        graded = [p for p in pitches if "return_pct" in p]
        if graded:
            labels = [f"{p['date']} ({p['ticker']})" for p in graded[-8:]]
            returns = [p["return_pct"] for p in graded[-8:]]
            bar_colors = ["#34d399" if r >= 0 else "#f87171" for r in returns]
            fig_sb = go.Figure(go.Bar(
                x=labels, y=returns, marker_color=bar_colors,
                text=[f"{r:+.2f}%" for r in returns], textposition="auto"
            ))
            fig_sb.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(15,23,42,0.65)",
                yaxis_title="Call Return (%)",
                height=370,
                margin=dict(l=10, r=10, t=20, b=10)
            )
            st.plotly_chart(fig_sb, use_container_width=True)
        else:
            st.info("No graded calls yet. Your daily GitHub Action populates this automatically.")

with tab_briefing:
    if os.path.exists("latest_briefing.md"):
        with open("latest_briefing.md", "r") as f:
            st.markdown(f.read())
    else:
        st.warning("No daily briefing found yet. Trigger your GitHub Action workflow once to generate `latest_briefing.md`.")

with tab_generator:
    api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    user_prompt = st.text_area(
        "Ask about your ETFs or request a new market pitch:",
        value="Analyze XLU, GRID, and UTES with today's news and pitch 1 complementary idea.",
        height=100
    )

    if st.button("🚀 Run Critical Analysis", type="primary"):
        with st.status("Initializing Aegis Neural Engine...", expanded=True) as status:
            live_context = {sym: f"${p:.2f} ({c:+.2f}%)" for sym, (p, c) in metrics.items()}
            full_prompt = (
                f"You are Aegis Research, an institutional ETF analyst. "
                f"Current live prices: {live_context}. "
                f"Past learned lessons: {memory.get('lessons_learned', [])}. "
                f"User request: {user_prompt}"
            )
            
            stream_response = None
            active_model = None
            for model_id in ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]:
                try:
                    st.write(f"Connecting to `{model_id}`...")
                    stream_response = client.models.generate_content_stream(
                        model=model_id,
                        contents=full_prompt
                    )
                    active_model = model_id
                    break
                except Exception as err:
                    st.write(f"`{model_id}` unavailable, switching...")

            if stream_response:
                status.update(label=f"Connected via {active_model}!", state="complete", expanded=False)
                
                def typewriter():
                    for chunk in stream_response:
                        if chunk.text:
                            yield chunk.text
                            time.sleep(0.012)

                st.markdown("### ⚖️ Aegis Research Output")
                st.write_stream(typewriter())
                st.toast("Analysis complete!", icon="✅")
            else:
                status.update(label="Connection failed", state="error")
                st.error("All Gemini fallback models failed. Verify your GEMINI_API_KEY in Streamlit Secrets.")
