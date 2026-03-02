"""
=============================================================================
CURSOR INSTRUCTIONS: AI Insights Integration for dashboard.py
=============================================================================

This file contains the EXACT changes needed to add OpenAI-powered AI insights
to your Streamlit arb monitor dashboard. 

PREREQUISITES:
    pip install openai
    Add to your .env:
        OPENAI_API_KEY=sk-your-key-here
        OPENAI_MODEL=gpt-4o-mini        # optional, defaults to gpt-4o-mini

FILE TO ADD:
    Copy ai_insights.py into your streamlit_app/ directory (same level as dashboard.py)

CHANGES TO dashboard.py — Apply these 4 patches in order:
=============================================================================
"""

# =============================================================================
# PATCH 1: Add import at top of dashboard.py (after the existing imports)
# =============================================================================
# Find this line:
#     from streamlit_app.fetch_markets import fetch_kalshi_markets, fetch_poly_markets, validate_match
# 
# Add directly AFTER it:

# --- START PATCH 1 ---
from ai_insights import generate_session_insights, generate_browse_insights
# --- END PATCH 1 ---


# =============================================================================
# PATCH 2: Add session state for AI insights (in the session state init block)
# =============================================================================
# Find this block:
#     if "arb_events" not in st.session_state:
#         st.session_state.arb_events = []
#
# Add directly AFTER it:

# --- START PATCH 2 ---
if "ai_insights" not in st.session_state:
    st.session_state.ai_insights = None
if "ai_loading" not in st.session_state:
    st.session_state.ai_loading = False
if "browse_insights" not in st.session_state:
    st.session_state.browse_insights = None
# --- END PATCH 2 ---


# =============================================================================
# PATCH 3: Add AI insights to the BROWSE phase (market overview)
# =============================================================================
# In the browse phase main content, find:
#     if st.session_state.match_result and st.session_state.match_result["matched"]:
#
# Add this block BEFORE that line (after the 3 metric cards):

# --- START PATCH 3 ---
    # AI Market Overview
    st.markdown("")
    st.markdown('<div class="section-header">🤖 AI Market Overview</div>', unsafe_allow_html=True)
    
    if st.button("🔍 Analyze Market Landscape", key="browse_ai"):
        with st.spinner("Generating AI analysis..."):
            # Build matched pairs data for AI
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
# --- END PATCH 3 ---


# =============================================================================
# PATCH 4: Add AI insights to the ANALYZE phase (post-session analysis)
# =============================================================================
# In the analyze phase, find the detailed stats table section:
#     # --- Detailed Stats Table ---
#     st.markdown('<div class="section-header">📋 Detailed Statistics</div>', unsafe_allow_html=True)
#
# Add this ENTIRE block AFTER the stats table (at the very end of the analyze phase):

# --- START PATCH 4 ---
    # --- AI-Powered Insights ---
    st.markdown("")
    st.markdown('<div class="section-header">🤖 AI-Powered Insights</div>', unsafe_allow_html=True)
    
    # Generate insights button
    if st.session_state.ai_insights is None:
        if st.button("🧠 Generate AI Analysis", type="primary", use_container_width=True):
            st.session_state.ai_loading = True
            st.rerun()
    
    # Handle the loading state (runs after rerun from button click)
    if st.session_state.ai_loading and st.session_state.ai_insights is None:
        with st.spinner("🤖 Analyzing session data with AI..."):
            cfg = st.session_state.match_result["config"]
            
            # Build summary stats dict
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
            
            # Call OpenAI
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
    
    # Display insights
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
        
        # Regenerate button
        if st.button("🔄 Regenerate Analysis", key="regen_ai"):
            st.session_state.ai_insights = None
            st.session_state.ai_loading = True
            st.rerun()
# --- END PATCH 4 ---


# =============================================================================
# PATCH 5: Reset AI state when starting a new session
# =============================================================================
# Find the "Run Bot" button handler:
#     if st.button("🚀 Run Bot", use_container_width=True, type="primary"):
#         st.session_state.phase = "monitor"
#
# Add these TWO lines after the existing state resets in that block:

# --- START PATCH 5 ---
                    st.session_state.ai_insights = None
                    st.session_state.ai_loading = False
# --- END PATCH 5 ---


# =============================================================================
# OPTIONAL PATCH 6: Add AI insight to live arb alerts (monitor phase)
# =============================================================================
# This is OPTIONAL — it adds a short AI explanation to arb alerts during monitoring.
# Be cautious: this calls OpenAI on every arb event, which adds latency and cost.
# 
# If you want it, find the arb alert section in the monitor phase:
#     if spread is not None and abs(spread) > 0.03:
#         direction = "Kalshi > Poly" if spread > 0 else "Poly > Kalshi"
#
# Replace that entire arb alert block with:

# --- START PATCH 6 (OPTIONAL) ---
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
# --- END PATCH 6 (OPTIONAL) ---
