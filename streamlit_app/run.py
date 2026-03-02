"""
Main entrypoint for the auto-discovery trading bot.

Usage:
    cd poly_stat_arb
    python -m streamlit_app.run
"""
import asyncio
import time

from streamlit_app.config.settings import (
    PAPER_MODE, MAX_BUDGET, STRATEGY, DYNAMIC_SIZING,
    TRADING_FEE_PCT, OBSERVATION_SECONDS,
)
from streamlit_app.config.games import CONFIG, resolve_poly_ids
from streamlit_app.discovery.discover import discover_games
from streamlit_app.feeds.state import LATEST_PRICES, initialize_shared_state
from streamlit_app.feeds import state as shared_state
from streamlit_app.feeds.bolt import run_bolt_client
from streamlit_app.feeds.kalshi_ws import run_kalshi_client
from streamlit_app.feeds.polymarket_ws import run_poly_client
from streamlit_app.execution.paper_engine import PaperTradingEngine
from streamlit_app.execution.kalshi_rest import KalshiRest
from streamlit_app.execution import signals as signals_mod
from streamlit_app.execution.signals import _lead_lag_metrics, _record_lead_lag_snapshot


# --- Ticker Loop (Heartbeat + Exit checks) ---

async def ticker_loop(paper_engine, kalshi_client):
    """Periodic loop: sync positions, check exit signals, print heartbeat."""
    while True:
        await asyncio.sleep(5)

        # Sync with Kalshi
        if not PAPER_MODE and paper_engine.positions:
            kalshi_pos = kalshi_client.get_positions()
            for ticker in list(paper_engine.positions.keys()):
                if kalshi_pos.get(ticker, 0) == 0:
                    del paper_engine.positions[ticker]
                    print(f"🔄 [SYNC] Position {ticker} closed on Kalshi")

        # Check exit signals
        if paper_engine.positions:
            for game in CONFIG:
                signals_mod.check_signals(game)

        # Print Heartbeat per game
        for game in CONFIG:
            prices = LATEST_PRICES.get(game)
            if not prices:
                continue

            cfg = CONFIG[game]
            target = cfg["kalshi_target_outcome"]

            bp = 0.0
            side_str = "?"
            if target == cfg.get("bolt_home"):
                bp = prices.get("Bolt_Home_Prob") or 0.0
                side_str = "Home"
            elif target == cfg.get("bolt_away"):
                bp = prices.get("Bolt_Away_Prob") or 0.0
                side_str = "Away"

            kp = prices.get("Kalshi_Prob") or 0.0
            kb = prices.get("Kalshi_Bid") or 0.0
            ka = prices.get("Kalshi_Ask") or 0.0
            ks = prices.get("Kalshi_Ask_Size") or 0

            pb = prices.get("Poly_Bid") or 0.0
            pa = prices.get("Poly_Ask") or 0.0

            # Lead-lag snapshot
            bolt_raw = prices.get("Bolt_Home_Prob") if target == cfg.get("bolt_home") else prices.get("Bolt_Away_Prob")
            kalshi_mid = (kb + ka) / 2 if (kb and ka) else kp
            poly_mid = (pb + pa) / 2 if (pb and pa) else prices.get("Poly_Prob")
            if bolt_raw is not None and kalshi_mid is not None:
                _record_lead_lag_snapshot(game, bolt_raw, kalshi_mid, poly_mid)

            edge_k = bp - ka
            edge_p = bp - pa

            # Portfolio value
            if not PAPER_MODE:
                balance, pos_value, port_val = kalshi_client.get_portfolio_balance()
                if port_val <= 0:
                    port_val = paper_engine.cash
                    for t, pos in paper_engine.positions.items():
                        g = pos.get("game")
                        mark = LATEST_PRICES.get(g, {}).get("Kalshi_Bid") if g else None
                        mark = mark if mark is not None else pos["avg_entry"]
                        port_val += pos["count"] * mark
            else:
                port_val = paper_engine.cash
                for t, pos in paper_engine.positions.items():
                    g = pos.get("game")
                    mark = LATEST_PRICES.get(g, {}).get("Kalshi_Bid") if g else None
                    mark = mark if mark is not None else pos["avg_entry"]
                    port_val += pos["count"] * mark
            total_pnl = port_val - MAX_BUDGET

            elapsed = (time.time() - shared_state.BOT_START_TIME) if shared_state.BOT_START_TIME else 0
            obs_str = f" [Observing {elapsed:.0f}s/{OBSERVATION_SECONDS}s]" if elapsed < OBSERVATION_SECONDS else ""
            print(f"💰 Portfolio: ${port_val:.2f} | PnL: ${total_pnl:+.2f} | Open: {len(paper_engine.positions)}{obs_str}")
            print(f"💓 [{game}] Kalshi: {kb:.1%}/{ka:.1%} ({ks}x) | Poly: {pb:.2f}/{pa:.2f}")


# --- Main ---

async def main():
    # 1. AUTO-DISCOVER games on both exchanges
    discovered = discover_games()
    if not discovered:
        print("❌ No active games found on both Kalshi and Polymarket. Exiting.")
        return
    
    # Populate CONFIG
    CONFIG.update(discovered)
    print(f"📋 Active games: {list(CONFIG.keys())}")
    
    # 2. Resolve Poly asset IDs
    resolve_poly_ids()

    # 3. Initialize shared state
    initialize_shared_state()
    shared_state.BOT_START_TIME = time.time()

    # 4. Create engines
    paper_engine = PaperTradingEngine(initial_cash=MAX_BUDGET)
    kalshi_client = KalshiRest()
    signals_mod.paper_engine = paper_engine
    signals_mod.kalshi_client = kalshi_client

    # 5. Startup banner
    mode_str = "LIVE" if not PAPER_MODE else "PAPER"
    print(f"\n📉 {mode_str} BOT | Strategy: {STRATEGY} | {len(CONFIG)} game(s)")
    print(f"⚙️ Sizing: {'Dynamic' if DYNAMIC_SIZING else 'Fixed'} | Fee={TRADING_FEE_PCT:.1%}")
    print(f"⏱️ Observation: {OBSERVATION_SECONDS}s warmup")
    print("Connecting to feeds...\n")

    # 6. Run (Bolt disabled — only Kalshi WS + Poly WS + ticker loop)
    await asyncio.gather(
        run_bolt_client(),
        run_kalshi_client(),
        run_poly_client(),
        ticker_loop(paper_engine, kalshi_client),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot Stopped by User")
