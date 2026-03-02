"""
Trading signal logic — entry and exit decisions.
Called by feeds whenever prices update. Executes via paper_engine + kalshi_rest.
"""
import time

from streamlit_app.config.settings import (
    PAPER_MODE, MIN_SPREAD, ORDER_SIZE_USD, MAX_HOLD_DURATION,
    STRATEGY, DYNAMIC_SIZING, SIZE_EDGE_STEP, MAX_SIZE_MULT,
    BUY_AGGRESSION_CENTS, SELL_AGGRESSION_CENTS,
    ORDER_FAIL_COOLDOWN, MIN_ASK_SIZE, LEAD_LAG_HISTORY_SEC,
    OBSERVATION_SECONDS,
)
from streamlit_app.config.games import CONFIG

# These will be set in run.py after initialisation
paper_engine = None
kalshi_client = None

# Lazy imports for shared state (avoids circular import at module load)
def _state():
    from streamlit_app.feeds.state import LATEST_PRICES, LEAD_LAG_HISTORY, LAST_ORDER_FAIL, LAST_POLY_SIGNAL, BOT_START_TIME
    return LATEST_PRICES, LEAD_LAG_HISTORY, LAST_ORDER_FAIL, LAST_POLY_SIGNAL, BOT_START_TIME


# --- Lead-Lag helpers ---

def _record_lead_lag_snapshot(game, bolt, kalshi_mid, poly_mid):
    """Record price snapshot for lead-lag analysis."""
    _, LEAD_LAG_HISTORY, *_ = _state()
    if bolt is None or kalshi_mid is None:
        return
    ts = time.time()
    poly = poly_mid if poly_mid is not None else kalshi_mid
    hist = LEAD_LAG_HISTORY.get(game)
    if hist is not None:
        hist.append((ts, bolt, kalshi_mid, poly))


def _lead_lag_metrics(game):
    """Compute B-K, B-P, K-P spreads and market order. Returns dict or None."""
    _, LEAD_LAG_HISTORY, *_ = _state()
    hist = LEAD_LAG_HISTORY.get(game)
    if not hist or len(hist) < 2:
        return None
    now = time.time()
    recent = [(t, b, k, p) for t, b, k, p in hist if now - t <= LEAD_LAG_HISTORY_SEC]
    if not recent:
        return None
    avg_b = sum(r[1] for r in recent) / len(recent)
    avg_k = sum(r[2] for r in recent) / len(recent)
    avg_p = sum(r[3] for r in recent) / len(recent)
    b_k = avg_b - avg_k
    b_p = avg_b - avg_p
    k_p = avg_k - avg_p
    order = sorted([("B", avg_b), ("K", avg_k), ("P", avg_p)], key=lambda x: -x[1])
    order_str = ">".join(o[0] for o in order)
    pct_bolt_leading = sum(1 for r in recent if r[1] > r[2]) / len(recent)
    pct_poly_leading = sum(1 for r in recent if r[3] > r[2]) / len(recent)
    pct_both_leading = sum(1 for r in recent if r[1] > r[2] and r[3] > r[2]) / len(recent)
    return {
        "b_k": b_k, "b_p": b_p, "k_p": k_p,
        "order": order_str,
        "pct_bolt_leading": pct_bolt_leading,
        "pct_poly_leading": pct_poly_leading,
        "pct_both_leading": pct_both_leading,
        "n": len(recent),
    }


# --- Main signal check ---

