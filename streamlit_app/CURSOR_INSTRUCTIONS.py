# AI Insights Integration — Cursor Instructions
# ================================================
# 
# This document tells Cursor exactly how to add OpenAI-powered AI insights
# to the Streamlit arb monitor dashboard.
#
# OVERVIEW OF CHANGES:
#   1. Add ai_insights.py (new file — the AI module)
#   2. Update .env with OPENAI_API_KEY
#   3. Update requirements.txt to include openai
#   4. Modify dashboard.py with 5 surgical patches
#
# The AI integration adds:
#   - A "Generate AI Analysis" button in the post-session analyze phase
#   - An "Analyze Market Landscape" button in the browse phase
#   - OpenAI generates insights about spread behavior, arb exploitability,
#     dislocation drivers, and actionable recommendations


# ===========================================================================
# STEP 1: Create ai_insights.py in streamlit_app/ directory
# ===========================================================================
#
# Create file: streamlit_app/ai_insights.py
# Contents:

"""
AI-Powered Insights Module for Arb Monitor
============================================
Generates analysis of prediction market dislocations using OpenAI.
"""
import os
import json
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI()
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def generate_session_insights(
    home_team: str,
    away_team: str,
    game_date: str,
    spread_history: list[dict],
    arb_events: list[dict],
    summary_stats: dict,
) -> str:
    """
    Generate AI analysis of a completed monitoring session.
    Called from the analyze phase of dashboard.py.
    """
    # Sample spread history to keep tokens manageable
    n = len(spread_history)
    if n > 30:
        step = n // 30
        sampled = spread_history[::step][:30]
    else:
        sampled = spread_history

    spread_timeline = []
    for row in sampled:
        spread_timeline.append({
            "time": row.get("time", ""),
            "kalshi": round(row["kalshi_mid"], 4) if row.get("kalshi_mid") else None,
            "poly": round(row["poly_mid"], 4) if row.get("poly_mid") else None,
            "spread": round(row["spread"], 4) if row.get("spread") else None,
        })

    data_payload = {
        "game": f"{away_team} @ {home_team}",
        "date": game_date,
        "summary": summary_stats,
        "arb_events": arb_events[:20],
        "spread_samples": spread_timeline,
    }

    system_prompt = """You are a quantitative analyst specializing in prediction markets and cross-exchange arbitrage. 
You analyze monitoring sessions between Kalshi and Polymarket to identify patterns, explain dislocations, and assess exploitability.

Your analysis should cover:
1. **Session Overview** — What happened during this monitoring window
2. **Spread Dynamics** — Was one exchange consistently leading? Mean-reverting or trending?
3. **Arbitrage Assessment** — Were the arb windows exploitable given typical execution constraints (latency, fees ~1.5%, liquidity)?
4. **Dislocation Drivers** — Hypothesize WHY spreads existed (liquidity asymmetry, different user bases, stale quotes, etc.)
5. **Actionable Takeaways** — What would you recommend for future sessions on this matchup?

Keep your response concise (250-400 words). Use markdown formatting with bold headers.
Be specific — reference actual numbers from the data. Don't hedge excessively."""

    user_prompt = f"""Analyze this prediction market monitoring session:

{json.dumps(data_payload, indent=2)}

Provide a quantitative analysis of the cross-exchange spread behavior and arbitrage opportunities."""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=800,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ AI analysis unavailable: {str(e)}\n\nEnsure OPENAI_API_KEY is set in your .env file."


