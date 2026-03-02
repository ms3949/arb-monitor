import time
import pandas as pd
from py_clob_client.client import ClobClient

class StrategyEngine:
    def __init__(self, client: ClobClient):
        self.client = client
        self.opportunities = []
        self.near_misses = []

    def check_touch_arb(self, touch_markets):
        """
        Strategy A: "The Touch" (Monotonicity/Calendar Arb)
        Logic: Ask(Yes, Late) < Bid(Yes, Early)
        """
        print("\n--- Running Strategy A: Touch Arb ---")
        # Key is now just 'Event Base' (string), not (Asset, Strike) tuple
        for event_base, markets in touch_markets.items():
            if len(markets) < 2:
                continue
            
            # Sort by expiration date
            # Ensure we have end_date_iso and it is not None
            valid_markets = [m for m in markets if m.get('end_date_iso')]
            valid_markets.sort(key=lambda x: x['end_date_iso'])
            
            # Iterate pairs
            for i in range(len(valid_markets)):
                for j in range(i + 1, len(valid_markets)):
                    early = valid_markets[i]
                    late = valid_markets[j]
                    
                    try:
                        # Fetch Orderbooks
                        early_yes = self._get_token_id(early, 'Yes')
                        late_yes = self._get_token_id(late, 'Yes')
                        
                        if not early_yes or not late_yes:
                            continue
                            
                        ob_early = self.client.get_order_book(early_yes)
                        ob_late = self.client.get_order_book(late_yes)
                        
                        # Bid (Sell price) for Early
                        bid_early = float(ob_early.bids[0].price) if ob_early.bids else 0.0
                        
                        # Ask (Buy price) for Late
                        ask_late = float(ob_late.asks[0].price) if ob_late.asks else 1.0
                        
                        # Calculate Spread
                        # Positive Spread = Profit
                        profit = bid_early - ask_late
                        
                        # Check condition
                        if profit > 0:
                            opp = {
                                'Strategy': 'Touch (Calendar)',
                                'Event': event_base,
                                'Early Date': early['end_date_iso'],
                                'Late Date': late['end_date_iso'],
                                'Buy Late (Ask)': ask_late,
                                'Sell Early (Bid)': bid_early,
                                'Profit Spread': profit,
                                'Early Market': early['question'],
                                'Late Market': late['question']
                            }
                            self.opportunities.append(opp)
                            print(f"FOUND ARB (Touch): {opp['Early Market']} vs {opp['Late Market']} | Spread: {profit:.3f}")
                        
                        # Near Miss Logic (e.g. Spread > -0.05, meaning cost is < 5 cents)
                        elif profit > -0.05:
                             self.near_misses.append({
                                'Type': 'Touch',
                                'Group': f"{early['question']} vs {late['question']}",
                                'Metric': 'Spread',
                                'Value': profit,
                                'Gap': -profit # How far from 0
                            })

                        time.sleep(0.05) # Rate limit
                        
                    except Exception as e:
                        continue

    def check_basket_arb(self, basket_markets):
        """
        Strategy B: "The Basket" (Sum-of-Parts Arb)
        Logic: Sum(Ask(Yes)) < 0.995 (0.5% buffer)
        """
        print("\n--- Running Strategy B: Basket Arb ---")
        for base_question, markets in basket_markets.items():
            if len(markets) < 2:
                continue
            
            total_ask_cost = 0.0
            market_details = []
            valid_group = True
            
            for m in markets:
                try:
                    yes_token = self._get_token_id(m, 'Yes')
                    if not yes_token:
                        valid_group = False
                        break
                        
                    ob = self.client.get_order_book(yes_token)
                    ask = float(ob.asks[0].price) if ob.asks else 1.0
                    
                    total_ask_cost += ask
                    market_details.append({
                        'question': m['question'],
                        'ask': ask
                    })
                    
                    time.sleep(0.05)
                    
                except Exception as e:
                    valid_group = False
                    break
            
            if valid_group:
                # Check condition (allowing 0.5% for fees/slippage buffer, so < 0.995)
                if total_ask_cost < 0.995:
                    profit = 1.0 - total_ask_cost
                    opp = {
                        'Strategy': 'Basket (Sum)',
                        'Group': base_question,
                        'Total Cost': total_ask_cost,
                        'Profit Potential': profit,
                        'Markets Count': len(markets)
                    }
                    self.opportunities.append(opp)
                    print(f"FOUND ARB (Basket): {base_question} | Cost: {total_ask_cost:.3f}")
                
                # Near Miss Logic (e.g. Cost < 1.05)
                elif total_ask_cost < 1.05:
                    self.near_misses.append({
                        'Type': 'Basket',
                        'Group': base_question,
                        'Metric': 'Cost',
                        'Value': total_ask_cost,
                        'Gap': total_ask_cost - 1.0 # How far from 1.0
                    })

    def _get_token_id(self, market, outcome_label='Yes'):
        tokens = market.get('tokens', [])
        for t in tokens:
            if t.get('outcome', '').lower() == outcome_label.lower():
                return t.get('token_id')
        return None

    def get_results(self):
        return pd.DataFrame(self.opportunities)

    def print_near_misses(self, top_n=5):
        if not self.near_misses:
            print("\nNo near misses found.")
            return
            
        print(f"\n--- TOP {top_n} NEAR MISSES ---")
        # Sort by Gap (closest to 0)
        # For Touch: Gap is -Spread (lower is better/closer to 0)
        # For Basket: Gap is Cost - 1.0 (lower is better/closer to 0)
        # Actually, let's just sort by 'Gap' ascending.
        
        self.near_misses.sort(key=lambda x: x['Gap'])
        
        for m in self.near_misses[:top_n]:
            print(f"[{m['Type']}] {m['Group']} | {m['Metric']}: {m['Value']:.4f} | Gap: {m['Gap']:.4f}")
