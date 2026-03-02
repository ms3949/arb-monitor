"""
Auto-discovery: find active NCAAB games on BOTH Kalshi and Polymarket.

Flow:
  1. Fetch all open Kalshi KXNCAAMBGAME markets
  2. Group by event ticker (one event = one game)
  3. For each event, extract date + team abbreviations
  4. Search Polymarket Gamma API for a matching CBB slug
  5. If both exist, build a CONFIG entry

Result: a dict ready to drop into CONFIG.
"""
import json
import re
import requests
from datetime import datetime
from typing import Optional


KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA_API = "https://gamma-api.polymarket.com"


# ---------- Kalshi ----------

def fetch_kalshi_ncaab_events() -> dict:
    """
    Fetch all open KXNCAAMBGAME markets, grouped by event_ticker.
    Returns {event_ticker: [market_dict, ...]}.
    """
    events = {}
    cursor = None
    while True:
        params = {"series_ticker": "KXNCAAMBGAME", "status": "open", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        try:
            r = requests.get(f"{KALSHI_API}/markets", params=params, timeout=15)
            if r.status_code != 200:
                print(f"  Kalshi API error {r.status_code}")
                break
            data = r.json()
            markets = data.get("markets", [])
            if not markets:
                break
            for m in markets:
                etk = m.get("event_ticker", "")
                if etk:
                    events.setdefault(etk, []).append(m)
            cursor = data.get("cursor")
            if not cursor:
                break
        except Exception as e:
            print(f"  Kalshi fetch error: {e}")
            break
    return events


def _parse_event_ticker(event_ticker: str) -> tuple:
    """
    Parse e.g. KXNCAAMBGAME-26MAR01DUKEUNC
    -> (date_str 'YYYY-MM-DD', team_code_a, team_code_b, raw_teams_str)
    """
    m = re.search(r"(\d{2})([A-Z]{3})(\d{2})([A-Z]+)", event_ticker, re.IGNORECASE)
    if not m:
        return None, None, None, None
    day, mon_str, yr, teams_raw = m.group(1), m.group(2).upper(), m.group(3), m.group(4)
    months = {"JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
              "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12"}
    mm = months.get(mon_str)
    if not mm:
        return None, None, None, None
    date_str = f"20{yr}-{mm}-{day}"

    # Split teams: Kalshi uses 4-letter abbreviations butted together e.g. DUKEUNC, TLSAWICH
    # Common lengths: 2-6 chars each. Try all splits and pick the best.
    team_a, team_b = _split_team_codes(teams_raw)
    return date_str, team_a, team_b, teams_raw


def _split_team_codes(raw: str) -> tuple:
    """Split e.g. 'DUKEUNC' into ('DUKE', 'UNC'). Uses Kalshi market subtitles when available."""
    # Try common splits (each team 2-6 chars)
    best = (raw, "")
    for i in range(2, len(raw) - 1):
        a, b = raw[:i], raw[i:]
        if 2 <= len(a) <= 6 and 2 <= len(b) <= 6:
            best = (a, b)
            # Prefer even-ish splits
    # Actually just take midpoint-ish split
    n = len(raw)
    mid = n // 2
    for offset in range(0, n // 2):
        for pos in [mid + offset, mid - offset]:
            if 2 <= pos <= n - 2:
                return raw[:pos], raw[pos:]
    return raw, ""


def _extract_teams_from_kalshi_markets(markets: list) -> tuple:
    """Extract team names from Kalshi market titles. Format: 'X at Y Winner?'"""
    for m in markets:
        title = m.get("title", "")
        match = re.search(r"(.+?)\s+at\s+(.+?)(?:\s+Winner|\s*\?|\s*$)", title, re.IGNORECASE)
        if match:
            away = match.group(1).strip()
            home = match.group(2).strip()
            return home, away
    return None, None


# ---------- Polymarket ----------

# Team abbreviation -> slug abbreviation mapping (Kalshi uses different codes than Polymarket)
# This is not exhaustive but covers common patterns
_KALSHI_TO_POLY_SLUG = {
    # Build on the fly from Kalshi market titles
}

def _team_name_to_slug_part(name: str) -> str:
    """Convert team name to a Polymarket slug fragment: 'New Mexico St.' -> 'nmxst'"""
    if not name:
        return ""
    # Remove common suffixes
    s = name.strip()
    s = re.sub(r"\s+(Winner|$)\??", "", s, flags=re.IGNORECASE).strip()
    # Polymarket uses abbreviated lowercase
    # e.g. "Wichita State" -> "wichst", "Tulsa" -> "tulsa"
    return s.lower().replace(" ", "").replace(".", "")[:8]


def search_poly_for_game(date_str: str, home_name: str, away_name: str) -> Optional[dict]:
    """
    Search Polymarket for a matching CBB game.
    Tries slug patterns and keyword search.
    Returns market/event data or None.
    """
    # Strategy 1: Try constructing slug patterns
    home_slug = _team_name_to_slug_part(home_name)
    away_slug = _team_name_to_slug_part(away_name)
    
    # Polymarket slugs are typically: cbb-{away}-{home}-YYYY-MM-DD
    slug_patterns = [
        f"cbb-{away_slug}-{home_slug}-{date_str}",
        f"cbb-{home_slug}-{away_slug}-{date_str}",
    ]
    
    for slug in slug_patterns:
        result = _try_poly_slug(slug)
        if result:
            return result
    
    # Strategy 2: Search via active events with tag
    try:
        # Use Gamma API to search for events
        r = requests.get(f"{GAMMA_API}/events", params={
            "tag": "cbb",
            "closed": "false",
            "limit": 100,
        }, timeout=15)
        if r.status_code == 200:
            events = r.json()
            if isinstance(events, list):
                for ev in events:
                    title = (ev.get("title") or "").lower()
                    slug = (ev.get("slug") or "").lower()
                    # Check if both team names appear in the title or slug
                    h_terms = _search_terms(home_name)
                    a_terms = _search_terms(away_name)
                    text = f"{title} {slug}"
                    if any(t in text for t in h_terms) and any(t in text for t in a_terms):
                        # Check date matches
                        if date_str in slug or date_str in (ev.get("startDate") or ""):
                            return ev
    except Exception:
        pass
    
    # Strategy 3: Search markets directly
    try:
        r = requests.get(f"{GAMMA_API}/markets", params={
            "tag": "cbb",
            "closed": "false",
            "limit": 200,
        }, timeout=15)
        if r.status_code == 200:
            markets = r.json()
            if isinstance(markets, list):
                for m in markets:
                    slug = (m.get("slug") or "").lower()
                    question = (m.get("question") or "").lower()
                    h_terms = _search_terms(home_name)
                    a_terms = _search_terms(away_name)
                    text = f"{slug} {question}"
                    if any(t in text for t in h_terms) and any(t in text for t in a_terms):
                        if date_str in slug:
                            return m
    except Exception:
        pass
    
    return None


def _try_poly_slug(slug: str) -> Optional[dict]:
    """Try to fetch a Polymarket market by slug."""
    try:
        r = requests.get(f"{GAMMA_API}/markets", params={"slug": slug}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and data:
                m = data[0]
                if m.get("active", True) and not m.get("closed", False):
                    return m
    except Exception:
        pass
    return None


def _search_terms(name: str) -> list:
    """Generate search terms from a team name."""
    if not name:
        return []
    parts = name.lower().replace(".", "").split()
    terms = [name.lower()]
    # Add individual significant words
    for p in parts:
        if len(p) > 2 and p not in ("the", "and", "state", "university"):
            terms.append(p)
    # Add without "State" suffix for matching
    if "state" in name.lower():
        terms.append(name.lower().replace(" state", "").replace(" st.", "").strip())
    return terms


# ---------- Combined Discovery ----------

def discover_games() -> dict:
    """
    Scan Kalshi + Polymarket for active NCAAB games on both exchanges.
    Returns a CONFIG dict ready for the bot.
    """
    print("\n🔍 [DISCOVERY] Scanning for active games...")
    
    # 1. Fetch Kalshi events
    print("  📡 Fetching Kalshi NCAAB events...")
    kalshi_events = fetch_kalshi_ncaab_events()
    print(f"  ✅ Found {len(kalshi_events)} Kalshi events")
    
    if not kalshi_events:
        print("  ❌ No active Kalshi NCAAB events found.")
        return {}
    
    # 2. For each event, try to find a matching Polymarket market
    config = {}
    matched = 0
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    for event_ticker, markets in kalshi_events.items():
        date_str, team_a, team_b, raw = _parse_event_ticker(event_ticker)
        if not date_str:
            continue
        
        # Extract full team names from Kalshi market titles
        home_name, away_name = _extract_teams_from_kalshi_markets(markets)
        if not home_name or not away_name:
            # Fallback: use ticker abbreviations
            home_name = team_b or raw[len(raw)//2:]
            away_name = team_a or raw[:len(raw)//2]
        
        # Search Polymarket
        poly_data = search_poly_for_game(date_str, home_name, away_name)
        
        if poly_data:
            matched += 1
            
            # Extract Poly details
            cond_id = poly_data.get("conditionId", "")
            poly_slug = poly_data.get("slug", "")
            
            # Determine outcomes
            outcomes_raw = poly_data.get("outcomes")
            outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else (outcomes_raw or [])
            
            # Find which outcome index matches home team
            poly_outcome_index = 0
            for i, o in enumerate(outcomes):
                o_lower = (o or "").lower()
                if home_name.lower().split()[0] in o_lower or home_name.lower() in o_lower:
                    poly_outcome_index = i
                    break
            
            # Determine Kalshi market ticker for the home team
            kalshi_market_ticker = markets[0]["ticker"]
            kalshi_target_outcome = home_name
            for m in markets:
                subtitle = (m.get("yes_sub_title") or m.get("title") or "").lower()
                if home_name.lower().split()[0] in subtitle:
                    kalshi_market_ticker = m["ticker"]
                    break
            
            # Build game key
            game_key = f"{away_name.split()[0].upper()}_VS_{home_name.split()[0].upper()}"
            game_key = re.sub(r"[^A-Z0-9_]", "", game_key)
            
            # Get token IDs for Poly WS subscription
            clob_ids = poly_data.get("clobTokenIds")
            if isinstance(clob_ids, str):
                clob_ids = json.loads(clob_ids) if clob_ids else []
            
            config[game_key] = {
                "kalshi_market_ticker": kalshi_market_ticker,
                "kalshi_event_ticker": event_ticker,
                "kalshi_target_outcome": kalshi_target_outcome,
                "poly_slug": poly_slug,
                "poly_condition_id": cond_id,
                "poly_outcome_index": poly_outcome_index,
                # Bolt fields (set but unused for now)
                "bolt_home": home_name,
                "bolt_away": away_name,
                "bolt_home_aliases": [home_name],
                "bolt_away_aliases": [away_name],
                # Metadata
                "game_date": date_str,
                "home_team": home_name,
                "away_team": away_name,
            }
            
            print(f"  ✅ MATCHED: {away_name} @ {home_name} ({date_str}) | K:{kalshi_market_ticker} P:{poly_slug}")
        
    print(f"\n🎯 [DISCOVERY] {matched}/{len(kalshi_events)} games matched on BOTH exchanges\n")
    return config


if __name__ == "__main__":
    config = discover_games()
    if config:
        print("\n=== Generated CONFIG ===")
        for key, val in config.items():
            print(f"\n{key}:")
            for k, v in val.items():
                print(f"  {k}: {v}")
    else:
        print("No games found.")