def generate_browse_insights(
    matched_pairs: list[dict],
    kalshi_count: int,
    poly_count: int,
) -> str:
    """
    Generate AI analysis of the current market landscape.
    Called from the browse phase of dashboard.py.
    """
    data_payload = {
        "kalshi_markets": kalshi_count,
        "poly_markets": poly_count,
        "matched_pairs": matched_pairs[:15],
        "timestamp": datetime.now().isoformat(),
    }

    system_prompt = """You are a prediction markets analyst. Given a snapshot of matched markets between Kalshi and Polymarket, 
provide a brief market landscape overview (150-250 words). Cover:
1. Overall market activity and coverage gap between exchanges
2. Which matchups show the largest spreads and why that might be
3. Which games look most promising for arbitrage monitoring
Use markdown formatting. Be specific with numbers."""

    user_prompt = f"""Current prediction market landscape:

{json.dumps(data_payload, indent=2)}

Provide a brief market overview and highlight the most interesting opportunities."""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=500,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ AI analysis unavailable: {str(e)}"


# ===========================================================================
# STEP 2: Update .env — add these lines
# ===========================================================================
#
# OPENAI_API_KEY=sk-your-openai-api-key-here
# OPENAI_MODEL=gpt-4o-mini


# ===========================================================================
# STEP 3: Update requirements.txt — add this line
# ===========================================================================
#
# openai


