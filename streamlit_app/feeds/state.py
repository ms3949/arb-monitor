"""
Shared mutable state used by feeds, signals, and the ticker loop.
Centralised here so every module imports from one place.
"""
import collections
import time

from streamlit_app.config.games import CONFIG

# Per-game latest prices  (populated by feeds, read by signals)
LATEST_PRICES = {}

# Kalshi local order books  (ticker -> {"bids": {price: qty}, "asks": {price: qty}})
KALSHI_BOOKS = {}

# Bot start timestamp (set once in main)
BOT_START_TIME = None

# Lead-Lag history  (game -> deque of (ts, bolt, kalshi_mid, poly_mid))
LEAD_LAG_HISTORY = {}

# Throttle / cooldown state
LAST_POLY_SIGNAL = {}     # game -> timestamp
LAST_ORDER_FAIL = {}      # game -> timestamp


def initialize_shared_state():
    """Call once at startup after CONFIG is finalised."""
    global LEAD_LAG_HISTORY
    for game in CONFIG:
        LATEST_PRICES[game] = {
            "Bolt_Home_Prob": None, "Bolt_Away_Prob": None,
            "Bolt_Home_Book": None, "Bolt_Away_Book": None,
            "Kalshi_Prob": None, "Kalshi_Bid": None, "Kalshi_Ask": None,
            "Kalshi_Bid_Size": 0, "Kalshi_Ask_Size": 0,
            "Poly_Bid": None, "Poly_Ask": None, "Poly_Prob": None,
            "updated_at": 0,
        }
        LEAD_LAG_HISTORY[game] = collections.deque(maxlen=500)
