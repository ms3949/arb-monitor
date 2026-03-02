"""
Centralized settings for the trading bot.
All tuneable parameters live here.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- API Keys ---
BOLT_KEY = os.getenv("BOLT_KEY")
KALSHI_KEY_ID = os.getenv("KALSHI_KEY_ID")
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH")

# --- Execution Settings ---
PAPER_MODE = False          # False = LIVE TRADING!
MAX_BUDGET = 50.0           # Starting cash
ORDER_SIZE_USD = 10.0       # Target cost per order
MIN_SPREAD = 0.05           # 5% edge to enter

# --- Fees ---
TRADING_FEE_PCT = 0.015     # 1.5% Taker Fee

# --- Exit Settings ---
MAX_HOLD_DURATION = 120     # Seconds before forced exit (Time Stop)

# --- Observation / Lead-Lag ---
OBSERVATION_SECONDS = 60    # No trading until we've observed this long
LEAD_LAG_HISTORY_SEC = 90   # Seconds of history for lead-lag metrics

# --- Strategy ---
STRATEGY = "BOLT"           # "BOLT" | "POLY" | "COMBINED"
DYNAMIC_SIZING = True
SIZE_EDGE_STEP = 0.03       # Each 3% above MIN_SPREAD adds 1x
MAX_SIZE_MULT = 3.0         # Cap at 3x base size

# --- Order Execution ---
BUY_AGGRESSION_CENTS = 2    # Pay up to 2¢ above ask
SELL_AGGRESSION_CENTS = 2   # Sell at bid-2¢
ORDER_FAIL_COOLDOWN = 30    # Seconds cooldown after failed order
MIN_ASK_SIZE = 1            # Skip if ask liquidity < this
