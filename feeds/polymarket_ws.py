"""
Polymarket WebSocket feed for real-time price data.
Subscribes to resolved asset IDs and updates LATEST_PRICES.
"""
import asyncio
import json
import websockets

from streamlit_app.config.games import CONFIG, RESOLVED_IDS
from streamlit_app.feeds.state import LATEST_PRICES
from streamlit_app.execution.signals import check_signals


# --- Poly helpers ---

def _poly_asset_to_game_and_idx(asset_id):
    """Return (game, outcome_index) if asset_id matches resolved assets, else None."""
    for c_id, a_ids in RESOLVED_IDS["poly_asset_ids"].items():
        ids = a_ids if isinstance(a_ids, list) else [a_ids]
        if asset_id in ids:
            idx = ids.index(asset_id)
            for gn, gcfg in CONFIG.items():
                if gcfg.get("poly_condition_id") == c_id:
                    return (gn, idx)
    return None


def _poly_asset_to_game(asset_id):
    r = _poly_asset_to_game_and_idx(asset_id)
    return r[0] if r else None


def _poly_asset_is_our_outcome(asset_id, game):
    """True if this asset_id is the one we track (poly_outcome_index) for this game."""
    r = _poly_asset_to_game_and_idx(asset_id)
    if not r:
        return False
    gn, idx = r
    if gn != game:
        return False
    return idx == CONFIG[game].get("poly_outcome_index", 0)


def _apply_poly_update(target_game, price, bid=None, bid_size=None, ask=None, ask_size=None):
    if bid is not None:
        LATEST_PRICES[target_game]["Poly_Bid"] = bid
    if bid_size is not None:
        LATEST_PRICES[target_game]["Poly_Bid_Size"] = bid_size
    if ask is not None:
        LATEST_PRICES[target_game]["Poly_Ask"] = ask
    if ask_size is not None:
        LATEST_PRICES[target_game]["Poly_Ask_Size"] = ask_size

    if price is not None:
        import time
        LATEST_PRICES[target_game]["Poly_Prob"] = price
        LATEST_PRICES[target_game]["updated_at"] = time.time()
        check_signals(target_game)


def _poly_apply_update_maybe_convert(game, price, bid, bid_size, ask, ask_size, is_our_outcome):
    """Apply Poly update; if other outcome, convert bid/ask (binary complement)."""
    if not is_our_outcome:
        if bid is not None and ask is not None:
            bid, ask = 1.0 - ask, 1.0 - bid
        elif bid is not None:
            ask = 1.0 - bid
        elif ask is not None:
            bid = 1.0 - ask
        if bid is not None or ask is not None:
            price = (bid + ask) / 2 if (bid and ask) else (bid or ask)
    _apply_poly_update(game, price, bid, bid_size, ask, ask_size)


def _poly_price_changes(update):
    """Yield (asset_id, best_bid, best_ask) for price_change events."""
    for pc in update.get("price_changes", []):
        asset_id = pc.get("asset_id")
        b, a = pc.get("best_bid"), pc.get("best_ask")
        if asset_id and (b is not None or a is not None):
            yield asset_id, (float(b) if b else None), (float(a) if a else None)


def _poly_best_bid_ask(update):
    event_type = update.get("event_type")
    if event_type == "book":
        bids = update.get("bids", []) or update.get("buys", [])
        asks = update.get("asks", []) or update.get("sells", [])
        bb = float(bids[0]["price"]) if bids else None
        bbs = float(bids[0]["size"]) if bids else None
        ba = float(asks[0]["price"]) if asks else None
        bas = float(asks[0]["size"]) if asks else None
        return bb, bbs, ba, bas
    if event_type == "best_bid_ask":
        b = update.get("best_bid")
        a = update.get("best_ask")
        return (float(b) if b else None, None, float(a) if a else None, None)
    return None, None, None, None


# --- WebSocket Client ---

async def run_poly_client():
    uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    print(f"Connecting to Polymarket: {uri}...")

    assets_to_sub = []
    for game, cfg in CONFIG.items():
        cond_id = cfg.get("poly_condition_id")
        if cond_id and cond_id in RESOLVED_IDS["poly_asset_ids"]:
            a_ids = RESOLVED_IDS["poly_asset_ids"][cond_id]
            ids = a_ids if isinstance(a_ids, list) else [a_ids]
            assets_to_sub.extend(ids)

    if not assets_to_sub:
        print("Poly Warning: No assets to subscribe.")

    backoff = 1
    while True:
        try:
            async with websockets.connect(uri) as ws:
                print("Polymarket Connected.")
                backoff = 1
                if assets_to_sub:
                    sub = {"type": "market", "assets_ids": assets_to_sub}
                    await ws.send(json.dumps(sub))

                while True:
                    msg_txt = await ws.recv()
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

                        if event == "price_change":
                            for asset_id, best_bid, best_ask in _poly_price_changes(update):
                                r = _poly_asset_to_game_and_idx(asset_id)
                                if not r:
                                    continue
                                game, _ = r
                                is_ours = _poly_asset_is_our_outcome(asset_id, game)
                                price = (best_bid + best_ask) / 2 if (best_bid and best_ask) else (best_ask or best_bid)
                                if price is not None:
                                    _poly_apply_update_maybe_convert(game, price, best_bid, None, best_ask, None, is_ours)
                            continue

                        asset_id = update.get("asset_id")
                        if not asset_id:
                            continue

                        r = _poly_asset_to_game_and_idx(asset_id)
                        if not r:
                            continue
                        game, _ = r
                        is_ours = _poly_asset_is_our_outcome(asset_id, game)
                        bb, bbs, ba, bas = _poly_best_bid_ask(update)
                        price = (bb + ba) / 2 if (bb and ba) else (bb or ba)
                        _poly_apply_update_maybe_convert(game, price, bb, bbs, ba, bas, is_ours)

        except Exception as e:
            print(f"Poly Error: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