# ===========================================================================
# STEP 4: Modify dashboard.py — Apply these 5 patches
# ===========================================================================
#
# PATCH 1/5 — Add import
# Location: After the line "from streamlit_app.fetch_markets import ..."
# Add:
#
#     from ai_insights import generate_session_insights, generate_browse_insights
#
# --------------------------------------------------------------------------
#
# PATCH 2/5 — Add session state variables
# Location: After the block "if 'arb_events' not in st.session_state:"
# Add:
#
#     if "ai_insights" not in st.session_state:
#         st.session_state.ai_insights = None
#     if "ai_loading" not in st.session_state:
#         st.session_state.ai_loading = False
#     if "browse_insights" not in st.session_state:
#         st.session_state.browse_insights = None
#
# --------------------------------------------------------------------------
#
# PATCH 3/5 — Add AI insights to browse phase
# Location: In the browse phase (elif st.session_state.phase == "browse":),
#           AFTER the 3 metric cards (col1, col2, col3), 
#           BEFORE the "if st.session_state.match_result..." block
# Add this code block:
#
#     # --- AI Market Overview ---
#     st.markdown("")
#     st.markdown('<div class="section-header">🤖 AI Market Overview</div>', unsafe_allow_html=True)
#     
#     if st.button("🔍 Analyze Market Landscape", key="browse_ai"):
#         with st.spinner("Generating AI analysis..."):
#             matched_data = []
#             for km in st.session_state.kalshi_markets:
#                 for pm in st.session_state.poly_markets:
#                     result = validate_match(km, pm)
#                     if result["matched"]:
#                         matched_data.append({
#                             "away": km.get("away", "?"),
#                             "home": km.get("home", "?"),
#                             "date": km.get("date", "?"),
#                             "confidence": result["confidence"],
#                         })
#             st.session_state.browse_insights = generate_browse_insights(
#                 matched_pairs=matched_data,
#                 kalshi_count=len(st.session_state.kalshi_markets),
#                 poly_count=len(st.session_state.poly_markets),
#             )
#     
#     if st.session_state.browse_insights:
#         st.markdown(f"""
#         <div style="background: linear-gradient(135deg, rgba(167,139,250,0.05) 0%, rgba(100,255,218,0.05) 100%);
#                     border: 1px solid rgba(167,139,250,0.15); border-radius: 12px; padding: 1.2rem; margin-top: 0.5rem;">
#             <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 0.8rem;">
#                 <span style="color: #a78bfa; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">
#                     🤖 AI Market Analysis
#                 </span>
#                 <span style="color: #4a5568; font-size: 0.65rem; background: rgba(167,139,250,0.1);
#                              padding: 2px 8px; border-radius: 4px;">Powered by OpenAI</span>
#             </div>
#         </div>
#         """, unsafe_allow_html=True)
#         st.markdown(st.session_state.browse_insights)
#     
#     st.markdown("---")
#
# --------------------------------------------------------------------------
#
# PATCH 4/5 — Add AI insights to analyze phase (THE MOST IMPORTANT PATCH)
# Location: At the END of the analyze phase, AFTER the detailed stats table
#           (after st.dataframe(pd.DataFrame(stats)...))
# Add this entire block:
#
#     # --- AI-Powered Insights ---
#     st.markdown("")
#     st.markdown('<div class="section-header">🤖 AI-Powered Insights</div>', unsafe_allow_html=True)
#     
#     if st.session_state.ai_insights is None:
#         if st.button("🧠 Generate AI Analysis", type="primary", use_container_width=True):
#             st.session_state.ai_loading = True
#             st.rerun()
#     
#     if st.session_state.ai_loading and st.session_state.ai_insights is None:
#         with st.spinner("🤖 Analyzing session data with AI..."):
#             cfg = st.session_state.match_result["config"]
#             
#             summary_stats = {
#                 "n_observations": len(df),
#                 "session_duration_sec": round(df["ts"].max() - df["ts"].min(), 1) if len(df) > 1 else 0,
#                 "mean_spread": round(float(spreads.mean()), 4) if len(spreads) else None,
#                 "std_spread": round(float(spreads.std()), 4) if len(spreads) > 1 else None,
#                 "max_spread": round(float(spreads.max()), 4) if len(spreads) else None,
#                 "min_spread": round(float(spreads.min()), 4) if len(spreads) else None,
#                 "mean_kalshi": round(float(df["kalshi_mid"].dropna().mean()), 4) if len(df) else None,
#                 "mean_poly": round(float(df["poly_mid"].dropna().mean()), 4) if len(df) else None,
#                 "n_arb_events": len(arb_events),
#                 "pct_time_in_arb": round(len(arb_events) / len(df) * 100, 1) if len(df) > 0 else 0,
#             }
#             
#             st.session_state.ai_insights = generate_session_insights(
#                 home_team=cfg.get("home_team", "Unknown"),
#                 away_team=cfg.get("away_team", "Unknown"),
#                 game_date=cfg.get("game_date", ""),
#                 spread_history=[
#                     {
#                         "time": row.get("time", ""),
#                         "kalshi_mid": row.get("kalshi_mid"),
#                         "poly_mid": row.get("poly_mid"),
#                         "spread": row.get("spread"),
#                     }
#                     for row in history
#                 ],
#                 arb_events=arb_events,
#                 summary_stats=summary_stats,
#             )
#             st.session_state.ai_loading = False
#             st.rerun()
#     
#     if st.session_state.ai_insights:
#         st.markdown(f"""
#         <div style="background: linear-gradient(135deg, rgba(167,139,250,0.05) 0%, rgba(100,255,218,0.05) 100%);
#                     border: 1px solid rgba(167,139,250,0.15); border-radius: 12px; padding: 1.5rem;">
#             <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 1rem;">
#                 <span style="font-size: 1.1rem;">🤖</span>
#                 <span style="color: #a78bfa; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">
#                     AI Session Analysis
#                 </span>
#                 <span style="color: #4a5568; font-size: 0.65rem; background: rgba(167,139,250,0.1);
#                              padding: 2px 8px; border-radius: 4px;">Powered by OpenAI</span>
#             </div>
#         </div>
#         """, unsafe_allow_html=True)
#         st.markdown(st.session_state.ai_insights)
#         
#         if st.button("🔄 Regenerate Analysis", key="regen_ai"):
#             st.session_state.ai_insights = None
#             st.session_state.ai_loading = True
#             st.rerun()
#
# --------------------------------------------------------------------------
#
# PATCH 5/5 — Reset AI state when starting new monitoring session
# Location: Inside the "Run Bot" button handler in the sidebar,
#           after "st.session_state.arb_events = []"
# Add:
#
#     st.session_state.ai_insights = None
#     st.session_state.ai_loading = False
#
# ===========================================================================
# DONE — Test by running: streamlit run dashboard.py
# ===========================================================================
