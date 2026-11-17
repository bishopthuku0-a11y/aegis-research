import streamlit as st
import yfinance as yf
import json
import feedparser
import plotly.graph_objects as go
import plotly.express as px
from google import genai
from google.genai.errors import ClientError

# 1. Command Center Setup
st.set_page_config(page_title="Aegis Research", page_icon="🛡️", layout="wide")

# 2. Custom CSS: Ambient Dark Background, Glassmorphism & Pulse Animations
st.markdown("""
<style>
    /* Deep Obsidian Ambient Background */
    .stApp {
        background: radial-gradient(circle at 15% 15%, #111927 0%, #090c10 55%, #050709 100%);
        color: #e6edf3;
    }
    
    /* Frosted Glass Sidebar */
    [data-testid="stSidebar"] {
        background: rgba(13, 17, 23, 0.75);
        backdrop-filter: blur(14px);
        border-right: 1px solid rgba(56, 189, 248, 0.15);
    }

    /* Glowing Metric Cards */
    [data-testid="stMetric"] {
        background: rgba(22, 27, 34, 0.65);
        border: 1px solid rgba(56, 189, 248, 0.2);
        border-radius: 12px;
        padding: 12px 16px;
        transition: transform 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
    }
    [data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        border-color: rgba(56, 189, 248, 0.6);
        box-shadow: 0 6px 20px rgba(56, 189, 248, 0.12);
    }

    /* Animated Live Status Pulse */
    @keyframes pulse-glow {
        0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
        70% { box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
        100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
    }
    .status-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: rgba(16, 185, 129, 0.1);
        border: 1px solid rgba(16, 185, 129, 0.35);
        color: #34d399;
        padding: 4px 12px;
        border-radius: 999px;
        font-size: 0.8rem;
        font-weight: 600;
        margin-bottom: 12px;
    }
    .pulse-dot {
        width: 8px;
        height: 8px;
        background-color: #10b981;
        border-radius: 50%;
        animation: pulse-glow 2s infinite;
    }

    /* Sleek Primary Button Glow */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%);
        border: none;
        border-radius: 10px;
        font-weight: 600;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(14, 165, 233, 0.3);
    }
    .stButton > button[kind="primary"]:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 25px rgba(14, 165, 233, 0.55);
    }
</style>
""", unsafe_allow_html=True)

# Live Breaking News Fetcher (Free Google News RSS)
def get_live_market_news(queries=["XLU utilities ETF", "GRID smart grid ETF", "UTES ETF", "10 year treasury yield"]):
    headlines = []
    for q in queries:
        try:
            url = f"https://google.com{q.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
            feed = feedparser.parse(url)
            for entry in feed.entries[:2]:
                headlines.append(f"- [{q}] {entry.title} ({entry.get('published', 'Recent')})")
        except Exception:
            continue
    return "\n".join(headlines) if headlines else "No major breaking headlines fetched."

# Header with Live Pulse Indicator
st.markdown('<div class="status-badge"><span class="pulse-dot"></span>SYSTEM ONLINE • GEMINI 4 HYDROGEN + LIVE NEWS FEED</div>', unsafe_allow_html=True)
st.title("🛡️ AEGIS RESEARCH // Autonomous Intelligence")
st.caption("Live Portfolio Telemetry • Real-Time News Research • Plain-English Action Signals")

# Connect Free Gemini API
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

# Load Memory
with open("memory.json", "r") as f:
    memory = json.load(f)

