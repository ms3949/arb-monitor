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

_client = None


def get_client():
    global _client
    if _client is None:
        _client = OpenAI()
    return _client
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
        response = get_client().chat.completions.create(
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
        response = get_client().chat.completions.create(
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
