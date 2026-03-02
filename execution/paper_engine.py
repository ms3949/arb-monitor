"""
Paper (simulated) trading engine.
Tracks positions, cash, and realized PnL.
"""
import time
from datetime import datetime
from streamlit_app.config.settings import TRADING_FEE_PCT, PAPER_MODE


class PaperTradingEngine:
    def __init__(self, initial_cash=100.0):
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.positions = {}       # ticker -> { "count", "avg_entry", "entry_time", "game" }
        self.realized_pnl = 0.0
        self.trade_history = []

    def buy(self, ticker, count, price_cents, game_name):
        gross_cost = (count * price_cents) / 100.0
        fee = gross_cost * TRADING_FEE_PCT
        total_cost = gross_cost + fee

        if total_cost > self.cash:
            print(f"❌ [PAPER] Insufficient Cash to Buy {ticker}. Need ${total_cost:.2f}, Have ${self.cash:.2f}")
            return False

        self.cash -= total_cost

        pos = self.positions.get(ticker, {
            "count": 0, "avg_entry": 0.0, "ticker": ticker,
            "game": game_name, "entry_time": time.time()
        })

        total_prev_cost = pos["count"] * pos["avg_entry"]
        new_total_cost = total_prev_cost + total_cost
        new_count = pos["count"] + count
        pos["avg_entry"] = new_total_cost / new_count if new_count > 0 else 0.0
        pos["count"] = new_count
        if "entry_time" not in pos:
            pos["entry_time"] = time.time()

        self.positions[ticker] = pos
        print(f"🔵 [PAPER BUY] {game_name} | {count}x @ {price_cents}¢ | Fee: ${fee:.2f} | Pos: {pos['count']}x avg {pos['avg_entry']:.3f}")
        return True

    def sell(self, ticker, count, price_cents, reason="Exit"):
        pos = self.positions.get(ticker)
        if not pos or pos["count"] < count:
            print(f"❌ [PAPER] Cannot Sell {count}x {ticker}. Own {pos['count'] if pos else 0}")
            return False

        gross_proceeds = (count * price_cents) / 100.0
        fee = gross_proceeds * TRADING_FEE_PCT
        net_proceeds = gross_proceeds - fee

        cost_basis = count * pos["avg_entry"]
        pnl = net_proceeds - cost_basis

        self.cash += net_proceeds
        self.realized_pnl += pnl

        pos["count"] -= count
        if pos["count"] == 0:
            del self.positions[ticker]

        print(f"🟠 [PAPER SELL] {ticker} | {count}x @ {price_cents}¢ | Fee: ${fee:.2f} | PnL: ${pnl:.2f} ({reason})")
        return True

    def print_status(self):
        title = "LIVE PORTFOLIO" if not PAPER_MODE else "PAPER DASHBOARD"
        print(f"\n=== 💸 {title} | {datetime.now().strftime('%H:%M:%S')} ===")
        print(f"Cash: ${self.cash:.2f} | Realized PnL: ${self.realized_pnl:+.2f}")
        print(f"Positions: {len(self.positions)}")
        for ticker, pos in self.positions.items():
            print(f"  - {pos['game']}: {pos['count']}x @ ${pos['avg_entry']:.3f}")
        print("==================================\n")
