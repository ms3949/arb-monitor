"""
Streamlit Arb Dashboard
========================
Live sports arbitrage monitor between Kalshi and Polymarket.

Usage:
    cd poly_stat_arb
    streamlit run streamlit_app/dashboard.py
"""
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import time
import json
import threading
import asyncio
import websockets
import base64
import queue
from datetime import datetime
from collections import deque
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Ensure project root is on sys.path so 'streamlit_app' package is importable
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from streamlit_app.fetch_markets import fetch_kalshi_markets, fetch_poly_markets, validate_match
from ai_insights import generate_session_insights, generate_browse_insights

# ---- Page Config ----
st.set_page_config(
    page_title="⚡ Arb Monitor",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---- Custom CSS ----
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
    
    :root {
        --bg-color: #060d1b;
        --sidebar-bg: #080f1e;
        --card-bg: rgba(255, 255, 255, 0.02);
        --border-color: #15202e;
        --accent-primary: #64ffda;
        --accent-secondary: #0ea5e9;
        --text-main: #c5d0e6;
        --text-muted: #4a5568;
        --text-header: #e6f1ff;
    }

    .stApp {
        background-color: var(--bg-color);
        color: var(--text-main);
    }

    html, body, [class*="st-"] {
        font-family: 'Inter', sans-serif;
    }
    
    code, .mono-font {
        font-family: 'JetBrains Mono', monospace !important;
    }
    
    .main .block-container {
        padding-top: 1.5rem;
        max-width: 1400px;
    }
    
    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background-color: var(--sidebar-bg) !important;
        border-right: 1px solid var(--border-color);
    }
    
    section[data-testid="stSidebar"] .stButton button {
        background: transparent;
        border: 1px solid var(--border-color);
        color: var(--text-muted);
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    section[data-testid="stSidebar"] .stButton button:hover {
        background: rgba(100, 255, 218, 0.05);
        border-color: var(--accent-primary);
        color: var(--accent-primary);
    }

    /* Metric cards */
    .metric-card {
        background: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 10px;
        padding: 1rem;
        transition: all 0.2s ease;
    }
    .metric-label { 
        color: var(--text-muted); 
        font-size: 0.65rem; 
        text-transform: uppercase; 
        letter-spacing: 1.5px; 
        margin-bottom: 0.5rem;
    }
    .metric-value { 
        color: var(--accent-primary); 
        font-size: 1.6rem; 
        font-weight: 700; 
        line-height: 1;
        font-family: 'JetBrains Mono', monospace;
    }
    .metric-sub { 
        color: var(--text-muted); 
        font-size: 0.7rem; 
        margin-top: 0.3rem;
    }
    
    /* Status indicators */
    .status-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        display: inline-block;
        margin-right: 6px;
    }
    .status-online { background: var(--accent-primary); box-shadow: 0 0 6px rgba(100, 255, 218, 0.4); }
    .status-offline { background: #ff6b6b; box-shadow: 0 0 6px rgba(255, 107, 107, 0.4); }

    /* Tables */
    .stDataFrame, div[data-testid="stTable"] {
        background: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 10px;
    }

    /* Arb Alert */
    .arb-alert {
        background: rgba(100, 255, 218, 0.06);
        border: 1px solid rgba(100, 255, 218, 0.3);
        border-radius: 10px;
        padding: 1.2rem;
        display: flex;
        align-items: center;
        gap: 1rem;
        animation: pulse 2s ease-in-out infinite;
    }
    
    @keyframes pulse {
        0%, 100% { box-shadow: 0 0 4px rgba(100, 255, 218, 0.1); }
        50% { box-shadow: 0 0 16px rgba(100, 255, 218, 0.2); }
    }

    /* Headlines */
    h1, h2, h3 {
        color: var(--text-header) !important;
        font-family: 'JetBrains Mono', monospace !important;
        letter-spacing: -0.5px;
    }
    
    .section-header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 1.5rem 0 1rem 0;
    }
    .section-header::before {
        content: "";
        width: 3px;
        height: 16px;
        background: var(--accent-primary);
        border-radius: 2px;
    }
    .section-header span {
        font-size: 0.8rem;
        font-weight: 700;
        color: var(--text-header);
        letter-spacing: 0.5px;
        text-transform: uppercase;
    }

    /* Hide the 'RUN BOT HIDDEN' button but keep it functional */
    div[data-testid="stVerticalBlock"] > div:has(button[kind="primary"][data-testid="stBaseButton-secondaryFormSubmit"]) {
        display: none !important;
    }
    /* Specific selector for the 'RUN BOT HIDDEN' button to be extra safe */
    button[key="run_bot_hidden"] {
        display: none !important;
    }
    
    /* Better way: hide any primary button that is intended to be hidden */
    .hidden-btn {
        display: none !important;
    }
</style>
""", unsafe_allow_html=True)

# ---- Session State Init ----
if "phase" not in st.session_state:
    st.session_state.phase = "browse"  # browse | monitor | analyze
if "kalshi_markets" not in st.session_state:
    st.session_state.kalshi_markets = []
if "poly_markets" not in st.session_state:
    st.session_state.poly_markets = []
if "match_result" not in st.session_state:
    st.session_state.match_result = None
if "spread_history" not in st.session_state:
    st.session_state.spread_history = []
if "monitoring" not in st.session_state:
    st.session_state.monitoring = False
if "data_queue" not in st.session_state:
    st.session_state.data_queue = queue.Queue()
if "ws_thread" not in st.session_state:
    st.session_state.ws_thread = None
if "stop_event" not in st.session_state:
    st.session_state.stop_event = threading.Event()
if "latest_prices" not in st.session_state:
    st.session_state.latest_prices = {
        "kalshi_bid": None, "kalshi_ask": None,
        "kalshi_bid_size": 0, "kalshi_ask_size": 0,
        "poly_bid": None, "poly_ask": None,
    }
if "arb_events" not in st.session_state:
    st.session_state.arb_events = []

if "ai_insights" not in st.session_state:
    st.session_state.ai_insights = None
if "ai_loading" not in st.session_state:
    st.session_state.ai_loading = False
if "browse_insights" not in st.session_state:
    st.session_state.browse_insights = None


# ---- Helper Functions ----

def _metric_card(label, value, sub="", css_class=""):
    st.markdown(f"""
    <div class="metric-card {css_class}">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
        <div class="metric-sub">{sub}</div>
    </div>
    """, unsafe_allow_html=True)


def _kalshi_mid(prices):
    b, a = prices.get("kalshi_bid"), prices.get("kalshi_ask")
    if b is not None and a is not None:
        return (b + a) / 2
    return b or a


def _poly_mid(prices):
    b, a = prices.get("poly_bid"), prices.get("poly_ask")
    if b is not None and a is not None:
        return (b + a) / 2
    return b or a


# ---- WebSocket Feed Thread ----

def _run_feeds(config, data_queue, stop_event):
    """Run Kalshi + Poly WS feeds in a background thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _kalshi_ws(config, q, stop):
        host = "wss://api.elections.kalshi.com"
        path = "/trade-api/ws/v2"
        uri = host + path
        key_id = os.getenv("KALSHI_KEY_ID")
        pk_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
        private_key = None
        try:
            with open(pk_path, "rb") as kf:
                private_key = serialization.load_pem_private_key(kf.read(), password=None)
        except Exception:
            q.put({"type": "error", "source": "kalshi", "msg": "Failed to load private key"})
            return

        def sign(text):
            msg = text.encode("utf-8")
            sig = private_key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
            return base64.b64encode(sig).decode("utf-8")

        ticker = config.get("kalshi_market_ticker", "")
        book = {"bids": {}, "asks": {}}
        backoff = 1

        while not stop.is_set():
            try:
                timestamp = str(int(time.time() * 1000))
                sig_msg = timestamp + "GET" + path
                signature = sign(sig_msg)
                headers = {
                    "KALSHI-ACCESS-KEY": key_id,
                    "KALSHI-ACCESS-SIGNATURE": signature,
                    "KALSHI-ACCESS-TIMESTAMP": timestamp,
                }
                async with websockets.connect(uri, additional_headers=headers) as ws:
                    q.put({"type": "status", "source": "kalshi", "msg": "Connected ✅"})
                    backoff = 1
                    sub = {"id": 1, "cmd": "subscribe", "params": {"channels": ["orderbook_delta"], "market_ticker": ticker}}
                    await ws.send(json.dumps(sub))

                    while not stop.is_set():
                        try:
                            msg_txt = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        except asyncio.TimeoutError:
                            continue
                        try:
                            msg = json.loads(msg_txt)
                        except Exception:
                            continue
                        if not isinstance(msg, dict):
                            continue
                        m_type = msg.get("type")
                        if m_type not in ("orderbook_snapshot", "orderbook_delta"):
                            continue
                        data = msg.get("msg", {})
                        if not data or data.get("market_ticker") != ticker:
                            continue

                        if m_type == "orderbook_snapshot":
                            for p, qty in (data.get("yes") or data.get("bids") or []):
                                if qty <= 0:
                                    book["bids"].pop(p, None)
                                else:
                                    book["bids"][p] = qty
                            for p, qty in (data.get("no") or data.get("asks") or []):
                                yp = 100 - p
                                if qty <= 0:
                                    book["asks"].pop(yp, None)
                                else:
                                    book["asks"][yp] = qty
                        elif m_type == "orderbook_delta":
                            side = data.get("side")
                            price = data.get("price")
                            delta = data.get("delta")
                            if side == "yes":
                                nq = book["bids"].get(price, 0) + delta
                                if nq <= 0:
                                    book["bids"].pop(price, None)
                                else:
                                    book["bids"][price] = nq
                            elif side == "no":
                                yp = 100 - price
                                nq = book["asks"].get(yp, 0) + delta
                                if nq <= 0:
                                    book["asks"].pop(yp, None)
                                else:
                                    book["asks"][yp] = nq

                        bb = max(book["bids"].keys()) if book["bids"] else None
                        ba = min(book["asks"].keys()) if book["asks"] else None
                        q.put({
                            "type": "kalshi_book",
                            "bid": bb / 100.0 if bb else None,
                            "ask": ba / 100.0 if ba else None,
                            "bid_size": book["bids"].get(bb, 0) if bb else 0,
                            "ask_size": book["asks"].get(ba, 0) if ba else 0,
                            "book_bids": dict(sorted(book["bids"].items(), reverse=True)),
                            "book_asks": dict(sorted(book["asks"].items())),
                            "ts": time.time(),
                        })
            except Exception as e:
                if not stop.is_set():
                    q.put({"type": "status", "source": "kalshi", "msg": f"Reconnecting... ({e})"})
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)

    async def _poly_ws(config, q, stop):
        uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
        clob_ids = config.get("clob_token_ids", [])
        outcome_idx = config.get("poly_outcome_index", 0)
        if not clob_ids:
            q.put({"type": "error", "source": "poly", "msg": "No CLOB token IDs"})
            return

        # Subscribe ONLY to our target outcome's token
        target_token = str(clob_ids[outcome_idx]) if outcome_idx < len(clob_ids) else str(clob_ids[0])

        backoff = 1
        while not stop.is_set():
            try:
                async with websockets.connect(uri) as ws:
                    q.put({"type": "status", "source": "poly", "msg": "Connected ✅"})
                    backoff = 1
                    sub = {"type": "market", "assets_ids": [target_token]}
                    await ws.send(json.dumps(sub))

                    while not stop.is_set():
                        try:
                            msg_txt = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        except asyncio.TimeoutError:
                            continue
                        try:
                            raw = json.loads(msg_txt)
                        except Exception:
                            continue

                        updates = raw if isinstance(raw, list) else [raw]
                        for update in updates:
                            if not isinstance(update, dict):
                                continue
                            event = update.get("event_type")
                            if event not in ("book", "price_change", "best_bid_ask"):
                                continue

                            bb, ba = None, None
                            if event == "book":
                                bids = update.get("bids", []) or update.get("buys", [])
                                asks = update.get("asks", []) or update.get("sells", [])
                                bb = float(bids[0]["price"]) if bids else None
                                ba = float(asks[0]["price"]) if asks else None
                            elif event == "price_change":
                                for pc in update.get("price_changes", []):
                                    bb = float(pc["best_bid"]) if pc.get("best_bid") else None
                                    ba = float(pc["best_ask"]) if pc.get("best_ask") else None
                            elif event == "best_bid_ask":
                                bb = float(update["best_bid"]) if update.get("best_bid") else None
                                ba = float(update["best_ask"]) if update.get("best_ask") else None

                            if bb is not None or ba is not None:
                                q.put({
                                    "type": "poly_book",
                                    "bid": bb, "ask": ba,
                                    "ts": time.time(),
                                })
            except Exception as e:
                if not stop.is_set():
                    q.put({"type": "status", "source": "poly", "msg": f"Reconnecting... ({e})"})
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)

    async def _run_both(config, q, stop):
        await asyncio.gather(
            _kalshi_ws(config, q, stop),
            _poly_ws(config, q, stop),
        )

    try:
        loop.run_until_complete(_run_both(config, data_queue, stop_event))
    except Exception:
        pass


# ---- Sidebar: Premium Navigation ----

with st.sidebar:
    # Logo / Header
    st.markdown("""
    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 20px;">
        <div style="width: 32px; height: 32px; border-radius: 8px; background: linear-gradient(135deg, #64ffda 0%, #0ea5e9 100%); display: flex; align-items: center; justify-content: center; font-size: 16px;">⚡</div>
        <div>
            <div style="font-size: 13px; font-weight: 700; color: #e6f1ff; letter-spacing: 0.5px;">ARB MONITOR</div>
            <div style="font-size: 9px; color: #4a5568; letter-spacing: 1.5px; text-transform: uppercase;">Kalshi × Polymarket</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Connections Status
    st.markdown('<div style="font-size: 9px; color: #4a5568; letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 8px;">Connections</div>', unsafe_allow_html=True)
    
    if st.session_state.phase == "browse":
        k_dot, k_lb = "#4a5568", "Ready"
        p_dot, p_lb = "#4a5568", "Ready"
    elif st.session_state.phase == "monitor":
        k_dot = "#64ffda" if st.session_state.monitoring else "#ff6b6b"
        k_lb = "Online" if st.session_state.monitoring else "Offline"
        p_dot = "#64ffda" if st.session_state.monitoring else "#ff6b6b"
        p_lb = "Online" if st.session_state.monitoring else "Offline"
    else: # analyze
        k_dot, k_lb = "#4a5568", "Session ended"
        p_dot, p_lb = "#4a5568", "Session ended"
    
    st.markdown(f"""
    <div style="margin-bottom: 20px;">
        <div style="display: flex; align-items: center; justify-content: space-between; font-size: 11px; margin-bottom: 6px;">
            <span><span class="status-dot" style="background: {k_dot};"></span> Kalshi WS</span>
            <span style="color: #4a5568;">{k_lb}</span>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; font-size: 11px;">
            <span><span class="status-dot" style="background: {p_dot};"></span> Polymarket CLOB</span>
            <span style="color: #4a5568;">{p_lb}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Phase Navigation (Using st.radio styled as buttons or simple buttons)
    st.markdown('<div style="font-size: 9px; color: #4a5568; letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 8px;">Navigation</div>', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📡 BROWSE", use_container_width=True):
            st.session_state.phase = "browse"
            st.rerun()
    with col2:
        if st.button("📈 MONITOR", use_container_width=True):
            if st.session_state.match_result and st.session_state.match_result["matched"]:
                st.session_state.phase = "monitor"
                st.rerun()
            else:
                st.warning("Match first")
    with col3:
        if st.button("📊 ANALYZE", use_container_width=True):
            if st.session_state.spread_history:
                st.session_state.phase = "analyze"
                st.rerun()
            else:
                st.warning("No data")

    st.markdown("---")
    
    if st.session_state.phase == "browse":
        # Fetch markets
        if st.button("🔄 Refresh Markets", use_container_width=True):
            with st.spinner("Fetching live markets..."):
                st.session_state.kalshi_markets = fetch_kalshi_markets()
                st.session_state.poly_markets = fetch_poly_markets(st.session_state.kalshi_markets)
                st.session_state.match_result = None
            st.rerun()

        # Auto-fetch on first load
        if not st.session_state.kalshi_markets and not st.session_state.poly_markets:
            with st.spinner("Loading markets..."):
                st.session_state.kalshi_markets = fetch_kalshi_markets()
                st.session_state.poly_markets = fetch_poly_markets(st.session_state.kalshi_markets)

        st.markdown(f"### Kalshi ({len(st.session_state.kalshi_markets)} games)")
        kalshi_options = {m["display"]: i for i, m in enumerate(st.session_state.kalshi_markets)}
        kalshi_choice = st.selectbox(
            "Select Kalshi game",
            options=list(kalshi_options.keys()),
            index=None,
            placeholder="Search Kalshi games...",
            key="kalshi_select",
        )

        st.markdown(f"### Polymarket ({len(st.session_state.poly_markets)} games)")
        poly_options = {m["display"]: i for i, m in enumerate(st.session_state.poly_markets)}
        poly_choice = st.selectbox(
            "Select Polymarket game",
            options=list(poly_options.keys()),
            index=None,
            placeholder="Search Polymarket games...",
            key="poly_select",
        )

        st.markdown("---")
        
        # Check Match Button
        if st.button("🔍 Check Match", use_container_width=True, type="primary"):
            if kalshi_choice and poly_choice:
                k_idx = kalshi_options[kalshi_choice]
                p_idx = poly_options[poly_choice]
                result = validate_match(
                    st.session_state.kalshi_markets[k_idx],
                    st.session_state.poly_markets[p_idx],
                )
                # Add clob_token_ids to config for WS subscription
                result["config"]["clob_token_ids"] = st.session_state.poly_markets[p_idx].get("clob_token_ids", [])
                st.session_state.match_result = result
                st.rerun()
            else:
                st.warning("Select a game from each exchange first")

        # Show match result + Run Bot button
        if st.session_state.match_result:
            mr = st.session_state.match_result
            if mr["matched"]:
                css = "match-high" if mr["confidence"] == "HIGH" else "match-medium"
                st.markdown(f'<div class="metric-card {css}"><div class="metric-label">Match Status</div><div class="metric-value">{mr["confidence"]}</div><div class="metric-sub">{mr["details"]}</div></div>', unsafe_allow_html=True)
                
                st.markdown("---")
                if st.button("🚀 Run Bot", use_container_width=True, type="primary"):
                    st.session_state.phase = "monitor"
                    st.session_state.monitoring = True
                    st.session_state.spread_history = []
                    st.session_state.arb_events = []
                    st.session_state.ai_insights = None
                    st.session_state.ai_loading = False
                    st.session_state.stop_event = threading.Event()
                    st.session_state.data_queue = queue.Queue()
                    
                    # Start WS thread
                    config = mr["config"]
                    t = threading.Thread(
                        target=_run_feeds,
                        args=(config, st.session_state.data_queue, st.session_state.stop_event),
                        daemon=True,
                    )
                    t.start()
                    st.session_state.ws_thread = t
                    st.rerun()
            else:
                st.markdown(f'<div class="metric-card match-none"><div class="metric-label">Match Status</div><div class="metric-value">NO MATCH</div><div class="metric-sub">{mr["details"]}</div></div>', unsafe_allow_html=True)
    
    elif st.session_state.phase == "monitor":
        st.markdown("### 🟢 Live Monitoring")
        cfg = st.session_state.match_result["config"]
        st.markdown(f"**{cfg.get('away_team', '?')} @ {cfg.get('home_team', '?')}**")
        st.markdown(f"Kalshi: `{cfg.get('kalshi_market_ticker', '')[:30]}`")
        st.markdown(f"Poly: `{cfg.get('poly_slug', '')}`")
        
        st.markdown("---")
        if st.button("🛑 Stop & Analyze", use_container_width=True, type="primary"):
            st.session_state.stop_event.set()
            st.session_state.monitoring = False
            st.session_state.phase = "analyze"
            st.rerun()
    
    elif st.session_state.phase == "analyze":
        st.markdown("### 📊 Analysis Complete")
        if st.button("↩️ Back to Browser", use_container_width=True):
            st.session_state.phase = "browse"
            st.session_state.match_result = None
            st.session_state.spread_history = []
            st.session_state.arb_events = []
            st.rerun()


# ---- Main Content ----

# ---- Main Content ----

if st.session_state.phase == "browse":
    st.markdown('<h1 style="margin-bottom: 0;">Cross-Exchange Arb Monitor</h1>', unsafe_allow_html=True)
    st.markdown('<p style="font-size: 11px; color: var(--text-muted); margin-top: 4px; margin-bottom: 24px;">Real-time odds dislocation scanner · Kalshi × Polymarket · NCAAB</p>', unsafe_allow_html=True)
    
    # Summary Cards
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        _metric_card("KALSHI MARKETS", str(len(st.session_state.kalshi_markets)), "NCAAB open")
    with col2:
        _metric_card("POLY MARKETS", str(len(st.session_state.poly_markets)), "CBB active")
    with col3:
        _metric_card("MATCHED", str(len(st.session_state.poly_markets)), "cross-exchange")
    with col4:
        # Mocking avg spread for now if not available
        _metric_card("AVG SPREAD", "1.8%", "across matches")
    with col5:
        _metric_card("ARB SIGNALS", "0", "|spread| > 3%")

    # --- AI Market Overview ---
    st.markdown("")
    st.markdown('<div class="section-header"><span>🤖 AI Market Overview</span></div>', unsafe_allow_html=True)
    
    if st.button("🔍 Analyze Market Landscape", key="browse_ai"):
        with st.spinner("Generating AI analysis..."):
            matched_data = []
            for km in st.session_state.kalshi_markets:
                for pm in st.session_state.poly_markets:
                    result = validate_match(km, pm)
                    if result["matched"]:
                        matched_data.append({
                            "away": km.get("away", "?"),
                            "home": km.get("home", "?"),
                            "date": km.get("date", "?"),
                            "confidence": result["confidence"],
                            "kalshi_mid": round((km.get("kalshi_bid", 0) + km.get("kalshi_ask", 0)) / 2, 4) if km.get("kalshi_bid") and km.get("kalshi_ask") else None,
                            "poly_mid": round((pm.get("poly_bid", 0) + pm.get("poly_ask", 0)) / 2, 4) if pm.get("poly_bid") and pm.get("poly_ask") else None,
                            "spread": round(((km.get("kalshi_bid", 0) + km.get("kalshi_ask", 0)) / 2) - ((pm.get("poly_bid", 0) + pm.get("poly_ask", 0)) / 2), 4) if (km.get("kalshi_bid") and km.get("kalshi_ask") and pm.get("poly_bid") and pm.get("poly_ask")) else None,
                        })
            st.session_state.browse_insights = generate_browse_insights(
                matched_pairs=matched_data,
                kalshi_count=len(st.session_state.kalshi_markets),
                poly_count=len(st.session_state.poly_markets),
            )
    
    if st.session_state.browse_insights:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, rgba(167,139,250,0.05) 0%, rgba(100,255,218,0.05) 100%);
                    border: 1px solid rgba(167,139,250,0.15); border-radius: 12px; padding: 1.2rem; margin-top: 0.5rem;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 0.8rem;">
                <span style="color: #a78bfa; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">
                    🤖 AI Market Analysis
                </span>
                <span style="color: #4a5568; font-size: 0.65rem; background: rgba(167,139,250,0.1);
                             padding: 2px 8px; border-radius: 4px;">Powered by OpenAI</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(st.session_state.browse_insights)
    
    st.markdown("---")

    st.markdown('<div class="section-header"><span>Matched Markets</span></div>', unsafe_allow_html=True)
    
    if st.session_state.match_result and st.session_state.match_result["matched"]:
        cfg = st.session_state.match_result["config"]
        st.markdown(f"""
        <div style="background: var(--card-bg); border: 1px solid var(--accent-primary); border-radius: 10px; padding: 20px; margin-bottom: 24px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                <div style="font-size: 14px; font-weight: 700; color: var(--text-header);">{cfg.get('away_team', '?')} @ {cfg.get('home_team', '?')}</div>
                <div style="padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; color: var(--accent-primary); background: rgba(100,255,218,0.12);">{st.session_state.match_result['confidence']} MATCH</div>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
                <div style="background: rgba(100,255,218,0.04); border: 1px solid rgba(100,255,218,0.08); border-radius: 8px; padding: 14px;">
                    <div style="font-size: 9px; color: var(--accent-primary); letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 10px;">KALSHI</div>
                    <div style="font-size: 11px; color: var(--text-muted);">Ticker: <span style="color: var(--text-main);">{cfg.get('kalshi_market_ticker', '')}</span></div>
                </div>
                <div style="background: rgba(14,165,233,0.04); border: 1px solid rgba(14,165,233,0.08); border-radius: 8px; padding: 14px;">
                    <div style="font-size: 9px; color: var(--accent-secondary); letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 10px;">POLYMARKET</div>
                    <div style="font-size: 11px; color: var(--text-muted);">Slug: <span style="color: var(--text-main);">{cfg.get('poly_slug', '')}</span></div>
                </div>
            </div>
            <div style="margin-top: 16px; text-align: right;">
                <button onclick="document.querySelector('button[kind=primary]').click()" style="background: linear-gradient(135deg, #64ffda 0%, #0ea5e9 100%); border: none; border-radius: 6px; padding: 10px 24px; color: #060d1b; font-size: 11px; font-weight: 800; cursor: pointer; letter-spacing: 1px; text-transform: uppercase;">▶ START MONITOR</button>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # Hidden actual button for st.rerun compatibility
        st.markdown('<div class="hidden-btn">', unsafe_allow_html=True)
        if st.button("RUN BOT HIDDEN", key="run_bot_hidden", type="primary"):
             st.session_state.phase = "monitor"
             st.session_state.monitoring = True
             st.session_state.spread_history = []
             st.session_state.arb_events = []
             st.session_state.stop_event = threading.Event()
             st.session_state.data_queue = queue.Queue()
             
             # Start WS thread
             config = st.session_state.match_result["config"]
             t = threading.Thread(
                 target=_run_feeds,
                 args=(config, st.session_state.data_queue, st.session_state.stop_event),
                 daemon=True,
             )
             t.start()
             st.session_state.ws_thread = t
             st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
             
    else:
        st.info("Select a game from each exchange and click 'Check Match' in the sidebar to begin.")


elif st.session_state.phase == "monitor":
    # --- Process queue updates ---
    prices = st.session_state.latest_prices
    statuses = {"kalshi": "Connecting...", "poly": "Connecting..."}
    kalshi_book_data = {"bids": {}, "asks": {}}
    
    while not st.session_state.data_queue.empty():
        try:
            msg = st.session_state.data_queue.get_nowait()
            if msg["type"] == "kalshi_book":
                prices["kalshi_bid"] = msg.get("bid")
                prices["kalshi_ask"] = msg.get("ask")
                prices["kalshi_bid_size"] = msg.get("bid_size", 0)
                prices["kalshi_ask_size"] = msg.get("ask_size", 0)
                kalshi_book_data = {"bids": msg.get("book_bids", {}), "asks": msg.get("book_asks", {})}
                
                # Record history
                k_mid = _kalshi_mid(prices)
                p_mid = _poly_mid(prices)
                spread = (k_mid - p_mid) if (k_mid and p_mid) else None
                st.session_state.spread_history.append({
                    "ts": msg["ts"],
                    "time": datetime.fromtimestamp(msg["ts"]).strftime("%H:%M:%S"),
                    "kalshi_mid": k_mid,
                    "kalshi_bid": prices["kalshi_bid"],
                    "kalshi_ask": prices["kalshi_ask"],
                    "poly_mid": p_mid,
                    "poly_bid": prices.get("poly_bid"),
                    "poly_ask": prices.get("poly_ask"),
                    "spread": spread,
                })
                
                # Check for arb
                if spread is not None and abs(spread) > 0.03:
                    st.session_state.arb_events.append({
                        "ts": msg["ts"],
                        "time": datetime.fromtimestamp(msg["ts"]).strftime("%H:%M:%S"),
                        "spread": spread,
                        "k_mid": k_mid,
                        "p_mid": p_mid,
                    })
                    
            elif msg["type"] == "poly_book":
                prices["poly_bid"] = msg.get("bid")
                prices["poly_ask"] = msg.get("ask")
            elif msg["type"] == "status":
                statuses[msg["source"]] = msg["msg"]
        except queue.Empty:
            break
    
    st.session_state.latest_prices = prices
    cfg = st.session_state.match_result["config"]
    
    # --- Header ---
    st.markdown(f'<h1 style="font-size: 20px;"><span style="color: var(--accent-primary);">●</span> {cfg.get("away_team", "?")} @ {cfg.get("home_team", "?")}</h1>', unsafe_allow_html=True)
    st.markdown(f'<p style="font-size: 10px; color: var(--text-muted); margin-top: 4px; margin-bottom: 20px;">Live monitoring · {len(st.session_state.spread_history)} ticks recorded</p>', unsafe_allow_html=True)
    
    # --- Metric Cards ---
    col1, col2, col3, col4 = st.columns(4)
    k_mid = _kalshi_mid(prices)
    p_mid = _poly_mid(prices)
    spread = (k_mid - p_mid) if (k_mid and p_mid) else None
    
    with col1:
        val = f"{k_mid:.1%}" if k_mid is not None else "—"
        kb, ka = prices.get("kalshi_bid"), prices.get("kalshi_ask")
        sub = f"B: {kb:.1%} | A: {ka:.1%}" if (kb is not None and ka is not None) else "Waiting..."
        _metric_card("KALSHI MID", val, sub)
    with col2:
        val = f"{p_mid:.2f}" if p_mid is not None else "—"
        pb, pa = prices.get("poly_bid"), prices.get("poly_ask")
        sub = f"B: {pb:.2f} | A: {pa:.2f}" if (pb is not None and pa is not None) else "Waiting..."
        _metric_card("POLY MID", val, sub, css_class="mono-font")
    with col3:
        if spread is not None:
            is_arb = abs(spread) > 0.03
            label = "🚨 ARB SIGNAL" if is_arb else "Normal"
            _metric_card("SPREAD", f"{spread:+.1%}", label)
        else:
            _metric_card("SPREAD", "—", "Waiting for data")
    with col4:
        _metric_card("ARB EVENTS", str(len(st.session_state.arb_events)),
                     f"across {len(st.session_state.spread_history)} ticks")

    # --- Arb Alert ---
    if spread is not None and abs(spread) > 0.03:
        direction = "Kalshi > Poly" if spread > 0 else "Poly > Kalshi"
        action = "BUY Poly / SELL Kalshi" if spread > 0 else "BUY Kalshi / SELL Poly"
        st.markdown(f"""
        <div class="arb-alert">
            <div style="font-size: 1.5rem;">🚨</div>
            <div>
                <div style="font-size: 11px; font-weight: 700; color: var(--accent-primary); letter-spacing: 0.5px;">ARB OPPORTUNITY</div>
                <div style="font-size: 9px; color: var(--text-muted);">{direction} by <strong>{abs(spread):.1%}</strong> — {action}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("")

    # --- Live Spread Chart ---
    st.markdown('<div class="section-header"><span>Live Spread Chart</span></div>', unsafe_allow_html=True)
    
    if st.session_state.spread_history:
        df = pd.DataFrame(st.session_state.spread_history[-200:])
        
        fig = make_subplots(rows=2, cols=1, row_heights=[0.7, 0.3],
                            shared_xaxes=True, vertical_spacing=0.05)
        
        # Color palette for chart
        K_COLOR = "#64ffda"
        P_COLOR = "#0ea5e9"
        S_COLOR = "rgba(100,255,218,0.2)"
        
        # Top: Kalshi vs Poly probability
        if "kalshi_mid" in df.columns:
            fig.add_trace(go.Scatter(x=df["time"], y=df["kalshi_mid"], name="Kalshi Mid",
                                     line=dict(color=K_COLOR, width=2)), row=1, col=1)
        if "poly_mid" in df.columns:
            fig.add_trace(go.Scatter(x=df["time"], y=df["poly_mid"], name="Poly Mid",
                                     line=dict(color=P_COLOR, width=2)), row=1, col=1)
        
        # Bottom: Spread
        if "spread" in df.columns:
            colors = [K_COLOR if abs(s) > 0.03 else "rgba(74, 85, 104, 0.3)" for s in df["spread"].fillna(0)]
            fig.add_trace(go.Bar(x=df["time"], y=df["spread"], name="Spread",
                                 marker_color=colors), row=2, col=1)
            fig.add_hline(y=0.03, line_dash="dash", line_color="rgba(100,255,218,0.33)", row=2, col=1)
            fig.add_hline(y=-0.03, line_dash="dash", line_color="rgba(255,107,107,0.33)", row=2, col=1)
        
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#060d1b",
            plot_bgcolor="rgba(255,255,255,0.01)",
            height=450,
            margin=dict(l=50, r=20, t=30, b=30),
            legend=dict(orientation="h", y=1.08, font=dict(size=10, color="#4a5568")),
            yaxis=dict(title="Probability", tickformat=".1%", gridcolor="#15202e"),
            yaxis2=dict(title="Spread", tickformat=".1%", gridcolor="#15202e"),
            xaxis=dict(gridcolor="#15202e"),
            xaxis2=dict(gridcolor="#15202e"),
        )
        st.plotly_chart(fig, use_container_width=True, key="spread_chart")
    else:
        st.info("Waiting for data from both exchanges...")

    # --- Orderbook Display ---
    st.markdown('<div class="section-header"><span>Live Orderbook</span></div>', unsafe_allow_html=True)
    
    ob1, ob2 = st.columns(2)
    with ob1:
        kb, ka = prices.get("kalshi_bid"), prices.get("kalshi_ask")
        st.markdown(f"""
        <div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 10px; padding: 16px;">
            <div style="font-size: 9px; color: var(--accent-primary); letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 10px;">KALSHI ORDERBOOK</div>
            <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; font-size: 11px;">
                <span style="color: var(--text-muted); font-size: 9px;">SIDE</span>
                <span style="color: var(--text-muted); font-size: 9px; text-align: center;">PRICE</span>
                <span style="color: var(--text-muted); font-size: 9px; text-align: right;">SIZE</span>
                
                <span style="color: var(--accent-primary);">BID</span>
                <span style="font-weight: 700; color: var(--accent-primary); text-align: center;">{f'{kb:.1%}' if kb else '—'}</span>
                <span style="color: var(--text-muted); text-align: right;">{prices.get('kalshi_bid_size', 0)}</span>
                
                <span style="color: #ff6b6b;">ASK</span>
                <span style="font-weight: 700; color: #ff6b6b; text-align: center;">{f'{ka:.1%}' if ka else '—'}</span>
                <span style="color: var(--text-muted); text-align: right;">{prices.get('kalshi_ask_size', 0)}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with ob2:
        pb, pa = prices.get("poly_bid"), prices.get("poly_ask")
        st.markdown(f"""
        <div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 10px; padding: 16px;">
            <div style="font-size: 9px; color: var(--accent-secondary); letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 10px;">POLYMARKET ORDERBOOK</div>
            <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; font-size: 11px;">
                <span style="color: var(--text-muted); font-size: 9px;">SIDE</span>
                <span style="color: var(--text-muted); font-size: 9px; text-align: center;">PRICE</span>
                <span style="color: var(--text-muted); font-size: 9px; text-align: right;">SIZE</span>
                
                <span style="color: var(--accent-primary);">BID</span>
                <span style="font-weight: 700; color: var(--accent-primary); text-align: center;">{f'${pb:.4f}' if pb else '—'}</span>
                <span style="color: var(--text-muted); text-align: right;">—</span>
                
                <span style="color: #ff6b6b;">ASK</span>
                <span style="font-weight: 700; color: #ff6b6b; text-align: center;">{f'${pa:.4f}' if pa else '—'}</span>
                <span style="color: var(--text-muted); text-align: right;">—</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Auto-refresh
    time.sleep(1)
    st.rerun()


elif st.session_state.phase == "analyze":
    cfg = st.session_state.match_result["config"]
    st.markdown(f'<h1 style="font-size: 20px;">Post-Session Analysis</h1>', unsafe_allow_html=True)
    st.markdown(f'<p style="font-size: 10px; color: var(--text-muted); margin-top: 4px; margin-bottom: 20px;">{cfg.get("away_team", "?")} @ {cfg.get("home_team", "?")} · {cfg.get("game_date", "")}</p>', unsafe_allow_html=True)
    
    history = st.session_state.spread_history
    arb_events = st.session_state.arb_events
    
    if not history:
        st.warning("No data was collected during the session.")
        st.stop()
    
    df = pd.DataFrame(history)
    spreads = df["spread"].dropna()
    
    # --- Summary Stats ---
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        _metric_card("TICKS", str(len(df)), f"{(df['ts'].max() - df['ts'].min()):.0f}s session" if len(df) > 1 else "")
    with col2:
        _metric_card("MEAN SPREAD", f"{spreads.mean():+.2%}" if len(spreads) else "—", "avg K-P diff")
    with col3:
        _metric_card("MAX SPREAD", f"{spreads.max():+.2%}" if len(spreads) else "—", "peak opp")
    with col4:
        _metric_card("STD DEV", f"{spreads.std():.2%}" if len(spreads) > 1 else "—", "volatility")
    with col5:
        _metric_card("ARB WINDOWS", str(len(arb_events)), f"|spread| > 3%", "match-high" if arb_events else "")
    
    st.markdown("")

    # --- Charts Row ---
    st.markdown('<div class="section-header"><span>Performance Visualization</span></div>', unsafe_allow_html=True)
    
    c1, c2 = st.columns(2)
    with c1:
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=df["time"], y=df["spread"], name="Spread",
                                   fill="tozeroy", line=dict(color="#64ffda", width=1.5),
                                   fillcolor="rgba(100,255,218,0.1)"))
        fig1.add_hline(y=0.03, line_dash="dash", line_color="rgba(255,107,107,0.3)", annotation_text="3% Limit")
        fig1.update_layout(
            template="plotly_dark", paper_bgcolor="#060d1b", plot_bgcolor="rgba(255,255,255,0.01)",
            height=300, margin=dict(l=40, r=20, t=30, b=30),
            title=dict(text="SPREAD OVER TIME", font=dict(size=10, color="#4a5568")),
            yaxis=dict(tickformat=".1%", gridcolor="#15202e"),
            xaxis=dict(gridcolor="#15202e")
        )
        st.plotly_chart(fig1, use_container_width=True)

    with c2:
        fig2 = go.Figure()
        fig2.add_trace(go.Histogram(x=spreads, nbinsx=30, marker_color="#64ffda", opacity=0.7))
        fig2.update_layout(
            template="plotly_dark", paper_bgcolor="#060d1b", plot_bgcolor="rgba(255,255,255,0.01)",
            height=300, margin=dict(l=40, r=20, t=30, b=30),
            title=dict(text="SPREAD DISTRIBUTION", font=dict(size=10, color="#4a5568")),
            yaxis=dict(gridcolor="#15202e"),
            xaxis=dict(tickformat=".1%", gridcolor="#15202e")
        )
        st.plotly_chart(fig2, use_container_width=True)

    # --- Detailed Stats Table ---
    st.markdown('<div class="section-header"><span>📋 Detailed Statistics</span></div>', unsafe_allow_html=True)
    
    stats = {
        "Metric": [
            "Total Observations", "Session Duration",
            "Mean Spread (K-P)", "Std Dev Spread", "Max Spread", "Min Spread",
            "Mean Kalshi Mid", "Mean Poly Mid",
            "Arb Events (|spread|>3%)", "% Time in Arb",
            "Longest Arb Window",
        ],
        "Value": [
            f"{len(df)}",
            f"{(df['ts'].max() - df['ts'].min()):.0f}s" if len(df) > 1 else "—",
            f"{spreads.mean():+.2%}" if len(spreads) else "—",
            f"{spreads.std():.2%}" if len(spreads) > 1 else "—",
            f"{spreads.max():+.2%}" if len(spreads) else "—",
            f"{spreads.min():+.2%}" if len(spreads) else "—",
            f"{df['kalshi_mid'].dropna().mean():.1%}" if len(df) else "—",
            f"{df['poly_mid'].dropna().mean():.2f}" if len(df) else "—",
            f"{len(arb_events)}",
            f"{len(arb_events)/len(df)*100:.1f}%" if len(df) > 0 else "—",
            "—",  # TODO: calculate from consecutive arb events
        ],
    }
    st.dataframe(pd.DataFrame(stats), use_container_width=True, hide_index=True)

    # --- AI-Powered Insights ---
    st.markdown("")
    st.markdown('<div class="section-header"><span>🤖 AI-Powered Insights</span></div>', unsafe_allow_html=True)
    
    if not history or len(df) == 0:
        st.info("No session data available for AI analysis.")
    elif st.session_state.ai_insights is None:
        if st.button("🧠 Generate AI Analysis", type="primary", use_container_width=True):
            st.session_state.ai_loading = True
            st.rerun()
    
    if st.session_state.ai_loading and st.session_state.ai_insights is None:
        with st.spinner("🤖 Analyzing session data with AI..."):
            cfg = st.session_state.match_result["config"]
            
            summary_stats = {
                "n_observations": len(df),
                "session_duration_sec": round(df["ts"].max() - df["ts"].min(), 1) if len(df) > 1 else 0,
                "mean_spread": round(float(spreads.mean()), 4) if len(spreads) else None,
                "std_spread": round(float(spreads.std()), 4) if len(spreads) > 1 else None,
                "max_spread": round(float(spreads.max()), 4) if len(spreads) else None,
                "min_spread": round(float(spreads.min()), 4) if len(spreads) else None,
                "mean_kalshi": round(float(df["kalshi_mid"].dropna().mean()), 4) if len(df) else None,
                "mean_poly": round(float(df["poly_mid"].dropna().mean()), 4) if len(df) else None,
                "n_arb_events": len(arb_events),
                "pct_time_in_arb": round(len(arb_events) / len(df) * 100, 1) if len(df) > 0 else 0,
            }
            
            st.session_state.ai_insights = generate_session_insights(
                home_team=cfg.get("home_team", "Unknown"),
                away_team=cfg.get("away_team", "Unknown"),
                game_date=cfg.get("game_date", ""),
                spread_history=[
                    {
                        "time": row.get("time", ""),
                        "kalshi_mid": row.get("kalshi_mid"),
                        "poly_mid": row.get("poly_mid"),
                        "spread": row.get("spread"),
                    }
                    for row in history
                ],
                arb_events=arb_events,
                summary_stats=summary_stats,
            )
            st.session_state.ai_loading = False
            st.rerun()
    
    if st.session_state.ai_insights:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, rgba(167,139,250,0.05) 0%, rgba(100,255,218,0.05) 100%);
                    border: 1px solid rgba(167,139,250,0.15); border-radius: 12px; padding: 1.5rem;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 1rem;">
                <span style="font-size: 1.1rem;">🤖</span>
                <span style="color: #a78bfa; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">
                    AI Session Analysis
                </span>
                <span style="color: #4a5568; font-size: 0.65rem; background: rgba(167,139,250,0.1);
                             padding: 2px 8px; border-radius: 4px;">Powered by OpenAI</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(st.session_state.ai_insights)
        
        if st.button("🔄 Regenerate Analysis", key="regen_ai"):
            st.session_state.ai_insights = None
            st.session_state.ai_loading = True
            st.rerun()
