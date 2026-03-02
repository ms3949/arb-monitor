"""
Kalshi REST API client for live order execution.
Handles authentication (RSA PSS signing), order placement, cancellation, and portfolio queries.
"""
import time
import base64
import requests
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

from streamlit_app.config.settings import KALSHI_KEY_ID, KALSHI_PRIVATE_KEY_PATH


class KalshiRest:
    def __init__(self):
        self.host = "https://api.elections.kalshi.com"
        self.private_key = None
        if KALSHI_PRIVATE_KEY_PATH:
            try:
                with open(KALSHI_PRIVATE_KEY_PATH, "rb") as kf:
                    self.private_key = serialization.load_pem_private_key(kf.read(), password=None)
            except Exception as e:
                print(f"❌ [INIT] Failed to load Kalshi Private Key: {e}")

    def _headers(self, method, path):
        timestamp = str(int(time.time() * 1000))
        signature = self._sign(method, path, timestamp)
        return {
            "KALSHI-ACCESS-KEY": KALSHI_KEY_ID,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }

    def _sign(self, method, path, timestamp):
        if not self.private_key:
            return ""
        msg = f"{timestamp}{method}{path}".encode("utf-8")
        sig = self.private_key.sign(
            msg,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return base64.b64encode(sig).decode("utf-8")

    # ---- Orders ----

    def create_order(self, ticker, action, count, price_cents, side="yes", ioc=False):
        """
        Place a real order on Kalshi.
        Returns order_id on fill, None otherwise.
        """
        if not self.private_key:
            print("❌ [EXEC] No Private Key available for execution.")
            return None

        path = "/trade-api/v2/portfolio/orders"
        body = {
            "action": action,
            "client_order_id": str(int(time.time() * 1000000)),
            "count": int(count),
            "ticker": ticker,
            "side": side,
            "type": "limit",
            "yes_price": int(price_cents),
        }
        if ioc:
            body["expiration_ts"] = int(time.time()) + 10

        try:
            print(f"🚀 [LIVE {action.upper()}] Sending Order: {count}x {ticker} @ {price_cents}¢...")
            resp = requests.post(self.host + path, json=body, headers=self._headers("POST", path))

            if resp.status_code == 201:
                data = resp.json()
                order = data.get("order", {})
                oid = order.get("order_id")
                status = order.get("status")
                print(f"✅ [LIVE SUCCESS] Order Placed! ID: {oid} | Status: {status}")

                if status == "executed":
                    return oid
                if status == "resting":
                    print(f"⚠️ [LIVE] Order {oid} resting (not filled). Cancelling to unlock position.")
                    self.cancel_order(oid)
                return None
            else:
                err_body = resp.text
                print(f"❌ [LIVE ERROR] {resp.status_code}: {err_body}")
                if resp.status_code == 400 and "insufficient_balance" in err_body:
                    print("⚠️ [LIVE] insufficient_balance — cancelling resting orders.")
                    self.cancel_resting_orders_for_ticker(ticker)
                return None

        except Exception as e:
            print(f"❌ [LIVE EXCEPTION] {e}")
            return None

    def cancel_order(self, order_id):
        """Cancel a resting order. Returns True on success."""
        if not self.private_key or not order_id:
            return False
        path = f"/trade-api/v2/portfolio/orders/{order_id}"
        try:
            resp = requests.delete(self.host + path, headers=self._headers("DELETE", path))
            if resp.status_code == 200:
                print(f"🔄 [LIVE] Cancelled resting order {order_id}")
                return True
            return False
        except Exception:
            return False

    def cancel_resting_orders_for_ticker(self, ticker):
        """Cancel all resting orders for a ticker."""
        if not self.private_key:
            return
        path = "/trade-api/v2/portfolio/orders"
        query = f"?ticker={ticker}&status=resting&limit=50"
        full_path = path + query
        try:
            resp = requests.get(self.host + full_path, headers=self._headers("GET", full_path))
            if resp.status_code != 200:
                return
            for o in resp.json().get("orders", []):
                oid = o.get("order_id")
                if oid:
                    self.cancel_order(oid)
        except Exception:
            pass

    # ---- Portfolio ----

    def get_portfolio_balance(self):
        """Returns (balance, portfolio_value, total) in dollars."""
        if not self.private_key:
            return (0.0, 0.0, 0.0)
        path = "/trade-api/v2/portfolio/balance"
        try:
            resp = requests.get(self.host + path, headers=self._headers("GET", path))
            if resp.status_code == 200:
                data = resp.json()
                balance = data.get("balance", 0) / 100.0
                portfolio_value = data.get("portfolio_value", 0) / 100.0
                return (balance, portfolio_value, balance + portfolio_value)
            return (0.0, 0.0, 0.0)
        except Exception:
            return (0.0, 0.0, 0.0)

    def get_positions(self):
        """Returns dict ticker -> position count (positive=YES)."""
        if not self.private_key:
            return {}
        path = "/trade-api/v2/portfolio/positions"
        try:
            resp = requests.get(self.host + path, headers=self._headers("GET", path))
            if resp.status_code != 200:
                return {}
            out = {}
            for mp in resp.json().get("market_positions", []):
                pos = mp.get("position", 0)
                if pos != 0:
                    out[mp.get("ticker", "")] = pos
            return out
        except Exception:
            return {}
