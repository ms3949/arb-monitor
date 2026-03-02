import re
import time
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON

class MarketScanner:
    def __init__(self, client: ClobClient):
        self.client = client
        self.touch_markets = {}  # Key: Event Base, Value: List of markets
        self.basket_markets = {} # Key: Question Base, Value: List of markets

    def fetch_active_markets(self, limit=None):
        """
        Fetches active markets using the standard endpoint with offset pagination.
        This allows deep scanning beyond the sampling endpoint's limits.
        """
        markets = []
        offset = 0
        print("Fetching active markets (standard)...")
        
        while True:
            try:
                resp = self.client.get_markets(next_cursor=self._encode_cursor(offset))
                if not resp or 'data' not in resp:
                    break
                
                batch = resp['data']
                if not batch:
                    break
                    
                markets.extend(batch)
                offset += len(batch)
                print(f"Fetched {len(markets)} markets...", end='\r')
                
                if limit and len(markets) >= limit:
                    break
                    
            except Exception as e:
                print(f"\nError fetching markets: {e}")
                break
        
        print(f"\nTotal markets fetched: {len(markets)}")
        return markets

    def _encode_cursor(self, offset):
        import base64
        if offset == 0:
            return ""
        return base64.b64encode(str(offset).encode('ascii')).decode('ascii')

    def classify_markets(self, markets):
        """
        Classifies markets into Strategy A (Touch) or Strategy B (Basket).
        """
        self.touch_markets = {}
        self.basket_markets = {}
        
        print("Classifying markets...")
        for m in markets:
            if not m.get('active'):
                continue
            
            # Zombie Filter: Ignore low volume markets
            # Note: 'volume' might be a string or float depending on API
            # If volume is None (missing), we CANNOT assume it is 0 and filter it out,
            # because the get_markets endpoint often omits this field for active markets.
            # We only filter if we explicitly see a low volume value.
            vol_raw = m.get('volume')
            if vol_raw is not None:
                try:
                    vol = float(vol_raw)
                    if vol < 1000:
                        continue
                except:
                    pass # If parse fails, be safe and keep it
                
            question = m.get('question', '')
            q_lower = question.lower()
            
            # --- Strategy A: "The Touch" ---
            # Keywords: hit, touch, reach, before, by, >
            # Logic: Look for Event + Date. Group by Event (stripping date).
            touch_keywords = ['hit', 'touch', 'reach', 'before', 'by ', '>']
            if any(k in q_lower for k in touch_keywords):
                # Exclude "Above/Below" if they are not time-based (but > usually is)
                # Actually, "Above" often means "Will X be above Y at Date Z", which is valid if we have multiple dates.
                
                # Extract Event Base (remove date)
                event_base = self._extract_event_base(question)
                
                if event_base:
                    if event_base not in self.touch_markets:
                        self.touch_markets[event_base] = []
                    
                    # We store the asset as the event base for display purposes
                    m['asset'] = event_base 
                    # We don't strictly need 'parsed_strike' anymore for grouping, 
                    # but strategies.py might expect 'Strike' in the key if we iterate items().
                    # The previous key was (Asset, Strike). Now it's just EventBase.
                    # We need to update strategies.py to handle this new key structure.
                    
                    self.touch_markets[event_base].append(m)
                    continue # Matched Strategy A

            # --- Strategy B: "The Basket" ---
            # Keywords: Close at, End of Year, Range, Bracket, Win by, Score, Nomination, etc.
            basket_keywords = [
                'close at', 'end of year', 'range', 'bracket', 'price at', 'between', # Finance
                'win by', 'margin', 'score', 'points', 'vs', 'winner', 'champion', # Sports
                'nomination', 'candidate', 'elect', 'president', 'senate', 'house' # Politics
            ]
            
            if any(k in q_lower for k in basket_keywords):
                # Use normalization to group "parallel" contracts
                # e.g. "Lakers win by 1-5" and "Lakers win by 6-10" -> "Lakers win by {NUM}-{NUM}"
                base_question = self._normalize_basket_question(question)
                
                if base_question not in self.basket_markets:
                    self.basket_markets[base_question] = []
                self.basket_markets[base_question].append(m)

        print(f"Classified {len(self.touch_markets)} Touch groups and {len(self.basket_markets)} Basket groups.")
        return self.touch_markets, self.basket_markets

    def _extract_event_base(self, question):
        """
        Removes date components from the question to create a normalized 'Event Base' key.
        """
        # Regex patterns for dates
        patterns = [
            r'(?i)\s+by\s+[A-Za-z]+\s+\d+(?:st|nd|rd|th)?(?:,\s+\d{4})?', # by June 30, 2023
            r'(?i)\s+before\s+[A-Za-z]+\s+\d+(?:st|nd|rd|th)?(?:,\s+\d{4})?', # before March 1
            r'(?i)\s+by\s+\d{4}', # by 2024
            r'(?i)\s+before\s+\d{4}', # before 2025
            r'(?i)\s+by\s+EOY', # by EOY
            r'(?i)\s+before\s+EOY',
            r'(?i)\s+by\s+end\s+of\s+[A-Za-z]+', # by end of year/month
            r'(?i)\s+on\s+[A-Za-z]+\s+\d+(?:st|nd|rd|th)?(?:,\s+\d{4})?', # on Feb 15
        ]
        
        base = question
        for p in patterns:
            base = re.sub(p, '', base)
            
        return base.strip()

    def _normalize_basket_question(self, question):
        """
        Normalizes questions for Basket grouping by replacing numbers and specific entities with placeholders.
        This helps group parallel contracts like "Win by 1-5" and "Win by 6-10".
        """
        # 1. Replace specific number ranges or numbers with {NUM}
        # e.g. "1-5" -> "{NUM}"
        norm = re.sub(r'\d+-\d+', '{RANGE}', question)
        norm = re.sub(r'\d+(\.\d+)?', '{NUM}', norm)
        
        # 2. Handle "Above/Below" or "< >" which are common in baskets
        norm = re.sub(r'[<>]\s*{NUM}', '{CMP}', norm)
        norm = re.sub(r'(?i)(above|below|more than|less than)\s*{NUM}', '{CMP}', norm)
        
        # 3. Strip content in parenthesis if it looks like a condition
        # e.g. "Who will win? (Team A)" -> "Who will win?" - WAIT, this might merge mutually exclusive teams!
        # For "Who will win?", the markets are usually "Team A", "Team B".
        # If the question is "Who will win the Super Bowl?", and the outcomes are tokens in ONE market, 
        # then we don't need to group multiple markets.
        # But if they are separate markets: "Will Team A win?", "Will Team B win?"
        # Then we need to group them.
        
        # Let's try to be conservative. If we replace too much, we group unrelated things.
        # But "Lakers win by 1-5" vs "Lakers win by 6-10" -> "Lakers win by {RANGE}" works.
        
        return norm.strip()