def check_signals(game):
    LATEST_PRICES, _, LAST_ORDER_FAIL, LAST_POLY_SIGNAL, BOT_START_TIME = _state()
    prices = LATEST_PRICES.get(game)
    if not prices:
        return

    cfg = CONFIG[game]
    ticker = cfg.get("kalshi_market_ticker")
    if not ticker:
        return

    kalshi_bid = prices.get("Kalshi_Bid")
    kalshi_ask = prices.get("Kalshi_Ask")
    kalshi_bid_size = prices.get("Kalshi_Bid_Size", 0)
    kalshi_ask_size = prices.get("Kalshi_Ask_Size", 0)

    bolt_prob = None
    target = cfg["kalshi_target_outcome"]
    if target == cfg.get("bolt_home"):
        bolt_prob = prices.get("Bolt_Home_Prob")
    elif target == cfg.get("bolt_away"):
        bolt_prob = prices.get("Bolt_Away_Prob")

    # Determine signal probability based on strategy
    poly_bid = prices.get("Poly_Bid")
    poly_ask = prices.get("Poly_Ask")
    poly_mid = (poly_bid + poly_ask) / 2 if (poly_bid and poly_ask) else prices.get("Poly_Prob")
    if STRATEGY == "POLY":
        signal_prob = poly_mid
    elif STRATEGY == "COMBINED":
        if bolt_prob is not None and poly_mid is not None:
            signal_prob = min(bolt_prob, poly_mid)
        else:
            signal_prob = None
    else:
        signal_prob = bolt_prob

    # --- 1. EXIT LOGIC ---
    if ticker in paper_engine.positions:
        pos = paper_engine.positions[ticker]
        bid_cents = int(kalshi_bid * 100) if kalshi_bid else 0
        exit_reason = None
        gap = (signal_prob - kalshi_bid) if (signal_prob is not None and kalshi_bid is not None) else None
        duration = time.time() - pos["entry_time"]

        # A) Time Stop — only when edge is gone
        if duration > MAX_HOLD_DURATION and (gap is None or gap <= 0):
            exit_reason = f"Time Stop {duration:.1f}s"

        # B) Convergence
        elif gap is not None and gap <= 0:
            exit_reason = f"Convergence (Gap {gap:.1%})"

        # C) Lead Lag Breakdown
        elif signal_prob is not None and kalshi_bid is not None and kalshi_bid > signal_prob:
            exit_reason = f"Lead Lag Breakdown (Kalshi {kalshi_bid:.1%} > {STRATEGY} {signal_prob:.1%})"

        # EXECUTE EXIT
        if exit_reason and bid_cents > 0:
            exit_qty = min(pos["count"], kalshi_bid_size) if kalshi_bid_size > 0 else pos["count"]
            if exit_qty > 0:
                if game in LAST_ORDER_FAIL and (time.time() - LAST_ORDER_FAIL[game]) < ORDER_FAIL_COOLDOWN:
                    return
                filled = True
                if not PAPER_MODE:
                    sell_cents = max(1, bid_cents - SELL_AGGRESSION_CENTS)
                    oid = kalshi_client.create_order(ticker, "sell", exit_qty, sell_cents, side="yes", ioc=True)
                    if not oid:
                        filled = False
                        LAST_ORDER_FAIL[game] = time.time()
                        print(f"❌ [LIVE FAIL] Sell order not filled. Cooldown {ORDER_FAIL_COOLDOWN}s.")
                if filled:
                    if game in LAST_ORDER_FAIL:
                        del LAST_ORDER_FAIL[game]
                    paper_engine.sell(ticker, exit_qty, bid_cents, reason=exit_reason)
                    paper_engine.print_status()
            return

    # --- 2. ENTRY LOGIC ---
    elapsed = (time.time() - BOT_START_TIME) if BOT_START_TIME else 0
    if elapsed < OBSERVATION_SECONDS:
        return

    ll = _lead_lag_metrics(game)
    if ll is None:
        return
    if STRATEGY == "COMBINED":
        pct_leading = ll["pct_both_leading"]
    elif STRATEGY == "POLY":
        pct_leading = ll["pct_poly_leading"]
    else:
        pct_leading = ll["pct_bolt_leading"]
    if pct_leading <= 0.5:
        return

    if signal_prob is not None and kalshi_ask is not None:
        edge = signal_prob - kalshi_ask
        ask_cents = int(kalshi_ask * 100)

        if edge > MIN_SPREAD and ask_cents > 0 and ask_cents < 100:
            if ticker not in paper_engine.positions:
                if game in LAST_ORDER_FAIL and (time.time() - LAST_ORDER_FAIL[game]) < ORDER_FAIL_COOLDOWN:
                    return
                if kalshi_ask_size < MIN_ASK_SIZE:
                    return

                base_count = int((ORDER_SIZE_USD * 100) / ask_cents)
                if base_count < 1:
                    base_count = 1

                if DYNAMIC_SIZING:
                    size_mult = 1.0 + (edge - MIN_SPREAD) / SIZE_EDGE_STEP
                    size_mult = min(max(size_mult, 1.0), MAX_SIZE_MULT)
                    count_desired = int(base_count * size_mult)
                    if size_mult > 1.01:
                        print(f"📊 [SIZE] Edge {edge:.1%} -> {size_mult:.1f}x ({count_desired} contracts)")
                else:
                    count_desired = base_count

                count_desired = max(count_desired, 1)
                count_final = min(count_desired, int(kalshi_ask_size))

                if count_final > 0:
                    buy_cents = min(99, ask_cents + BUY_AGGRESSION_CENTS)
                    cost = (count_final * buy_cents) / 100.0
                    if not PAPER_MODE:
                        if paper_engine.cash < cost:
                            print(f"⚠️ [LIVE SKIP] Insufficient Budget. Need ${cost:.2f}, Have ${paper_engine.cash:.2f}")
                            return

                    filled = True
                    if not PAPER_MODE:
                        oid = kalshi_client.create_order(ticker, "buy", count_final, buy_cents, side="yes", ioc=True)
                        if not oid:
                            filled = False
                            LAST_ORDER_FAIL[game] = time.time()
                            print(f"❌ [LIVE FAIL] Order resting/rejected. Cooldown {ORDER_FAIL_COOLDOWN}s.")

                    if filled:
                        if paper_engine.buy(ticker, count_final, buy_cents, game):
                            if game in LAST_ORDER_FAIL:
                                del LAST_ORDER_FAIL[game]
                            paper_engine.print_status()

    # B) Bolt vs Poly (Monitor Only when STRATEGY=BOLT)
    if STRATEGY == "BOLT":
        poly_ask_val = prices.get("Poly_Ask")
        if bolt_prob is not None and poly_ask_val is not None:
            edge_poly = bolt_prob - poly_ask_val
            if edge_poly > MIN_SPREAD:
                now = time.time()
                if now - LAST_POLY_SIGNAL.get(game, 0) >= 60:
                    LAST_POLY_SIGNAL[game] = now
                    print(f"🚨 [POLY SIGNAL] {game} | Bolt {bolt_prob:.1%} > Poly Ask {poly_ask_val:.2f} | Edge: {edge_poly:+.1%}")
