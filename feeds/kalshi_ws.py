"""
Kalshi WebSocket feed for real-time orderbook data.
Maintains local order book per ticker and updates LATEST_PRICES.
"""
import asyncio
import json
import time
import base64
import websockets
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

from streamlit_app.config.settings import KALSHI_KEY_ID, KALSHI_PRIVATE_KEY_PATH
from streamlit_app.config.games import CONFIG
from streamlit_app.feeds.state import LATEST_PRICES, KALSHI_BOOKS
from streamlit_app.execution.signals import check_signals


async def run_kalshi_client():
    host = "wss://api.elections.kalshi.com"
    path = "/trade-api/ws/v2"
    uri = host + path

    private_key = None
    try:
        with open(KALSHI_PRIVATE_KEY_PATH, "rb") as kf:
            private_key = serialization.load_pem_private_key(kf.read(), password=None)
    except Exception:
        pass

    def sign(text):
        if not private_key:
            return ""
        msg = text.encode("utf-8")
        sig = private_key.sign(
            msg,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return base64.b64encode(sig).decode("utf-8")

    backoff = 1
    while True:
        try:
            timestamp = str(int(time.time() * 1000))
            sig_msg = timestamp + "GET" + path
            signature = sign(sig_msg)
            headers = {
                "KALSHI-ACCESS-KEY": KALSHI_KEY_ID,
                "KALSHI-ACCESS-SIGNATURE": signature,
                "KALSHI-ACCESS-TIMESTAMP": timestamp,
            }

            async with websockets.connect(uri, additional_headers=headers) as ws:
                print("Kalshi Connected.")
                backoff = 1
                for game_key, cfg in CONFIG.items():
                    ticker = cfg["kalshi_market_ticker"]
                    msg = {"id": 1, "cmd": "subscribe", "params": {"channels": ["orderbook_delta"], "market_ticker": ticker}}
                    await ws.send(json.dumps(msg))
                    KALSHI_BOOKS[ticker] = {"bids": {}, "asks": {}}

                while True:
                    msg_txt = await ws.recv()
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
                    if not data:
                        continue

                    ticker = data.get("market_ticker")
                    if not ticker:
                        continue

                    if ticker not in KALSHI_BOOKS:
                        KALSHI_BOOKS[ticker] = {"bids": {}, "asks": {}}
                    book = KALSHI_BOOKS[ticker]

                    # SNAPSHOT
                    if m_type == "orderbook_snapshot":
                        yes_orders = data.get("yes") or data.get("bids") or []
                        no_orders = data.get("no") or data.get("asks") or []
                        for p, q in yes_orders:
                            if q <= 0:
                                book["bids"].pop(p, None)
                            else:
                                book["bids"][p] = q
                        for p, q in no_orders:
                            yes_ask_price = 100 - p
                            if q <= 0:
                                book["asks"].pop(yes_ask_price, None)
                            else:
                                book["asks"][yes_ask_price] = q

                    # DELTA
                    elif m_type == "orderbook_delta":
                        side = data.get("side")
                        price = data.get("price")
                        delta = data.get("delta")

                        if side == "yes":
                            new_qty = book["bids"].get(price, 0) + delta
                            if new_qty <= 0:
                                book["bids"].pop(price, None)
                            else:
                                book["bids"][price] = new_qty
                        elif side == "no":
                            yes_ask_price = 100 - price
                            new_qty = book["asks"].get(yes_ask_price, 0) + delta
                            if new_qty <= 0:
                                book["asks"].pop(yes_ask_price, None)
                            else:
                                book["asks"][yes_ask_price] = new_qty

                    # Best bid/ask -> update state
                    best_bid = max(book["bids"].keys()) if book["bids"] else None
                    best_ask = min(book["asks"].keys()) if book["asks"] else None
                    best_bid_size = book["bids"][best_bid] if best_bid else 0
                    best_ask_size = book["asks"][best_ask] if best_ask else 0

                    for game_key, cfg in CONFIG.items():
                        if cfg["kalshi_market_ticker"] == ticker:
                            k_bid_prob = best_bid / 100.0 if best_bid else None
                            k_ask_prob = best_ask / 100.0 if best_ask else None

                            LATEST_PRICES[game_key]["Kalshi_Bid"] = k_bid_prob
                            LATEST_PRICES[game_key]["Kalshi_Ask"] = k_ask_prob
                            LATEST_PRICES[game_key]["Kalshi_Bid_Size"] = best_bid_size
                            LATEST_PRICES[game_key]["Kalshi_Ask_Size"] = best_ask_size

                            if k_bid_prob and k_ask_prob:
                                LATEST_PRICES[game_key]["Kalshi_Prob"] = (k_bid_prob + k_ask_prob) / 2
                            elif k_bid_prob:
                                LATEST_PRICES[game_key]["Kalshi_Prob"] = k_bid_prob

                            LATEST_PRICES[game_key]["updated_at"] = time.time()
                            check_signals(game_key)

        except Exception as e:
            print(f"Kalshi Connection Error: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