# 3. Sidebar: Live Portfolio Cards, Macro Rate Watch & Memory Bank
with st.sidebar:
    st.header("📊 Core Portfolio")
    live_prices_summary = []
    for ticker, weight in memory["portfolio"].items():
        info = yf.Ticker(ticker).fast_info
        price = info["last_price"]
        prev_close = info["previous_close"]
        pct_change = ((price - prev_close) / prev_close) * 100
        live_prices_summary.append(f"{ticker}: ${price:.2f} ({pct_change:+.2f}%)")
        st.metric(
            label=f"{ticker} • {int(weight*100)}% Target",
            value=f"${price:.2f}",
            delta=f"{pct_change:+.2f}%"
        )

    # Macro Interest Rate Indicator (10-Year US Treasury Yield)
    try:
        tnx_info = yf.Ticker("^TNX").fast_info
        tnx_yield = tnx_info["last_price"]
        tnx_prev = tnx_info["previous_close"]
        tnx_delta = tnx_yield - tnx_prev
        st.metric(
            label="🏦 10-Yr Treasury Yield (Rate Watch)",
            value=f"{tnx_yield:.2f}%",
            delta=f"{tnx_delta:+.2f}%",
            delta_color="inverse"
        )
        macro_context = f"10-Year US Treasury Yield: {tnx_yield:.2f}% ({tnx_delta:+.2f}%)"
    except Exception:
        macro_context = "10-Year US Treasury Yield: Unavailable"

    # Interactive Donut Chart for Portfolio Weights
    fig_donut = px.pie(
        names=list(memory["portfolio"].keys()),
        values=list(memory["portfolio"].values()),
        hole=0.62,
        color_discrete_sequence=["#38bdf8", "#818cf8", "#34d399"]
    )
    fig_donut.update_layout(
        showlegend=True,
        height=200,
        margin=dict(t=10, b=10, l=10, r=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e6edf3", size=12)
    )
    st.plotly_chart(fig_donut, use_container_width=True)

    st.divider()
    st.header("🧬 Learned Rules (Memory)")
    for i, lesson in enumerate(memory["lessons_learned"], 1):
        st.info(f"**{i}.** {lesson}")

# 4. Interactive 30-Day Normalized Performance Chart
st.subheader("📈 30-Day Relative Momentum (%)")
tickers = list(memory["portfolio"].keys())
hist_data = yf.download(tickers, period="1mo", progress=False)["Close"]

fig_line = go.Figure()
colors = ["#38bdf8", "#818cf8", "#34d399"]

for idx, ticker in enumerate(tickers):
    if ticker in hist_data:
        series = hist_data[ticker].dropna()
        norm_series = ((series / series.iloc[0]) - 1) * 100
        fig_line.add_trace(go.Scatter(
            x=norm_series.index,
            y=norm_series,
            mode="lines",
            name=ticker,
            line=dict(width=2.5, color=colors[idx % len(colors)]),
            fill="tozeroy" if idx == 0 else None,
            fillcolor="rgba(56, 189, 248, 0.06)" if idx == 0 else None
        ))

fig_line.update_layout(
    height=280,
    margin=dict(t=10, b=10, l=10, r=10),
    paper_bgcolor="rgba(13, 17, 23, 0.5)",
    plot_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(showgrid=False, color="#8b949e"),
    yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)", ticksuffix="%", color="#8b949e"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hovermode="x unified"
)
st.plotly_chart(fig_line, use_container_width=True)

st.divider()

# 5. Main Area: Proactive Pitch & Plain-English Research Engine
col1, col2 = st.columns([1, 1.2])

with col1:
    st.subheader("💡 Ask Aegis Research")
    user_query = st.text_area(
        "Ask why your ETFs are moving or if it is safe to buy right now:",
        "Why are GRID and UTES moving right now, and should I buy or wait?",
        height=130
    )
    
    if st.button("🚀 Run Live News & Market Research", type="primary", use_container_width=True):
        with st.spinner("Scanning live financial news & debating risks..."):
            live_news = get_live_market_news()
            prompt = f"""
            You are Aegis Research, a friendly, super-clear investment mentor helping a complete beginner grow money safely.
            Avoid all confusing Wall Street jargon. Explain everything in plain, everyday English using the live market data and breaking news below.
            
            User Portfolio & Live Prices: {', '.join(live_prices_summary)}
            Macro Interest Rate Watch: {macro_context}
            Past Rules to Obey: {memory['lessons_learned']}
            
            Live Breaking News Headlines Today:
            {live_news}
            
            User Question: {user_query}
            
            Respond strictly in 4 simple sections:
            1. 🚦 ACTION SIGNAL: Pick ONE (🟢 SAFE TO BUY, 🟡 WAIT & HOLD CASH, or 🔴 AVOID / TOO RISKY) and explain why in 2 short sentences based on today's news and rates.
            2. 📰 WHAT IS HAPPENING RIGHT NOW: Explain why the prices are moving today using the live headlines in simple words.
            3. ⚠️ BIGGEST RISK TO WATCH: Explain what could go wrong clearly so the user protects their money.
            4. 📝 NEW LESSON TO REMEMBER: Write 1 short, beginner-friendly takeaway rule for memory.
            """
            try:
                response = client.models.generate_content(
                    model="gemini-4-hydrogen",
                    contents=prompt
                )
                st.session_state["last_analysis"] = response.text
                st.session_state["last_news"] = live_news
            except ClientError as e:
                st.error(f"API Error ({e.code}): {e.message}")

with col2:
    st.subheader("⚖️ Aegis Research Output")
    if "last_analysis" in st.session_state:
        st.markdown(st.session_state["last_analysis"])
        with st.expander("🗞️ View Live Headlines Aegis Scanned"):
            st.text(st.session_state.get("last_news", ""))
        if st.button("💾 Save New Lesson to Memory"):
            new_rule = st.session_state["last_analysis"].split("NEW LESSON TO REMEMBER")[-1].strip(": \n*")
            memory["lessons_learned"].append(new_rule)
            with open("memory.json", "w") as f:
                json.dump(memory, f, indent=2)
            st.success("Memory updated! Reloading...")
            st.rerun()
    else:
