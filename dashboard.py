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
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    html, body, [class*="st-"] {
        font-family: 'Inter', sans-serif;
    }
    
    .main .block-container {
        padding-top: 1.5rem;
        max-width: 1400px;
    }
    
    /* Metric cards */
    .metric-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #30475e;
        border-radius: 12px;
        padding: 1.2rem;
        text-align: center;
        transition: transform 0.2s;
    }
    .metric-card:hover { transform: translateY(-2px); }
    .metric-label { color: #8892b0; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1px; }
    .metric-value { color: #e6f1ff; font-size: 1.8rem; font-weight: 700; margin: 0.3rem 0; }
    .metric-sub { color: #64ffda; font-size: 0.85rem; }
    
    /* Match status */
    .match-high { background: linear-gradient(135deg, #0a3d2e 0%, #0f4c3a 100%); border-color: #64ffda; }
    .match-medium { background: linear-gradient(135deg, #3d3a0a 0%, #4c4a0f 100%); border-color: #ffd93d; }
    .match-none { background: linear-gradient(135deg, #3d0a0a 0%, #4c0f0f 100%); border-color: #ff6b6b; }
    
    /* Orderbook */
    .ob-bid { color: #64ffda; font-weight: 600; }
    .ob-ask { color: #ff6b6b; font-weight: 600; }
    .ob-header { color: #8892b0; font-size: 0.7rem; text-transform: uppercase; }
    
    /* Section headers */
    .section-header {
        background: linear-gradient(90deg, #64ffda22 0%, transparent 100%);
        border-left: 3px solid #64ffda;
        padding: 0.5rem 1rem;
        margin: 1rem 0;
        font-weight: 600;
        color: #ccd6f6;
    }
    
    /* Arb alert */
    .arb-alert {
        background: linear-gradient(135deg, #0a3d2e 0%, #16213e 100%);
        border: 2px solid #64ffda;
        border-radius: 12px;
        padding: 1rem;
        text-align: center;
        animation: pulse 2s ease-in-out infinite;
    }
    @keyframes pulse {
        0%, 100% { box-shadow: 0 0 5px #64ffda33; }
        50% { box-shadow: 0 0 20px #64ffda66; }
    }
    
    div[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0a192f 0%, #112240 100%);
    }
    
    .stSelectbox label, .stRadio label { color: #ccd6f6 !important; }
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


# ---- Helper Functions ----

def _metric_card(label, value, sub="", css_class=""):
    cls = f"metric-card {css_class}"
    st.markdown(f"""
    <div class="{cls}">
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


# ---- Sidebar: Market Browser ----

with st.sidebar:
    st.markdown("## ⚡ Arb Monitor")
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

if st.session_state.phase == "browse":
    st.markdown("# ⚡ Cross-Exchange Arb Monitor")
    st.markdown("Select a game on **Kalshi** and **Polymarket** from the sidebar, then check if they match.")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        _metric_card("Kalshi Games", str(len(st.session_state.kalshi_markets)), "NCAAB Active")
    with col2:
        _metric_card("Poly Games", str(len(st.session_state.poly_markets)), "CBB Active")
    with col3:
        status = "Ready" if not st.session_state.match_result else (
            st.session_state.match_result["confidence"] + " Match")
        _metric_card("Match Status", status, "Select games →")

    if st.session_state.match_result and st.session_state.match_result["matched"]:
        cfg = st.session_state.match_result["config"]
        st.markdown("---")
        st.markdown('<div class="section-header">✅ Matched Game Configuration</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Kalshi**")
            st.code(f"Ticker: {cfg.get('kalshi_market_ticker', '')}\nEvent: {cfg.get('kalshi_event_ticker', '')}\nTarget: {cfg.get('kalshi_target_outcome', '')}")
        with c2:
            st.markdown("**Polymarket**")
            st.code(f"Slug: {cfg.get('poly_slug', '')}\nCondition: {cfg.get('poly_condition_id', '')[:30]}...\nOutcome Index: {cfg.get('poly_outcome_index', 0)}")


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
    st.markdown(f"# 🟢 {cfg.get('away_team', '?')} @ {cfg.get('home_team', '?')}")
    
    # --- Metric Cards ---
    col1, col2, col3, col4 = st.columns(4)
    k_mid = _kalshi_mid(prices)
    p_mid = _poly_mid(prices)
    spread = (k_mid - p_mid) if (k_mid and p_mid) else None
    
    with col1:
        val = f"{k_mid:.1%}" if k_mid is not None else "—"
        kb, ka = prices.get("kalshi_bid"), prices.get("kalshi_ask")
        sub = f"Bid: {kb:.1%} | Ask: {ka:.1%}" if (kb is not None and ka is not None) else "Waiting..."
        _metric_card("Kalshi Mid", val, sub)
    with col2:
        val = f"{p_mid:.2f}" if p_mid is not None else "—"
        pb, pa = prices.get("poly_bid"), prices.get("poly_ask")
        sub = f"Bid: {pb:.2f} | Ask: {pa:.2f}" if (pb is not None and pa is not None) else "Waiting..."
        _metric_card("Poly Mid", val, sub)
    with col3:
        if spread is not None:
            color = "#64ffda" if abs(spread) > 0.03 else "#8892b0"
            _metric_card("Spread", f"{spread:+.1%}", f"{'🚨 ARB SIGNAL' if abs(spread) > 0.03 else 'Normal'}")
        else:
            _metric_card("Spread", "—", "Waiting for data")
    with col4:
        _metric_card("Arb Events", str(len(st.session_state.arb_events)),
                     f"{len(st.session_state.spread_history)} ticks")

    # --- Arb Alert ---
    if spread is not None and abs(spread) > 0.03:
        direction = "Kalshi > Poly" if spread > 0 else "Poly > Kalshi"
        action = "BUY Poly / SELL Kalshi" if spread > 0 else "BUY Kalshi / SELL Poly"
        st.markdown(f"""
        <div class="arb-alert">
            <div style="font-size: 1.5rem; font-weight: 700; color: #64ffda;">🚨 ARB OPPORTUNITY</div>
            <div style="color: #ccd6f6; margin-top: 0.5rem;">
                {direction} by <strong>{abs(spread):.1%}</strong> — {action}
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("")

    # --- Live Spread Chart ---
    st.markdown('<div class="section-header">📈 Live Spread Chart</div>', unsafe_allow_html=True)
    
    if st.session_state.spread_history:
        df = pd.DataFrame(st.session_state.spread_history[-200:])
        
        fig = make_subplots(rows=2, cols=1, row_heights=[0.7, 0.3],
                            shared_xaxes=True, vertical_spacing=0.05)
        
        # Top: Kalshi vs Poly probability
        if "kalshi_mid" in df.columns:
            fig.add_trace(go.Scatter(x=df["time"], y=df["kalshi_mid"], name="Kalshi Mid",
                                     line=dict(color="#64ffda", width=2)), row=1, col=1)
        if "poly_mid" in df.columns:
            fig.add_trace(go.Scatter(x=df["time"], y=df["poly_mid"], name="Poly Mid",
                                     line=dict(color="#ffd93d", width=2)), row=1, col=1)
        
        # Bottom: Spread
        if "spread" in df.columns:
            colors = ["#64ffda" if abs(s) > 0.03 else "#30475e" for s in df["spread"].fillna(0)]
            fig.add_trace(go.Bar(x=df["time"], y=df["spread"], name="Spread",
                                 marker_color=colors), row=2, col=1)
            fig.add_hline(y=0.03, line_dash="dash", line_color="rgba(100,255,218,0.33)", row=2, col=1)
            fig.add_hline(y=-0.03, line_dash="dash", line_color="rgba(255,107,107,0.33)", row=2, col=1)
        
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0a192f",
            plot_bgcolor="#112240",
            height=450,
            margin=dict(l=50, r=20, t=30, b=30),
            legend=dict(orientation="h", y=1.08),
            yaxis=dict(title="Probability", tickformat=".1%"),
            yaxis2=dict(title="Spread", tickformat=".1%"),
        )
        st.plotly_chart(fig, use_container_width=True, key="spread_chart")
    else:
        st.info("Waiting for data from both exchanges...")

    # --- Orderbook Display ---
    st.markdown('<div class="section-header">📊 Orderbook</div>', unsafe_allow_html=True)
    
    ob1, ob2 = st.columns(2)
    with ob1:
        st.markdown("**Kalshi**")
        kb, ka = prices.get("kalshi_bid"), prices.get("kalshi_ask")
        if kb is not None and ka is not None:
            k_spread = ka - kb
            st.markdown(f"""
            | | Price | Size |
            |---|---|---|
            | 🟢 Bid | **{kb:.1%}** | {prices.get('kalshi_bid_size', 0)} |
            | 🔴 Ask | **{ka:.1%}** | {prices.get('kalshi_ask_size', 0)} |
            | Spread | {k_spread:.1%} | |
            """)
        elif kb is not None:
            st.markdown(f"🟢 Bid: **{kb:.1%}** (waiting for ask...)")
        else:
            st.info("Connecting to Kalshi...")

    with ob2:
        st.markdown("**Polymarket**")
        pb, pa = prices.get("poly_bid"), prices.get("poly_ask")
        if pb is not None and pa is not None:
            p_spread = pa - pb
            st.markdown(f"""
            | | Price | |
            |---|---|---|
            | 🟢 Bid | **{pb:.4f}** | |
            | 🔴 Ask | **{pa:.4f}** | |
            | Spread | {p_spread:.4f} | |
            """)
        elif pb is not None:
            st.markdown(f"🟢 Bid: **{pb:.4f}** (waiting for ask...)")
        else:
            st.info("Connecting to Polymarket...")

    # Auto-refresh
    time.sleep(1)
    st.rerun()


elif st.session_state.phase == "analyze":
    cfg = st.session_state.match_result["config"]
    st.markdown(f"# 📊 Post-Session Analysis")
    st.markdown(f"**{cfg.get('away_team', '?')} @ {cfg.get('home_team', '?')}** | {cfg.get('game_date', '')}")
    
    history = st.session_state.spread_history
    arb_events = st.session_state.arb_events
    
    if not history:
        st.warning("No data was collected during the session.")
        st.stop()
    
    df = pd.DataFrame(history)
    
    # --- Summary Stats ---
    st.markdown('<div class="section-header">📋 Summary Statistics</div>', unsafe_allow_html=True)
    
    spreads = df["spread"].dropna()
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        _metric_card("Observations", str(len(df)), f"{(df['ts'].max() - df['ts'].min()):.0f}s session" if len(df) > 1 else "")
    with col2:
        _metric_card("Mean Spread", f"{spreads.mean():+.2%}" if len(spreads) else "—", "avg K-P difference")
    with col3:
        _metric_card("Max Spread", f"{spreads.max():+.2%}" if len(spreads) else "—", "peak opportunity")
    with col4:
        _metric_card("Min Spread", f"{spreads.min():+.2%}" if len(spreads) else "—", "deepest reversal")
    with col5:
        _metric_card("Arb Events", str(len(arb_events)), f"|spread| > 3% threshold", "match-high" if arb_events else "")
    
    st.markdown("")

    # --- Spread Time Series ---
    st.markdown('<div class="section-header">📈 Spread Over Time</div>', unsafe_allow_html=True)
    
    fig1 = make_subplots(rows=2, cols=1, row_heights=[0.6, 0.4],
                          shared_xaxes=True, vertical_spacing=0.08,
                          subplot_titles=("Probability Comparison", "Kalshi-Poly Spread"))
    
    fig1.add_trace(go.Scatter(x=df["time"], y=df["kalshi_mid"], name="Kalshi",
                               line=dict(color="#64ffda", width=2)), row=1, col=1)
    fig1.add_trace(go.Scatter(x=df["time"], y=df["poly_mid"], name="Poly",
                               line=dict(color="#ffd93d", width=2)), row=1, col=1)
    
    # Spread with fill
    fig1.add_trace(go.Scatter(x=df["time"], y=df["spread"], name="Spread",
                               fill="tozeroy", line=dict(color="#64ffda", width=1.5),
                               fillcolor="rgba(100,255,218,0.15)"), row=2, col=1)
    fig1.add_hline(y=0.03, line_dash="dash", line_color="rgba(100,255,218,0.33)", row=2, col=1,
                    annotation_text="3% threshold")
    fig1.add_hline(y=-0.03, line_dash="dash", line_color="rgba(255,107,107,0.33)", row=2, col=1)
    fig1.add_hline(y=0, line_color="rgba(255,255,255,0.13)", row=2, col=1)
    
    # Mark arb events
    if arb_events:
        arb_df = pd.DataFrame(arb_events)
        fig1.add_trace(go.Scatter(x=arb_df["time"], y=arb_df["spread"],
                                   mode="markers", name="Arb Signal",
                                   marker=dict(color="#ff6b6b", size=8, symbol="diamond")),
                        row=2, col=1)
    
    fig1.update_layout(
        template="plotly_dark", paper_bgcolor="#0a192f", plot_bgcolor="#112240",
        height=550, margin=dict(l=50, r=20, t=40, b=30),
        legend=dict(orientation="h", y=1.08),
        yaxis=dict(tickformat=".1%"), yaxis2=dict(tickformat=".2%"),
    )
    st.plotly_chart(fig1, use_container_width=True)

    # --- Spread Distribution ---
    an1, an2 = st.columns(2)
    
    with an1:
        st.markdown('<div class="section-header">📊 Spread Distribution</div>', unsafe_allow_html=True)
        fig2 = go.Figure()
        fig2.add_trace(go.Histogram(
            x=spreads, nbinsx=40, name="Spread",
            marker_color="#64ffda", opacity=0.8,
        ))
        fig2.add_vline(x=0.03, line_dash="dash", line_color="#ff6b6b",
                        annotation_text="3% threshold")
        fig2.add_vline(x=-0.03, line_dash="dash", line_color="#ff6b6b")
        fig2.add_vline(x=spreads.mean(), line_dash="solid", line_color="#ffd93d",
                        annotation_text=f"Mean: {spreads.mean():.2%}")
        fig2.update_layout(
            template="plotly_dark", paper_bgcolor="#0a192f", plot_bgcolor="#112240",
            height=350, margin=dict(l=50, r=20, t=30, b=30),
            xaxis=dict(title="Spread (K-P)", tickformat=".1%"),
            yaxis=dict(title="Count"),
            showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True)
    
    with an2:
        st.markdown('<div class="section-header">🎯 Arb Windows</div>', unsafe_allow_html=True)
        if arb_events:
            arb_df = pd.DataFrame(arb_events)
            fig3 = go.Figure()
            colors = ["#64ffda" if s > 0 else "#ff6b6b" for s in arb_df["spread"]]
            fig3.add_trace(go.Scatter(
                x=arb_df["time"], y=arb_df["spread"],
                mode="markers+lines", name="Arb Events",
                marker=dict(color=colors, size=10, symbol="diamond"),
                line=dict(color="#30475e", width=1),
            ))
            fig3.add_hline(y=0, line_color="rgba(255,255,255,0.13)")
            fig3.update_layout(
                template="plotly_dark", paper_bgcolor="#0a192f", plot_bgcolor="#112240",
                height=350, margin=dict(l=50, r=20, t=30, b=30),
                xaxis=dict(title="Time"),
                yaxis=dict(title="Spread", tickformat=".1%"),
                showlegend=False,
            )
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("No arb events detected during this session (|spread| > 3%)")

    # --- Detailed Stats Table ---
    st.markdown('<div class="section-header">📋 Detailed Statistics</div>', unsafe_allow_html=True)
    
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
